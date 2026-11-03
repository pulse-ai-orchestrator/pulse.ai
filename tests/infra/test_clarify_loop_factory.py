"""The PRD clarify loop fits the approval turn cap, on fresh and old databases."""

from __future__ import annotations

from pathlib import Path

from pulse.domain.workflow import StepDef, WorkflowDef
from pulse.store.db import connect
from pulse.store.workflow_defs import get_agent, get_workflow, save_workflow


def _prd_step(db_path: Path | None = None) -> StepDef:
    workflow = get_workflow("new-issue", db_path=db_path)
    assert workflow is not None
    return next(step for step in workflow.steps if step.step_id == "prd")


def test_the_clarify_loop_batches_and_persists_instead_of_asking_forever():
    """The approval loop has a turn cap: one question per round never reached approval."""
    from pulse.store import factory

    step = _prd_step()
    prd = get_agent("prd")

    assert prd is not None
    assert factory.UNCAPPED_STEP_MARK not in step.prompt_template
    assert factory.UNCAPPED_AGENT_MARK not in prd.instructions
    assert "Never dump 3+ product questions" not in prd.instructions
    assert "Rounds are limited" in step.prompt_template
    assert "Rounds are limited" in prd.instructions


def test_old_db_refreshes_the_uncapped_clarify_loop_on_open(tmp_path: Path):
    """`seed` never rewrites rows, so old installs would keep asking one question per round."""
    from pulse.store import factory

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

    prd = get_agent("prd", db_path=db_path)
    assert prd is not None
    assert prd.instructions == get_agent("prd").instructions
    assert _prd_step(db_path).prompt_template == _prd_step().prompt_template


def test_user_rewritten_clarify_loop_is_not_touched(tmp_path: Path):
    """Without the factory sentence the rows belong to the user."""
    db_path = tmp_path / "editado.db"
    connection = connect(db_path)
    connection.execute(
        "UPDATE workflow_steps SET prompt_template = 'PRD do meu jeito.' "
        "WHERE workflow_id = 'new-issue' AND step_id = 'prd'"
    )
    connection.execute(
        "UPDATE agent_defs SET instructions = 'Pergunte à vontade.' WHERE id = 'prd'"
    )
    connection.commit()
    connection.close()

    connect(db_path).close()

    prd = get_agent("prd", db_path=db_path)
    assert prd is not None
    assert prd.instructions == "Pergunte à vontade."
    assert _prd_step(db_path).prompt_template == "PRD do meu jeito."


def test_a_user_workflow_carrying_the_old_sentence_is_left_alone(tmp_path: Path):
    """Only factory steps have a factory text to go back to."""
    from pulse.store import factory

    db_path = tmp_path / "proprio.db"
    save_workflow(
        WorkflowDef(
            id="meu-fluxo",
            label="Meu fluxo",
            steps=(
                StepDef(
                    "meu-fluxo",
                    "entrevista",
                    1,
                    "Entrevista",
                    "prd",
                    f"Pergunte. {factory.UNCAPPED_STEP_MARK}",
                    True,
                ),
            ),
        ),
        db_path=db_path,
    )

    connect(db_path).close()

    workflow = get_workflow("meu-fluxo", db_path=db_path)
    assert workflow is not None
    assert workflow.steps[0].prompt_template == f"Pergunte. {factory.UNCAPPED_STEP_MARK}"
