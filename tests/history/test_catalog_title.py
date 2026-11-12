"""The history names a run after its title, and falls back for runs that had none."""

from __future__ import annotations

from pathlib import Path

from pulse.domain.run import StepRecord
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
