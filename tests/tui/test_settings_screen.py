from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import pytest

from pulse.config.project_config import init_project_config, load_project_config
from pulse.store.agent_settings import upsert_agent_settings
from pulse.tui.screens.settings import SettingsScreen
from pulse.tui.theme import COCKPIT_CSS
from tests.tui.conftest import WAIT_SECONDS, wait_until


def test_settings_shows_saved_model_after_select(tmp_path: Path):
    init_project_config(tmp_path)
    project = load_project_config(tmp_path)
    assert project is not None

    async def run() -> None:
        from textual.app import App
        from textual.widgets import OptionList

        class Harness(App[None]):
            CSS = COCKPIT_CSS

            def on_mount(self) -> None:
                self.push_screen(SettingsScreen(cwd=tmp_path))

        app = Harness()
        async with app.run_test(size=(100, 32)) as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, SettingsScreen)
            header = str(screen.query_one("#settings-header").render())
            assert header == f"Configurações  ·  {tmp_path.name}"
            screen._show_pulse_agents()
            await pilot.pause()
            picked = next(
                str(opt.id)
                for opt in screen.query_one(OptionList)._options
                if opt.id and str(opt.id).startswith("workflow:")
            )
            screen._workflow_id = picked.split(":", 1)[1]
            upsert_agent_settings(project.project_id, screen._workflow_id, model="composer-2.5")
            screen._show_workflow_fields()
            await pilot.pause()
            labels = [opt.prompt.plain for opt in screen.query_one(OptionList)._options]
            assert any(label.split() == ["Modelo", "composer-2.5"] for label in labels)
            screen._show_pulse_agents()
            await pilot.pause()
            labels = [opt.prompt.plain for opt in screen.query_one(OptionList)._options]
            assert any(label.endswith("· composer-2.5") for label in labels)

    asyncio.run(run())


def test_settings_model_picker_uses_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    init_project_config(tmp_path)
    project = load_project_config(tmp_path)
    assert project is not None
    seen: dict[str, str | None] = {}

    def fake_models(cwd: Path, agent_name: str | None = None) -> list[str]:
        seen["runtime"] = agent_name
        if agent_name == "claude":
            return ["claude-opus-4.8"]
        return ["gpt-5.5", "composer-2.5"]

    # Listing models spawns each runtime's ACP CLI; the daemon route is real.
    monkeypatch.setattr("pulse.api.settings_routes.collect_available_models", fake_models)

    async def run() -> None:
        from textual.app import App
        from textual.widgets import OptionList

        class Harness(App[None]):
            CSS = COCKPIT_CSS

            def on_mount(self) -> None:
                self.push_screen(SettingsScreen(cwd=tmp_path))

        app = Harness()
        async with app.run_test(size=(100, 32)) as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, SettingsScreen)
            upsert_agent_settings(project.project_id, "default", runtime="claude")
            screen._workflow_id = "default"
            screen._show_workflow_fields()
            screen._open_models()
            await wait_until(
                pilot,
                lambda: any(
                    str(opt.id).startswith("model:claude-opus")
                    for opt in screen.query_one(OptionList)._options
                ),
            )
            labels = [str(opt.prompt) for opt in screen.query_one(OptionList)._options]
            assert seen["runtime"] == "claude"
            assert any("claude-opus-4.8" in label for label in labels)
            assert not any("gpt-5.5" in label for label in labels)

    asyncio.run(run())


def _option_ids(screen: SettingsScreen) -> list[str]:
    from textual.widgets import OptionList

    widget = screen.query_one("#settings-options", OptionList)
    return [str(widget.get_option_at_index(i).id) for i in range(widget.option_count)]


async def _select(pilot, screen: SettingsScreen, option_id: str) -> None:
    from textual.widgets import OptionList

    widget = screen.query_one("#settings-options", OptionList)
    widget.focus()
    widget.highlighted = widget.get_option_index(option_id)
    await pilot.press("enter")
    await pilot.pause()


async def _wait_for_option(pilot, screen: SettingsScreen, prefix: str) -> None:
    """`_load_models` runs in a worker thread; wait for its options to land."""
    await pilot.app.workers.wait_for_complete()
    await pilot.pause()
    assert any(option.startswith(prefix) for option in _option_ids(screen))


def _run_settings(tmp_path: Path, scenario) -> None:
    async def run() -> None:
        from textual.app import App

        class Harness(App[None]):
            CSS = COCKPIT_CSS

            def on_mount(self) -> None:
                self.push_screen(SettingsScreen(cwd=tmp_path))

        app = Harness()
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, SettingsScreen)
            await scenario(pilot, screen)

    asyncio.run(run())


def test_global_settings_menu_saves_each_field(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Each global row opens its picker and the pick lands in the project config."""
    init_project_config(tmp_path)
    monkeypatch.setattr(
        "pulse.api.settings_routes.collect_available_models",
        lambda cwd, agent_name=None: ["model-a", "model-b"],
    )
    picked: dict[str, str] = {}

    async def scenario(pilot, screen: SettingsScreen) -> None:
        assert _option_ids(screen)[:2] == ["global", "agents"]
        await _select(pilot, screen, "global")
        assert _option_ids(screen) == ["g_agent", "g_model", "g_permission"]

        await _select(pilot, screen, "g_permission")
        assert _option_ids(screen) == ["policy:ask", "policy:auto_approve", "policy:deny_writes"]
        await _select(pilot, screen, "policy:deny_writes")
        assert _option_ids(screen) == ["g_agent", "g_model", "g_permission"]

        await _select(pilot, screen, "g_model")
        await _wait_for_option(pilot, screen, "model:")
        assert _option_ids(screen) == ["model:model-a", "model:model-b"]
        await _select(pilot, screen, "model:model-b")
        assert _option_ids(screen) == ["g_agent", "g_model", "g_permission"]

        await _select(pilot, screen, "g_agent")
        runtimes = _option_ids(screen)
        assert runtimes
        assert all(option.startswith("agent:") for option in runtimes)
        picked["runtime"] = runtimes[-1].split(":", 1)[1]
        await _select(pilot, screen, runtimes[-1])
        assert _option_ids(screen) == ["g_agent", "g_model", "g_permission"]

    _run_settings(tmp_path, scenario)
    project = load_project_config(tmp_path)
    assert project is not None
    assert project.permission_policy == "deny_writes"
    assert project.model == "model-b"
    assert project.default_agent == picked["runtime"]


def test_agent_settings_menu_saves_per_agent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Picking an agent edits that agent only; back returns to the agent list."""
    from pulse.store.agent_settings import load_agent_settings

    init_project_config(tmp_path)
    monkeypatch.setattr(
        "pulse.api.settings_routes.collect_available_models",
        lambda cwd, agent_name=None: ["model-x"],
    )
    picked: dict[str, str] = {}

    async def scenario(pilot, screen: SettingsScreen) -> None:
        await _select(pilot, screen, "agents")
        agents = _option_ids(screen)
        assert agents
        assert all(option.startswith("workflow:") for option in agents)
        picked["agent"] = agents[0].split(":", 1)[1]

        await _select(pilot, screen, agents[0])
        assert _option_ids(screen) == ["wf_agent", "wf_model", "wf_permission"]
        await _select(pilot, screen, "wf_agent")
        runtime_option = _option_ids(screen)[-1]
        picked["runtime"] = runtime_option.split(":", 1)[1]
        await _select(pilot, screen, runtime_option)
        await _select(pilot, screen, "wf_permission")
        await _select(pilot, screen, "policy:auto_approve")
        await _select(pilot, screen, "wf_model")
        await _wait_for_option(pilot, screen, "model:")
        await _select(pilot, screen, "model:model-x")
        assert _option_ids(screen) == ["wf_agent", "wf_model", "wf_permission"]

        await pilot.press("escape")
        await pilot.pause()
        assert _option_ids(screen) == agents

    _run_settings(tmp_path, scenario)
    project = load_project_config(tmp_path)
    assert project is not None
    stored = load_agent_settings(project.project_id, picked["agent"])
    assert stored["runtime"] == picked["runtime"]
    assert stored["permission_policy"] == "auto_approve"
    assert stored["model"] == "model-x"


def test_worktree_and_doctor_rows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The worktree row toggles the project flag; doctor shows a report and goes back."""
    init_project_config(tmp_path)
    _git_init(tmp_path)
    # The doctor runs every runtime's CLI; what matters here is the report row.
    monkeypatch.setattr("pulse.api.system_routes.run_doctor_checks", lambda: [])

    async def scenario(pilot, screen: SettingsScreen) -> None:
        root = ["global", "agents", "worktree", "atomic", "pull_request", "doctor"]
        assert _option_ids(screen) == root
        await _select(pilot, screen, "atomic")
        assert "Worktree" in str(screen.query_one("#settings-report").render())
        await _select(pilot, screen, "worktree")
        await _select(pilot, screen, "atomic")
        await _select(pilot, screen, "pull_request")
        assert _option_ids(screen) == root
        await _select(pilot, screen, "doctor")
        assert _option_ids(screen) == ["back"]
        await _select(pilot, screen, "back")
        assert _option_ids(screen) == root

    _run_settings(tmp_path, scenario)
    project = load_project_config(tmp_path)
    assert project is not None
    assert project.use_worktree is True


def test_the_doctor_report_shows_each_check_as_an_icon_and_its_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A failed check reads as `✗`, not only as red: the icon carries the state.

    Messages are shown as written, never parsed as Rich markup.
    """
    from textual.widgets import Static

    from pulse.doctor.checks import CheckResult

    init_project_config(tmp_path)
    checks = [
        CheckResult(name="cli", status="ok", message="agent [1.0]", detail=""),
        CheckResult(name="auth", status="fail", message="not logged in", detail=""),
        CheckResult(name="login", status="warn", message="inconclusive", detail=""),
    ]
    monkeypatch.setattr("pulse.api.system_routes.run_doctor_checks", lambda: checks)
    shown: list[str] = []

    async def scenario(pilot, screen: SettingsScreen) -> None:
        await _select(pilot, screen, "doctor")
        await pilot.app.workers.wait_for_complete()
        await pilot.pause()
        report = screen.query_one("#settings-report", Static)
        shown.append(str(report.render()))

    _run_settings(tmp_path, scenario)
    assert shown[0].splitlines()[:3] == ["✓ agent [1.0]", "✗ not logged in", "! inconclusive"]


def _report(screen: SettingsScreen) -> str:
    return str(screen.query_one("#settings-report").render())


def test_a_doctor_report_from_an_earlier_visit_never_replaces_the_current_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Leaving and reopening the doctor starts a new report; the late first one is dropped."""
    from pulse.tui.engine import Check

    init_project_config(tmp_path)
    calls: list[int] = []
    release = threading.Event()

    def doctor_checks() -> list[Check]:
        calls.append(len(calls))
        if len(calls) == 1:
            release.wait(WAIT_SECONDS)
            return [Check(name="old", status="ok", message="primeira visita", detail="")]
        return [Check(name="new", status="ok", message="segunda visita", detail="")]

    monkeypatch.setattr("pulse.tui.engine.doctor_checks", doctor_checks)
    shown: list[str] = []

    async def scenario(pilot, screen: SettingsScreen) -> None:
        await _select(pilot, screen, "doctor")
        await wait_until(pilot, lambda: len(calls) == 1)
        await pilot.press("escape")
        await pilot.pause()
        await _select(pilot, screen, "doctor")
        await wait_until(pilot, lambda: "segunda visita" in _report(screen))

        release.set()
        await pilot.app.workers.wait_for_complete()
        await pilot.pause()
        shown.append(_report(screen))

    _run_settings(tmp_path, scenario)
    assert "segunda visita" in shown[0]
    assert "primeira visita" not in shown[0]


def test_a_model_list_that_lands_after_leaving_never_takes_over_the_menu(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A late list would turn the visible menu into a model picker for whatever is open now."""
    init_project_config(tmp_path)
    asked = threading.Event()
    release = threading.Event()

    def models(_workspace: Path, _runtime: str) -> list[str]:
        asked.set()
        release.wait(WAIT_SECONDS)
        return ["model-late"]

    monkeypatch.setattr("pulse.tui.engine.models", models)
    seen: list[list[str]] = []

    async def scenario(pilot, screen: SettingsScreen) -> None:
        await _select(pilot, screen, "global")
        await _select(pilot, screen, "g_model")
        await wait_until(pilot, asked.is_set)
        await pilot.press("escape")
        await pilot.pause()
        await _select(pilot, screen, "global")
        await _select(pilot, screen, "g_permission")

        release.set()
        await pilot.app.workers.wait_for_complete()
        await pilot.pause()
        seen.append(_option_ids(screen))

    _run_settings(tmp_path, scenario)
    assert seen == [["policy:ask", "policy:auto_approve", "policy:deny_writes"]]


def _pointed(screen: SettingsScreen) -> str:
    from textual.widgets import OptionList

    widget = screen.query_one("#settings-options", OptionList)
    assert widget.highlighted is not None
    return str(widget.get_option_at_index(widget.highlighted).id)


def test_leaving_a_picker_puts_the_pointer_back_on_the_row_that_opened_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Esc or a pick returns to the row the user came from, not to the top of the menu."""
    init_project_config(tmp_path)
    monkeypatch.setattr(
        "pulse.api.settings_routes.collect_available_models",
        lambda cwd, agent_name=None: ["model-a", "model-b"],
    )
    pointed: list[str] = []

    async def scenario(pilot, screen: SettingsScreen) -> None:
        await _select(pilot, screen, "global")
        await _select(pilot, screen, "g_permission")
        await pilot.press("escape")
        await pilot.pause()
        pointed.append(_pointed(screen))

        await _select(pilot, screen, "g_model")
        await _wait_for_option(pilot, screen, "model:")
        await _select(pilot, screen, "model:model-b")
        pointed.append(_pointed(screen))

        await pilot.press("escape")
        await pilot.pause()
        pointed.append(_pointed(screen))

    _run_settings(tmp_path, scenario)
    assert pointed == ["g_permission", "g_model", "global"]


def test_a_picker_opens_on_the_current_choice(tmp_path: Path):
    """The pointer starts where the setting already is, marked with a check."""
    from textual.widgets import OptionList

    init_project_config(tmp_path)
    seen: dict[str, object] = {}

    async def scenario(pilot, screen: SettingsScreen) -> None:
        await _select(pilot, screen, "global")
        await _select(pilot, screen, "g_permission")
        await _select(pilot, screen, "policy:deny_writes")
        await _select(pilot, screen, "g_permission")
        widget = screen.query_one("#settings-options", OptionList)
        seen["pointed"] = _pointed(screen)
        seen["checked"] = [
            str(widget.get_option_at_index(i).id)
            for i in range(widget.option_count)
            if widget.get_option_at_index(i).prompt.plain.endswith("✓")
        ]

    _run_settings(tmp_path, scenario)
    assert seen == {"pointed": "policy:deny_writes", "checked": ["policy:deny_writes"]}


def test_space_flips_a_toggle_and_the_pointer_stays_on_it(tmp_path: Path):
    """Flipping a setting redraws the menu; the pointer must not jump back to the top."""
    init_project_config(tmp_path)
    _git_init(tmp_path)
    seen: dict[str, object] = {}

    async def scenario(pilot, screen: SettingsScreen) -> None:
        from textual.widgets import OptionList

        widget = screen.query_one("#settings-options", OptionList)
        widget.highlighted = widget.get_option_index("worktree")
        await pilot.press("space")
        await pilot.pause()
        seen["pointed"] = _pointed(screen)
        seen["row"] = widget.get_option(_pointed(screen)).prompt.plain.splitlines()[0]

    _run_settings(tmp_path, scenario)
    project = load_project_config(tmp_path)
    assert project is not None
    assert project.use_worktree is True
    assert seen["pointed"] == "worktree"
    assert seen["row"].split() == ["❯", "Worktree", "●", "ligado"]


def test_an_unavailable_toggle_says_what_it_needs_before_it_is_tried(tmp_path: Path):
    """The prerequisite shows under the row, so nobody has to press it to learn why."""
    init_project_config(tmp_path)
    _git_init(tmp_path)
    rows: dict[str, list[str]] = {}

    async def scenario(pilot, screen: SettingsScreen) -> None:
        from textual.widgets import OptionList

        widget = screen.query_one("#settings-options", OptionList)
        for option_id in ("atomic", "pull_request"):
            rows[option_id] = widget.get_option(option_id).prompt.plain.splitlines()

    _run_settings(tmp_path, scenario)
    assert rows["atomic"][0].split()[-2:] == ["○", "desligado"]
    assert rows["atomic"][1].strip() == "Um commit por entrega"
    assert rows["pull_request"][0].split()[-2:] == ["–", "indisponível"]
    assert rows["pull_request"][1].strip() == (
        "PR/MR só liga com o Worktree e o Autocommit ligados."
    )


def _git_init(path: Path) -> None:
    import subprocess

    subprocess.run(["git", "init", "-q", str(path)], check=True)  # noqa: S603, S607 - fixed argv, test repo
