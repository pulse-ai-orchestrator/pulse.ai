import os
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from hypothesis import settings

from pulse.client.protocol import PING
from pulse.daemon.events import EventBus
from pulse.domain.ports import JsonObject
from pulse.domain.run import RunStatus, StepRecord
from pulse.domain.workflow import AgentDef, RepeatRule, StepDef, WorkflowDef
from pulse.store import runs as run_store
from pulse.store.workflow_defs import get_workflow, save_agent, save_workflow

# Property tests replay the same examples for a given Hypothesis and Python version
# (AGENTS.md §5.1): a failure reproduces on the CI job with the same versions,
# and no example database is left on disk.
settings.register_profile("pulse", derandomize=True, database=None)
settings.load_profile("pulse")


@pytest.fixture(autouse=True)
def _isolate_pulse_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PULSE_DB", str(tmp_path / "pulse.db"))


def make_workflow(
    workflow_id: str = "demo",
    *,
    steps: list[tuple[str, str]] | None = None,
    label: str = "Demo",
    requires_approval: bool = True,
    prompt_template: str = "{{user_prompt}}",
    fan_out: tuple[str, ...] | set[str] = (),
    requires_outcome: bool = True,
    repeat: tuple[str, str, int] | None = None,
    commit_types: dict[str, str] | None = None,
    opens_request: tuple[str, ...] | set[str] = (),
    pull_request_template: str = "",
) -> WorkflowDef:
    """Persist a test workflow in the database and return its definition.

    Pulse ships only the single-step `default` workflow, so each test seeds its own.
    `repeat=(step_id, back_to, max)` marks a loop: that step may send the run back
    to repeat the span.
    """
    entries = steps or [("one", "Um"), ("two", "Dois")]
    save_agent(AgentDef(id="tester", label="Tester"))
    definition = WorkflowDef(
        id=workflow_id,
        label=label,
        pull_request_template=pull_request_template,
        steps=tuple(
            StepDef(
                workflow_id=workflow_id,
                step_id=step_id,
                position=index,
                label=step_label,
                agent_id="tester",
                prompt_template=prompt_template,
                requires_approval=requires_approval,
                fan_out=step_id in fan_out,
                requires_outcome=requires_outcome,
                repeat=RepeatRule(back_to=repeat[1], max_rounds=repeat[2])
                if repeat and repeat[0] == step_id
                else None,
                commit_type=(commit_types or {}).get(step_id, ""),
                opens_request=step_id in opens_request,
            )
            for index, (step_id, step_label) in enumerate(entries, start=1)
        ),
    )
    save_workflow(definition)
    return definition


@pytest.fixture
def demo_workflow() -> WorkflowDef:
    return make_workflow()


def store_step(run_id: str, step: StepRecord) -> None:
    """Fixture shortcut: write one step of a stored run as a past execution left it."""
    record = run_store.load_run(run_id)
    assert record is not None, run_id
    record.steps = [step if item.step_id == step.step_id else item for item in record.steps]
    run_store.save(record)


def store_run_status(run_id: str, status: str) -> None:
    """Fixture shortcut: leave a stored run in `status`, as the daemon would."""
    record = run_store.load_run(run_id)
    assert record is not None, run_id
    record.status = RunStatus(status)
    run_store.save(record)


def wait_for_event(bus: EventBus, event_type: str, *, timeout: float = 5.0) -> JsonObject:
    """The first `event_type` on a run's bus, replayed or live.

    Waiting on the bus instead of polling state with `sleep` makes the test wake
    exactly when the daemon says so. A heartbeat means `timeout` seconds passed
    in silence, which is a failure here, not a reason to keep waiting.
    """
    for event in bus.subscribe(poll=timeout):
        if event["type"] == event_type:
            return event
        if event["type"] == PING:
            raise AssertionError(f"no {event_type} within {timeout}s")
    raise AssertionError(f"the bus closed before {event_type}")


@pytest.fixture
def in_process_daemon(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Every `EngineClient` talks to a daemon app in this process.

    The routes and the test's SQLite are real; only the socket is skipped, so a
    screen exercises the same `/api/*` contract it uses against `pulse-engine`
    without spawning one.
    """
    from pulse.api.app import create_app
    from pulse.client.engine_client import EngineClient
    from pulse.daemon.runs import RunManager

    # Not entered as a context manager: the app has no lifespan to run, and a
    # long-lived portal would hang on teardown in tests that freeze the clock.
    # A failing route answers 500, as the real daemon does, instead of raising here.
    daemon = TestClient(
        create_app(RunManager()), base_url="http://127.0.0.1", raise_server_exceptions=False
    )
    monkeypatch.setattr(EngineClient, "_http", lambda _self: daemon)
    monkeypatch.setattr(EngineClient, "close", lambda _self: None)
    return daemon


def configure_from_db(state: Any, workflow_id: str) -> None:
    """Hand a seeded workflow's shape to a `CockpitState`, as the cockpit does from the daemon."""
    definition = get_workflow(workflow_id)
    state.configure_workflow(
        workflow_id,
        label=definition.label if definition else "",
        steps=[(step.step_id, step.label) for step in definition.steps] if definition else (),
    )


def onboard_machine() -> None:
    """Finish the setup wizard in the test database: Home then offers sessions."""
    from pulse.config.global_config import mark_onboarding_complete

    mark_onboarding_complete(
        agent_binary="agent",
        acp_command=["agent", "acp"],
        auth_method="login",
        workspace_dir=Path(os.environ["PULSE_DB"]).parent,
        model="Auto",
        permission_policy="ask",
        acp_test_passed=True,
    )


def served_log(run_id: str) -> Any:
    """A stored run's `RunLog` as the daemon serves it; needs `in_process_daemon`."""
    from pulse.tui import engine

    log = engine.run_log(run_id)
    assert log is not None, run_id
    return log
