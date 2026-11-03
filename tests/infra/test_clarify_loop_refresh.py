"""Databases seeded before the round limit stop telling the agent its questions are uncapped.

`seed` never rewrites rows, so an old database kept saying "there is no cap on
rounds": the agent asked one question per round, hit the approval turn cap, and
its retry asked everything again.
"""

from __future__ import annotations

from pathlib import Path

from pulse.store import factory
from pulse.store.db import connect
from pulse.store.workflow_defs import get_agent, get_workflow
from tests.conftest import make_workflow


def _prd_template(db_path: Path | None = None) -> str:
    workflow = get_workflow("new-issue", db_path=db_path)
    assert workflow is not None
    return next(step for step in workflow.steps if step.step_id == "prd").prompt_template


def _prd_instructions(db_path: Path | None = None) -> str:
    agent = get_agent("prd", db_path=db_path)
    assert agent is not None
    return agent.instructions


def test_the_factory_no_longer_promises_uncapped_rounds():
    assert factory.UNCAPPED_STEP_MARK not in _prd_template()
    assert factory.UNCAPPED_AGENT_MARK not in _prd_instructions()


def test_old_db_rows_with_the_uncapped_sentence_reset_to_the_factory_on_open(tmp_path: Path):
    db_path = tmp_path / "antigo.db"
    connection = connect(db_path)
    connection.execute(
        "UPDATE workflow_steps SET prompt_template = prompt_template || ? "
        "WHERE workflow_id = 'new-issue' AND step_id = 'prd'",
        (f"\n\n{factory.UNCAPPED_STEP_MARK}\n",),
    )
    connection.execute(
        "UPDATE agent_defs SET instructions = instructions || ? WHERE id = 'prd'",
        (f"\n\n{factory.UNCAPPED_AGENT_MARK}\n",),
    )
    connection.commit()
    connection.close()

    connect(db_path).close()

    assert _prd_template(db_path) == _prd_template()
    assert _prd_instructions(db_path) == _prd_instructions()


def test_user_rewritten_clarify_rows_are_not_touched(tmp_path: Path):
    """Without the old sentence the row belongs to the user."""
    db_path = tmp_path / "editado.db"
    connection = connect(db_path)
    connection.execute(
        "UPDATE workflow_steps SET prompt_template = 'PRD do meu jeito.' "
        "WHERE workflow_id = 'new-issue' AND step_id = 'prd'"
    )
    connection.execute("UPDATE agent_defs SET instructions = 'Meu PRD.' WHERE id = 'prd'")
    connection.commit()
    connection.close()

    connect(db_path).close()

    assert _prd_template(db_path) == "PRD do meu jeito."
    assert _prd_instructions(db_path) == "Meu PRD."


def test_a_user_step_carrying_the_sentence_outside_the_factory_is_kept():
    """Only factory rows have a text to reset to; a user's own workflow stays as written."""
    template = f"Pergunte à vontade. {factory.UNCAPPED_STEP_MARK}"
    make_workflow("meu", steps=[("perguntar", "Perguntar")], prompt_template=template)

    connect().close()

    workflow = get_workflow("meu")
    assert workflow is not None
    assert workflow.steps[0].prompt_template == template
