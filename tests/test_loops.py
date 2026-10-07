from __future__ import annotations

from pulse.orchestrator.loops import Loop, find_loops
from pulse.store.workflow_defs import StepDef, WorkflowDef


def _workflow(*steps: tuple[str, str], fan_out: str = "") -> WorkflowDef:
    return WorkflowDef(
        id="w",
        label="w",
        description="",
        is_default=False,
        default_prompt="",
        steps=tuple(
            StepDef(
                workflow_id="w",
                step_id=step_id,
                position=position,
                label=step_id,
                agent_id="default",
                prompt_template="",
                requires_approval=False,
                repeat_from=repeat_from,
                repeat_max=3 if repeat_from else 0,
                fan_out=step_id == fan_out,
            )
            for position, (step_id, repeat_from) in enumerate(steps, start=1)
        ),
    )


def test_a_range_crossing_another_is_ignored():
    """c goes back to a, d goes back to b: the second range used to overwrite the first."""
    loops = find_loops(_workflow(("a", ""), ("b", ""), ("c", "a"), ("d", "b")))

    assert loops[2] == Loop(start=0, end=2)
    assert 3 not in loops


def test_separate_ranges_both_count():
    loops = find_loops(_workflow(("a", ""), ("b", "a"), ("c", ""), ("d", "c")))

    assert loops[1] == Loop(start=0, end=1)
    assert loops[3] == Loop(start=2, end=3)


def test_a_range_opened_by_a_fan_out_is_ignored():
    """The fan-out replaces its row with one per item, so nothing would count the rounds."""
    loops = find_loops(_workflow(("a", ""), ("b", "a"), fan_out="a"))

    assert loops == {}


def test_a_range_with_a_fan_out_inside_is_ignored():
    """Reopening the range would not reach the items, so they would never run again."""
    loops = find_loops(_workflow(("a", ""), ("b", ""), ("c", "a"), fan_out="b"))

    assert loops == {}


def test_a_fan_out_before_the_range_keeps_the_loop():
    loops = find_loops(_workflow(("a", ""), ("b", ""), ("c", "b"), fan_out="a"))

    assert loops[2] == Loop(start=1, end=2)
