"""The turns of one step inside its own ACP session.

A step may take more than one turn: answers to the approval questionnaire or a
nudge to declare its outcome continue the same session, so the agent keeps its
context. Lives outside [pulse.acp.session_runner], which is the transport.
"""

from __future__ import annotations

from typing import Any, Protocol

from pulse.domain.ports import PhaseContinuation, PromptContinuation, StreamSink
from pulse.replies.approval import ApprovalOutcome, classify_outcome

# An agent that asks until no doubt is left needs room; the cap only stops an
# endless question loop, and hitting it sends the step to the retry menu.
MAX_PHASE_APPROVAL_TURNS = 12

# The work plus one continuation, the agent's chance to unblock itself. An agent
# that repeats the block after one nudge needs a person; more turns only burn
# tokens to reach the same menu.
MAX_PROMPT_TURNS = 2

# ACP stop reason of a turn the agent or the user cut short; also the outcome reported for it.
CANCELLED = "cancelled"


class _SessionHost(Protocol):
    """What the turns need from the runner they are mixed into."""

    _cwd: str
    _stream: StreamSink
    ask_question_count: int
    last_answer_rounds: tuple[str, ...]

    def new_session(self, cwd: str, *, workflow: str = "") -> dict[str, Any]: ...

    def _activate_session(self, session_id: str) -> None: ...

    def _enter_phase(self, phase_id: str) -> None: ...

    def apply_model(self, session: dict[str, Any], preferred_model: str | None) -> None: ...

    def apply_mode(self, session: dict[str, Any], *, execute: bool) -> None: ...

    def prompt(self, session_id: str, text: str) -> dict[str, Any]: ...

    def run_isolated_prompt(
        self,
        *,
        workflow: str,
        phase_label: str,
        prompt_text: str,
        preferred_model: str | None = None,
        agent_mode: bool = True,
        phase_id: str = "",
        build_continuation: PromptContinuation | None = None,
        max_turns: int = MAX_PROMPT_TURNS,
    ) -> dict[str, Any]: ...

    def close_session(self) -> None: ...

    def _begin_phase(self, label: str, *, turn: int = 1) -> None: ...

    def _run_text_questionnaire(self, phase1_text: str) -> str | None: ...


class StepTurns:
    """Runner mixin: one step, its session, and the turns that continue it."""

    last_answer_rounds: tuple[str, ...] = ()

    def run_isolated_phase(
        self: _SessionHost,
        *,
        workflow: str,
        phase_label: str,
        initial_prompt: str,
        preferred_model: str | None = None,
        build_continuation: PhaseContinuation | None = None,
        phase_id: str = "",
    ) -> dict[str, Any]:
        self.last_answer_rounds = ()
        if phase_id:
            self._enter_phase(phase_id)
        session = self.new_session(self._cwd, workflow=workflow)
        session_id = session.get("sessionId")
        if not session_id:
            raise RuntimeError("ACP session returned no sessionId")
        active_session = str(session_id)
        self._activate_session(active_session)

        self.apply_model(session, preferred_model)

        self.apply_mode(session, execute=False)
        next_prompt = initial_prompt
        phase_summary = ""
        answers_text = ""
        approved = False
        exhausted = False
        outcome: str = ApprovalOutcome.UNKNOWN
        phase_result: dict[str, Any] = {}

        try:
            for turn in range(MAX_PHASE_APPROVAL_TURNS):
                self._begin_phase(phase_label, turn=turn + 1)
                self._stream.reset_capture()
                phase_result = self.prompt(active_session, next_prompt)
                if phase_result.get("stopReason") == CANCELLED:
                    phase_result["approved"] = False
                    phase_result["outcome"] = CANCELLED
                    phase_result["phaseSummary"] = phase_summary
                    return phase_result

                phase_summary = self._stream.agent_text()
                answers = self._run_text_questionnaire(phase_summary)
                if answers is None:
                    return {
                        "stopReason": CANCELLED,
                        "phaseStopReason": phase_result.get("stopReason"),
                        "askQuestionCount": self.ask_question_count,
                        "approved": False,
                        "outcome": CANCELLED,
                        "phaseSummary": phase_summary,
                    }

                answers_text = answers
                if not answers_text.strip():
                    break

                outcome = classify_outcome(answers_text)
                if outcome == ApprovalOutcome.APPROVE:
                    approved = True
                    break
                if outcome in {ApprovalOutcome.CANCEL, ApprovalOutcome.SKIP}:
                    return {
                        "stopReason": phase_result.get("stopReason", "end_turn"),
                        "phaseStopReason": phase_result.get("stopReason"),
                        "askQuestionCount": self.ask_question_count,
                        "approved": False,
                        "outcome": outcome,
                        "phaseSummary": phase_summary,
                    }

                self.last_answer_rounds = (*self.last_answer_rounds, answers_text)
                if build_continuation is None:
                    break
                next_prompt = build_continuation(
                    phase_summary=phase_summary,
                    questionnaire_answers=answers_text,
                    outcome=outcome,
                )
            else:
                exhausted = True

            phase_result["approved"] = approved
            phase_result["outcome"] = outcome
            phase_result["phaseSummary"] = phase_summary
            phase_result["approvalAnswers"] = answers_text
            phase_result["turnsExhausted"] = exhausted
            phase_result["askQuestionCount"] = self.ask_question_count
            return phase_result
        finally:
            self.close_session()

    def run_isolated_prompt(
        self: _SessionHost,
        *,
        workflow: str,
        phase_label: str,
        prompt_text: str,
        preferred_model: str | None = None,
        agent_mode: bool = True,
        phase_id: str = "",
        build_continuation: PromptContinuation | None = None,
        max_turns: int = MAX_PROMPT_TURNS,
    ) -> dict[str, Any]:
        """Run the step in its own session, allowing continuation turns.

        `build_continuation` receives the turn result and returns the next prompt,
        or empty to stop. Continuing in the same session preserves the agent's context.
        """
        self.last_answer_rounds = ()
        if phase_id:
            self._enter_phase(phase_id)
        session = self.new_session(self._cwd, workflow=workflow)
        session_id = session.get("sessionId")
        if not session_id:
            raise RuntimeError("ACP session returned no sessionId")
        active_session = str(session_id)
        self._activate_session(active_session)

        self.apply_model(session, preferred_model)

        self.apply_mode(session, execute=agent_mode)

        next_prompt = prompt_text
        parts: list[str] = []
        result: dict[str, Any] = {}
        try:
            for turn in range(max(1, max_turns)):
                self._begin_phase(phase_label, turn=turn + 1)
                self._stream.reset_capture()
                result = self.prompt(active_session, next_prompt)
                text = self._stream.agent_text().strip()
                if text:
                    parts.append(text)
                result["phaseSummary"] = "\n\n".join(parts)
                result["askQuestionCount"] = self.ask_question_count
                result["turns"] = turn + 1
                if build_continuation is None or result.get("stopReason") == CANCELLED:
                    break
                follow_up = str(build_continuation(result=result, turn=turn) or "").strip()
                if not follow_up:
                    break
                next_prompt = follow_up
            return result
        finally:
            self.close_session()

    def draft_pull_request(
        self: _SessionHost,
        *,
        workflow: str,
        phase_label: str,
        prompt_text: str,
    ) -> dict[str, Any]:
        """A session that only writes the request body, with nothing for the agent to edit."""
        return self.run_isolated_prompt(
            workflow=workflow,
            phase_label=phase_label,
            prompt_text=prompt_text,
            agent_mode=False,
            max_turns=1,
        )
