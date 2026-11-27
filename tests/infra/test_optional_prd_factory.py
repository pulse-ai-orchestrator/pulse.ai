"""The factory PRD step may skip itself, and the steps after it find a contract without it."""

from __future__ import annotations

from pathlib import Path

import pytest

from pulse.store import factory
from pulse.store.db import connect
from pulse.store.workflow_defs import get_agent, get_workflow, list_workflows

CONTRACT_HEADING = "### The feature's contract"


def _steps(db_path: Path | None = None) -> dict[str, str]:
    workflow = get_workflow("new-issue", db_path=db_path)
    assert workflow is not None
    return {step.step_id: step.prompt_template for step in workflow.steps}


def test_only_the_prd_step_of_the_full_spec_may_skip_itself():
    """Every other factory step exists to be reviewed or to deliver; none decides it is moot."""
    skippable = [
        (workflow.id, step.step_id)
        for workflow in list_workflows()
        for step in workflow.steps
        if step.skippable
    ]

    assert skippable == [("new-issue", "prd")]


def test_the_prd_step_triages_before_it_asks_anything():
    template = _steps()["prd"]

    assert template.index("## Triage first") < template.index("## PRD phase")
    assert "PRD dispensado" in template
    assert "Unsure → write the PRD." in template


@pytest.mark.parametrize(
    "step_id", ["techspec", "tasks", "implement", "verify", "verify-fix", "review", "review-fix"]
)
def test_every_step_after_the_prd_knows_where_the_contract_is_without_one(step_id: str):
    """A missing `PRD.md` would otherwise read as a broken spec, and review would drop passes."""
    template = _steps()[step_id]

    assert CONTRACT_HEADING in template
    assert "`## Requirements` section of\n`TECHSPEC.md`" in template


def test_the_techspec_writes_the_requirements_when_the_prd_was_skipped():
    assert "write a `## Requirements` section" in _steps()["techspec"]


def test_no_current_playbook_carries_a_sentence_the_upgrade_looks_for():
    """A mark left in the factory text would reset the row, and the user's edits, on every open."""
    templates = list(_steps().values())
    instructions = [agent.instructions for agent in factory.load_agents()]

    for mark in factory.REQUIRED_PRD_STEP_MARKS:
        assert all(mark not in text for text in templates), mark
    for mark in factory.REQUIRED_PRD_AGENT_MARKS:
        assert all(mark not in text for text in instructions), mark


def test_an_old_database_gets_the_triage_and_the_contract_on_open(tmp_path: Path):
    """`seed` never rewrites rows: without the refresh an upgrade keeps the PRD mandatory."""
    db_path = tmp_path / "antigo.db"
    connection = connect(db_path)
    step_marks = dict(zip(("techspec", "prd"), factory.REQUIRED_PRD_STEP_MARKS, strict=True))
    for step_id, mark in step_marks.items():
        connection.execute(
            "UPDATE workflow_steps SET prompt_template = ? "
            "WHERE workflow_id = 'new-issue' AND step_id = ?",
            (f"texto antigo\n{mark}\n", step_id),
        )
    agent_marks = dict(
        zip(("prd", "techspec", "verify", "review"), factory.REQUIRED_PRD_AGENT_MARKS, strict=True)
    )
    for agent_id, mark in agent_marks.items():
        connection.execute(
            "UPDATE agent_defs SET instructions = ? WHERE id = ?", (f"antigo {mark}", agent_id)
        )
    connection.commit()
    connection.close()

    connect(db_path).close()

    fresh = _steps()
    upgraded = _steps(db_path)
    assert upgraded["prd"] == fresh["prd"]
    assert upgraded["techspec"] == fresh["techspec"]
    for agent_id in agent_marks:
        current = get_agent(agent_id, db_path=db_path)
        assert current is not None
        assert current.instructions == get_agent(agent_id).instructions


def test_a_row_the_user_rewrote_keeps_its_text(tmp_path: Path):
    db_path = tmp_path / "editado.db"
    connection = connect(db_path)
    connection.execute(
        "UPDATE workflow_steps SET prompt_template = 'Techspec do meu jeito.' "
        "WHERE workflow_id = 'new-issue' AND step_id = 'techspec'"
    )
    connection.execute("UPDATE agent_defs SET instructions = 'Revise assim.' WHERE id = 'review'")
    connection.commit()
    connection.close()

    connect(db_path).close()

    assert _steps(db_path)["techspec"] == "Techspec do meu jeito."
    review = get_agent("review", db_path=db_path)
    assert review is not None
    assert review.instructions == "Revise assim."
