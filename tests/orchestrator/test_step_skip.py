"""A step the definition marks `skippable` may declare it does not apply, and the run moves on."""

from __future__ import annotations

from pulse.domain.control import RUN_BLOCKED
from pulse.orchestrator import wording
from tests.conftest import make_workflow
from tests.fakes import FakeAgentSession
from tests.orchestrator.harness import approved_turn, delivered_turn

SKIP_REASON = "tarefa puramente técnica, sem decisão de produto"


def skipped_turn(summary: str = "feature: .pulse/specs/features/upgrade-lib/") -> dict[str, object]:
    """Turn that ends without a questionnaire, declaring the step does not apply."""
    return {
        "stopReason": "end_turn",
        "approved": False,
        "outcome": "unknown",
        "phaseSummary": (
            f"{summary}\n\n```pulse:outcome\nstatus: skipped\nreason: {SKIP_REASON}\n```"
        ),
    }


def test_a_skippable_approval_step_skips_itself_without_asking_anyone(wired):
    """A purely technical task has no product decision: nobody should approve an empty step."""
    make_workflow(
        "demo",
        steps=[("one", "Um"), ("two", "Dois")],
        skippable={"one"},
        prompt_template="anterior: {{previous_status}} | {{previous_summary}}",
    )
    runner = FakeAgentSession([skipped_turn(), approved_turn()])

    code = wired.run(runner, workflow_id="demo", user_prompt="x")

    assert code == 0
    record = wired.runs.only()
    assert [step.status for step in record.steps] == ["skipped", "done"]
    assert runner.prompts.asked == [], "skipping asks no one"
    assert runner.stream.messages.count(wording.step_skipped_by_agent("Um", SKIP_REASON)) == 1
    assert runner.sent[1].startswith(
        "anterior: skipped | feature: .pulse/specs/features/upgrade-lib/"
    ), "the next step learns the earlier one was skipped and still gets its summary"


def test_the_skip_protocol_is_offered_only_where_the_definition_allows_it(wired):
    """An agent never told it may skip has no reason to try; one that may, needs the format."""
    make_workflow("demo", steps=[("one", "Um"), ("two", "Dois")], skippable={"one"})
    runner = FakeAgentSession([approved_turn(), approved_turn()])

    wired.run(runner, workflow_id="demo", user_prompt="x")

    assert "status: skipped" in runner.sent[0]
    assert "status: skipped" not in runner.sent[1]


def test_an_approval_step_that_may_not_skip_is_blocked_by_the_claim(wired):
    """The definition decides: the agent's word alone never drops a step."""
    make_workflow("demo", steps=[("one", "Um"), ("two", "Dois")])
    runner = FakeAgentSession([skipped_turn()])
    runner.prompts.choice = "stop"

    code = wired.run(runner, workflow_id="demo", user_prompt="x")

    assert code == RUN_BLOCKED
    assert runner.prompts.prompts == [wording.SKIP_NOT_ALLOWED]
    assert [step.status for step in wired.runs.only().steps] == ["blocked", "pending"]


def test_an_outcome_step_that_may_not_skip_is_blocked_without_a_self_unblock_turn(wired):
    """A skip is not a block the agent can work its way out of: no continuation is sent."""
    make_workflow("demo", steps=[("one", "Um"), ("two", "Dois")], requires_approval=False)
    runner = FakeAgentSession([skipped_turn()])
    runner.prompts.choice = "stop"

    code = wired.run(runner, workflow_id="demo", user_prompt="x")

    assert code == RUN_BLOCKED
    assert len(runner.sent) == 1
    assert runner.prompts.prompts == [wording.SKIP_NOT_ALLOWED]


def test_a_skippable_outcome_step_skips_and_the_next_one_runs(wired):
    make_workflow(
        "demo",
        steps=[("one", "Um"), ("two", "Dois")],
        requires_approval=False,
        skippable={"one"},
    )
    runner = FakeAgentSession([skipped_turn(), delivered_turn()])

    code = wired.run(runner, workflow_id="demo", user_prompt="x")

    assert code == 0
    assert [step.status for step in wired.runs.only().steps] == ["skipped", "done"]
    assert len(runner.sent) == 2, "the skip spends no continuation turn"


def test_an_approval_wins_over_a_skip_in_the_same_reply(wired):
    """Once the person approved, the step delivered; a stray skip block changes nothing."""
    make_workflow("demo", steps=[("one", "Um")], skippable={"one"})
    turn = skipped_turn()
    turn.update(approved=True, outcome="approve")
    runner = FakeAgentSession([turn])

    wired.run(runner, workflow_id="demo", user_prompt="x")

    assert wired.runs.only().step("one").status == "done"
