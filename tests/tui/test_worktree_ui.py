"""The branch on screen, and removing the worktree from history."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pulse import vcs
from pulse.config.project_config import load_project_config, update_project_defaults
from pulse.daemon.runs import RunManager
from pulse.domain.run import StepRecord, StepStatus
from pulse.history.catalog import HistoryCatalog
from pulse.store import runs as run_store
from pulse.store.paths import worktrees_dir
from pulse.tui.hydrate import hydrate_history_item
from pulse.tui.screens.history_detail import HistoryDetailScreen
from pulse.tui.screens.settings import SettingsScreen
from pulse.tui.state import CockpitState
from pulse.tui.theme import COCKPIT_CSS
from pulse.tui.widgets.app_header import AppHeader
from tests.conftest import configure_from_db, make_workflow, served_log
from tests.infra.test_worktree import make_repo, prepare

git_only = pytest.mark.skipif(not vcs.git_available(), reason="git is not on PATH")


def _run_in(workspace: Path, *, run_id: str = "run-1", branch: str = "", worktree: str = "") -> str:
    make_workflow("demo", steps=[("plan", "Planejar")])
    record = run_store.create_run(
        run_id=run_id,
        workflow_id="demo",
        workspace=workspace,
        user_prompt="Adicionar login",
        steps=[StepRecord(step_id="plan", position=1, label="Planejar", agent_id="tester")],
    )
    if branch or worktree:
        record.work_in(worktree_path=worktree, branch=branch)
    for step in record.steps:
        step.status = StepStatus.DONE
    record.complete()
    run_store.save(record)
    return record.id


def _header_where(state: CockpitState) -> str:
    async def run() -> str:
        from textual.app import App, ComposeResult

        class Harness(App[None]):
            CSS = COCKPIT_CSS

            def compose(self) -> ComposeResult:
                yield AppHeader()

        app = Harness()
        async with app.run_test(size=(140, 40)) as pilot:
            app.query_one(AppHeader).sync_from_state(state)
            await pilot.pause()
            return str(app.query_one("#run-where").render())

    return asyncio.run(run())


def test_header_shows_model_and_branch():
    state = CockpitState()
    make_workflow("demo")
    configure_from_db(state, "demo")
    state.set_model("opus")
    state.set_branch("pulse/demo-abc123")

    assert _header_where(state) == "branch pulse/demo-abc123 · opus"


def test_without_branch_the_header_shows_only_the_model():
    """A project outside git gets no dangling separator before the model."""
    state = CockpitState()
    make_workflow("demo")
    configure_from_db(state, "demo")
    state.set_model("opus")

    assert _header_where(state) == "opus"


def test_history_reopens_with_run_branch(tmp_path: Path):
    run_id = _run_in(tmp_path, branch="pulse/demo-abc123")
    item = HistoryCatalog(tmp_path).get(run_id)
    assert item is not None
    assert item.branch == "pulse/demo-abc123"
    assert hydrate_history_item(item, tmp_path, served_log(run_id)).branch_label == (
        "pulse/demo-abc123"
    )


def test_resume_reopens_with_run_branch(tmp_path: Path):
    from pulse.tui.hydrate import restore_run

    run_id = _run_in(tmp_path, branch="pulse/demo-abc123")
    state = CockpitState()
    configure_from_db(state, "demo")
    exec_root = restore_run(state, served_log(run_id), tmp_path)
    assert state.branch_label == "pulse/demo-abc123"
    assert exec_root == str(tmp_path.resolve())


def test_resume_points_to_worktree_before_engine_reports(tmp_path: Path):
    """The screen must not read artifacts from the root before `run.context` arrives."""
    from pulse.tui.hydrate import restore_run

    worktree = tmp_path / "wt"
    worktree.mkdir()
    run_id = _run_in(tmp_path, branch="pulse/demo-abc", worktree=str(worktree))
    state = CockpitState()
    configure_from_db(state, "demo")
    assert restore_run(state, served_log(run_id), tmp_path) == str(worktree)


@git_only
def test_remove_worktree_through_catalog(tmp_path: Path):
    repo = make_repo(tmp_path / "repo")
    run_id = _run_in(repo)
    record = run_store.load_run(run_id)
    assert record is not None
    exec_dir, _branch = prepare(record, repo, use_worktree=True)
    assert _branch

    item = HistoryCatalog(repo).get(run_id)
    assert item is not None
    assert item.worktree_path == str(exec_dir)

    assert HistoryCatalog(repo).remove_worktree(item) is True
    assert not exec_dir.exists()
    stored = run_store.load_run(run_id)
    assert stored is not None
    assert stored.worktree_path == ""
    assert stored.branch == _branch, "the branch still holds the work"


@git_only
def test_dirty_worktree_is_not_silently_deleted(tmp_path: Path):
    """Uncommitted work inside is not ours to throw away."""
    repo = make_repo(tmp_path / "repo")
    run_id = _run_in(repo)
    record = run_store.load_run(run_id)
    assert record is not None
    exec_dir, _ = prepare(record, repo, use_worktree=True)
    (exec_dir / "rascunho.md").write_text("não commitado\n", encoding="utf-8")

    item = HistoryCatalog(repo).get(run_id)
    assert item is not None
    assert HistoryCatalog(repo).remove_worktree(item) is False
    assert exec_dir.exists()

    assert HistoryCatalog(repo).delete(run_id) is True
    assert exec_dir.exists()
    assert run_store.load_run(run_id) is None


@git_only
def test_deleting_run_removes_clean_worktree(tmp_path: Path):
    repo = make_repo(tmp_path / "repo")
    run_id = _run_in(repo)
    record = run_store.load_run(run_id)
    assert record is not None
    exec_dir, _ = prepare(record, repo, use_worktree=True)

    assert HistoryCatalog(repo).delete(run_id) is True
    assert not exec_dir.exists()


@git_only
def test_detail_offers_removal_only_with_worktree(tmp_path: Path):
    repo = make_repo(tmp_path / "repo")
    plain_id = _run_in(repo, run_id="run-sem-wt")
    plain = HistoryCatalog(repo).get(plain_id)
    assert plain is not None

    async def run() -> None:
        from textual.app import App

        class Harness(App[None]):
            CSS = COCKPIT_CSS

            def on_mount(self) -> None:
                self.push_screen(HistoryDetailScreen(plain, workspace=repo))

        app = Harness()
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, HistoryDetailScreen)
            assert screen.check_action("remove_worktree", ()) is False

    asyncio.run(run())


def test_removing_the_worktree_never_rewrites_the_steps_of_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """History does not own the run: the daemon may save it while the screen is open.

    The daemon's save is injected right after any read the history does, the
    interleaving that made a delivered step go back to `pending`.
    """
    make_workflow("demo", steps=[("plan", "Planejar")])
    live = run_store.create_run(
        run_id="run-live",
        workflow_id="demo",
        workspace=tmp_path,
        user_prompt="Adicionar login",
        steps=[StepRecord(step_id="plan", position=1, label="Planejar", agent_id="tester")],
    )
    live.work_in(worktree_path=str(tmp_path / "gone"), branch="pulse/demo-run-live")
    run_store.save(live)
    item = HistoryCatalog(tmp_path).get(live.id)
    assert item is not None

    def daemon_delivers() -> None:
        if live.step("plan").settled:
            return
        live.start_step("plan")
        live.step("plan").deliver()
        run_store.save(live)

    real_load = run_store.load_run

    def load_then_daemon_delivers(run_id: str, **kwargs):
        loaded = real_load(run_id, **kwargs)
        daemon_delivers()
        return loaded

    with monkeypatch.context() as patched:
        patched.setattr(run_store, "load_run", load_then_daemon_delivers)
        HistoryCatalog(tmp_path).remove_worktree(item)

    cleared = run_store.load_run(live.id)
    assert cleared is not None
    assert cleared.worktree_path == ""
    assert cleared.branch == "pulse/demo-run-live", "the branch still holds the work"

    daemon_delivers()
    stored = run_store.load_run(live.id)
    assert stored is not None
    assert stored.step("plan").status == StepStatus.DONE


@git_only
@pytest.mark.parametrize(
    ("daemon_runs_it", "confirmation_offered"),
    [(True, False), (False, True)],
    ids=["daemon-runs-it", "stuck-after-a-crash"],
)
def test_worktree_removal_is_refused_only_while_the_daemon_runs_the_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    in_process_daemon: TestClient,
    daemon_runs_it: bool,
    confirmation_offered: bool,
):
    """The agent works in that directory and the daemon would write its path back.

    A run left `running` by a dead process must stay removable, so the daemon
    decides, not the stored status.
    """
    repo = make_repo(tmp_path / "repo")
    make_workflow("demo", steps=[("plan", "Planejar")])
    live = run_store.create_run(
        run_id="run-live",
        workflow_id="demo",
        workspace=repo,
        user_prompt="Adicionar login",
        steps=[StepRecord(step_id="plan", position=1, label="Planejar", agent_id="tester")],
    )
    worktree = tmp_path / "wt"
    worktree.mkdir()
    live.work_in(worktree_path=str(worktree), branch="pulse/demo-run-live")
    live.start_step("plan")
    run_store.save(live)
    item = HistoryCatalog(repo).get(live.id)
    assert item is not None
    release = threading.Event()

    def engine_at_work(**_kwargs: object) -> int:
        release.wait(5)
        return 0

    monkeypatch.setattr("pulse.daemon.runs.run_engine", engine_at_work)
    manager: RunManager = in_process_daemon.app.state.runs
    if daemon_runs_it:
        manager.start_run(
            workflow_id="demo", prompt="x", workspace=str(repo), resume_run_id=live.id
        )

    async def run() -> None:
        from textual.app import App

        from pulse.tui.screens.confirm import ConfirmScreen

        class Harness(App[None]):
            CSS = COCKPIT_CSS

            def on_mount(self) -> None:
                self.push_screen(HistoryDetailScreen(item, workspace=repo))

        app = Harness()
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            detail = next(s for s in app.screen_stack if isinstance(s, HistoryDetailScreen))
            detail.action_remove_worktree()
            await pilot.pause()
            offered = any(isinstance(s, ConfirmScreen) for s in app.screen_stack)
            assert offered is confirmation_offered

    try:
        asyncio.run(run())
    finally:
        release.set()
    assert worktree.exists()


@git_only
def test_detail_reads_artifact_from_inside_worktree(tmp_path: Path):
    """The pane looks for the file where the agent wrote it, not at the root."""
    repo = make_repo(tmp_path / "repo")
    run_id = _run_in(repo)
    record = run_store.load_run(run_id)
    assert record is not None
    exec_dir, _ = prepare(record, repo, use_worktree=True)
    (exec_dir / "PLANO.md").write_text("# plano\n\nconteúdo do worktree\n", encoding="utf-8")
    run_store.record_artifact(run_id, "PLANO.md", step_id="plan")

    item = HistoryCatalog(repo).get(run_id)
    assert item is not None
    state = hydrate_history_item(item, repo, served_log(run_id))
    assert [artifact.path for artifact in state.artifacts] == ["PLANO.md"]
    assert state.artifacts[0].has_content is True


@git_only
def test_settings_offers_toggle_in_git_repo(tmp_path: Path):
    repo = make_repo(tmp_path / "repo")

    async def run() -> None:
        from textual.app import App
        from textual.widgets import OptionList

        class Harness(App[None]):
            CSS = COCKPIT_CSS

            def on_mount(self) -> None:
                self.push_screen(SettingsScreen(cwd=repo))

        app = Harness()
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, SettingsScreen)
            options = screen.query_one("#settings-options", OptionList)
            ids = [options.get_option_at_index(index).id for index in range(options.option_count)]
            assert "worktree" in ids

            screen._toggle_worktree()
            await pilot.pause()
            assert load_project_config(repo).use_worktree is True
            screen._toggle_worktree()
            await pilot.pause()
            assert load_project_config(repo).use_worktree is False

    asyncio.run(run())


def test_settings_hides_toggle_outside_git(tmp_path: Path):
    """A toggle that enables nothing is worse than no toggle."""
    plain = tmp_path / "sem-git"
    plain.mkdir()

    async def run() -> None:
        from textual.app import App
        from textual.widgets import OptionList

        class Harness(App[None]):
            CSS = COCKPIT_CSS

            def on_mount(self) -> None:
                self.push_screen(SettingsScreen(cwd=plain))

        app = Harness()
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            options = app.screen.query_one("#settings-options", OptionList)
            ids = [options.get_option_at_index(index).id for index in range(options.option_count)]
            assert "worktree" not in ids

    asyncio.run(run())


@git_only
def test_enabled_toggle_moves_run_to_worktree(tmp_path: Path):
    """From toggle to directory: the whole path, with no mocks."""
    repo = make_repo(tmp_path / "repo")
    update_project_defaults(repo, use_worktree=True)

    from pulse.config.resolved import resolve_config

    run_id = _run_in(repo)
    record = run_store.load_run(run_id)
    assert record is not None
    exec_dir, branch = prepare(record, repo, use_worktree=resolve_config(repo).use_worktree)

    assert exec_dir == worktrees_dir() / "adicionar-login"
    assert branch == "adicionar-login"
