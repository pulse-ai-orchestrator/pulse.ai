"""Single status vocabulary (label, color, icon) for everything shown on screen.

Indexed by the raw status value so the same state renders identically whether it
comes from the workflow, event history or catalog enums.
"""

from __future__ import annotations

from enum import Enum

AWAITING_YOU = "precisa de você"
RUNNING = "executando"
STATUS_LABELS: dict[str, str] = {
    "pending": "pendente",
    "in_progress": RUNNING,
    "running": RUNNING,
    "awaiting_input": AWAITING_YOU,
    "awaiting_approval": AWAITING_YOU,
    "approved": "aprovado",
    "blocked": "bloqueado",
    "stopped": "parado",
    "done": "concluído",
    "completed": "concluído",
    "skipped": "pulado",
    "failed": "falhou",
}

_PENDING = "#8C8C90"
_RUNNING = "#38BDF8"
_AWAITING = "#FBBF24"
_DONE = "#4ADE80"
_BLOCKED = "#FB923C"
_STOPPED = "#A78BFA"
_SKIPPED = "#6C7A89"
_FAILED = "#F87171"

STATUS_COLORS: dict[str, str] = {
    "pending": _PENDING,
    "in_progress": _RUNNING,
    "running": _RUNNING,
    "awaiting_input": _AWAITING,
    "awaiting_approval": _AWAITING,
    "approved": _DONE,
    "blocked": _BLOCKED,
    "stopped": _STOPPED,
    "done": _DONE,
    "completed": _DONE,
    "skipped": _SKIPPED,
    "failed": _FAILED,
}

# Dark shade of each color, painted behind it so a status reads as a badge.
STATUS_TINTS: dict[str, str] = {
    _PENDING: "#232326",
    _RUNNING: "#0C2A3A",
    _AWAITING: "#3A2C06",
    _DONE: "#12301F",
    _BLOCKED: "#3A2008",
    _STOPPED: "#241B3D",
    _SKIPPED: "#1F2329",
    _FAILED: "#3B1414",
}

STATUS_ICONS: dict[str, str] = {
    "pending": "○",
    "in_progress": "●",
    "running": "●",
    "awaiting_input": "◆",
    "awaiting_approval": "◆",
    "approved": "✓",
    "blocked": "⊘",
    "stopped": "■",
    "done": "✓",
    "completed": "✓",
    "skipped": "↷",
    "failed": "✗",
}

FALLBACK_COLOR = "#888888"
FALLBACK_ICON = "·"


def normalize(status: str | Enum) -> str:
    """Treat an enum, `in progress` and `in_progress` as the same state."""
    raw = status.value if isinstance(status, Enum) else status
    return str(raw or "").strip().lower().replace(" ", "_").replace("-", "_")


def status_label(status: str | Enum) -> str:
    key = normalize(status)
    return STATUS_LABELS.get(key, key.replace("_", " "))


def status_color(status: str | Enum) -> str:
    return STATUS_COLORS.get(normalize(status), FALLBACK_COLOR)


def status_icon(status: str | Enum) -> str:
    return STATUS_ICONS.get(normalize(status), FALLBACK_ICON)


def status_tint(status: str | Enum) -> str:
    """Dark shade of the status color, to paint behind it."""
    return STATUS_TINTS.get(status_color(status), STATUS_TINTS[_PENDING])


def status_badge_style(status: str | Enum) -> str:
    """Rich style for a status badge: bold color over its own dark tint."""
    return f"bold {status_color(status)} on {status_tint(status)}"


LABEL_WIDTH = max(len(label) for label in STATUS_LABELS.values())
