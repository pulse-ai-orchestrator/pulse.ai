from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pulse.domain.run import StepStatus
from pulse.replies.acp_payloads import non_negative_int

# The screen shows the persisted step states; one vocabulary, no translation.
PhaseStatus = StepStatus


class LogKind(StrEnum):
    SEARCH = "Search"
    LIST = "List"
    READ = "Read"
    EDIT = "Edit"
    WRITE = "Write"
    SHELL = "Shell"
    INFO = "Info"
    ERROR = "Error"
    ASSISTANT = "Assistant"
    QUESTION = "Question"
    ANSWER = "Answer"
    TOOL = "Tool"


def format_elapsed(seconds: float) -> str:
    """Readable duration for a narrow column.

    `MM:SS` up to one hour, then `1h06`, then `2d03`.
    """
    total = int(max(0.0, seconds))
    if total < 3600:
        minutes, secs = divmod(total, 60)
        return f"{minutes:02d}:{secs:02d}"
    hours, remainder = divmod(total, 3600)
    if hours < 24:
        return f"{hours}h{remainder // 60:02d}"
    days, leftover = divmod(hours, 24)
    return f"{days}d{leftover:02d}"


def format_tokens(tokens: int) -> str:
    """Token count for a narrow column: `950`, `42k`, `1.2M`."""
    if tokens < 1000:
        return str(tokens)
    if tokens < 1_000_000:
        return f"{tokens // 1000}k"
    return f"{tokens // 100_000 / 10:.1f}M"


@dataclass(frozen=True)
class ContextUsage:
    """How many tokens a step's context holds, as the agent's `usage_update` reports it.

    A level, not a running sum: compaction can lower it.
    """

    used: int

    @classmethod
    def parse(cls, update: dict[str, Any]) -> ContextUsage | None:
        """Agent output is untrusted: without a valid `used` there is no reading."""
        used = non_negative_int(update.get("used"))
        return None if used is None else cls(used=used)


@dataclass
class PhaseItem:
    id: str
    label: str
    status: PhaseStatus = PhaseStatus.PENDING
    started_at: float | None = None
    ended_at: float | None = None
    awaiting_since: float | None = None
    waiting_total: float = 0.0
    rounds: int = 1
    files: int = 0
    issues: int = 0
    context: ContextUsage | None = None
    _seen_files: set[str] = field(default_factory=set, repr=False, compare=False)
    _seen_issues: set[str] = field(default_factory=set, repr=False, compare=False)

    def elapsed_label(self, now: float | None = None) -> str:
        """Step duration; the clock only runs while the step executes.

        A closed duration (`ended_at`) wins over the status, since a run opened
        from history may still be marked `running`. Time spent waiting on the
        user is excluded: the clock freezes at `awaiting_since` and past waits
        are subtracted via `waiting_total`.
        """
        seconds = self.elapsed_seconds(now)
        return "" if seconds is None else format_elapsed(seconds)

    def elapsed_seconds(self, now: float | None = None) -> float | None:
        """The seconds behind `elapsed_label`; `None` when the step shows no clock."""
        if self.started_at is None:
            return None
        if self.ended_at is not None:
            end = self.ended_at
        elif self.awaiting_since is not None:
            end = self.awaiting_since
        elif self.status == PhaseStatus.RUNNING:
            end = now or time.monotonic()
        else:
            return None
        return max(0.0, end - self.started_at - self.waiting_total)

    def closed_seconds(self) -> float:
        """Closed time of this step, net of waiting. Zero if it never closed.

        Used as the starting point when the step runs again, like
        `carried_seconds` in the database.
        """
        if self.started_at is None or self.ended_at is None:
            return 0.0
        return max(0.0, self.ended_at - self.started_at - self.waiting_total)

    def display_status(self) -> str:
        """The status as the UI should name it.

        `awaiting_input` is not a stored step state (the step stays `running`);
        it is overlaid only for display.
        """
        if self.awaiting_since is not None:
            return "awaiting_input"
        return self.status.value

    def begin_waiting(self, now: float | None = None) -> None:
        if self.awaiting_since is None:
            self.awaiting_since = now if now is not None else time.monotonic()

    def end_waiting(self, now: float | None = None) -> None:
        if self.awaiting_since is None:
            return
        end = now if now is not None else time.monotonic()
        self.waiting_total += max(0.0, end - self.awaiting_since)
        self.awaiting_since = None

    def finish(self, ended_at: float | None = None) -> None:
        self.end_waiting(ended_at)
        if self.status == PhaseStatus.RUNNING and self.started_at is not None:
            self.ended_at = ended_at if ended_at is not None else time.monotonic()
        if self.status == PhaseStatus.RUNNING:
            self.status = PhaseStatus.DONE

    def end_as(self, status: PhaseStatus, now: float) -> None:
        """Move to a terminal `status`, stopping the clock if the step was running."""
        if self.status == PhaseStatus.RUNNING and self.started_at is not None:
            self.ended_at = now
        self.status = status

    def restart(self) -> None:
        """Back to pending with no time spent: an interrupted step reruns from scratch."""
        self.status = PhaseStatus.PENDING
        self.started_at = None
        self.ended_at = None
        self.awaiting_since = None
        self.waiting_total = 0.0
        self.context = None

    def show_closed(self, seconds: float) -> None:
        """A fixed duration read from storage; it does not tick."""
        self.started_at = 0.0
        self.ended_at = seconds
        self.waiting_total = 0.0

    def resume_clock(self, started_at: float, waiting_total: float) -> None:
        """Keep ticking a running step from where the persisted clock left it."""
        self.started_at = started_at
        self.ended_at = None
        self.waiting_total = max(0.0, waiting_total)


@dataclass
class LogEntry:
    kind: LogKind
    title: str
    detail: str = ""
    body: str = ""
    active: bool = False
    pending: bool = False
    entry_id: int = 0
    tool_id: str = ""
    phase_id: str = ""


@dataclass
class ArtifactItem:
    path: str
    phase_id: str = ""
    ready: bool = False
    has_content: bool = False
