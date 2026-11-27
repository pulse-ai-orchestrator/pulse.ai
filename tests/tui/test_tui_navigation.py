"""Moving between screens: home menus, waiting sessions and reopening a live run."""

from __future__ import annotations

import asyncio

from pulse.tui.screens.home import HomeScreen
from pulse.tui.theme import COCKPIT_CSS
from pulse.tui.widgets.phase_sidebar import PhaseSidebar
from tests.conftest import configure_from_db, make_workflow, onboard_machine


def test_home_root_options_open_their_screens(monkeypatch):
    """Each root option asks the app for its screen; `exit` quits without stopping runs."""
    import pulse.tui.screens.home as home_module

    monkeypatch.setattr(home_module, "active_runs", lambda: [])

    async def run() -> None:
        from textual.app import App, ComposeResult
        from textual.widgets import Static

        class Harness(App[None]):
            def compose(self) -> ComposeResult:
                yield Static("ok")

            def open_settings(self) -> None:
                called.append("settings")

            def open_history(self) -> None:
                called.append("history")

            def open_onboarding(self) -> None:
                called.append("init")

        called: list[str] = []
        app = Harness()
        async with app.run_test(size=(80, 24)) as pilot:
            screen = HomeScreen()
            app.push_screen(screen)
            await pilot.pause()
            for option_id in ("settings", "history", "init", "unknown"):
                screen.on_option_selected(_selected(option_id))
            assert called == ["settings", "history", "init"]
            screen.on_option_selected(_selected("exit"))
            await pilot.pause()
        assert app.return_code == 0

    asyncio.run(run())


def _home_option_ids(screen) -> list[str]:
    from textual.widgets import OptionList

    options = screen.query_one("#home-options", OptionList)
    return [str(options.get_option_at_index(index).id) for index in range(options.option_count)]


def _highlighted(option_id: str):
    return _selected(option_id)


def _selected(option_id: str):
    """`on_option_selected` only reads `option_id`; building the real event needs the widget."""
    from types import SimpleNamespace

    return SimpleNamespace(option_id=option_id)


def test_home_hides_the_loops_behind_new_session(monkeypatch):
    """The root menu does not grow with the database: loops live one level below."""

    onboard_machine()

    async def run() -> None:
        from textual.app import App, ComposeResult
        from textual.widgets import Static

        class Harness(App[None]):
            CSS = COCKPIT_CSS

            def compose(self) -> ComposeResult:
                yield Static("ok")

            def open_cockpit(self, workflow_id: str, prompt: str) -> None:
                opened.append((workflow_id, prompt))

        opened: list[tuple[str, str]] = []
        app = Harness()
        async with app.run_test(size=(80, 24)) as pilot:
            screen = HomeScreen()
            app.push_screen(screen)
            await pilot.pause()

            root = _home_option_ids(screen)
            assert root == ["session", "history", "settings", "exit"]

            screen.on_option_selected(_selected("session"))
            await pilot.pause()
            loops = _home_option_ids(screen)
            assert "workflow:new-issue" in loops
            assert "workflow:quick-fix" in loops
            assert "back" not in loops, "esc goes back; the key line says so"
            assert "workflow:default" not in loops

            screen.action_back()
            await pilot.pause()
            assert _home_option_ids(screen) == root

    asyncio.run(run())


def test_a_workflow_with_its_own_task_confirms_the_branch_and_cancel_does_not_start(
    monkeypatch,
):
    """With no form to name the branch, a worktree project still confirms the slug first."""
    from types import SimpleNamespace

    import pulse.tui.screens.home as home_module

    onboard_machine()
    monkeypatch.setattr(
        home_module.engine,
        "project_settings",
        lambda _path: SimpleNamespace(use_worktree=True),
    )

    async def run() -> None:
        from textual.app import App, ComposeResult
        from textual.widgets import Input, Static

        from pulse.tui.screens.branch_name import BranchNameScreen

        class Harness(App[None]):
            CSS = COCKPIT_CSS

            def compose(self) -> ComposeResult:
                yield Static("ok")

            def open_cockpit(self, workflow_id: str, prompt: str, branch: str = "") -> None:
                opened.append((workflow_id, prompt, branch))

        opened: list[tuple[str, str, str]] = []
        app = Harness()
        async with app.run_test(size=(80, 24)) as pilot:
            screen = HomeScreen()
            app.push_screen(screen)
            await pilot.pause()
            screen.on_option_selected(_selected("session"))
            screen.on_option_selected(_selected("workflow:review"))
            await pilot.pause()

            assert isinstance(app.screen, BranchNameScreen)
            assert app.screen.query_one("#branch-name", Input).value == "revisar-a-branch-atual"
            app.screen.action_cancel()
            await pilot.pause()
            assert opened == []

    asyncio.run(run())


def test_escape_closes_the_form_before_leaving_the_submenu(monkeypatch):
    """Esc goes one step at a time: closes the run form, then returns to the root."""

    onboard_machine()

    async def run() -> None:
        from textual.app import App, ComposeResult
        from textual.widgets import Static

        class Harness(App[None]):
            CSS = COCKPIT_CSS

            def compose(self) -> ComposeResult:
                yield Static("ok")

        app = Harness()
        async with app.run_test(size=(80, 24)) as pilot:
            screen = HomeScreen()
            app.push_screen(screen)
            await pilot.pause()
            screen.on_option_selected(_selected("session"))
            screen.on_option_selected(_selected("workflow:new-issue"))
            await pilot.pause()

            screen.action_back()
            await pilot.pause()
            assert screen.query_one("#task-form").display is False
            assert "workflow:new-issue" in _home_option_ids(screen)

            screen.action_back()
            await pilot.pause()
            assert _home_option_ids(screen) == ["session", "history", "settings", "exit"]

    asyncio.run(run())


def test_a_workflow_row_shows_its_size_and_description_and_the_hint_its_step_chain(monkeypatch):
    """The row says how big the workflow is; the long step chain goes under the list."""

    onboard_machine()

    async def run() -> None:
        from textual.app import App, ComposeResult
        from textual.widgets import OptionList, Static

        class Harness(App[None]):
            CSS = COCKPIT_CSS

            def compose(self) -> ComposeResult:
                yield Static("ok")

        app = Harness()
        async with app.run_test(size=(80, 24)) as pilot:
            screen = HomeScreen()
            app.push_screen(screen)
            await pilot.pause()
            screen.on_option_selected(_selected("session"))
            await pilot.pause()

            options = screen.query_one("#home-options", OptionList)
            row = options.get_option("workflow:new-issue").prompt.plain.splitlines()
            assert row[0].split() == ["Nova", "spec", "8", "etapas"]
            assert row[1].strip() == "da ideia ao código revisado"

            hint = screen.query_one(".home-hint", Static)
            screen.on_option_highlighted(_highlighted("workflow:new-issue"))
            await pilot.pause()
            assert str(hint.render()).splitlines()[0].startswith("PRD → Techspec → Tasks → ")

    asyncio.run(run())


def test_the_sidebar_nests_the_fan_out_items_under_the_step_name():
    """The fan-out step name stays; its tasks are indented below it."""
    from pulse.tui.state import CockpitState

    make_workflow("demo", steps=[("plan", "Planejar"), ("run", "Implementar")])
    state = CockpitState()
    configure_from_db(state, "demo")
    state.apply_phase_statuses(
        steps=[
            {"id": "plan", "label": "Planejar"},
            {"id": "run:T1", "label": "Criar o endpoint"},
            {"id": "run:T2", "label": "Montar o CSV"},
        ],
        done_ids=["plan", "run:T1"],
    )

    sidebar = PhaseSidebar(state)
    lines = str(sidebar._render_phases(state)).splitlines()

    header = next(line for line in lines if "Implementar" in line)
    assert header.rstrip().endswith("1/2"), "the step name carries how many tasks settled"
    # Unlaid-out, the sidebar draws at its narrowest, so long task names are cut.
    assert any("T1 · Criar o" in line for line in lines)
    assert any("T2 · Montar o" in line for line in lines)
    task = next(line for line in lines if "T1 · Criar o" in line)
    assert _indent(task) > _indent(header)


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def test_new_session_lists_pipelines_and_hides_the_generic_loop():
    """`is_default` marks the generic loop, which the menu leaves out."""
    from pulse.store.workflow_defs import list_workflows
    from pulse.tui.screens.home import _session_workflows

    listed = [item.id for item in _session_workflows()]
    everything = {item.id for item in list_workflows()}

    assert "default" in everything, "the generic loop is still in the database"
    assert "default" not in listed
    assert {"new-issue", "quick-fix", "review"} <= set(listed)

    labels = [item.label for item in _session_workflows()]
    assert labels == sorted(labels), "the menu is alphabetical"


def test_loop_with_builtin_task_starts_without_asking_for_text(monkeypatch):
    """Codebase analysis and project setup inspect the repository, not a request.

    Asking for a task description there had no meaningful answer, so Enter
    starts the run immediately.
    """

    onboard_machine()

    async def run() -> None:
        from textual.app import App, ComposeResult
        from textual.widgets import Static

        class Harness(App[None]):
            CSS = COCKPIT_CSS

            def compose(self) -> ComposeResult:
                yield Static("ok")

            def open_cockpit(self, workflow_id: str, prompt: str) -> None:
                opened.append((workflow_id, prompt))

        opened: list[tuple[str, str]] = []
        app = Harness()
        async with app.run_test(size=(80, 24)) as pilot:
            screen = HomeScreen()
            app.push_screen(screen)
            await pilot.pause()
            screen.on_option_selected(_selected("session"))
            await pilot.pause()

            screen.on_option_selected(_selected("workflow:analyze-codebase"))
            await pilot.pause()
            assert screen.query_one("#task-form").display is False

            screen.on_option_selected(_selected("workflow:setup-project"))
            await pilot.pause()
            assert screen.query_one("#task-form").display is False

            screen.on_option_selected(_selected("workflow:review"))
            await pilot.pause()
            assert screen.query_one("#task-form").display is False

            assert opened == [
                ("analyze-codebase", "Mapear codebase existente"),
                ("setup-project", "Novo projeto"),
                ("review", "Revisar a branch atual"),
            ]

    asyncio.run(run())


def test_hint_says_enter_starts_these_loops(monkeypatch):

    onboard_machine()

    async def run() -> None:
        from textual.app import App, ComposeResult
        from textual.widgets import Static

        class Harness(App[None]):
            CSS = COCKPIT_CSS

            def compose(self) -> ComposeResult:
                yield Static("ok")

        app = Harness()
        async with app.run_test(size=(80, 24)) as pilot:
            screen = HomeScreen()
            app.push_screen(screen)
            await pilot.pause()
            screen.on_option_selected(_selected("session"))
            await pilot.pause()

            screen.on_option_highlighted(_highlighted("workflow:analyze-codebase"))
            await pilot.pause()
            hint = str(screen.query_one(".home-hint", Static).render())
            assert "Enter inicia agora" in hint

            screen.on_option_highlighted(_highlighted("workflow:new-issue"))
            await pilot.pause()
            hint = str(screen.query_one(".home-hint", Static).render())
            assert "Enter para descrever a tarefa" in hint

    asyncio.run(run())


def _waiting_run(run_id: str = "run-7", *, held: float = 180.0) -> dict:
    import time

    return {
        "id": run_id,
        "workflow_id": "new-issue",
        "workflow_label": "Nova spec",
        "prompt": "fazer algo",
        "workspace": "/repo",
        "status": "awaiting_input",
        "active": True,
        "awaiting_prompt": True,
        "awaiting_since": time.time() - held,
        "current_step_label": "Especificar",
        "started_at": time.time() - held - 60,
    }


def test_home_announces_the_sessions_waiting_for_the_user(monkeypatch):
    """Leaving the cockpit with an open question must not hide that the run is waiting."""

    onboard_machine()

    async def run() -> None:
        from textual.app import App, ComposeResult
        from textual.widgets import Static

        class Harness(App[None]):
            CSS = COCKPIT_CSS

            def compose(self) -> ComposeResult:
                yield Static("ok")

        app = Harness()
        async with app.run_test(size=(80, 24)) as pilot:
            screen = HomeScreen()
            app.push_screen(screen)
            await pilot.pause()

            panel = screen.query_one("#home-alerts", Static)
            assert panel.display is False
            assert _home_option_ids(screen) == ["session", "history", "settings", "exit"]

            screen._apply_alerts([_waiting_run()])
            await pilot.pause()
            assert panel.display is True
            text = str(panel.render())
            assert "1 sessão precisa de você" in text
            assert "Nova spec" in text
            assert "Especificar" in text
            assert "há 3min" in text
            assert _home_option_ids(screen)[0] == "alerts"

            screen.on_option_selected(_selected("alerts"))
            await pilot.pause()
            assert _home_option_ids(screen) == ["attach:run-7", "back"]

            screen._apply_alerts([])
            await pilot.pause()
            assert panel.display is False
            assert _home_option_ids(screen) == ["session", "history", "settings", "exit"]

    asyncio.run(run())


def test_home_opens_the_waiting_session_live(monkeypatch):
    """Entering through the alert attaches to the run, where the question is still open."""
    from pathlib import Path as _Path

    class _App:
        def __init__(self) -> None:
            self.opened: list = []

        def open_cockpit(self, workflow_id, prompt, **kwargs):
            self.opened.append((workflow_id, prompt, kwargs))

    class _Screen(HomeScreen):
        fake_app = _App()

        @property
        def app(self):  # type: ignore[override]  # stands in for the running App
            return self.fake_app

    screen = _Screen()
    screen._alerts = [_waiting_run()]
    screen.on_option_selected(_selected("attach:run-7"))

    assert screen.fake_app.opened == [
        (
            "new-issue",
            "fazer algo",
            {"attach_run_id": "run-7", "workspace": _Path("/repo")},
        )
    ]


def test_history_reopens_a_live_run_in_the_cockpit(monkeypatch, tmp_path):
    """An in-progress run the daemon still holds reopens live, not as a page."""
    import pulse.tui.screens.history as history_module
    from pulse.history.models import HistoryItem, HistoryStatus

    item = HistoryItem(
        run_id="run-9",
        workflow_id="new-issue",
        workflow_label="Nova spec",
        title="algo",
        prompt="fazer algo",
        status=HistoryStatus.IN_PROGRESS,
        updated_at="2026-01-01T00:00:00+00:00",
    )
    monkeypatch.setattr(history_module, "active_run_ids", lambda: {"run-9"})

    class _App:
        def __init__(self) -> None:
            self.opened: list = []
            self.pushed: list = []

        def open_cockpit(self, workflow_id, prompt, **kwargs):
            self.opened.append((workflow_id, prompt, kwargs))

        def push_screen(self, screen):
            self.pushed.append(screen)

    class _Screen(history_module.HistoryListScreen):
        fake_app = _App()

        @property
        def app(self):  # type: ignore[override]  # stands in for the running App
            return self.fake_app

    screen = _Screen(workspace=tmp_path)
    screen._items = {"run-9": item}
    screen.on_option_selected(_selected("run-9"))

    assert screen.fake_app.pushed == []
    assert screen.fake_app.opened == [
        (
            "new-issue",
            "fazer algo",
            {"attach_run_id": "run-9", "workspace": tmp_path},
        )
    ]


def test_home_alert_poll_finishing_after_the_app_exited_does_not_crash(monkeypatch):
    """The alert poll runs in a thread; if the app can no longer take its result
    (`call_from_thread` raises `RuntimeError`), the worker ends cleanly instead
    of erroring the whole app."""
    from textual.worker import WorkerState

    import pulse.tui.screens.home as home_module

    onboard_machine()
    monkeypatch.setattr(home_module, "awaiting_runs", lambda: [_waiting_run()])

    async def run() -> None:
        from textual.app import App, ComposeResult
        from textual.widgets import Static

        class Harness(App[None]):
            CSS = COCKPIT_CSS

            def compose(self) -> ComposeResult:
                yield Static("ok")

        app = Harness()
        async with app.run_test(size=(80, 24)) as pilot:
            screen = HomeScreen()
            app.push_screen(screen)
            await pilot.pause()
            await app.workers.wait_for_complete()
            screen._apply_alerts([])

            def _app_gone(*_args) -> None:
                raise RuntimeError("App is not running")

            monkeypatch.setattr(app, "call_from_thread", _app_gone)
            screen._poll_alerts()
            await app.workers.wait_for_complete()
            await pilot.pause()

            assert [worker.state for worker in screen.workers] in ([], [WorkerState.SUCCESS])
            assert screen._alerts == []

    asyncio.run(run())


def test_a_workflow_row_counts_its_steps_and_says_when_it_starts_at_once():
    from pulse.tui.engine import WorkflowShape
    from pulse.tui.screens.home import _workflow_row

    asks = WorkflowShape(id="fix", label="Fix", description="d", steps=(("p", "Plano"),))
    runs = WorkflowShape(
        id="scan", label="Scan", default_prompt="go", steps=(("a", "A"), ("b", "B"))
    )

    assert _workflow_row(asks).value == "1 etapa"
    assert _workflow_row(asks).description == "d"
    assert _workflow_row(runs).value == "2 etapas · inicia direto"
    assert _workflow_row(runs).id == "workflow:scan"


def test_new_session_swaps_the_banner_for_the_picker_and_back_restores_it(monkeypatch):
    """The picker drops the banner for a breadcrumb and a key line; Esc brings the home
    back with the pointer on `Nova sessão`, the row that led there, not on the top row.
    """
    from pathlib import Path

    from textual.app import App, ComposeResult
    from textual.widgets import Footer, Static

    onboard_machine()
    seen: dict[str, object] = {}

    async def run() -> None:
        class Harness(App[None]):
            CSS = COCKPIT_CSS

            def compose(self) -> ComposeResult:
                yield Static("ok")

        app = Harness()
        async with app.run_test(size=(100, 30)) as pilot:
            screen = HomeScreen()
            app.push_screen(screen)
            await pilot.pause()
            # A waiting run puts `alerts` above `session`: the top row is not the answer.
            screen._apply_alerts([_waiting_run()])
            await pilot.pause()
            await pilot.press("down", "down")
            screen.on_option_selected(_selected("session"))
            await pilot.pause()
            seen["picker"] = {
                "brand": screen.query_one(".home-brand").display,
                "footer": screen.query_one(Footer).display,
                "keys": str(screen.query_one("#home-keys", Static).render()),
                "header": str(screen.query_one("#home-header", Static).render()).splitlines()[0],
            }

            await pilot.press("escape")
            await pilot.pause()
            options = screen.query_one("#home-options", MenuList)
            seen["root"] = {
                "brand": screen.query_one(".home-brand").display,
                "keys": screen.query_one("#home-keys").display,
                "pointed": options.pointed.id if options.pointed else None,
            }

    from pulse.tui.widgets.menu_list import MenuList

    asyncio.run(run())
    assert seen["picker"] == {
        "brand": False,
        "footer": False,
        "keys": "↑↓ navegar  ·  enter escolher  ·  esc voltar",
        "header": f"Nova sessão  ·  {Path.cwd().name}",
    }
    assert seen["root"] == {"brand": True, "keys": False, "pointed": "session"}
