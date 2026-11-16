"""Waiting for the user does not count as agent work.

While a prompt is open (permission, questionnaire, approval, retry menu) the run
is alive but paused: the step clock freezes, the waited time is excluded from the
stored duration, and the run is listed as `awaiting_input`.
"""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from pulse.acp.session_runner import AcpSessionRunner
from pulse.acp.watched_prompts import WatchedPrompts
from pulse.domain.control import RUN_STOPPED
from pulse.domain.ports import NullPromptPort
from pulse.domain.run import RunRecord, RunStatus, StepRecord, StepStatus
from pulse.history.events import PhaseItem, PhaseStatus
from pulse.history.session_log import RecordedSessionLog
from pulse.orchestrator.waits import RunWaits
from pulse.runtimes import get_runtime
from pulse.store import runs as run_store
from pulse.store.runs import SqliteRunRepository
from pulse.tui.hydrate import _stamp_persisted
from pulse.tui.state import CockpitState
from tests.conftest import served_log, store_step, wait_for_event
from tests.orchestrator.test_run_context import _ReplayClient

_HALF_SECOND = 0.5


def _run_with_step(step_id: str = "one") -> RunRecord:
    return run_store.create_run(
        run_id="run-1",
        workflow_id="demo",
        workspace=Path.cwd(),
        user_prompt="tarefa",
        steps=[StepRecord(step_id=step_id, position=1, label="Um", agent_id="tester")],
    )


def test_the_step_clock_freezes_while_the_question_is_open():
    phase = PhaseItem(id="one", label="Um", status=PhaseStatus.RUNNING, started_at=0.0)
    assert phase.elapsed_label(now=10.0) == "00:10"

    phase.begin_waiting(now=10.0)
    assert phase.elapsed_label(now=310.0) == "00:10"
    assert phase.display_status() == "awaiting_input"

    phase.end_waiting(now=310.0)
    assert phase.elapsed_label(now=320.0) == "00:20"
    assert phase.display_status() == PhaseStatus.RUNNING.value


def test_two_waits_in_the_same_step_both_come_off_the_clock():
    phase = PhaseItem(id="one", label="Um", status=PhaseStatus.RUNNING, started_at=0.0)
    phase.begin_waiting(now=5.0)
    phase.end_waiting(now=65.0)
    phase.begin_waiting(now=70.0)
    phase.end_waiting(now=100.0)
    assert phase.elapsed_label(now=100.0) == "00:10"


def test_finishing_a_step_that_is_waiting_closes_the_wait():
    phase = PhaseItem(id="one", label="Um", status=PhaseStatus.RUNNING, started_at=0.0)
    phase.begin_waiting(now=10.0)
    phase.finish(ended_at=40.0)
    assert phase.awaiting_since is None
    assert phase.elapsed_label() == "00:10"


def test_cockpit_state_marks_the_running_phase_and_the_run():
    state = CockpitState()
    state.phases = [
        PhaseItem(id="one", label="Um", status=PhaseStatus.DONE),
        PhaseItem(id="two", label="Dois", status=PhaseStatus.RUNNING, started_at=0.0),
    ]

    state.begin_waiting()
    assert state.awaiting_input is True
    assert state.phases[1].awaiting_since is not None
    assert state.phases[0].awaiting_since is None

    state.end_waiting()
    assert state.awaiting_input is False
    assert state.phases[1].awaiting_since is None


def test_stopping_a_waiting_run_clears_the_wait():
    state = CockpitState()
    state.phases = [PhaseItem(id="one", label="Um", status=PhaseStatus.RUNNING, started_at=0.0)]
    state.begin_waiting()
    state.mark_stopped()
    assert state.awaiting_input is False
    assert state.phases[0].awaiting_since is None
    assert state.phases[0].status == PhaseStatus.PENDING


def test_waits_accumulate_on_the_step_and_survive_a_save():
    run = _run_with_step()
    run.start_step("one")
    waits = RunWaits(run, SqliteRunRepository())

    waits.user_wait_ended("one", 30.0)
    waits.user_wait_ended("one", 12.5)
    assert run_store.load_run(run.id).steps[0].waiting_seconds == 42.5

    run.steps[0].start()
    run.steps[0].deliver()
    run_store.save(run)
    assert run_store.load_run(run.id).steps[0].waiting_seconds == 42.5


def test_a_wait_for_a_step_that_is_not_there_charges_nobody():
    """The resume menu asks before any step runs."""
    run = _run_with_step()
    RunWaits(run, SqliteRunRepository()).user_wait_ended("fantasma", 10.0)
    assert run_store.load_run(run.id).steps[0].waiting_seconds == 0.0


def test_concurrent_waits_lose_no_time():
    """Waits close on the ACP reader, the MCP bridge and the engine thread alike."""
    run = _run_with_step()
    run.start_step("one")
    waits = RunWaits(run, SqliteRunRepository())
    workers = 8
    start = threading.Barrier(workers)

    def close_one() -> None:
        start.wait()
        for _ in range(25):
            waits.user_wait_ended("one", 1.0)

    threads = [threading.Thread(target=close_one) for _ in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert run.steps[0].waiting_seconds == workers * 25
    assert run_store.load_run(run.id).steps[0].waiting_seconds == workers * 25


def test_a_database_from_before_the_column_gains_it_on_open(tmp_path: Path):
    """An already-deployed database must not break or lose the old run."""
    import sqlite3

    from pulse.store.db import connect

    db_path = tmp_path / "antigo.db"
    connect(db_path).close()

    raw = sqlite3.connect(str(db_path))
    raw.execute("ALTER TABLE run_steps DROP COLUMN waiting_seconds")
    # A database from before the column also predates the schema version.
    raw.execute("PRAGMA user_version = 0")
    raw.commit()
    raw.close()

    run_store.create_run(
        run_id="run-velha",
        workflow_id="demo",
        workspace=tmp_path,
        user_prompt="x",
        steps=[StepRecord(step_id="one", position=1, label="Um", agent_id="tester")],
        db_path=db_path,
    )
    record = run_store.load_run("run-velha", db_path=db_path)
    assert record.steps[0].waiting_seconds == 0.0


@pytest.mark.usefixtures("in_process_daemon")
def test_history_duration_discounts_the_wait():
    run = _run_with_step()
    step = run.steps[0]
    step.started_at = datetime(2026, 10, 1, 10, 0, tzinfo=UTC)
    step.ended_at = datetime(2026, 10, 1, 10, 10, tzinfo=UTC)
    step.status = "done"
    step.add_wait(540.0)
    run_store.save(run)

    state = CockpitState()
    state.phases = [PhaseItem(id="one", label="Um", status=PhaseStatus.DONE)]
    _stamp_persisted(state, served_log(run.id))
    assert state.phases[0].elapsed_label() == "01:00"


def _permission(kind: str = "edit") -> dict:
    return {
        "permission": {"title": "Editar app.py", "kind": kind},
        "toolCall": {"kind": kind, "rawInput": {"path": "/repo/app.py"}},
        "options": [
            {"optionId": "allow-once", "kind": "allow_once"},
            {"optionId": "reject-once", "kind": "reject_once"},
        ],
    }


def _port_and_bus():
    """The daemon port as the engine sees it: through the runner proxy, where
    the policy decides before opening the wait."""
    from pulse.daemon.adapters import ApiPromptPort, ApiStreamSink
    from pulse.daemon.events import EventBus, PromptCorrelator

    bus = EventBus()
    correlator = PromptCorrelator(bus)
    runner = AcpSessionRunner(
        ["echo"],
        cwd=str(Path.cwd()),
        stream=ApiStreamSink(bus, run_id="r1"),
        prompt_handler=ApiPromptPort(correlator),
        runtime=get_runtime("cursor"),
        session_log=RecordedSessionLog(project_root=Path.cwd()),
    )
    return runner._prompt_handler, correlator, bus


def test_a_permission_the_policy_resolves_never_becomes_a_question():
    """With the cockpit closed, an `edit` under `deny_writes` used to hang the run.

    The daemon published a prompt nobody could answer for a decision the policy
    had already made.
    """
    for policy, expected in [("deny_writes", "reject-once"), ("auto_approve", "allow-once")]:
        port, correlator, bus = _port_and_bus()
        answer = port.respond_to_permission(_permission(), policy=policy)
        assert answer["outcome"]["optionId"] == expected
        assert correlator.pending() == [], f"{policy} must not leave a prompt open"
        assert [e for e in bus._history if e["type"] == "prompt.request"] == []
        assert [e for e in bus._history if e["type"] == "run.awaiting"] == [], policy


def test_a_policy_decision_never_touches_the_run_status():
    """Each tool call in an `auto_approve` step used to store `awaiting_input` then
    `running`, making the run flicker in Home and history."""
    run = _run_with_step()
    run.start_step("one")
    run_store.save(run)
    port, _correlator, _bus = _port_and_bus()
    runner = port._on_enter.__self__
    runner.bind_run(run.id, RunWaits(run, SqliteRunRepository()))

    port.respond_to_permission(_permission(), policy="auto_approve")

    assert run.status == RunStatus.RUNNING
    assert run_store.load_run(run.id).status == RunStatus.RUNNING


def test_the_terminal_veto_is_decided_without_asking_anyone():
    """Terminal is a Pulse veto, not a question: not even `ask` prompts for it."""
    for kind in ("terminal", "shell", "bash", "run_command"):
        port, correlator, _bus = _port_and_bus()
        answer = port.respond_to_permission(_permission(kind), policy="ask")
        assert answer["outcome"]["optionId"] == "reject-once", kind
        assert correlator.pending() == [], kind


def test_a_permission_that_needs_a_person_still_waits():
    """Under `ask`, asking is the point, so it still waits."""
    from concurrent.futures import ThreadPoolExecutor

    port, correlator, bus = _port_and_bus()
    with ThreadPoolExecutor(max_workers=1) as pool:
        asking = pool.submit(port.respond_to_permission, _permission(), policy="ask")
        wait_for_event(bus, "prompt.request")
        pending = correlator.pending()
        assert len(pending) == 1
        correlator.answer(
            pending[0].id, {"outcome": {"outcome": "selected", "optionId": "allow-once"}}
        )
        assert asking.result(timeout=5)["outcome"]["optionId"] == "allow-once"


def test_waiting_runs_come_oldest_first_and_say_how_long(monkeypatch):
    import pulse.client.active_runs as active_runs_module
    from pulse.client.active_runs import awaiting_runs
    from pulse.history.run_lines import describe, waiting_for

    now = 1_000_000.0
    runs = [
        {"id": "nova", "awaiting_prompt": True, "awaiting_since": now - 30, "active": True},
        {"id": "velha", "awaiting_prompt": True, "awaiting_since": now - 4000, "active": True},
        {"id": "rodando", "awaiting_prompt": False, "active": True},
    ]
    monkeypatch.setattr(active_runs_module, "list_runs", lambda: runs)

    assert [item["id"] for item in awaiting_runs()] == ["velha", "nova"]

    assert waiting_for(runs[0], now=now) == "30s"
    assert waiting_for(runs[1], now=now) == "1h06"
    assert waiting_for({"id": "x"}, now=now) == ""

    line = describe(
        {
            "workflow_label": "Nova spec",
            "current_step_label": "Especificar",
            "awaiting_prompt": True,
            "awaiting_since": time.time() - 180,
        }
    )
    assert line == "Nova spec · Especificar · precisa de você há 3min"


class _Sink:
    def __init__(self) -> None:
        self.events: list[str] = []

    def begin_user_wait(self) -> None:
        self.events.append("begin")

    def end_user_wait(self) -> None:
        self.events.append("end")


class _Port:
    """Port that asks another question in the middle of the first: a nested wait."""

    def __init__(self, runner: AcpSessionRunner | None = None) -> None:
        self._runner = runner
        self.asked: list[str] = []

    def ask_text(self, prompt: str, *, title: str = "") -> str:
        self.asked.append(prompt)
        if self._runner is not None and len(self.asked) == 1:
            self._runner._prompt_handler.select_choice("e isso?", [])
        return "ok"

    def select_choice(self, prompt: str, choices, *, title: str = ""):
        self.asked.append(prompt)
        return None


def _runner(sink: _Sink, port: _Port) -> AcpSessionRunner:
    return AcpSessionRunner(
        ["echo"],
        cwd=str(Path.cwd()),
        stream=sink,
        prompt_handler=port,
        runtime=get_runtime("cursor"),
        session_log=RecordedSessionLog(project_root=Path.cwd()),
    )


def test_every_question_opens_and_closes_exactly_one_wait():
    sink = _Sink()
    runner = _runner(sink, _Port())
    runner._prompt_handler.ask_text("e agora?")
    assert sink.events == ["begin", "end"]


def test_a_question_inside_another_is_one_wait_only():
    """Otherwise the nested wait would discount the same time twice."""
    sink = _Sink()
    port = _Port()
    runner = _runner(sink, port)
    port._runner = runner
    runner._prompt_handler.ask_text("e agora?")
    assert sink.events == ["begin", "end"]
    assert len(port.asked) == 2


class _StatusProbe(_Port):
    """Port that reads the stored run status while its question is open."""

    def __init__(self, run_id: str) -> None:
        super().__init__()
        self._run_id = run_id
        self.seen: list[str] = []

    def ask_text(self, prompt: str, *, title: str = "") -> str:
        self.seen.append(run_store.load_run(self._run_id).status)
        return "ok"


def _bound(run: RunRecord, port: _Port) -> AcpSessionRunner:
    runner = _runner(_Sink(), port)
    runner.bind_run(run.id, RunWaits(run, SqliteRunRepository()))
    runner._enter_phase(run.steps[0].step_id)
    return runner


def test_the_wait_lands_on_the_bound_run_and_step(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    run = _run_with_step()
    run.start_step("one")
    run_store.save(run)

    class _SlowAnswer(_StatusProbe):
        def ask_text(self, prompt: str, *, title: str = "") -> str:
            clock[0] += 90.0
            return super().ask_text(prompt, title=title)

    port = _SlowAnswer(run.id)
    _bound(run, port)._prompt_handler.ask_text("e agora?")

    assert port.seen == [RunStatus.AWAITING_INPUT], "Home and history must see the run waiting"
    record = run_store.load_run(run.id)
    assert record.status == RunStatus.RUNNING
    assert record.steps[0].waiting_seconds == 90.0


def test_a_wait_that_closes_after_a_stop_keeps_the_run_stopped():
    """The stop ends the run while the question is still on screen."""
    run = _run_with_step()
    run.start_step("one")
    run_store.save(run)

    class _StopWhileAsking(_Port):
        def ask_text(self, prompt: str, *, title: str = "") -> str:
            run.end(RUN_STOPPED)
            run_store.save(run)
            return ""

    _bound(run, _StopWhileAsking())._prompt_handler.ask_text("e agora?")

    assert run_store.load_run(run.id).status == RunStatus.STOPPED


def test_a_wait_the_run_cannot_record_still_answers_the_agent():
    """Recording the wait is bookkeeping; losing it must not lose the user's answer."""

    class _Broken:
        def user_wait_began(self) -> None:
            raise OSError("disk full")

        def user_wait_ended(self, step_id: str, seconds: float) -> None:
            raise OSError("disk full")

    run = _run_with_step()
    sink = _Sink()
    runner = _runner(sink, _Port())
    runner.bind_run(run.id, _Broken())

    assert runner._prompt_handler.ask_text("e agora?") == "ok"
    assert sink.events == ["begin", "end"]
    unrecorded = [
        event
        for event in run_store.list_events(run.id)
        if event["title"] == "User wait not recorded"
    ]
    assert [event["detail"] for event in unrecorded] == ["OSError: disk full"] * 2


def test_the_wait_travels_from_the_runner_to_the_screen():
    """Contract between both ends: what the daemon publishes is what the screen reads.

    The bus event, not the local dock, freezes the screen clock so two windows on
    the same run stop together. Renaming the event on one side only fails here.
    """
    from pulse.client.run_session import EngineRunSession
    from pulse.daemon.adapters import ApiStreamSink
    from pulse.daemon.events import EventBus

    bus = EventBus()
    sink = _runner(ApiStreamSink(bus, run_id="r1"), _Port())
    sink._prompt_handler.ask_text("e agora?")

    published = [event for event in bus._history if event["type"] == "run.awaiting"]
    assert [event["waiting"] for event in published] == [True, False]

    state = CockpitState()
    state.phases = [PhaseItem(id="one", label="Um", status=PhaseStatus.RUNNING, started_at=0.0)]
    from pulse.tui.adapters.cockpit_sink import CockpitSink

    session = EngineRunSession(
        stream=CockpitSink(state, on_change=lambda: None),
        prompt_handler=NullPromptPort(),
        client=_ReplayClient([]),
    )
    session._dispatch(published[0])
    assert state.awaiting_input is True
    session._dispatch(published[1])
    assert state.awaiting_input is False


def test_the_proxy_still_hides_nothing_from_whoever_asks():
    """The proxy forwards, it does not invent: a method the port lacks stays missing."""
    proxy = WatchedPrompts(object(), on_enter=lambda: None, on_exit=lambda: None)

    assert not hasattr(proxy, "select_choice")


@pytest.mark.usefixtures("in_process_daemon")
def test_reattaching_mid_wait_freezes_the_clock_where_the_run_stopped():
    """A step started 10min ago, worked 2 and has waited 8: a reattach must show
    `02:00` frozen, not `10:00`, which would count the wait as agent work."""
    from datetime import UTC, datetime, timedelta

    from pulse.client.run_session import EngineRunSession
    from pulse.tui.adapters.cockpit_sink import CockpitSink
    from pulse.tui.hydrate import stamp_live_elapsed

    run = _run_with_step()
    step = run.steps[0]
    step.status = StepStatus.RUNNING
    step.started_at = (datetime.now(UTC) - timedelta(minutes=10)).replace(microsecond=0)
    store_step(run.id, step)

    state = CockpitState()
    state.phases = [PhaseItem(id="one", label="Um", status=PhaseStatus.RUNNING, started_at=0.0)]
    session = EngineRunSession(
        stream=CockpitSink(state, on_change=lambda: None),
        prompt_handler=NullPromptPort(),
        client=_ReplayClient([]),
    )
    since = step.started_at.timestamp() + 2 * 60 + _HALF_SECOND
    session._dispatch({"type": "run.awaiting", "waiting": True, "since": since})
    stamp_live_elapsed(state, served_log(run.id))

    assert state.phases[0].elapsed_label() == "02:00"
