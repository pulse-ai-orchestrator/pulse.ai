from __future__ import annotations

import time
from typing import TYPE_CHECKING

from rich.text import Text
from textual.app import ComposeResult
from textual.css.query import NoMatches
from textual.events import Click
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

from pulse.history.status_labels import status_color
from pulse.tui import strings
from pulse.tui.badges import status_badge
from pulse.tui.palette import LIME, RAISED, TEXT, TEXT_DIM, TEXT_MUTED
from pulse.tui.state import NAV_PHASE, CockpitState, PhaseItem, PhaseStatus

if TYPE_CHECKING:
    from typing import Unpack

    from pulse.tui.widgets.options import WidgetOptions


class NavSelected(Message):
    def __init__(self, kind: str, index: int) -> None:
        super().__init__()
        self.kind = kind
        self.index = index


PhaseSelected = NavSelected

_ATTENTION = frozenset(
    {
        PhaseStatus.RUNNING.value,
        PhaseStatus.FAILED.value,
        PhaseStatus.BLOCKED.value,
        "awaiting_input",
    }
)
_SETTLED = frozenset({PhaseStatus.DONE, PhaseStatus.SKIPPED})
# Before the first layout the widget has no width; render for the narrowest sidebar.
_FALLBACK_WIDTH = 28
_NO_CLOCK = "--:--"


def _row(left: Text, right: Text, width: int, background: str) -> Text:
    """`left` and `right` pushed to the edges of one line, painted on `background`."""
    row = Text()
    row.append_text(left)
    row.append(" " * max(1, width - left.cell_len - right.cell_len))
    row.append_text(right)
    if background:
        row.stylize(f"on {background}")
    row.append("\n")
    return row


def _fit(label: str, room: int) -> str:
    room = max(4, room)
    return label if len(label) <= room else f"{label[: room - 1]}…"


def _group_status(statuses: list[PhaseStatus]) -> PhaseStatus:
    """The fan-out's status: the most urgent of its tasks."""
    for urgent in (PhaseStatus.FAILED, PhaseStatus.BLOCKED, PhaseStatus.RUNNING):
        if urgent in statuses:
            return urgent
    if all(status in _SETTLED for status in statuses):
        return PhaseStatus.DONE
    return PhaseStatus.PENDING


class PhaseSidebar(Widget):
    can_focus = True
    selected_index: reactive[int] = reactive(0)

    def __init__(self, state: CockpitState, **kwargs: Unpack[WidgetOptions]) -> None:
        super().__init__(**kwargs)
        self._state = state
        self._slots: list[tuple[int, int, str, int]] = []

    def compose(self) -> ComposeResult:
        yield Static("", id="phase-content")

    def on_mount(self) -> None:
        self.refresh_phases()
        self.set_interval(0.25, self.refresh_phases)

    def refresh_phases(self) -> None:
        content = self.query_one("#phase-content", Static)
        content.update(self._render_phases(self._state))

    def sync_from_state(self, state: CockpitState) -> None:
        self._state = state
        self.selected_index = state._selected_nav_index()
        self.refresh_phases()

    def on_click(self, event: Click) -> None:
        if not self._state.phases:
            return
        try:
            content = self.query_one("#phase-content", Static)
        except NoMatches:
            return
        y = event.screen_y - content.region.y
        if y < 0:
            return
        for start, end, kind, index in self._slots:
            if start <= y <= end:
                event.stop()
                self.post_message(NavSelected(kind, index))
                return

    def _width(self) -> int:
        width = self.content_region.width
        return width if width > 0 else _FALLBACK_WIDTH

    def _render_phases(self, state: CockpitState) -> Text:
        output = Text()
        self._slots = []
        now = time.monotonic()
        line = 0
        if not state.phases:
            output.append(f"{strings.SIDEBAR_NO_STEPS}\n", style=TEXT_MUTED)
            return output

        for number, (key, members) in enumerate(state.phase_groups(), start=1):
            if key:
                output.append_text(self._render_group(state, key, members, number=number))
                line += 2
            for index, phase in members:
                self._slots.append((line, line + 2, NAV_PHASE, index))
                output.append_text(
                    self._render_item(
                        state,
                        phase,
                        selected=index == state.selected_phase_index,
                        now=now,
                        nested=bool(key),
                        number=0 if key else number,
                    )
                )
                line += 3
        return output

    def _render_group(
        self,
        state: CockpitState,
        key: str,
        members: list[tuple[int, PhaseItem]],
        *,
        number: int,
    ) -> Text:
        """Fan-out header: the step, its most urgent task status and how many settled."""
        statuses = [phase.status for _index, phase in members]
        done = sum(1 for status in statuses if status in _SETTLED)
        status = _group_status(statuses)
        shown = (
            "awaiting_input"
            if any(phase.awaiting_since is not None for _index, phase in members)
            else status.value
        )
        tone = status_color(shown)
        width = self._width()
        head = Text()
        head.append("▌ " if status == PhaseStatus.RUNNING else "  ", style=tone)
        head.append(f"{number:02d} ", style=TEXT_MUTED)
        count = Text(f"{done}/{len(members)}", style=f"bold {tone}")
        room = width - head.cell_len - count.cell_len - 1
        name_style = f"bold {tone}" if shown in _ATTENTION else f"bold {TEXT}"
        head.append(_fit(state.base_step_label(key) or key, room), style=name_style)
        output = _row(head, count, width, "")
        output.append("     ")
        output.append_text(status_badge(shown))
        output.append("\n")
        return output

    def _render_item(
        self,
        state: CockpitState,
        item: PhaseItem,
        *,
        selected: bool,
        now: float,
        nested: bool = False,
        number: int = 0,
    ) -> Text:
        """Two lines and a spacer: name and clock, then the status badge and tokens."""
        shown = item.display_status()
        tone = status_color(shown)
        attention = shown in _ATTENTION
        focused = selected and state.focus_target == "phases"
        width = self._width()
        background = RAISED if selected else ""

        head = Text("  " if nested else "")
        if attention:
            head.append("▌ ", style=tone)
        elif focused:
            head.append("▌ ", style=LIME)
        elif selected:
            head.append("│ ", style=LIME)
        else:
            head.append("  ")
        lead = head.cell_len
        if number:
            head.append(f"{number:02d} ", style=TEXT_MUTED if item.status in _SETTLED else TEXT_DIM)

        elapsed = item.elapsed_label(now)
        clock = Text(elapsed or _NO_CLOCK, style=self._clock_style(item, tone, bool(elapsed)))
        rounds = f" ×{item.rounds}" if item.rounds > 1 else ""
        room = width - head.cell_len - clock.cell_len - len(rounds) - 1
        head.append(
            _fit(self._item_label(item, nested=nested), room),
            style=self._name_style(item, tone, attention=attention, selected=selected),
        )
        if rounds:
            head.append(rounds, style=f"bold {status_color('awaiting_input')}")
        output = _row(head, clock, width, background)

        meta = Text(" " * (lead + (3 if number else 0)))
        meta.append_text(status_badge(shown))
        context = Text(state.context_label(item), style=TEXT_MUTED)
        output.append_text(_row(meta, context, width, background))
        output.append("\n")
        return output

    @staticmethod
    def _clock_style(item: PhaseItem, tone: str, ticking: bool) -> str:
        if not ticking:
            return TEXT_DIM
        if item.status in _SETTLED:
            return f"bold {TEXT}"
        return f"bold {tone}"

    @staticmethod
    def _name_style(item: PhaseItem, tone: str, *, attention: bool, selected: bool) -> str:
        if attention:
            return f"bold {tone}"
        if selected:
            return f"bold {TEXT}"
        if item.status in _SETTLED:
            return TEXT
        return TEXT_MUTED

    @staticmethod
    def _item_label(item: PhaseItem, *, nested: bool) -> str:
        if not nested:
            return item.label
        _base, _sep, task_id = item.id.partition(":")
        if not task_id or item.label == task_id or item.label.startswith(f"{task_id} "):
            return item.label or task_id
        return f"{task_id} · {item.label}"
