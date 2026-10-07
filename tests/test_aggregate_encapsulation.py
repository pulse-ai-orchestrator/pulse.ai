"""Only the run aggregate changes its own state.

Every transition goes through an intent method with a guard (`record.block()`,
`run.repeat_loop(...)`). A field written from outside skips the guard and lets
an illegal state reach SQLite, so this test fails the build when one appears.
"""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

from pulse.domain.run import RunRecord, StepRecord

PACKAGE = Path(__file__).resolve().parent.parent / "pulse"
DOMAIN = PACKAGE / "domain"

STATE_FIELDS = frozenset(
    {field.name for field in dataclasses.fields(RunRecord)}
    | {field.name for field in dataclasses.fields(StepRecord)}
) - {"id", "clock"}

_AGGREGATE_MARKERS = ("RunRecord", "StepRecord", "run_store", "store.runs")
_LIST_MUTATORS = frozenset({"append", "insert", "remove", "pop", "extend", "clear"})

# Receivers that share a field name with the aggregate but are view models.
_VIEW_MODELS = frozenset(
    {
        ("tui/hydrate.py", "state"),  # TUI session state rebuilt from history
        ("tui/hydrate.py", "phase"),  # TUI panel row
        ("history/catalog.py", "item"),  # HistoryItem DTO shown in the history screen
    }
)


def _writes(source: str) -> list[tuple[int, str, str]]:
    """`(line, receiver, field)` for each write to an aggregate field on a non-`self` receiver."""
    found: list[tuple[int, str, str]] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AugAssign | ast.AnnAssign):
            targets = [node.target]
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _LIST_MUTATORS
        ):
            targets = [node.func.value]
        else:
            continue
        for target in targets:
            if not isinstance(target, ast.Attribute) or target.attr not in STATE_FIELDS:
                continue
            receiver = ast.unparse(target.value)
            if receiver != "self":
                found.append((node.lineno, receiver, target.attr))
    return found


def test_the_detector_flags_writes_that_bypass_the_aggregate():
    source = (
        "record.status = 'done'\n"
        "run.current_step = 'x'\n"
        "step.rounds += 1\n"
        "run.steps.append(step)\n"
    )

    assert _writes(source) == [
        (1, "record", "status"),
        (2, "run", "current_step"),
        (3, "step", "rounds"),
        (4, "run", "steps"),
    ]


def test_the_detector_leaves_intent_calls_and_own_fields_alone():
    source = "record.block()\nrun.repeat_loop(loop)\nself.status = 'x'\nlabel = record.label\n"

    assert _writes(source) == []


def test_nothing_outside_the_domain_writes_the_run_aggregate_state():
    violations: list[str] = []
    for path in sorted(PACKAGE.rglob("*.py")):
        if DOMAIN in path.parents:
            continue
        source = path.read_text(encoding="utf-8")
        if not any(marker in source for marker in _AGGREGATE_MARKERS):
            continue
        relative = path.relative_to(PACKAGE).as_posix()
        violations += [
            f"{relative}:{line} {receiver}.{name}"
            for line, receiver, name in _writes(source)
            if (relative, receiver) not in _VIEW_MODELS
        ]

    assert violations == [], "use an intent method on RunRecord/StepRecord instead"
