"""Step loops: a range of the definition that may run more than once.

The definition allows the loop (`repeat_from`, `repeat_max`); the agent requests
another round or the end via the outcome block's `next` field.
"""

from __future__ import annotations

from dataclasses import dataclass

from pulse.domain.run import RunRecord
from pulse.store.workflow_defs import WorkflowDef


@dataclass(frozen=True)
class Loop:
    """A repeatable range of the definition."""

    start: int
    end: int


def find_loops(definition: WorkflowDef) -> dict[int, Loop]:
    """Repeatable ranges of the definition, keyed by step index.

    A `repeat_from` that does not point to an earlier step is silently ignored,
    as is a range overlapping one already found.
    """
    found: dict[int, Loop] = {}
    at = {step.step_id: index for index, step in enumerate(definition.steps)}
    for end, step in enumerate(definition.steps):
        if not step.repeat_from or step.repeat_max < 2:
            continue
        start = at.get(step.repeat_from)
        if start is None or start >= end:
            continue
        span = range(start, end + 1)
        if any(index in found for index in span):
            continue
        loop = Loop(start=start, end=end)
        for index in span:
            found[index] = loop
    return found


def repeat_loop(
    run: RunRecord, definition: WorkflowDef, loop: Loop, label: str
) -> tuple[int | None, str]:
    """Handle a request for another round: `(index to jump back to, notice)`.

    Index is `None` when the ceiling was reached. Only the run in memory changes;
    the caller persists it.
    """
    ceiling = definition.steps[loop.end].repeat_max
    opener_id = definition.steps[loop.start].step_id
    number = run.loop_round(opener_id)
    if not run.can_repeat(opener_id, ceiling=ceiling):
        return None, f"{label}: teto de {ceiling} rodadas atingido — o que sobrou vai no relatório"
    last = number + 1 >= ceiling
    run.reopen_loop(_step_ids(definition, loop, last=last))
    if not last:
        return loop.start, f"{label} pediu a {number + 1}ª rodada"
    opener = run.step(opener_id)
    who = opener.label if opener else "o início do laço"
    return loop.start, f"{label} pediu a {number + 1}ª rodada — a última: só {who} roda"


def close_loop(run: RunRecord, definition: WorkflowDef, loop: Loop) -> int:
    """Settle the rest of the range without running it; return the index to continue from.

    Only the run in memory changes; the caller persists it.
    """
    run.close_loop(_step_ids(definition, loop))
    return loop.end + 1


def _step_ids(definition: WorkflowDef, loop: Loop, *, last: bool = False) -> list[str]:
    """The range's step ids, opener first. On the `last` round only the opener
    reopens, so the closer never gets the final word on its own fix."""
    end = loop.start + 1 if last else loop.end + 1
    return [step.step_id for step in definition.steps[loop.start : end]]
