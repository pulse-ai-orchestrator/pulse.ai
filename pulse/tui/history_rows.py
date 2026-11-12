"""How a run reads in the history list: a title line over a muted line of facts.

Kept apart from the screen so the row is a pure function of the item and the
clock, testable without mounting Textual.
"""

from __future__ import annotations

from datetime import UTC, datetime

from rich.text import Text

from pulse.history.events import format_elapsed
from pulse.history.models import HistoryItem
from pulse.history.status_labels import status_color, status_icon
from pulse.tui import strings
from pulse.tui.palette import LIME, TEXT, TEXT_MUTED

POINTER = "❯"
SEPARATOR = " · "
TITLE_LIMIT = 90
MINUTE = 60
HOUR = 60 * MINUTE
DAY = 24 * HOUR


def run_age(updated_at: str, now: datetime) -> str:
    """How long ago the run last moved, in the coarse words a picker needs.

    An unreadable timestamp shows nothing rather than a wrong age.
    """
    try:
        moment = datetime.fromisoformat(updated_at)
    except ValueError:
        return ""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    seconds = int((now - moment).total_seconds())
    if seconds < MINUTE:
        return strings.HISTORY_AGE_NOW
    if seconds < HOUR:
        return strings.HISTORY_AGE_MINUTES.format(count=seconds // MINUTE)
    if seconds < DAY:
        return strings.HISTORY_AGE_HOURS.format(count=seconds // HOUR)
    if seconds < 2 * DAY:
        return strings.HISTORY_AGE_YESTERDAY
    if seconds < 7 * DAY:
        return strings.HISTORY_AGE_DAYS.format(count=seconds // DAY)
    return moment.astimezone(UTC).strftime(strings.HISTORY_AGE_DATE_FORMAT)


def run_title(item: HistoryItem) -> str:
    title = " ".join(item.title.split()) or item.workflow_label or item.workflow_id
    if len(title) > TITLE_LIMIT:
        return title[: TITLE_LIMIT - 1] + "…"
    return title


def run_facts(item: HistoryItem, now: datetime) -> list[Text]:
    """The muted facts under the title; status keeps its color so it scans."""
    facts = [Text(item.workflow_label or item.workflow_id, style=TEXT_MUTED)]
    facts.append(Text(item.status_label, style=status_color(item.status)))
    if age := run_age(item.updated_at, now):
        facts.append(Text(age, style=TEXT_MUTED))
    if item.duration_seconds is not None:
        facts.append(
            Text(
                strings.HISTORY_DURATION.format(duration=format_elapsed(item.duration_seconds)),
                style=TEXT_MUTED,
            )
        )
    if item.steps:
        done = sum(1 for step in item.steps if step.settled)
        facts.append(
            Text(
                strings.HISTORY_STEPS.format(done=done, total=len(item.steps)),
                style=TEXT_MUTED,
            )
        )
    if item.branch:
        facts.append(Text(strings.HISTORY_BRANCH.format(branch=item.branch), style=TEXT_MUTED))
    return facts


def history_row(item: HistoryItem, *, now: datetime, selected: bool) -> Text:
    """Two lines and a gap, with the pointer and a lime title on the selected run.

    The status icon and label carry the state, so color is never the only cue.
    """
    row = Text(no_wrap=True, overflow="ellipsis")
    row.append(f"{POINTER} " if selected else "  ", style=f"bold {LIME}")
    row.append(f"{status_icon(item.status)} ", style=status_color(item.status))
    row.append(run_title(item), style=f"bold {LIME}" if selected else TEXT)
    row.append("\n    ")
    row.append(Text(SEPARATOR, style=TEXT_MUTED).join(run_facts(item, now)))
    row.append("\n")
    return row
