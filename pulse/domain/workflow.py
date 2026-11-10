"""Workflow, step and agent definitions: values the engine reads, never code.

They have no identity beyond their ids and no I/O; persistence lives in
[pulse.store.workflow_defs].
"""

from __future__ import annotations

from dataclasses import dataclass, replace

MIN_LOOP_ROUNDS = 2


@dataclass(frozen=True)
class AgentDef:
    id: str
    label: str
    runtime: str = ""
    model: str = ""
    permission_policy: str = ""
    instructions: str = ""


@dataclass(frozen=True)
class RepeatRule:
    """The step may send the run back to `back_to` for another round, up to `max_rounds`."""

    back_to: str
    max_rounds: int

    def __post_init__(self) -> None:
        if not self.back_to or self.max_rounds < MIN_LOOP_ROUNDS:
            raise ValueError(
                f"repeat rule needs a target and at least {MIN_LOOP_ROUNDS} rounds: "
                f"{self.back_to!r}, {self.max_rounds}"
            )

    @classmethod
    def from_columns(cls, repeat_from: str, repeat_max: int) -> RepeatRule | None:
        """Storage keeps the rule as two columns; a rule that cannot loop is no rule."""
        if not repeat_from or repeat_max < MIN_LOOP_ROUNDS:
            return None
        return cls(back_to=repeat_from, max_rounds=repeat_max)


@dataclass(frozen=True)
class LoopRound:
    """Another round of a loop: its number, whether it is the last, and the steps it reopens."""

    number: int
    last: bool
    reopens: range


@dataclass(frozen=True)
class Loop:
    """A repeatable range of the definition, by step index."""

    start: int
    end: int
    max_rounds: int

    def __post_init__(self) -> None:
        if not 0 <= self.start < self.end or self.max_rounds < MIN_LOOP_ROUNDS:
            raise ValueError(
                f"a loop spans at least two steps and {MIN_LOOP_ROUNDS} rounds: "
                f"{self.start}..{self.end}, {self.max_rounds}"
            )

    def opens(self, index: int) -> bool:
        return index == self.start

    def closes(self, index: int) -> bool:
        return index == self.end

    def next_round(self, rounds: int) -> LoopRound | None:
        """The round after `rounds` already run; `None` once the ceiling is reached.

        The last round reopens only the opener, so the closer never gets the
        final word on its own fix.
        """
        if rounds >= self.max_rounds:
            return None
        number = rounds + 1
        last = number >= self.max_rounds
        return LoopRound(
            number=number,
            last=last,
            reopens=range(self.start, self.start + 1 if last else self.end + 1),
        )

    @property
    def rest(self) -> range:
        """The steps after the opener, settled without running when the loop closes."""
        return range(self.start + 1, self.end + 1)


@dataclass(frozen=True)
class StepDef:
    workflow_id: str
    step_id: str
    position: int
    label: str
    agent_id: str
    prompt_template: str
    requires_approval: bool
    fan_out: bool = False
    requires_outcome: bool = True
    repeat: RepeatRule | None = None
    commit_type: str = ""
    opens_request: bool = False

    @property
    def declares_outcome(self) -> bool:
        """An approval step answers with the questionnaire; the others declare a `pulse:outcome`."""
        return self.requires_outcome and not self.requires_approval

    def for_item(self, *, step_id: str, label: str, position: int) -> StepDef:
        """The step a fan-out runs for one item: same agent and prompt, no fan-out or loop."""
        return replace(
            self, step_id=step_id, label=label, position=position, fan_out=False, repeat=None
        )


@dataclass(frozen=True)
class WorkflowDef:
    id: str
    label: str
    description: str = ""
    is_default: bool = False
    default_prompt: str = ""
    pull_request_template: str = ""
    steps: tuple[StepDef, ...] = ()

    def loops(self) -> dict[int, Loop]:
        """Repeatable ranges, keyed by every step index they cover.

        A rule that does not point to an earlier step is ignored, as is a range
        overlapping one already found.
        """
        found: dict[int, Loop] = {}
        at = {step.step_id: index for index, step in enumerate(self.steps)}
        for end, step in enumerate(self.steps):
            if step.repeat is None:
                continue
            start = at.get(step.repeat.back_to)
            if start is None or start >= end:
                continue
            span = range(start, end + 1)
            if any(index in found for index in span):
                continue
            loop = Loop(start=start, end=end, max_rounds=step.repeat.max_rounds)
            for index in span:
                found[index] = loop
        return found
