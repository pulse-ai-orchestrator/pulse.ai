"""How the agent's reply settles a step attempt.

A pure decision over the session result and the step definition: the engine
applies the verdict to the run aggregate and persists it. Failures before the
reply (template error, crashed session) never reach here.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pulse.orchestrator.outcome import LoopSignal, Outcome, OutcomeStatus, parse_outcome
from pulse.prompts.approval import CANCEL, SKIP
from pulse.store.workflow_defs import StepDef

_SUCCESS_STOPS = frozenset({"end_turn", "end", "stop"})
_CANCELLED = "cancelled"


class VerdictKind(StrEnum):
    DELIVERED = "delivered"
    SKIPPED = "skipped"
    BLOCKED = "blocked"
    FAILED = "failed"


@dataclass(frozen=True)
class Verdict:
    """`reason` explains a failure or a block to the person deciding what next;
    `signal` is what a delivery asks of the loop around the step."""

    kind: VerdictKind
    reason: str = ""
    signal: LoopSignal | None = None


def judge_attempt(result: Mapping[str, Any], step: StepDef, *, may_close: bool) -> Verdict:
    """Verdict of one attempt. Only a loop opener (`may_close`) can end its loop
    without approval: a clean review has nothing to approve."""
    text = str(result.get("phaseSummary", ""))
    outcome = str(result.get("outcome", ""))
    approved = bool(result.get("approved"))

    if outcome in {CANCEL, _CANCELLED} or result.get("stopReason") == _CANCELLED:
        return Verdict(VerdictKind.FAILED, reason="step cancelado")
    if outcome == SKIP:
        return Verdict(VerdictKind.SKIPPED)
    if may_close and not approved and parse_outcome(text).closes:
        return Verdict(VerdictKind.DELIVERED, signal=LoopSignal.CLOSE)

    if step.requires_approval:
        if approved:
            return Verdict(VerdictKind.DELIVERED)
        if not str(result.get("approvalAnswers", "")).strip():
            return Verdict(
                VerdictKind.FAILED,
                reason="o agente encerrou sem o bloco de aprovação nem um desfecho válido",
            )
        return Verdict(VerdictKind.FAILED, reason="step não aprovado")

    stop_reason = str(result.get("stopReason") or "")
    if stop_reason not in _SUCCESS_STOPS:
        return Verdict(VerdictKind.FAILED, reason=stop_reason or "o agente não concluiu o step")
    if not step.requires_outcome:
        return Verdict(VerdictKind.DELIVERED)

    declared = parse_outcome(text)
    if not declared.delivered:
        return Verdict(VerdictKind.BLOCKED, reason=_blocked_reason(declared))
    return Verdict(VerdictKind.DELIVERED, signal=LoopSignal.REPEAT if declared.repeats else None)


def _blocked_reason(declared: Outcome) -> str:
    if declared.status == OutcomeStatus.MISSING:
        return (
            "o agente encerrou sem declarar o desfecho do step — "
            "não dá para afirmar que ele entregou o que o step pede"
        )
    return declared.reason or "o agente declarou bloqueio sem dizer o motivo"
