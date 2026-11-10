"""The workflow definition answers questions about itself.

Loops, the outcome protocol and fan-out children used to be worked out by the
engine from raw columns; a rule kept outside the definition drifts from it.
"""

from __future__ import annotations

import pytest

from pulse.domain.workflow import Loop, LoopRound, RepeatRule, StepDef, WorkflowDef


def _step(step_id: str, *, repeat: RepeatRule | None = None, **fields: object) -> StepDef:
    values: dict[str, object] = {
        "workflow_id": "w",
        "step_id": step_id,
        "position": 1,
        "label": step_id,
        "agent_id": "tester",
        "prompt_template": "{{user_prompt}}",
        "requires_approval": False,
        "repeat": repeat,
    }
    values.update(fields)
    return StepDef(**values)


def _workflow(*steps: tuple[str, str]) -> WorkflowDef:
    """`(step_id, back_to)`; an empty `back_to` is a step without a loop."""
    return WorkflowDef(
        id="w",
        label="w",
        steps=tuple(
            _step(step_id, repeat=RepeatRule(back_to=back_to, max_rounds=3) if back_to else None)
            for step_id, back_to in steps
        ),
    )


@pytest.mark.parametrize(("repeat_from", "repeat_max"), [("", 3), ("review", 0), ("review", 1)])
def test_columns_without_a_target_or_a_second_round_are_no_loop(repeat_from, repeat_max):
    """Storage keeps the rule as two columns; only a target and two rounds make a loop."""
    assert RepeatRule.from_columns(repeat_from, repeat_max) is None


def test_columns_with_a_target_and_rounds_are_a_loop():
    assert RepeatRule.from_columns("review", 3) == RepeatRule(back_to="review", max_rounds=3)


@pytest.mark.parametrize(("back_to", "max_rounds"), [("", 3), ("review", 1)])
def test_a_repeat_rule_that_could_not_loop_cannot_be_built(back_to, max_rounds):
    with pytest.raises(ValueError, match="repeat rule"):
        RepeatRule(back_to=back_to, max_rounds=max_rounds)


@pytest.mark.parametrize(
    ("start", "end", "max_rounds"),
    [(2, 2, 3), (3, 1, 3), (-1, 2, 3), (0, 2, 1)],
    ids=["single-step", "backwards", "negative-start", "one-round"],
)
def test_a_loop_that_could_not_repeat_a_range_cannot_be_built(start, end, max_rounds):
    """`next_round` and `rest` assume `start < end`; an empty range would reopen nothing."""
    with pytest.raises(ValueError, match="loop spans"):
        Loop(start=start, end=end, max_rounds=max_rounds)


def test_the_smallest_loop_is_two_steps_and_two_rounds():
    loop = Loop(start=0, end=1, max_rounds=2)

    assert (loop.opens(0), loop.closes(1)) == (True, True)


def test_a_range_crossing_another_is_ignored():
    """c goes back to a, d goes back to b: the second range used to overwrite the first."""
    loops = _workflow(("a", ""), ("b", ""), ("c", "a"), ("d", "b")).loops()

    assert loops[2] == Loop(start=0, end=2, max_rounds=3)
    assert 3 not in loops


def test_separate_ranges_both_count():
    loops = _workflow(("a", ""), ("b", "a"), ("c", ""), ("d", "c")).loops()

    assert loops[1] == Loop(start=0, end=1, max_rounds=3)
    assert loops[3] == Loop(start=2, end=3, max_rounds=3)


@pytest.mark.parametrize("back_to", ["c", "b", "gone"])
def test_a_loop_back_to_itself_a_later_step_or_an_unknown_one_is_ignored(back_to):
    assert _workflow(("a", ""), ("b", back_to), ("c", "")).loops() == {}


def test_every_step_of_the_range_maps_to_the_same_loop():
    loops = _workflow(("a", ""), ("b", ""), ("c", "a")).loops()

    assert loops[0] is loops[1] is loops[2]


@pytest.mark.parametrize(
    ("index", "opens", "closes"), [(1, True, False), (2, False, False), (3, False, True)]
)
def test_only_the_first_step_opens_and_only_the_last_closes(index, opens, closes):
    """The opener may close the loop and the closer may ask for a round; nobody in between."""
    loop = Loop(start=1, end=3, max_rounds=3)

    assert (loop.opens(index), loop.closes(index)) == (opens, closes)


def test_the_next_round_counts_on_from_the_rounds_already_run():
    loop = Loop(start=1, end=3, max_rounds=3)

    assert loop.next_round(1) == LoopRound(number=2, last=False, reopens=range(1, 4))


def test_the_last_round_reopens_only_the_opener():
    """The closer never gets the final word on its own fix."""
    loop = Loop(start=1, end=3, max_rounds=3)

    assert loop.next_round(2) == LoopRound(number=3, last=True, reopens=range(1, 2))


def test_no_round_past_the_ceiling():
    assert Loop(start=1, end=3, max_rounds=3).next_round(3) is None


def test_closing_a_loop_settles_what_follows_the_opener():
    assert Loop(start=1, end=3, max_rounds=3).rest == range(2, 4)


@pytest.mark.parametrize(
    ("requires_outcome", "requires_approval", "declares"),
    [(True, False, True), (True, True, False), (False, False, False), (False, True, False)],
)
def test_only_a_step_without_approval_declares_an_outcome(
    requires_outcome, requires_approval, declares
):
    """An approval step answers with the questionnaire, so it never adds the outcome protocol."""
    step = _step("s", requires_outcome=requires_outcome, requires_approval=requires_approval)

    assert step.declares_outcome is declares


def test_a_fan_out_child_runs_like_its_step_without_fanning_out_or_looping():
    step = _step(
        "review",
        repeat=RepeatRule(back_to="plan", max_rounds=3),
        fan_out=True,
        requires_approval=True,
        requires_outcome=False,
        opens_request=True,
    )

    child = step.for_item(step_id="review:T1", label="Task 1", position=101)

    assert child == StepDef(
        workflow_id="w",
        step_id="review:T1",
        position=101,
        label="Task 1",
        agent_id="tester",
        prompt_template="{{user_prompt}}",
        requires_approval=True,
        requires_outcome=False,
        opens_request=True,
    )
