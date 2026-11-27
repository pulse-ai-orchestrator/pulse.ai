from __future__ import annotations

import asyncio

from pulse.tui.app import PulseApp
from pulse.tui.screens.cockpit import CockpitScreen
from pulse.tui.state import LogKind, PhaseStatus
from pulse.tui.theme import COCKPIT_CSS
from pulse.tui.widgets.log_stream import LogStream
from pulse.tui.widgets.phase_sidebar import PhaseSidebar
from tests.conftest import configure_from_db, make_workflow


def test_pulse_app_has_cockpit_theme():
    app = PulseApp()
    assert app.CSS == COCKPIT_CSS
    assert "#A2D729" in COCKPIT_CSS
    assert "SettingsScreen" in COCKPIT_CSS
    assert "OnboardingScreen" in COCKPIT_CSS
    assert "HistoryListScreen" in COCKPIT_CSS


def test_cockpit_screen_initial_state():
    make_workflow("demo", steps=[("a", "A"), ("b", "B"), ("c", "C"), ("d", "D")])
    screen = CockpitScreen("demo", "demo feature")
    assert len(screen.state.phases) == 4
    assert all(phase.status == PhaseStatus.PENDING for phase in screen.state.phases)
    assert screen.workflow_id == "demo"
    assert screen.state.entries == []


def test_log_stream_and_sidebar_render_text():
    async def run() -> None:
        from textual.app import App, ComposeResult
        from textual.containers import Horizontal

        state_holder: dict = {}

        class Harness(App[None]):
            CSS = COCKPIT_CSS

            def compose(self) -> ComposeResult:
                make_workflow("quick", steps=[("plan", "Planejar"), ("run", "Implementar")])
                screen = CockpitScreen("quick", "demo")
                state_holder["screen"] = screen
                with Horizontal(id="cockpit-body"):
                    yield PhaseSidebar(screen.state, id="phase-sidebar")
                    yield LogStream(screen.state, id="log-stream")

            def on_mount(self) -> None:
                screen = state_holder["screen"]
                screen.sink.begin_phase("Planejar")
                screen.sink.handle_update(
                    {
                        "update": {
                            "sessionUpdate": "tool_call",
                            "toolCallId": "t1",
                            "title": "Read File",
                            "kind": "read",
                            "rawInput": {"path": "/repo/pulse/cli.py"},
                        }
                    }
                )
                screen.sink.handle_update(
                    {
                        "update": {
                            "sessionUpdate": "agent_message_chunk",
                            "content": {"type": "text", "text": "Plano pronto"},
                        }
                    }
                )
                screen.sink.error(
                    "Classificação cancelada",
                    "O agente não definiu o flow (quick ou full).",
                )
                self.query_one(PhaseSidebar).sync_from_state(screen.state)
                self.query_one(LogStream).sync_from_state(screen.state, force=True)

        app = Harness()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            content = str(app.query_one("#stream-content").render())
            phases = str(app.query_one("#phase-content").render())
            assert "Read" in content
            assert "Plano" in content
            assert "Assistente" in content
            assert "Erro" in content
            assert "Classificação cancelada" in content
            assert "flow" in content
            assert "Planejar" in phases
            assert LogKind.READ in {entry.kind for entry in state_holder["screen"].state.entries}

    asyncio.run(run())


def test_cockpit_layout_keeps_header_and_body_sizes():
    async def run() -> None:
        from textual.app import App, ComposeResult
        from textual.containers import Horizontal

        from pulse.tui.state import CockpitState
        from pulse.tui.widgets.app_footer import AppFooter
        from pulse.tui.widgets.app_header import AppHeader

        make_workflow("demo", steps=[("a", "A"), ("b", "B"), ("c", "C"), ("d", "D")])
        state = CockpitState()
        configure_from_db(state, "demo")

        class Harness(App[None]):
            CSS = COCKPIT_CSS

            def compose(self) -> ComposeResult:
                yield AppHeader()
                with Horizontal(id="cockpit-body"):
                    yield PhaseSidebar(state, id="phase-sidebar")
                    yield LogStream(state, id="log-stream")
                yield AppFooter()

            def on_mount(self) -> None:
                self.query_one(AppHeader).sync_from_state(state)
                self.query_one(PhaseSidebar).sync_from_state(state)
                self.query_one(LogStream).sync_from_state(state, force=True)
                self.query_one(AppFooter).sync_from_state(state)

        app = Harness()
        async with app.run_test(size=(120, 32)) as pilot:
            await pilot.pause()
            header = app.query_one(AppHeader)
            body = app.query_one("#cockpit-body")
            footer = app.query_one(AppFooter)
            sidebar = app.query_one(PhaseSidebar)
            stream = app.query_one(LogStream)
            assert header.outer_size.height == 3
            assert footer.size.height == 1
            assert body.size.height == 28
            assert body.size.width == 120
            assert sidebar.size.height >= 24
            assert stream.size.height >= 24
            assert sidebar.size.width >= 20
            assert stream.size.width > sidebar.size.width
            assert "0/4" in str(app.query_one("#run-status").render())

    asyncio.run(run())


def test_leaving_the_cockpit_does_not_cancel_the_run():
    """`q` detaches the stream and abandons the prompts; nothing stops the run."""
    make_workflow("demo", steps=[("a", "A")])

    class _Session:
        def __init__(self) -> None:
            self.detached = False
            self.stopped = False

        def detach(self) -> None:
            self.detached = True

        def stop(self) -> bool:
            self.stopped = True
            return True

    class _App:
        def __init__(self) -> None:
            self.popped = 0

        def pop_screen(self) -> None:
            self.popped += 1

    class _Screen(CockpitScreen):
        """Unmounted screen: `action_back_to_menu` does not depend on widgets."""

        fake_app = _App()

        @property
        def app(self):  # type: ignore[override]  # stands in for the running App
            return self.fake_app

    screen = _Screen("demo", "x")
    session = _Session()
    screen._session = session
    screen.state.running = True
    used: list[str] = []
    screen.bridge.abandon = lambda: used.append("abandon")  # type: ignore[method-assign]  # records the call
    screen.bridge.close = lambda: used.append("close")  # type: ignore[method-assign]  # records the call

    screen.action_back_to_menu()

    assert session.detached is True
    assert session.stopped is False, "leaving is not stopping"
    assert screen.fake_app.popped == 1
    assert used == ["abandon"]


def test_leaving_before_the_first_step_still_detaches():
    """A run that has not opened a step yet is alive too: leaving detaches, not closes.

    Before the first `phase.begin` (`state.running` still false), leaving closed
    the bridge without detaching, and the orphan session auto-cancelled the run's
    prompts, including those shown by a reattached screen.
    """
    make_workflow("demo", steps=[("a", "A")])

    class _Session:
        detached = False

        def detach(self) -> None:
            self.detached = True

    class _App:
        def pop_screen(self) -> None:
            pass

    class _Screen(CockpitScreen):
        fake_app = _App()

        @property
        def app(self):  # type: ignore[override]  # stands in for the running App
            return self.fake_app

    screen = _Screen("demo", "x")
    session = _Session()
    screen._session = session
    assert screen.state.running is False
    used: list[str] = []
    screen.bridge.abandon = lambda: used.append("abandon")  # type: ignore[method-assign]  # records the call
    screen.bridge.close = lambda: used.append("close")  # type: ignore[method-assign]  # records the call

    screen.action_back_to_menu()

    assert session.detached is True
    assert used == ["abandon"]


class _FakeEngineSession:
    """Stands in for `EngineRunSession`: returns `code` or raises `error`."""

    error: Exception | None = None
    code = 0

    def __init__(self, **_kwargs) -> None:
        pass

    def run(self, **_kwargs) -> int:
        if self.error is not None:
            raise self.error
        return self.code


class _ThreadApp:
    """The slice of `App` the run worker calls once the run is over."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.done: list[int] = []

    def call_from_thread(self, callback, code: int) -> None:
        if self.error is not None:
            raise self.error
        self.done.append(code)


def _worker_screen(fake_app: _ThreadApp) -> CockpitScreen:
    make_workflow("demo", steps=[("a", "A")])

    class _Screen(CockpitScreen):
        @property
        def app(self):  # type: ignore[override]  # stands in for the running App
            return fake_app

    return _Screen("demo", "x")


def test_a_run_whose_daemon_is_unreachable_ends_failed_with_the_reason(monkeypatch):
    """The run worker is a thread top-level: a transport error must become the
    run's visible error and exit code 1, never an exception that kills the UI."""
    import httpx

    import pulse.client.run_session as run_session

    class _Unreachable(_FakeEngineSession):
        error = httpx.ConnectError("daemon socket refused")

    monkeypatch.setattr(run_session, "EngineRunSession", _Unreachable)
    fake_app = _ThreadApp()
    screen = _worker_screen(fake_app)

    screen._run_workflow()

    errors = [entry for entry in screen.state.entries if entry.kind == LogKind.ERROR]
    assert [(entry.title, entry.detail) for entry in errors] == [
        ("Workflow falhou", "daemon socket refused")
    ]
    assert screen.state.exit_code == 1
    assert fake_app.done == [1]


def test_a_run_ending_after_the_app_exited_still_records_the_exit_code(monkeypatch):
    """Quitting the app leaves no loop to hand the result to (`RuntimeError`);
    the worker must still finish quietly with the run's state up to date."""
    import pulse.client.run_session as run_session

    monkeypatch.setattr(run_session, "EngineRunSession", _FakeEngineSession)
    screen = _worker_screen(_ThreadApp(RuntimeError("App is not running")))

    screen._run_workflow()

    assert screen._run_over is True
    assert screen.state.exit_code == 0
    assert not [entry for entry in screen.state.entries if entry.kind == LogKind.ERROR]


def test_header_labels_follow_state_even_though_watchers_fire_before_compose():
    """Reactive watchers run before `compose` mounts the labels; that first call
    must be a no-op, and later changes must reach the labels."""
    from textual.app import App, ComposeResult
    from textual.widgets import Static

    from pulse.tui.widgets.app_header import AppHeader

    async def run() -> None:
        class Harness(App[None]):
            CSS = COCKPIT_CSS

            def compose(self) -> ComposeResult:
                yield AppHeader()

        app = Harness()
        async with app.run_test(size=(80, 24)) as pilot:
            header = app.query_one(AppHeader)
            header.run_label = "RUN 1/3"
            header.workflow_label = "demo"
            await pilot.pause()
            assert str(header.query_one("#run-status", Static).render()) == "RUN 1/3"
            assert str(header.query_one("#workflow-label", Static).render()) == "demo"

    asyncio.run(run())


def test_unmounted_log_stream_has_no_prompt_to_focus():
    """Focusing the prompt before the stream is composed reports `False`, not a crash."""
    from pulse.tui.state import CockpitState

    assert LogStream(CockpitState()).focus_prompt() is False


def test_click_on_an_unmounted_sidebar_is_ignored():
    """A click routed before the sidebar composed its content selects nothing."""
    from textual.events import Click

    from pulse.tui.state import CockpitState

    make_workflow("demo", steps=[("a", "A")])
    state = CockpitState()
    configure_from_db(state, "demo")
    sidebar = PhaseSidebar(state)
    posted: list = []
    sidebar.post_message = posted.append  # type: ignore[method-assign]  # records the message

    sidebar.on_click(Click(sidebar, 1, 1, 0, 0, 1, False, False, False, screen_x=1, screen_y=1))

    assert posted == []
