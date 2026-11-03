"""The turns of one step inside its own ACP session.

A step may take several turns in the same session: answering the approval
questionnaire, or a nudge to declare its outcome, continues where the agent
stopped. These tests drive a real `AcpSessionRunner` against a scripted agent on
the other end of the pipes and assert what crossed them and what the step returned.
"""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from queue import Queue
from typing import Any

import pytest

from pulse.acp import session_runner, step_turns
from pulse.acp.session_runner import AcpSessionRunner
from pulse.domain.ports import NullPromptPort
from pulse.domain.run import StepRecord
from pulse.history.session_log import RecordedSessionLog
from pulse.replies.text_questionnaire import TextQuestionnaire, format_questionnaire_answers
from pulse.runtimes import get_runtime
from pulse.store import runs as run_store
from tests.conftest import make_workflow
from tests.fakes import RecordingStream

SESSION = {
    "sessionId": "sess-1",
    "modes": {
        "availableModes": [{"id": "plan"}, {"id": "default"}],
        "currentModeId": "default",
    },
    "models": {"availableModels": [{"modelId": "gpt-5.5", "name": "GPT 5.5"}]},
}
QUESTIONNAIRE = (
    "Plan drafted.\n\n```text\n1. Approve the plan?\nA) Aprovar\nB) Ajustar\nC) Pular\n```\n"
)
APPROVE = "A) Aprovar"
ADJUST = "B) Ajustar"
SKIP = "C) Pular"


@dataclass(frozen=True)
class Turn:
    """What the agent says during one `session/prompt` and how it ends it."""

    text: str = ""
    stop_reason: str = "end_turn"
    error: str = ""


class _Stdin:
    def __init__(self, agent: ScriptedAgent) -> None:
        self._agent = agent

    def write(self, data: str) -> None:
        for line in data.splitlines():
            if line.strip():
                self._agent.receive(json.loads(line))

    def flush(self) -> None:
        return None

    def close(self) -> None:
        self._agent.hang_up()


class ScriptedAgent:
    """An ACP agent process: answers each request it reads on stdin, in order.

    Replies go through a queue the runner's real read loop consumes, so updates
    of a turn always arrive before the turn's reply, as with a real agent.
    """

    def __init__(
        self,
        turns: list[Turn],
        *,
        session: dict[str, Any] | None = None,
        errors: dict[str, str] | None = None,
    ) -> None:
        self._turns = deque(turns)
        self._session = SESSION if session is None else session
        self._errors = errors or {}
        self._lines: Queue[str | None] = Queue()
        self.received: list[dict[str, Any]] = []
        self.stdin = _Stdin(self)
        self.stdout: Iterator[str | None] = iter(self._lines.get, None)
        self.returncode: int | None = None

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        return self.returncode or 0

    def hang_up(self) -> None:
        self.returncode = 0
        self._lines.put(None)

    def receive(self, message: dict[str, Any]) -> None:
        self.received.append(message)
        if "method" not in message or "id" not in message:
            return
        method = message["method"]
        if method in self._errors:
            self._emit({"id": message["id"], "error": {"message": self._errors[method]}})
        elif method == "session/prompt":
            self._play_turn(message)
        else:
            self._emit({"id": message["id"], "result": self._result(method)})

    def _result(self, method: str) -> dict[str, Any]:
        if method == "initialize":
            return {"protocolVersion": 1, "authMethods": []}
        if method == "session/new":
            return self._session
        return {}

    def _play_turn(self, message: dict[str, Any]) -> None:
        turn = self._turns.popleft()
        if turn.error:
            self._emit({"id": message["id"], "error": {"message": turn.error}})
            return
        if turn.text:
            content = {"type": "text", "text": turn.text}
            chunk = {"sessionUpdate": "agent_message_chunk", "content": content}
            params = {"sessionId": message["params"]["sessionId"], "update": chunk}
            self._emit({"method": "session/update", "params": params})
        self._emit({"id": message["id"], "result": {"stopReason": turn.stop_reason}})

    def _emit(self, message: dict[str, Any]) -> None:
        self._lines.put(json.dumps({"jsonrpc": "2.0", **message}) + "\n")

    def calls(self, method: str) -> list[dict[str, Any]]:
        return [item["params"] for item in self.received if item.get("method") == method]

    def prompts(self) -> list[str]:
        return [params["prompt"][0]["text"] for params in self.calls("session/prompt")]


class AnswerSheet(NullPromptPort):
    """The user at the approval questionnaire, picking the same option for every question.

    `None` dismisses the questionnaire.
    """

    def __init__(self, *picks: str | None) -> None:
        self._picks = deque(picks)
        self.asked: list[TextQuestionnaire] = []

    def run_parsed_questionnaire(self, questionnaire: TextQuestionnaire) -> str | None:
        self.asked.append(questionnaire)
        pick = self._picks.popleft()
        if pick is None:
            return None
        return format_questionnaire_answers(
            questionnaire, [(question, pick) for question in questionnaire.questions]
        )


class Continuations:
    """Records every request for a next prompt and answers with a scripted one."""

    def __init__(self, *follow_ups: str) -> None:
        self._follow_ups = deque(follow_ups)
        self.calls: list[dict[str, Any]] = []

    def phase(self, *, phase_summary: str, questionnaire_answers: str, outcome: str) -> str:
        self.calls.append(
            {"summary": phase_summary, "answers": questionnaire_answers, "outcome": outcome}
        )
        return f"continue after {outcome}"

    def prompt(self, *, result: dict[str, Any], turn: int) -> str:
        self.calls.append({"turn": turn, "summary": result.get("phaseSummary")})
        return self._follow_ups.popleft() if self._follow_ups else "keep going"


@dataclass
class Harness:
    agent: ScriptedAgent
    runner: AcpSessionRunner
    stream: RecordingStream
    answers: AnswerSheet


@pytest.fixture
def connect(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    runners: list[AcpSessionRunner] = []

    def _connect(agent: ScriptedAgent, answers: AnswerSheet | None = None) -> Harness:
        monkeypatch.setattr(session_runner.subprocess, "Popen", lambda *_a, **_k: agent)
        sheet = answers or AnswerSheet()
        stream = RecordingStream()
        runner = AcpSessionRunner(
            ["agent", "acp"],
            cwd=str(tmp_path),
            timeout_seconds=5,
            stream=stream,
            prompt_handler=sheet,
            runtime=get_runtime("cursor"),
            session_log=RecordedSessionLog(project_root=tmp_path),
        )
        runner.start()
        runner.initialize()
        runners.append(runner)
        return Harness(agent=agent, runner=runner, stream=stream, answers=sheet)

    yield _connect
    for runner in runners:
        runner.close()


def _phase(harness: Harness, **kwargs: Any) -> dict[str, Any]:
    return harness.runner.run_isolated_phase(
        workflow="demo", phase_label="Plan", initial_prompt="draft the plan", **kwargs
    )


def _prompt(harness: Harness, **kwargs: Any) -> dict[str, Any]:
    return harness.runner.run_isolated_prompt(
        workflow="demo", phase_label="Build", prompt_text="build it", **kwargs
    )


# --- run_isolated_phase ------------------------------------------------------


def test_an_approved_questionnaire_ends_the_phase_approved(connect):
    harness = connect(ScriptedAgent([Turn(QUESTIONNAIRE)]), AnswerSheet(APPROVE))

    result = _phase(harness)

    assert result["approved"] is True
    assert result["outcome"] == "approve"
    assert result["stopReason"] == "end_turn"
    assert result["phaseSummary"] == QUESTIONNAIRE
    assert "→ A) Aprovar" in result["approvalAnswers"]
    assert result["askQuestionCount"] == 1
    assert harness.agent.prompts() == ["draft the plan"]
    assert harness.stream.phases == ["Plan"]


def test_the_phase_runs_in_interview_mode_and_closes_its_session(connect):
    """Approval steps interview first; their session never leaks into the next step."""
    harness = connect(ScriptedAgent([Turn(QUESTIONNAIRE)]), AnswerSheet(APPROVE))

    _phase(harness)

    assert harness.agent.calls("session/set_mode") == [{"sessionId": "sess-1", "modeId": "plan"}]
    assert harness.agent.calls("session/close") == [{"sessionId": "sess-1"}]
    assert harness.runner.last_session_id == "sess-1"


def test_the_preferred_model_is_applied_before_the_first_turn(connect):
    harness = connect(ScriptedAgent([Turn(QUESTIONNAIRE)]), AnswerSheet(APPROVE))

    _phase(harness, preferred_model="gpt-5.5")

    methods = [item.get("method") for item in harness.agent.received]
    assert harness.agent.calls("session/set_model") == [
        {"sessionId": "sess-1", "modelId": "gpt-5.5"}
    ]
    assert methods.index("session/set_model") < methods.index("session/prompt")


def test_the_new_session_carries_the_workflow_in_its_pulse_metadata(connect):
    """The agent sees which workflow it serves through `_meta.pulse`, not the prompt."""
    harness = connect(ScriptedAgent([Turn(QUESTIONNAIRE)]), AnswerSheet(APPROVE))

    _phase(harness)

    (params,) = harness.agent.calls("session/new")
    assert params["_meta"]["pulse"]["workflow"] == "demo"
    assert params["mcpServers"] == []


def test_the_phase_id_tags_every_run_log_row_of_the_step(connect, tmp_path):
    """History groups the log by step; a row without the step id is lost in it."""
    make_workflow("demo", steps=[("plan", "Plan")])
    run_store.create_run(
        run_id="run-1",
        workflow_id="demo",
        workspace=tmp_path,
        user_prompt="x",
        steps=[StepRecord(step_id="plan", position=1, label="Plan")],
    )
    harness = connect(ScriptedAgent([Turn("Nothing to ask.")]))
    harness.runner.bind_run("run-1")

    _phase(harness, phase_id="plan")

    events = run_store.list_events("run-1")
    assert [(row["kind"], row["detail"]) for row in events] == [
        ("Info", "Plan"),
        ("Assistant", "Nothing to ask."),
    ]
    assert {row["step_id"] for row in events} == {"plan"}
    assert {row["acp_session_id"] for row in events} == {"sess-1"}


def test_a_cancelled_turn_returns_without_asking_the_questionnaire(connect):
    """A stop must not open a question the user already walked away from."""
    harness = connect(ScriptedAgent([Turn(QUESTIONNAIRE, stop_reason="cancelled")]))

    result = _phase(harness)

    assert result == {
        "stopReason": "cancelled",
        "approved": False,
        "outcome": "cancelled",
        "phaseSummary": "",
    }
    assert harness.answers.asked == []
    assert harness.agent.calls("session/close") == [{"sessionId": "sess-1"}]


def test_dismissing_the_questionnaire_cancels_the_phase(connect):
    harness = connect(ScriptedAgent([Turn(QUESTIONNAIRE)]), AnswerSheet(None))

    result = _phase(harness)

    assert result == {
        "stopReason": "cancelled",
        "phaseStopReason": "end_turn",
        "askQuestionCount": 0,
        "approved": False,
        "outcome": "cancelled",
        "phaseSummary": QUESTIONNAIRE,
    }
    assert harness.agent.calls("session/close") == [{"sessionId": "sess-1"}]


def test_a_turn_without_a_questionnaire_is_not_an_approval(connect):
    """Fail safe: no questionnaire means nobody approved, so the engine must ask."""
    harness = connect(ScriptedAgent([Turn("All done, nothing to ask.")]))

    result = _phase(harness)

    assert result["approved"] is False
    assert result["outcome"] == "unknown"
    assert result["approvalAnswers"] == ""
    assert result["phaseSummary"] == "All done, nothing to ask."
    assert harness.answers.asked == []


@pytest.mark.parametrize(("pick", "outcome"), [(SKIP, "skip"), ("D) Cancelar", "cancel")])
def test_skip_or_cancel_answers_end_the_phase_without_continuing(connect, pick, outcome):
    harness = connect(ScriptedAgent([Turn(QUESTIONNAIRE)]), AnswerSheet(pick))
    continuations = Continuations()

    result = _phase(harness, build_continuation=continuations.phase)

    assert result == {
        "stopReason": "end_turn",
        "phaseStopReason": "end_turn",
        "askQuestionCount": 1,
        "approved": False,
        "outcome": outcome,
        "phaseSummary": QUESTIONNAIRE,
    }
    assert harness.runner.last_answer_rounds == ()
    assert continuations.calls == []
    assert harness.agent.prompts() == ["draft the plan"]


def test_an_adjust_answer_continues_the_same_session_until_approved(connect):
    """The agent keeps its context: the continuation is a new turn, not a new session."""
    agent = ScriptedAgent([Turn(QUESTIONNAIRE), Turn("Revised.\n" + QUESTIONNAIRE)])
    harness = connect(agent, AnswerSheet(ADJUST, APPROVE))
    continuations = Continuations()

    result = _phase(harness, build_continuation=continuations.phase)

    assert result["approved"] is True
    assert result["outcome"] == "approve"
    assert result["phaseSummary"] == "Revised.\n" + QUESTIONNAIRE
    assert result["askQuestionCount"] == 2
    assert agent.prompts() == ["draft the plan", "continue after adjust"]
    assert len(agent.calls("session/new")) == 1
    assert {params["sessionId"] for params in agent.calls("session/prompt")} == {"sess-1"}
    assert harness.stream.phases == ["Plan", "Plan"]
    assert harness.stream.turns == [1, 2], "the second turn is the same phase, continued"
    (call,) = continuations.calls
    assert call["outcome"] == "adjust"
    assert call["summary"] == QUESTIONNAIRE
    assert "→ B) Ajustar" in call["answers"]


def test_an_adjust_answer_without_a_continuation_ends_the_phase_unapproved(connect):
    harness = connect(ScriptedAgent([Turn(QUESTIONNAIRE)]), AnswerSheet(ADJUST))

    result = _phase(harness)

    assert result["approved"] is False
    assert result["outcome"] == "adjust"
    assert "→ B) Ajustar" in result["approvalAnswers"]
    assert harness.agent.prompts() == ["draft the plan"]


def test_a_cancel_after_a_continuation_keeps_the_previous_summary(connect):
    """What the agent said before the stop is the only summary the step has."""
    agent = ScriptedAgent([Turn(QUESTIONNAIRE), Turn("half", stop_reason="cancelled")])
    harness = connect(agent, AnswerSheet(ADJUST))

    result = _phase(harness, build_continuation=Continuations().phase)

    assert result["outcome"] == "cancelled"
    assert result["approved"] is False
    assert result["phaseSummary"] == QUESTIONNAIRE


def test_an_endless_question_loop_stops_at_the_turn_cap(connect):
    """The cap sends the step to the retry menu instead of asking forever."""
    cap = step_turns.MAX_PHASE_APPROVAL_TURNS
    agent = ScriptedAgent([Turn(QUESTIONNAIRE)] * cap)
    harness = connect(agent, AnswerSheet(*[ADJUST] * cap))

    result = _phase(harness, build_continuation=Continuations().phase)

    assert len(agent.prompts()) == cap
    assert result["approved"] is False
    assert result["outcome"] == "adjust"
    assert result["turnsExhausted"] is True
    assert len(harness.runner.last_answer_rounds) == cap
    assert all("→ B) Ajustar" in answers for answers in harness.runner.last_answer_rounds)
    assert result["askQuestionCount"] == cap
    assert agent.calls("session/close") == [{"sessionId": "sess-1"}]


def test_the_rounds_that_kept_the_conversation_going_stay_on_the_runner(connect):
    """A retry opens a fresh session; these answers keep it from asking again.

    The approval itself is not a decision for a retry to honour.
    """
    agent = ScriptedAgent([Turn(QUESTIONNAIRE), Turn(QUESTIONNAIRE), Turn(QUESTIONNAIRE)])
    harness = connect(agent, AnswerSheet(ADJUST, ADJUST, APPROVE))

    result = _phase(harness, build_continuation=Continuations().phase)

    assert result["approved"] is True
    assert result["turnsExhausted"] is False
    assert len(harness.runner.last_answer_rounds) == 2
    assert all("→ B) Ajustar" in answers for answers in harness.runner.last_answer_rounds)


@pytest.mark.parametrize("last", [None, SKIP, "D) Cancelar"])
def test_a_phase_ended_by_the_user_keeps_only_the_rounds_before_it(connect, last):
    """Cancelling or skipping is not an answer a retry should treat as a decision."""
    agent = ScriptedAgent([Turn(QUESTIONNAIRE), Turn(QUESTIONNAIRE)])
    harness = connect(agent, AnswerSheet(ADJUST, last))

    result = _phase(harness, build_continuation=Continuations().phase)

    assert result["approved"] is False
    assert len(harness.runner.last_answer_rounds) == 1
    assert "→ B) Ajustar" in harness.runner.last_answer_rounds[0]


def test_rounds_answered_before_a_crashing_turn_survive_the_crash(connect):
    """A session that dies mid-step raises; the retry still needs what was answered."""
    agent = ScriptedAgent([Turn(QUESTIONNAIRE), Turn(error="model overloaded")])
    harness = connect(agent, AnswerSheet(ADJUST))

    with pytest.raises(RuntimeError, match="model overloaded"):
        _phase(harness, build_continuation=Continuations().phase)

    (answers,) = harness.runner.last_answer_rounds
    assert "→ B) Ajustar" in answers


def test_a_new_step_starts_without_the_rounds_of_the_previous_one(connect):
    """Stale rounds would hand one step's decisions to the retry of another."""
    agent = ScriptedAgent([Turn(QUESTIONNAIRE), Turn(QUESTIONNAIRE), Turn("done")])
    harness = connect(agent, AnswerSheet(ADJUST, APPROVE))
    _phase(harness, build_continuation=Continuations().phase)

    _prompt(harness)

    assert harness.runner.last_answer_rounds == ()


def test_a_session_without_an_id_fails_the_phase_before_any_turn(connect):
    harness = connect(ScriptedAgent([], session={"modes": {}}))

    with pytest.raises(RuntimeError, match="no sessionId"):
        _phase(harness)

    assert harness.agent.prompts() == []
    assert harness.answers.asked == []


def test_a_failed_turn_still_closes_the_session(connect):
    """A crashing turn must not leave the agent's session open for the retry."""
    agent = ScriptedAgent([], errors={"session/prompt": "model overloaded"})
    harness = connect(agent)

    with pytest.raises(RuntimeError, match="model overloaded"):
        _phase(harness)

    assert agent.calls("session/close") == [{"sessionId": "sess-1"}]


# --- run_isolated_prompt -----------------------------------------------------


def test_a_single_turn_prompt_returns_the_agent_text(connect):
    harness = connect(ScriptedAgent([Turn("  built the thing  ")]))

    result = _prompt(harness, phase_id="build")

    assert result == {
        "stopReason": "end_turn",
        "phaseSummary": "built the thing",
        "askQuestionCount": 0,
        "turns": 1,
    }
    assert harness.stream.phases == ["Build"]
    assert harness.agent.calls("session/close") == [{"sessionId": "sess-1"}]


@pytest.mark.parametrize(("agent_mode", "mode"), [(True, "default"), (False, "plan")])
def test_the_prompt_mode_follows_whether_the_agent_may_execute(connect, agent_mode, mode):
    harness = connect(ScriptedAgent([Turn("ok")]))

    _prompt(harness, agent_mode=agent_mode)

    assert harness.agent.calls("session/set_mode") == [{"sessionId": "sess-1", "modeId": mode}]


def test_a_continuation_adds_a_turn_and_joins_the_summaries(connect):
    agent = ScriptedAgent([Turn("first part"), Turn("second part")])
    harness = connect(agent)
    continuations = Continuations("declare your outcome", "")

    result = _prompt(harness, build_continuation=continuations.prompt)

    assert agent.prompts() == ["build it", "declare your outcome"]
    assert result["phaseSummary"] == "first part\n\nsecond part"
    assert result["turns"] == 2
    assert harness.stream.phases == ["Build", "Build"]
    assert harness.stream.turns == [1, 2]
    assert continuations.calls[0] == {"turn": 0, "summary": "first part"}


def test_the_prompt_stops_at_max_turns_even_if_the_continuation_insists(connect):
    """One nudge is the agent's chance; after that a person decides."""
    agent = ScriptedAgent([Turn("one"), Turn("two"), Turn("three")])
    harness = connect(agent)
    continuations = Continuations("again", "again", "again")

    result = _prompt(harness, build_continuation=continuations.prompt)

    assert len(agent.prompts()) == step_turns.MAX_PROMPT_TURNS
    assert result["turns"] == step_turns.MAX_PROMPT_TURNS


def test_an_empty_follow_up_ends_the_prompt(connect):
    agent = ScriptedAgent([Turn("done")])
    harness = connect(agent)

    result = _prompt(harness, build_continuation=Continuations("   ").prompt)

    assert agent.prompts() == ["build it"]
    assert result["turns"] == 1


def test_a_cancelled_turn_is_not_continued(connect):
    """A stop wins over the nudge: continuing would undo the user's stop."""
    agent = ScriptedAgent([Turn("partial", stop_reason="cancelled")])
    harness = connect(agent)
    continuations = Continuations("again")

    result = _prompt(harness, build_continuation=continuations.prompt)

    assert result["stopReason"] == "cancelled"
    assert result["phaseSummary"] == "partial"
    assert continuations.calls == []


def test_a_silent_turn_adds_nothing_to_the_summary(connect):
    agent = ScriptedAgent([Turn(""), Turn("only words")])
    harness = connect(agent)

    result = _prompt(harness, build_continuation=Continuations("again", "").prompt)

    assert result["phaseSummary"] == "only words"


def test_zero_max_turns_still_runs_the_work_turn(connect):
    agent = ScriptedAgent([Turn("work")])
    harness = connect(agent)

    result = _prompt(harness, max_turns=0)

    assert agent.prompts() == ["build it"]
    assert result["turns"] == 1


def test_a_prompt_session_without_an_id_fails_before_any_turn(connect):
    harness = connect(ScriptedAgent([], session={}))

    with pytest.raises(RuntimeError, match="no sessionId"):
        _prompt(harness)

    assert harness.agent.prompts() == []


def test_a_failed_prompt_turn_still_closes_the_session(connect):
    agent = ScriptedAgent([], errors={"session/prompt": "boom"})
    harness = connect(agent)

    with pytest.raises(RuntimeError, match="boom"):
        _prompt(harness)

    assert agent.calls("session/close") == [{"sessionId": "sess-1"}]
