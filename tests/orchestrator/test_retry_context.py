"""A retried step learns which files its failed attempt wrote and what the user answered.

A retry opens a fresh ACP session: without this, the agent repeats the step from
scratch, may write the same artifact under another name, leaving two versions
of it in the run (issue #62), and asks the user the same questions again.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from pulse.domain import run as run_model
from pulse.orchestrator import wording
from pulse.orchestrator.agent_text import earlier_answers_block, earlier_attempt_block
from pulse.replies.text_questionnaire import (
    TextQuestion,
    TextQuestionnaire,
    format_questionnaire_answers,
)
from tests.conftest import make_workflow
from tests.fakes import FakeAgentSession
from tests.orchestrator.harness import approved_turn, delivered_turn

_HEADING = earlier_attempt_block(["any"]).strip().splitlines()[0]


def _fails_after_writing(wired, step_id: str, *paths: str):
    """`before_turn` hook: the first turn of `step_id` writes `paths`, then the session dies."""
    attempts: list[str] = []

    def hook(current: str) -> dict | None:
        if current != step_id:
            return None
        attempts.append(current)
        if len(attempts) > 1:
            return None
        for path in paths:
            wired.runs.add_artifact(wired.runs.ids()[0], path, step_id=step_id)
        raise RuntimeError("o processo do agente encerrou")

    return hook


def test_a_retry_lists_the_files_the_failed_attempt_wrote(wired, tmp_path: Path):
    make_workflow("demo", steps=[("spec", "Spec")])
    runner = FakeAgentSession(
        [approved_turn()],
        before_turn=_fails_after_writing(wired, "spec", "specs/login-sso/PRD.md"),
    )
    runner.prompts.choice = "retry"

    code = wired.run(runner, workflow_id="demo", user_prompt="x")

    assert code == 0
    first, retry = runner.sent
    assert _HEADING not in first
    assert earlier_attempt_block(["specs/login-sso/PRD.md"]) in retry


def test_files_of_other_steps_stay_out_of_the_retry_block(wired, tmp_path: Path):
    """Other steps' files reach a step through `{{artifacts}}` when its template asks."""
    make_workflow("demo", steps=[("plan", "Plano"), ("spec", "Spec")])

    def plan_writes_its_file(step_id: str) -> dict | None:
        if step_id == "plan":
            wired.runs.add_artifact(runner.run_id, "PLAN.md", step_id="plan")
            return approved_turn()
        return spec_fails(step_id)

    spec_fails = _fails_after_writing(wired, "spec", "specs/PRD.md")
    runner = FakeAgentSession([approved_turn()], before_turn=plan_writes_its_file)
    runner.prompts.choice = "retry"

    wired.run(runner, workflow_id="demo", user_prompt="x")

    retry = runner.sent[-1]
    assert earlier_attempt_block(["specs/PRD.md"]) in retry
    assert "PLAN.md" not in retry


def test_a_retry_of_a_step_that_wrote_nothing_has_no_block(wired, tmp_path: Path):
    make_workflow("demo", steps=[("spec", "Spec")])
    runner = FakeAgentSession([RuntimeError("o processo do agente encerrou"), approved_turn()])
    runner.prompts.choice = "retry"

    wired.run(runner, workflow_id="demo", user_prompt="x")

    assert len(runner.sent) == 2
    assert all(_HEADING not in prompt for prompt in runner.sent)


def test_a_new_loop_round_is_not_a_retry(wired, monkeypatch, tmp_path: Path):
    """Each round writes its own files on purpose: the block must not ask to overwrite them.

    A retry inside a later round lists only that round's files.
    """
    clock = [datetime(2026, 1, 1, tzinfo=UTC)]

    def tick() -> datetime:
        clock[0] += timedelta(minutes=1)
        return clock[0]

    monkeypatch.setattr(run_model, "utc_now", tick)
    make_workflow(
        "demo",
        steps=[("review", "Review"), ("fix", "Fix")],
        requires_approval=False,
        prompt_template="step {{step_id}}",
        repeat=("fix", "review", 3),
    )
    reviews: list[str] = []

    def review_writes_its_round(step_id: str) -> dict | None:
        if step_id != "review":
            return None
        reviews.append(step_id)
        round_file = "reviews/round-001.md" if len(reviews) == 1 else "reviews/round-002.md"
        wired.runs.add_artifact(runner.run_id, round_file, step_id="review")
        if len(reviews) == 2:
            raise RuntimeError("o processo do agente encerrou")
        return delivered_turn()

    runner = FakeAgentSession(
        [_repeating(), delivered_turn(), delivered_turn()],
        before_turn=review_writes_its_round,
    )
    runner.prompts.choice = "retry"

    code = wired.run(runner, workflow_id="demo", user_prompt="x")

    assert code == 0
    review_prompts = [prompt for prompt in runner.sent if prompt.startswith("step review")]
    first_round, second_round, retry = review_prompts[:3]
    assert _HEADING not in first_round
    assert _HEADING not in second_round
    assert earlier_attempt_block(["reviews/round-002.md"]) in retry


def _repeating() -> dict[str, object]:
    return {
        "stopReason": "end_turn",
        "phaseSummary": "falta corrigir\n\n```pulse:outcome\nstatus: done\nnext: repeat\n```",
    }


_ROUND_1 = format_questionnaire_answers(
    TextQuestionnaire(title="T", questions=(TextQuestion("q1", "1. Água e água são iguais?"),)),
    [(TextQuestion("q1", "1. Água e água são iguais?"), "A) Sim")],
)
_ROUND_2 = format_questionnaire_answers(
    TextQuestionnaire(title="T", questions=(TextQuestion("q1", "1. Ordem da lista?"),)),
    [(TextQuestion("q1", "1. Ordem da lista?"), "B) Alfabética")],
)
_ANSWERS_HEADING = earlier_answers_block([_ROUND_1]).strip().splitlines()[0]


def _asked_until_the_cap(*rounds: str) -> dict[str, object]:
    return {
        "approved": False,
        "outcome": "continue",
        "approvalAnswers": rounds[-1],
        "answerRounds": list(rounds),
        "turnsExhausted": True,
    }


def test_a_retry_carries_the_answers_the_user_already_gave(wired, tmp_path: Path):
    """Without them the fresh session asks the same questions again (issue: PRD loop)."""
    make_workflow("demo", steps=[("spec", "Spec")])
    runner = FakeAgentSession([_asked_until_the_cap(_ROUND_1, _ROUND_2), approved_turn()])
    runner.prompts.choice = "retry"

    code = wired.run(runner, workflow_id="demo", user_prompt="x")

    assert code == 0
    first, retry = runner.sent
    assert _ANSWERS_HEADING not in first
    assert earlier_answers_block([_ROUND_1, _ROUND_2]) in retry
    assert "→ A) Sim" in retry
    assert "→ B) Alfabética" in retry


def test_a_session_that_crashes_mid_step_still_hands_its_answers_to_the_retry(
    wired, tmp_path: Path
):
    """A timeout after many answered rounds must not make the user answer them again."""
    make_workflow("demo", steps=[("spec", "Spec")])

    def answered_then_crashed(_step_id: str) -> None:
        if not runner.sent[1:]:
            runner.last_answer_rounds = (_ROUND_1,)

    runner = FakeAgentSession(
        [RuntimeError("o processo do agente encerrou"), approved_turn()],
        before_turn=answered_then_crashed,
    )
    runner.prompts.choice = "retry"

    code = wired.run(runner, workflow_id="demo", user_prompt="x")

    assert code == 0
    _first, retry = runner.sent
    assert earlier_answers_block([_ROUND_1]) in retry


def test_answers_pile_up_across_every_failed_attempt(wired, tmp_path: Path):
    make_workflow("demo", steps=[("spec", "Spec")])
    runner = FakeAgentSession(
        [_asked_until_the_cap(_ROUND_1), _asked_until_the_cap(_ROUND_2), approved_turn()]
    )
    runner.prompts.choice = "retry"

    wired.run(runner, workflow_id="demo", user_prompt="x")

    _first, second, third = runner.sent
    assert earlier_answers_block([_ROUND_1]) in second
    assert earlier_answers_block([_ROUND_1, _ROUND_2]) in third


def test_hitting_the_turn_cap_says_so_in_the_retry_menu(wired, tmp_path: Path):
    """`step não aprovado` hid that the agent ran out of rounds, not that the user refused."""
    make_workflow("demo", steps=[("spec", "Spec")])
    runner = FakeAgentSession([_asked_until_the_cap(_ROUND_1)])

    code = wired.run(runner, workflow_id="demo", user_prompt="x")

    assert code == 1
    assert runner.prompts.prompts == [wording.APPROVAL_TURNS_EXHAUSTED]


def test_a_refused_approval_still_reads_as_not_approved(wired, tmp_path: Path):
    make_workflow("demo", steps=[("spec", "Spec")])
    refused = {"approved": False, "outcome": "continue", "approvalAnswers": _ROUND_1}
    runner = FakeAgentSession([refused])

    wired.run(runner, workflow_id="demo", user_prompt="x")

    assert runner.prompts.prompts == [wording.STEP_NOT_APPROVED]


def test_the_answers_block_keeps_each_round_without_the_frame():
    block = earlier_answers_block([_ROUND_1, _ROUND_2])

    assert "1. Água e água são iguais?\n→ A) Sim\n\n1. Ordem da lista?\n→ B) Alfabética\n" in block
    assert "Respostas coletadas" not in block
    assert "não pergunte\nde novo" in block


def test_no_answers_means_no_answers_block():
    assert earlier_answers_block([]) == ""
    header_only = "Respostas coletadas via questionário interativo do Pulse:"
    assert earlier_answers_block(["", header_only]) == ""


def test_the_block_names_each_file_and_asks_to_reuse_them():
    block = earlier_attempt_block(["docs/a.md", "src/b.py"])

    assert "- docs/a.md\n- src/b.py\n" in block
    assert "sobrescreva" in block


def test_no_files_means_no_block():
    assert earlier_attempt_block([]) == ""
