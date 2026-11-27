from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

from pulse.history.events import PhaseItem
from pulse.history.status_labels import status_color
from pulse.tui import strings
from pulse.tui.badges import status_badge
from pulse.tui.palette import BORDER, TEXT, TEXT_MUTED
from pulse.tui.state import CockpitState, PhaseStatus

if TYPE_CHECKING:
    from typing import Unpack

    from pulse.tui.widgets.options import WidgetOptions

METER_CELLS = 24
_CLOCK_TICK_SECONDS = 1.0


def format_clock(seconds: float) -> str:
    """`HH:MM:SS`, so the run total keeps one width as it grows."""
    total = int(max(0.0, seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def progress_meter(phases: list[PhaseItem], cells: int = METER_CELLS) -> Text:
    """One colored segment per step, so the bar says where the run stands, not just how far.

    More steps than cells (a wide fan-out) are sampled evenly across the bar.
    """
    meter = Text()
    count = len(phases)
    if not count:
        return meter
    shown = min(count, cells)
    width = max(1, cells // shown)
    glyph = "━" * (width - 1) + " " if width > 1 else "━"
    for slot in range(shown):
        phase = phases[slot * count // shown]
        status = phase.display_status()
        tone = BORDER if phase.status == PhaseStatus.PENDING else status_color(status)
        meter.append(glyph, style=tone)
    return meter


def run_clock(state: CockpitState) -> Text:
    clock = Text()
    clock.append(f" {strings.HEADER_TOTAL} ", style=TEXT_MUTED)
    clock.append(f"{format_clock(state.elapsed_seconds())} ", style=f"bold {TEXT}")
    return clock


class AppHeader(Widget):
    run_label: reactive[str] = reactive(strings.HEADER_RUN_EMPTY)
    workflow_label: reactive[str] = reactive("")

    def __init__(self, **kwargs: Unpack[WidgetOptions]) -> None:
        super().__init__(**kwargs)
        self._state: CockpitState | None = None

    def compose(self) -> ComposeResult:
        with Horizontal(id="header-top"):
            yield Static(strings.HEADER_BRAND, classes="brand")
            yield Static(self.workflow_label, classes="workflow-label", id="workflow-label")
            yield Static("", classes="run-badge", id="run-badge")
            yield Static("", classes="run-clock", id="run-clock")
        with Horizontal(id="header-sub"):
            yield Static("", classes="run-meter", id="run-meter")
            yield Static(self.run_label, classes="run-status", id="run-status")
            yield Static("", classes="run-where", id="run-where")

    def on_mount(self) -> None:
        self.set_interval(_CLOCK_TICK_SECONDS, self._tick_clock)

    # The watchers fire before `compose` has mounted the labels; compose seeds them.
    def watch_run_label(self, value: str) -> None:
        with contextlib.suppress(NoMatches):
            self.query_one("#run-status", Static).update(value)

    def watch_workflow_label(self, value: str) -> None:
        with contextlib.suppress(NoMatches):
            self.query_one("#workflow-label", Static).update(value)

    def sync_from_state(self, state: CockpitState) -> None:
        self._state = state
        done, total = state.done_count(), state.total_count()
        label = strings.HEADER_RUN_EMPTY
        if total:
            percent = round(100 * done / total)
            label = strings.HEADER_PROGRESS.format(done=done, total=total, percent=percent)
        if context := state.run_context_label():
            label = f"{label} · {context}"
        self.run_label = label
        self.workflow_label = state.workflow_label
        self.query_one("#run-badge", Static).update(status_badge(state.run_status(), loud=True))
        self.query_one("#run-meter", Static).update(progress_meter(state.phases))
        where = " · ".join(
            part
            for part in (
                strings.HEADER_BRANCH.format(branch=state.branch_label)
                if state.branch_label
                else "",
                state.model_label or state.agent_label,
            )
            if part
        )
        self.query_one("#run-where", Static).update(where)
        self._tick_clock()

    def _tick_clock(self) -> None:
        """The clock moves on its own: the screen only syncs when the run reports something."""
        if self._state is None:
            return
        with contextlib.suppress(NoMatches):
            self.query_one("#run-clock", Static).update(run_clock(self._state))
