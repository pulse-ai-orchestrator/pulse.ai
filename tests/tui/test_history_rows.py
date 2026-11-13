from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from pulse.domain.run import StepStatus
from pulse.history.models import HistoryItem, HistoryStatus, HistoryStep
from pulse.tui import strings
from pulse.tui.history_rows import POINTER, TITLE_LIMIT, history_row, run_age, run_title

NOW = datetime(2026, 10, 23, 15, 0, tzinfo=UTC)


def _item(**overrides: object) -> HistoryItem:
    fields: dict[str, object] = {
        "run_id": "run-1",
        "workflow_id": "demo",
        "workflow_label": "Demo",
        "title": "Corrigir refresh token",
        "prompt": "Corrigir refresh token",
        "status": HistoryStatus.FAILED,
        "updated_at": (NOW - timedelta(minutes=5)).isoformat(),
    }
    fields.update(overrides)
    return HistoryItem(**fields)  # type: ignore[arg-type]  # test builder over the dataclass fields


@pytest.mark.parametrize(
    ("ago", "expected"),
    [
        (timedelta(seconds=30), strings.HISTORY_AGE_NOW),
        (timedelta(minutes=5), "há 5 min"),
        (timedelta(minutes=59, seconds=59), "há 59 min"),
        (timedelta(hours=3), "há 3 h"),
        (timedelta(hours=30), strings.HISTORY_AGE_YESTERDAY),
        (timedelta(days=4), "há 4 dias"),
        (timedelta(days=40), "13/09/2026"),
    ],
)
def test_the_age_says_how_long_ago_the_run_last_moved(ago: timedelta, expected: str) -> None:
    """A picker is scanned by recency: coarse words beat a full timestamp."""
    assert run_age((NOW - ago).isoformat(), NOW) == expected


def test_a_timestamp_without_zone_is_read_as_utc() -> None:
    naive = (NOW - timedelta(hours=2)).replace(tzinfo=None).isoformat()

    assert run_age(naive, NOW) == "há 2 h"


@pytest.mark.parametrize("broken", ["", "ontem à tarde", "2026-13-45"])
def test_an_unreadable_timestamp_shows_no_age_instead_of_a_wrong_one(broken: str) -> None:
    assert run_age(broken, NOW) == ""


def test_the_title_folds_line_breaks_and_falls_back_to_the_workflow() -> None:
    assert run_title(_item(title="Corrigir\n  refresh\ttoken")) == "Corrigir refresh token"
    assert run_title(_item(title="  \n")) == "Demo"


def test_a_long_title_is_cut_with_an_ellipsis_at_the_limit() -> None:
    title = run_title(_item(title="x" * (TITLE_LIMIT + 10)))

    assert len(title) == TITLE_LIMIT
    assert title.endswith("…")


def test_the_selected_row_carries_the_pointer_and_the_others_do_not() -> None:
    item = _item()

    selected = history_row(item, now=NOW, selected=True).plain.splitlines()
    plain = history_row(item, now=NOW, selected=False).plain.splitlines()

    assert selected[0] == f"{POINTER} ✗ Corrigir refresh token"
    assert plain[0] == "  ✗ Corrigir refresh token"
    assert selected[1:] == plain[1:]


def test_the_facts_line_shows_workflow_status_age_progress_and_branch() -> None:
    """The status is spelled out next to its icon, so color is never the only cue."""
    item = _item(
        branch="feat/token",
        steps=[
            HistoryStep(id="plan", label="Planejar", status=StepStatus.DONE),
            HistoryStep(id="build", label="Construir", status=StepStatus.FAILED),
            HistoryStep(id="verify", label="Verificar", status=StepStatus.PENDING),
        ],
    )

    facts = history_row(item, now=NOW, selected=False).plain.splitlines()[1]

    assert facts.strip() == "Demo · falhou · há 5 min · 1/3 etapas · ⎇ feat/token"


def test_the_facts_line_shows_the_flow_duration_after_the_age() -> None:
    """14:32 is the net time already closed, in the same words as a step timer."""
    item = _item(duration_seconds=14 * 60 + 32)

    facts = history_row(item, now=NOW, selected=False).plain.splitlines()[1]

    assert facts.strip() == "Demo · falhou · há 5 min · duração 14:32"


def test_a_closed_instant_still_shows_a_duration() -> None:
    facts = history_row(_item(duration_seconds=0.0), now=NOW, selected=False).plain

    assert "duração 00:00" in facts


def test_a_run_without_steps_or_branch_omits_those_facts() -> None:
    facts = history_row(_item(), now=NOW, selected=False).plain.splitlines()[1]

    assert facts.strip() == "Demo · falhou · há 5 min"
