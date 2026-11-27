"""The quick-fix loop ends in the same review loop as the spec pipeline."""

from __future__ import annotations

from pathlib import Path

from pulse.domain.workflow import RepeatRule
from pulse.store.db import connect
from pulse.store.workflow_defs import get_workflow


def test_the_quick_fix_is_reviewed_against_its_task():
    """The quick task gets the merge loop too, judged by its `TASK.md`, not by a PRD."""
    quick = get_workflow("quick-fix")

    assert quick is not None
    assert [step.step_id for step in quick.steps] == [
        "quick-plan",
        "quick-implement",
        "review",
        "review-fix",
    ]
    assert [step.requires_approval for step in quick.steps] == [True, False, True, False]
    fix = quick.steps[3]
    assert fix.repeat == RepeatRule(back_to="review", max_rounds=3)
    assert fix.commit_type == "fix"
    for step in quick.steps[2:]:
        assert "TASK.md" in step.prompt_template
        assert ".pulse/specs/quick/NNN-slug/reviews/" in step.prompt_template
        assert "features/<slug>/reviews/" not in step.prompt_template


def test_seeded_db_gains_the_quick_fix_review_after_implement_on_open(tmp_path: Path):
    """A database seeded before the quick-fix review existed gains it after implement."""
    db_path = tmp_path / "antigo.db"
    connection = connect(db_path)
    connection.execute(
        "DELETE FROM workflow_steps "
        "WHERE workflow_id = 'quick-fix' AND step_id IN ('review', 'review-fix')"
    )
    connection.execute(
        "UPDATE workflow_steps SET label = 'Meu plano' "
        "WHERE workflow_id = 'quick-fix' AND step_id = 'quick-plan'"
    )
    connection.commit()
    connection.close()

    connect(db_path).close()

    workflow = get_workflow("quick-fix", db_path=db_path)
    assert workflow is not None
    assert [(step.step_id, step.position) for step in workflow.steps] == [
        ("quick-plan", 1),
        ("quick-implement", 2),
        ("review", 3),
        ("review-fix", 4),
    ]
    assert workflow.steps[0].label == "Meu plano"
    assert workflow.steps[3].repeat == RepeatRule(back_to="review", max_rounds=3)
