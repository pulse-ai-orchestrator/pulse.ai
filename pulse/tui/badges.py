from __future__ import annotations

from enum import Enum

from rich.text import Text

from pulse.history.status_labels import status_badge_style, status_icon, status_label


def status_badge(status: str | Enum, *, loud: bool = False) -> Text:
    """A status as a colored badge; `loud` capitalizes it for the run-level one."""
    label = status_label(status)
    return Text(
        f" {status_icon(status)} {label.upper() if loud else label} ",
        style=status_badge_style(status),
    )
