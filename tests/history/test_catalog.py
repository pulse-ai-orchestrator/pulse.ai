"""The history carries the net time a run's steps already closed."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from pulse.domain.run import StepRecord, StepStatus
from pulse.history.catalog import HistoryCatalog
from pulse.store import runs as run_store
from tests.conftest import make_workflow


def _create_run(tmp_path: Path) -> None:
    make_workflow("demo", steps=[("one", "Um"), ("two", "Dois")])
    run_store.create_run(
        run_id="run-1",
        workflow_id="demo",
        workspace=tmp_path,
        user_prompt="tarefa",
        steps=[
            StepRecord(step_id="one", position=1000, label="Um", agent_id="a"),
            StepRecord(step_id="two", position=2000, label="Dois", agent_id="a"),
        ],
    )


def test_a_listed_run_carries_the_net_time_its_steps_already_closed(tmp_path: Path):
    """History shows the sum the sidebar would freeze, after the run is saved."""
    _create_run(tmp_path)
    start = datetime(2026, 10, 1, 10, 0, tzinfo=UTC)
    record = run_store.load_run("run-1")
    assert record is not None
    plan, build = record.steps
    plan.status = StepStatus.DONE
    plan.started_at = start
    plan.ended_at = start + timedelta(minutes=10)
    plan.waiting_seconds = 120.0
    build.carried_seconds = 32.0
    run_store.save(record)

    item = HistoryCatalog(tmp_path).get("run-1")

    assert item is not None
    assert item.duration_seconds == 8 * 60 + 32.0


def test_a_listed_run_with_no_closed_step_time_has_no_duration(tmp_path: Path):
    """A run that never closed a step must not show a zero duration."""
    _create_run(tmp_path)

    item = HistoryCatalog(tmp_path).get("run-1")

    assert item is not None
    assert item.duration_seconds is None
