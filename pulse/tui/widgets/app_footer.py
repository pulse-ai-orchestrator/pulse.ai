from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static

from pulse.tui import strings
from pulse.tui.palette import KEY_CAP, LIME, TEXT, TEXT_MUTED
from pulse.tui.state import CockpitState

if TYPE_CHECKING:
    from typing import Unpack

    from pulse.tui.widgets.options import WidgetOptions


class AppFooter(Widget):
    def __init__(
        self, back_label: str = strings.FOOTER_MENU, **kwargs: Unpack[WidgetOptions]
    ) -> None:
        super().__init__(**kwargs)
        self._back_label = back_label

    def compose(self) -> ComposeResult:
        yield Static(id="footer-text")

    def on_mount(self) -> None:
        self.sync_from_state(None)

    def sync_from_state(self, state: CockpitState | None) -> None:
        focus = strings.FOOTER_FOCUS_PHASES
        if state is not None:
            if state.focus_target == "stream":
                focus = strings.FOOTER_FOCUS_STREAM
            elif state.focus_target == "artifact":
                focus = strings.FOOTER_FOCUS_ARTIFACT
        keys: list[tuple[str, str]] = []
        if state is not None and state.artifact_pane_open:
            keys += [("A/ESC", strings.FOOTER_CLOSE), ("[ ]", strings.FOOTER_FILE)]
        elif state is not None and state.phase_has_artifacts():
            keys.append(("A", strings.FOOTER_OPEN))
        if state is not None and state.running and state.can_stop:
            keys.append(("S", strings.FOOTER_STOP))
        keys += [
            ("↑↓/JK", strings.FOOTER_NAV),
            ("TAB", strings.FOOTER_FOCUS),
            ("Q/B", self._back_label),
        ]
        text = Text()
        text.append(f"{strings.FOOTER_FOCUS} ", style=TEXT_MUTED)
        text.append(focus, style=f"bold {LIME}")
        for key, label in keys:
            text.append("   ")
            text.append(f" {key} ", style=f"bold {TEXT} on {KEY_CAP}")
            text.append(f" {label}", style=TEXT_MUTED)
        self.query_one("#footer-text", Static).update(text)
