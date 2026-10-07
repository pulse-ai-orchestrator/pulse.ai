"""How the agent's reply settles a step attempt, without a session or a database.

The table used to live inside the engine, mixed with ACP calls; these tests pin
it as a pure decision so a change to one row cannot silently move another.
"""

from __future__ import annotations

from typing import Any

import pytest

from pulse.orchestrator.outcome import LoopSignal
from pulse.orchestrator.verdict import Verdict, VerdictKind, judge_attempt
from pulse.store.workflow_defs import StepDef


def _step(*, requires_approval: bool = False, requires_outcome: bool = True) -> StepDef:
    return StepDef(
        workflow_id="w",
        step_id="s",
        position=1,
        label="s",
        agent_id="default",
        prompt_template="",
        requires_approval=requires_approval,
        requires_outcome=requires_outcome,
    )


def _outcome(*lines: str) -> str:
    return "texto\n```pulse:outcome\n" + "\n".join(lines) + "\n```"


def _reply(text: str = "", **fields: Any) -> dict[str, Any]:
    return {"phaseSummary": text, "stopReason": "end_turn", **fields}


def test_a_declared_delivery_is_delivered():
    verdict = judge_attempt(_reply(_outcome("status: done")), _step(), may_close=False)

    assert verdict == Verdict(VerdictKind.DELIVERED)


def test_silence_is_not_a_delivery():
    """A turn that ended without the block cannot be trusted as delivered."""
    verdict = judge_attempt(_reply("terminei"), _step(), may_close=False)

    assert verdict.kind == VerdictKind.BLOCKED
    assert "sem declarar o desfecho" in verdict.reason


def test_a_declared_block_keeps_the_agent_reason():
    reply = _reply(_outcome("status: blocked", "reason: falta a credencial"))

    verdict = judge_attempt(reply, _step(), may_close=False)

    assert verdict == Verdict(VerdictKind.BLOCKED, reason="falta a credencial")


def test_a_block_without_reason_still_explains_itself():
    verdict = judge_attempt(_reply(_outcome("status: blocked")), _step(), may_close=False)

    assert verdict == Verdict(
        VerdictKind.BLOCKED, reason="o agente declarou bloqueio sem dizer o motivo"
    )


def test_a_step_that_declares_no_outcome_delivers_on_a_clean_turn():
    verdict = judge_attempt(_reply("feito"), _step(requires_outcome=False), may_close=False)

    assert verdict == Verdict(VerdictKind.DELIVERED)


@pytest.mark.parametrize(
    ("stop_reason", "reason"),
    [("max_tokens", "max_tokens"), ("", "o agente não concluiu o step")],
)
def test_a_turn_that_did_not_end_cleanly_fails(stop_reason: str, reason: str):
    reply = _reply(_outcome("status: done"), stopReason=stop_reason)

    verdict = judge_attempt(reply, _step(), may_close=False)

    assert verdict == Verdict(VerdictKind.FAILED, reason=reason)


@pytest.mark.parametrize(
    "fields", [{"outcome": "cancel"}, {"outcome": "cancelled"}, {"stopReason": "cancelled"}]
)
def test_a_cancelled_attempt_fails(fields: dict[str, str]):
    verdict = judge_attempt(_reply(_outcome("status: done"), **fields), _step(), may_close=False)

    assert verdict == Verdict(VerdictKind.FAILED, reason="step cancelado")


def test_a_user_skip_from_the_questionnaire_skips():
    verdict = judge_attempt(_reply(outcome="skip"), _step(requires_approval=True), may_close=False)

    assert verdict == Verdict(VerdictKind.SKIPPED)


def test_an_approved_step_is_delivered():
    reply = _reply("artefato", approved=True)

    verdict = judge_attempt(reply, _step(requires_approval=True), may_close=False)

    assert verdict == Verdict(VerdictKind.DELIVERED)


@pytest.mark.parametrize(
    ("answers", "reason"),
    [
        ("", "o agente encerrou sem o bloco de aprovação nem um desfecho válido"),
        ("C) Outro: refazer", "step não aprovado"),
    ],
)
def test_an_approval_step_without_approval_fails(answers: str, reason: str):
    reply = _reply("artefato", approved=False, approvalAnswers=answers)

    verdict = judge_attempt(reply, _step(requires_approval=True), may_close=False)

    assert verdict == Verdict(VerdictKind.FAILED, reason=reason)


def test_the_loop_opener_may_close_the_loop_without_approval():
    reply = _reply(_outcome("status: done", "next: close"), approved=False)

    verdict = judge_attempt(reply, _step(requires_approval=True), may_close=True)

    assert verdict == Verdict(VerdictKind.DELIVERED, signal=LoopSignal.CLOSE)


def test_outside_the_loop_opener_a_close_request_is_not_an_approval():
    reply = _reply(_outcome("status: done", "next: close"), approved=False)

    verdict = judge_attempt(reply, _step(requires_approval=True), may_close=False)

    assert verdict.kind == VerdictKind.FAILED


def test_a_delivery_passes_the_repeat_request_on():
    reply = _reply(_outcome("status: done", "next: repeat"))

    verdict = judge_attempt(reply, _step(), may_close=False)

    assert verdict == Verdict(VerdictKind.DELIVERED, signal=LoopSignal.REPEAT)


def test_a_block_never_carries_a_loop_signal():
    reply = _reply(_outcome("status: blocked", "next: repeat"))

    verdict = judge_attempt(reply, _step(), may_close=True)

    assert verdict.signal is None
