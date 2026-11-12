"""The history names a run after its title, and falls back for runs that had none."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from pulse.domain.run import StepRecord, StepStatus
from pulse.domain.task_brief import TaskBrief
from pulse.history.catalog import HistoryCatalog
from pulse.store import runs as run_store
from tests.conftest import make_workflow

STEPS = [StepRecord(step_id="one", position=1000, label="Um", agent_id="a")]


def test_a_run_with_a_title_is_listed_by_it_and_searchable_by_its_description(tmp_path: Path):
    make_workflow("demo", steps=[("one", "Um")])
    run_store.create_run(
        run_id="run-1",
        workflow_id="demo",
        workspace=tmp_path,
        user_prompt="Corrigir login\n\nerro 500 com e-mail maiúsculo",
        steps=STEPS,
        brief=TaskBrief(title="Corrigir login", description="erro 500 com e-mail maiúsculo"),
    )

    item = HistoryCatalog(tmp_path).get("run-1")

    assert item is not None
    assert item.title == "Corrigir login"
    assert [found.run_id for found in HistoryCatalog(tmp_path).search("maiúsculo")] == ["run-1"]


def test_a_run_without_a_title_is_still_named_after_its_prompt(tmp_path: Path):
    make_workflow("demo", steps=[("one", "Um")])
    run_store.create_run(
        run_id="run-1",
        workflow_id="demo",
        workspace=tmp_path,
        user_prompt="  tarefa  ",
        steps=STEPS,
    )

    item = HistoryCatalog(tmp_path).get("run-1")

    assert item is not None
    assert item.title == "tarefa"
    assert item.duration_seconds is None


def test_a_listed_run_carries_the_net_time_its_steps_already_closed(tmp_path: Path):
    """History shows the sum the sidebar would freeze, after the run is saved."""
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
