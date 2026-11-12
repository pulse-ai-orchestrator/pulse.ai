from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pulse.domain.run import SETTLED, StepStatus
from pulse.history.status_labels import status_label


class HistoryStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    AWAITING_INPUT = "awaiting_input"
    DONE = "done"
    FAILED = "failed"
    STOPPED = "stopped"
    BLOCKED = "blocked"


LIVE_STATUSES = frozenset({HistoryStatus.IN_PROGRESS, HistoryStatus.AWAITING_INPUT})


@dataclass
class HistoryStep:
    id: str
    label: str
    status: StepStatus
    acp_session_id: str = ""

    @property
    def settled(self) -> bool:
        return self.status in SETTLED

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "label": self.label,
            "status": self.status.value,
            "acp_session_id": self.acp_session_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> HistoryStep:
        return cls(
            id=str(data["id"]),
            label=str(data.get("label") or ""),
            status=StepStatus.parse(str(data.get("status") or "")),
            acp_session_id=str(data.get("acp_session_id") or ""),
        )


@dataclass
class HistoryItem:
    """A past run as the history screen shows it.

    A run is identified by its Pulse-generated id; files it left on disk are in
    `artifacts`.
    """

    run_id: str
    workflow_id: str
    workflow_label: str
    title: str
    prompt: str
    status: HistoryStatus
    updated_at: str
    steps: list[HistoryStep] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    branch: str = ""
    worktree_path: str = ""
    duration_seconds: float | None = None

    @property
    def item_id(self) -> str:
        return self.run_id

    def to_dict(self) -> dict[str, Any]:
        """The `/api/history` wire shape; `from_dict` reads it back on the client."""
        return {
            "id": self.item_id,
            "run_id": self.run_id,
            "workflow_id": self.workflow_id,
            "workflow_label": self.workflow_label,
            "title": self.title,
            "prompt": self.prompt,
            "status": self.status.value,
            "updated_at": self.updated_at,
            "artifacts": list(self.artifacts),
            "branch": self.branch,
            "worktree_path": self.worktree_path,
            "duration_seconds": self.duration_seconds,
            "steps": [step.to_dict() for step in self.steps],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> HistoryItem:
        try:
            status = HistoryStatus(str(data.get("status") or ""))
        except ValueError:
            status = HistoryStatus.PENDING
        return cls(
            run_id=str(data["run_id"]),
            workflow_id=str(data.get("workflow_id") or ""),
            workflow_label=str(data.get("workflow_label") or ""),
            title=str(data.get("title") or ""),
            prompt=str(data.get("prompt") or ""),
            status=status,
            updated_at=str(data.get("updated_at") or ""),
            steps=[HistoryStep.from_dict(step) for step in data.get("steps") or ()],
            artifacts=[str(path) for path in data.get("artifacts") or ()],
            branch=str(data.get("branch") or ""),
            worktree_path=str(data.get("worktree_path") or ""),
            duration_seconds=_duration_seconds(data.get("duration_seconds")),
        )

    @property
    def status_label(self) -> str:
        return status_label(self.status)

    @property
    def is_incomplete(self) -> bool:
        """Whether steps remain to be done, which decides if the run can resume.

        Steps decide, not the run status: `failed` and `stopped` runs can also
        have work left to resume.
        """
        if self.status is HistoryStatus.DONE:
            return False
        if not self.steps:
            return self.status is HistoryStatus.PENDING or self.status in LIVE_STATUSES
        return any(not step.settled for step in self.steps)


def _duration_seconds(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    seconds = float(value)
    if seconds < 0 or not math.isfinite(seconds):
        return None
    return seconds
