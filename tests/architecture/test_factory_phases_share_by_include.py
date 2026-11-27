"""A rule two phases share lives once, in `factory/shared/`, behind an include.

A copied block changes in one phase and not in its twin, and the workflows then
tell their agents different rules. Seeding expands includes, so a shared block
costs nothing at runtime.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

AGENTS = Path(__file__).resolve().parents[2] / "pulse" / "store" / "factory" / "agents"
WINDOW = 15


def _repeated_windows(texts: dict[str, str]) -> dict[str, list[str]]:
    """Every run of `WINDOW` non-blank lines found in more than one text."""
    owners: dict[str, set[str]] = defaultdict(set)
    for name, text in texts.items():
        lines = [line for line in text.splitlines() if line.strip()]
        for start in range(len(lines) - WINDOW + 1):
            owners["\n".join(lines[start : start + WINDOW])].add(name)
    return {window: sorted(names) for window, names in owners.items() if len(names) > 1}


def test_no_phase_copies_a_block_from_another_phase() -> None:
    phases = {
        str(path.relative_to(AGENTS)): path.read_text(encoding="utf-8")
        for path in sorted(AGENTS.glob("*/*.md"))
        if path.name != "AGENT.md"
    }

    copied = {tuple(names) for names in _repeated_windows(phases).values()}

    assert copied == set(), "move the shared block to factory/shared/ and include it"


def test_the_copy_check_recognises_a_copy() -> None:
    """Guards the guard: a window that never matches would pass the test above forever."""
    block = "\n".join(f"rule {number}" for number in range(WINDOW))

    assert _repeated_windows({"a": f"intro\n{block}", "b": f"{block}\noutro"})
    assert not _repeated_windows({"a": block, "b": block.replace("rule 7", "other")})
