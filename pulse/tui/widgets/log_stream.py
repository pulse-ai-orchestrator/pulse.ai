from __future__ import annotations

import re
import textwrap
from collections.abc import Callable
from typing import TYPE_CHECKING

from rich.markup import escape
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.widget import Widget
from textual.widgets import Static

from pulse.history.status_labels import status_color
from pulse.tui import strings
from pulse.tui.adapters.prompt_bridge import PromptKind, PromptRequest, format_prompt_reply
from pulse.tui.badges import status_badge
from pulse.tui.palette import ERROR, ERROR_SOFT, TEXT, TEXT_DIM, TEXT_MUTED
from pulse.tui.state import CockpitState, LogEntry, LogKind, PhaseStatus
from pulse.tui.widgets.prompt_dock import PromptDock

if TYPE_CHECKING:
    from typing import Unpack

    from pulse.tui.widgets.options import WidgetOptions

_SPINNER = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
_INLINE_RE = re.compile(r"`([^`]+)`|\*\*([^*]+)\*\*|__([^_]+)__")
_ASSIST_INDENT = "  "
_ASSIST_GUTTER = "│ "
_VISIBLE_ENTRIES = 120
_KIND_WIDTH = 7
# One hue per kind of tool, so a scan of the log tells reading from changing from running.
_KIND_COLORS: dict[LogKind, str] = {
    LogKind.READ: "#2DD4BF",
    LogKind.LIST: "#2DD4BF",
    LogKind.SEARCH: "#60A5FA",
    LogKind.EDIT: "#A2D729",
    LogKind.WRITE: "#A2D729",
    LogKind.SHELL: "#C084FC",
}
_TOOL_KINDS = frozenset(_KIND_COLORS) | {LogKind.TOOL}
# Gutter, check mark, kind column and a space: details hang under the call's target.
_DETAIL_INDENT = " " * (2 + 2 + _KIND_WIDTH + 1)


def _assistant_line(text: str) -> Text:
    line = Text()
    pos = 0
    for match in _INLINE_RE.finditer(text):
        if match.start() > pos:
            line.append(text[pos : match.start()], style="#E0E0E0")
        code, bold_a, bold_b = match.groups()
        if code is not None:
            line.append(code, style="bold #A2D729")
        else:
            line.append(bold_a or bold_b or "", style="bold #E0E0E0")
        pos = match.end()
    if pos < len(text):
        line.append(text[pos:], style="#E0E0E0")
    if not line.plain:
        line.append(text, style="#E0E0E0")
    return line


def format_assistant_lines(body: str, *, width: int = 72) -> list[str]:
    text = (body or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return []
    wrap_width = max(24, width)
    lines: list[str] = []
    paragraphs = re.split(r"\n\s*\n", text)
    for index, paragraph in enumerate(paragraphs):
        chunk = " ".join(part.strip() for part in paragraph.splitlines() if part.strip())
        if not chunk:
            continue
        wrapped = textwrap.wrap(
            chunk,
            width=wrap_width,
            break_long_words=True,
            break_on_hyphens=False,
        )
        lines.extend(wrapped or [chunk])
        if index < len(paragraphs) - 1:
            lines.append("")
    return lines


class LogStream(Widget):
    can_focus = True

    def __init__(self, state: CockpitState, **kwargs: Unpack[WidgetOptions]) -> None:
        super().__init__(**kwargs)
        self._state = state
        self._fingerprint: tuple[object, ...] | None = None
        self._spin_frame = 0

    def compose(self) -> ComposeResult:
        yield Static("", id="stream-header", classes="stream-title")
        yield Static("", id="stream-meta", classes="stream-meta")
        with VerticalScroll(id="stream-body"):
            yield Static("", id="stream-content")
        slot = Vertical(id="prompt-slot")
        slot.display = False
        yield slot

    def on_mount(self) -> None:
        self.sync_from_state(self._state, force=True)
        self.set_interval(0.08, self._tick_spinner)
        self.set_interval(1.0, self._tick_header)

    def on_resize(self) -> None:
        self.sync_from_state(self._state, force=True)

    def show_prompt(
        self,
        request: PromptRequest,
        on_result: Callable[[object | None], None],
    ) -> None:
        slot = self.query_one("#prompt-slot", Vertical)

        def _done(result: object | None) -> None:
            def _hide() -> None:
                if slot.is_mounted:
                    slot.remove_children()
                    slot.styles.height = None
                    slot.display = False

            self._state.add_qa(request.prompt, format_prompt_reply(request, result))
            self.sync_from_state(self._state, force=True)
            self.call_after_refresh(_hide)
            on_result(result)

        slot.remove_children()
        slot.styles.height = self._prompt_slot_height(request)
        slot.display = True
        slot.mount(PromptDock(request, _done))

    def focus_prompt(self) -> bool:
        try:
            dock = self.query_one(PromptDock)
        except NoMatches:
            return False
        dock.focus_inner()
        return True

    def _prompt_slot_height(self, request: PromptRequest) -> int:
        available = self.size.height if self.size.height > 0 else 24
        cap = max(12, min(available - 3, int(available * 0.8)))
        title = 1
        border = 1
        width = max(24, (self.size.width if self.size.width > 0 else 80) - 8)
        prompt_lines = min(3, max(1, (len(request.prompt) + width - 1) // width))
        hint = 1
        if request.kind in {PromptKind.SELECT, PromptKind.MULTI_SELECT}:
            rows = max(1, min(len(request.choices), 10))
            extra = 4 if request.kind == PromptKind.MULTI_SELECT else 0
            return min(cap, border + title + prompt_lines + hint + rows + extra)
        if request.kind == PromptKind.CONFIRM:
            return min(cap, border + title + prompt_lines + 3)
        return min(cap, border + title + prompt_lines + hint + 3)

    def _tick_header(self) -> None:
        """The step clock moves on its own, between the run's events."""
        self.query_one("#stream-header", Static).update(_render_header(self._state))

    def _tick_spinner(self) -> None:
        if not any(entry.pending for entry in self._state.visible_entries()):
            return
        self._spin_frame = (self._spin_frame + 1) % len(_SPINNER)
        self.sync_from_state(self._state, force=True)

    def sync_from_state(self, state: CockpitState, *, force: bool = False) -> None:
        self._state = state
        fingerprint = self._state_fingerprint(state)
        header = self.query_one("#stream-header", Static)
        meta = self.query_one("#stream-meta", Static)
        content = self.query_one("#stream-content", Static)
        body = self.query_one("#stream-body", VerticalScroll)

        header.update(_render_header(state))
        visible = state.visible_entries()
        count = len(visible)
        position = (state.selected_phase_index + 1) if state.phases else 0
        total = state.total_count()
        meta.update(
            Text(
                strings.STREAM_META.format(count=count, position=position, total=total),
                style=TEXT_MUTED,
            )
        )

        if not force and fingerprint == self._fingerprint:
            return
        self._fingerprint = fingerprint
        content.update(self._render_entries(state))
        body.scroll_end(animate=False)

    def _content_width(self) -> int:
        width = self.size.width if self.size.width > 0 else 80
        return max(24, width - 6)

    @staticmethod
    def _state_fingerprint(state: CockpitState) -> tuple[object, ...]:
        entries = state.visible_entries()
        current = state.selected_nav_item()
        nav_id = current.id if current is not None else ""
        if not entries:
            return (
                0,
                "",
                0,
                False,
                nav_id,
                state.selected_phase_index,
                state.model_label,
                state.branch_label,
            )
        last = entries[-1]
        pending = any(entry.pending for entry in entries)
        return (
            len(entries),
            last.entry_id,
            len(last.body),
            last.title,
            last.detail,
            last.active,
            last.pending,
            pending,
            state.model_label,
            state.branch_label,
            nav_id,
            state.selected_phase_index,
        )

    def _render_bubble(
        self,
        entry_active: bool,
        label: str,
        body: str,
        *,
        gutter_style: str = "#4A5F1A",
        styled: bool = True,
    ) -> Text:
        output = Text()
        prefix = "▌ " if entry_active else "  "
        output.append(prefix, style="#A2D729" if entry_active else "#333333")
        output.append(f"{label}\n", style="bold #E0E0E0")
        lines = format_assistant_lines(body, width=max(24, self._content_width() - 4))
        if not lines:
            output.append("\n")
            return output
        for line in lines:
            output.append(_ASSIST_INDENT)
            if line:
                output.append(_ASSIST_GUTTER, style=gutter_style)
                if styled:
                    output.append_text(_assistant_line(line))
                else:
                    output.append(line, style="#A2D729")
            else:
                output.append(_ASSIST_GUTTER.rstrip(), style=gutter_style)
            output.append("\n")
        output.append("\n")
        return output

    def _render_assistant(self, entry_active: bool, body: str) -> Text:
        return self._render_bubble(entry_active, strings.STREAM_ASSISTANT, body)

    def _render_entries(self, state: CockpitState) -> Text:
        entries = state.visible_entries()[-_VISIBLE_ENTRIES:]
        if not entries:
            return _render_empty(state)
        output = Text()
        last = len(entries) - 1
        previous: LogKind | None = None
        for index, entry in enumerate(entries):
            if previous in _TOOL_KINDS and entry.kind not in _TOOL_KINDS:
                output.append("\n")
            output.append_text(self._render_entry(entry, active=entry.active or index == last))
            previous = entry.kind
        return output

    def _render_entry(self, entry: LogEntry, *, active: bool) -> Text:
        if entry.kind == LogKind.ASSISTANT:
            return self._render_assistant(active, entry.body or "")
        if entry.kind == LogKind.QUESTION:
            return self._render_bubble(active, strings.QUESTION, entry.body or entry.title)
        if entry.kind == LogKind.ANSWER:
            return self._render_bubble(
                active,
                strings.ANSWER,
                entry.body or entry.title,
                gutter_style="#A2D729",
                styled=False,
            )
        if entry.kind == LogKind.ERROR:
            return _render_error(entry, active=active)
        if entry.kind == LogKind.INFO:
            return _render_info(entry, active=active)
        return _render_tool(entry, active=active, spin=_SPINNER[self._spin_frame])


def _render_header(state: CockpitState) -> Text:
    """The selected step's name, its status badge and its clock."""
    current = state.selected_nav_item()
    output = Text()
    if current is None:
        output.append(state.surface_title or strings.STREAM_DEFAULT_SURFACE, style=f"bold {TEXT}")
        return output
    output.append(current.label.upper(), style=f"bold {TEXT}")
    shown = current.display_status()
    output.append("  ")
    output.append_text(status_badge(shown))
    if elapsed := current.elapsed_label():
        output.append("  ")
        output.append(elapsed, style=f"bold {status_color(shown)}")
    return output


def _render_empty(state: CockpitState) -> Text:
    current = state.selected_nav_item()
    settled = current is not None and current.status in {PhaseStatus.DONE, PhaseStatus.SKIPPED}
    message = strings.STREAM_NO_ACTIVITY if settled else strings.STREAM_WAITING
    output = Text()
    output.append(f"{message}\n", style="#888888")
    return output


def _gutter(active: bool) -> str:
    return "▌ " if active else "  "


def _render_error(entry: LogEntry, *, active: bool) -> Text:
    output = Text()
    output.append(_gutter(active), style=ERROR if active else "#333333")
    output.append(f"{strings.ERROR}\n", style=f"bold {ERROR}")
    title = entry.title.strip() or strings.STREAM_WORKFLOW_FAILURE
    output.append(f"  {escape(title)}\n", style=f"bold {ERROR_SOFT}")
    reason = entry.detail.strip()
    if reason and reason != title:
        for line in reason.splitlines():
            output.append(f"  {escape(line)}\n", style=ERROR)
    output.append("\n")
    return output


def _render_info(entry: LogEntry, *, active: bool) -> Text:
    output = Text()
    output.append(_gutter(active), style="#A2D729" if active else "#333333")
    output.append(f"{entry.title}\n", style="#888888")
    output.append("\n")
    return output


def _render_tool(entry: LogEntry, *, active: bool, spin: str) -> Text:
    """One line per call: state, kind and target; details hang below it."""
    output = Text()
    tone = _KIND_COLORS.get(entry.kind, TEXT_MUTED)
    output.append(_gutter(active), style=tone if active else TEXT_DIM)
    if entry.pending:
        output.append(f"{spin} ", style=status_color("running"))
    else:
        output.append("✓ ", style=status_color("done"))
    output.append(f"{entry.kind.value:<{_KIND_WIDTH}} ", style=f"bold {tone}")
    target = entry.title.strip() or entry.detail.strip() or "…"
    if entry.pending and target in {"…", "..."}:
        output.append(f"{strings.STREAM_LOADING}\n", style=TEXT_MUTED)
    else:
        output.append(f"{escape(target)}\n", style=TEXT)
    detail = entry.detail.strip()
    if detail and detail != target:
        for line in detail.splitlines():
            output.append(f"{_DETAIL_INDENT}{escape(line)}\n", style=TEXT_MUTED)
    return output
