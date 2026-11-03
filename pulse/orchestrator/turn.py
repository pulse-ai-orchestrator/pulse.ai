"""What the session runner reports about one agent turn, and the user's menu choices.

The runner answers with a `dict` keyed by ACP/approval field names. It is parsed
here, once, so the engine branches on intent (`turn.cancelled`) instead of on
string keys spread across the step flow.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from pulse.domain.ports import JsonObject
from pulse.replies.approval import ApprovalOutcome

CANCELLED = "cancelled"
_CANCEL_OUTCOMES = frozenset({ApprovalOutcome.CANCEL, CANCELLED})
_CLEAN_STOPS = frozenset({"end_turn", "end", "stop"})


@dataclass(frozen=True)
class TurnResult:
    summary: str = ""
    outcome: str = ""
    stop_reason: str = ""
    approved: bool = False
    approval_answers: str = ""
    turns_exhausted: bool = False

    @classmethod
    def parse(cls, raw: JsonObject) -> TurnResult:
        return cls(
            summary=str(raw.get("phaseSummary") or ""),
            outcome=str(raw.get("outcome") or ""),
            stop_reason=str(raw.get("stopReason") or ""),
            approved=bool(raw.get("approved")),
            approval_answers=str(raw.get("approvalAnswers") or ""),
            turns_exhausted=bool(raw.get("turnsExhausted")),
        )

    @property
    def cancelled(self) -> bool:
        return self.outcome in _CANCEL_OUTCOMES or self.stop_reason == CANCELLED

    @property
    def skipped(self) -> bool:
        """The agent declared the step does not apply."""
        return self.outcome == ApprovalOutcome.SKIP

    @property
    def ended_cleanly(self) -> bool:
        """The agent ended its turn on its own; anything else is not a success."""
        return self.stop_reason in _CLEAN_STOPS

    @property
    def has_approval_answers(self) -> bool:
        """The approval questionnaire was answered, so the agent did ask."""
        return bool(self.approval_answers.strip())


class MenuChoice(StrEnum):
    """What the user picked after a failed or blocked step."""

    RETRY = "retry"
    GUIDANCE = "guidance"
    SKIP = "skip"
    STOP = "stop"
