from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from pulse.daemon.runs import RunState
from pulse.domain.control import RUN_BLOCKED, RUN_STOPPED
from pulse.domain.run import (
    InvalidTransition,
    RunRecord,
    RunStatus,
    StepRecord,
    StepStatus,
    fan_out_child_id,
)


def _running(step_id: str = "one") -> StepRecord:
    step = StepRecord(step_id=step_id)
    step.start()
    return step


def _run(*steps: StepRecord) -> RunRecord:
    return RunRecord(id="run-1", workflow_id="demo", workspace_root="/repo", steps=list(steps))


def test_start_marks_running_and_keeps_the_first_start_across_retries():
    step = _running()
    first = step.started_at
    step.fail()
    step.start()

    assert step.status == StepStatus.RUNNING
    assert step.started_at == first


@pytest.mark.parametrize("status", [StepStatus.DONE, StepStatus.SKIPPED])
def test_a_settled_step_cannot_start_again(status: StepStatus):
    step = StepRecord(step_id="one", status=status)

    with pytest.raises(InvalidTransition):
        step.start()


@pytest.mark.parametrize(
    ("end", "status"),
    [
        (StepRecord.deliver, StepStatus.DONE),
        (StepRecord.skip, StepStatus.SKIPPED),
        (StepRecord.block, StepStatus.BLOCKED),
        (StepRecord.fail, StepStatus.FAILED),
    ],
)
def test_ending_a_running_step_stamps_the_end(end, status: StepStatus):
    step = _running()

    end(step)

    assert step.status == status
    assert step.ended_at


@pytest.mark.parametrize("end", [StepRecord.deliver, StepRecord.block, StepRecord.fail])
def test_only_a_running_step_can_end(end):
    step = StepRecord(step_id="one")

    with pytest.raises(InvalidTransition):
        end(step)


def test_an_agent_skip_keeps_the_summary_but_a_user_skip_drops_it():
    agent = _running()
    agent.record_reply(session_id="s1", summary="nada a fazer")
    agent.skip()

    user = _running()
    user.record_reply(session_id="s2", summary="falta o token")
    user.block()
    user.skip_blocked()

    assert agent.summary == "nada a fazer"
    assert user.status == StepStatus.SKIPPED
    assert user.summary == ""


def test_a_user_skip_needs_a_blocked_step():
    with pytest.raises(InvalidTransition):
        _running().skip_blocked()


def test_an_empty_session_id_keeps_the_previous_one():
    step = _running()
    step.record_reply(session_id="s1", summary="a")
    step.record_reply(session_id="", summary="b")

    assert step.acp_session_id == "s1"
    assert step.summary == "b"


@pytest.mark.parametrize("status", [StepStatus.RUNNING, StepStatus.FAILED, StepStatus.BLOCKED])
def test_release_returns_an_interrupted_step_to_pending(status: StepStatus):
    step = StepRecord(step_id="one", status=status, ended_at=datetime(2026, 1, 1, tzinfo=UTC))

    assert step.release() is True
    assert step.status == StepStatus.PENDING
    assert step.ended_at is None


def test_release_leaves_a_settled_step_alone():
    step = StepRecord(
        step_id="one", status=StepStatus.DONE, ended_at=datetime(2026, 1, 1, tzinfo=UTC)
    )

    assert step.release() is False
    assert step.status == StepStatus.DONE


def test_reopening_a_round_clears_the_attempt_and_counts_only_on_the_opener():
    opener = _running("review")
    opener.record_reply(session_id="s1", summary="ok")
    opener.deliver()
    other = _running("fix")
    other.deliver()

    opener.reopen_round(opener=True)
    other.reopen_round(opener=False)

    assert (opener.rounds, other.rounds) == (2, 1)
    assert opener.status == StepStatus.PENDING
    assert (opener.summary, opener.acp_session_id) == ("", "")
    assert (opener.started_at, opener.ended_at) == (None, None)


def test_each_round_carries_its_net_time_into_the_next():
    """A round of 10min with 4min waiting adds 6min; the wait does not follow the step."""
    step = StepRecord(
        step_id="review",
        status=StepStatus.DONE,
        started_at=datetime(2026, 10, 1, 10, 0, tzinfo=UTC),
        ended_at=datetime(2026, 10, 1, 10, 10, tzinfo=UTC),
        waiting_seconds=240.0,
        carried_seconds=60.0,
    )

    step.reopen_round(opener=True)

    assert step.carried_seconds == 60.0 + 360.0
    assert step.waiting_seconds == 0.0


def test_a_round_that_never_ran_carries_nothing():
    step = StepRecord(step_id="fix", carried_seconds=30.0)
    step.reopen_round(opener=False)
    assert step.carried_seconds == 30.0


def test_a_running_step_cannot_be_reopened():
    with pytest.raises(InvalidTransition):
        _running().reopen_round(opener=True)


def test_closing_with_the_loop_depends_on_whether_the_step_ran_before():
    ran = StepRecord(step_id="a")
    never = StepRecord(step_id="b")

    ran.close_with_loop(ran_before=True)
    never.close_with_loop(ran_before=False)

    assert (ran.status, never.status) == (StepStatus.DONE, StepStatus.SKIPPED)


def test_start_step_points_the_run_at_the_step_and_starts_it():
    run = _run(StepRecord(step_id="one"))

    started = run.start_step("one")

    assert started is run.step("one")
    assert (run.status, run.current_step) == (RunStatus.RUNNING, "one")
    assert started.status == StepStatus.RUNNING


def test_an_unknown_step_cannot_start():
    run = _run(StepRecord(step_id="one"))

    with pytest.raises(InvalidTransition):
        run.start_step("ghost")
    assert (run.status, run.current_step) == (RunStatus.PENDING, "")


def test_a_step_cannot_start_while_another_is_running():
    """One ACP session per step: two running steps would share nobody's session."""
    run = _run(StepRecord(step_id="one"), StepRecord(step_id="two"))
    run.start_step("one")

    with pytest.raises(InvalidTransition):
        run.start_step("two")
    assert run.current_step == "one"
    assert run.step("two").status == StepStatus.PENDING


def test_a_retry_starts_the_same_step_again():
    run = _run(StepRecord(step_id="one"))
    run.start_step("one").fail()

    run.start_step("one")

    assert run.step("one").status == StepStatus.RUNNING


def test_ending_a_wait_charges_the_step_and_resumes_the_run():
    run = _run(StepRecord(step_id="one"))
    run.start_step("one")
    run.await_input()

    run.end_wait("one", 30.0)

    assert run.status == RunStatus.RUNNING
    assert run.step("one").waiting_seconds == 30.0


def test_a_wait_without_a_step_only_resumes_the_run():
    """The resume menu asks before any step exists."""
    run = _run(StepRecord(step_id="one"))
    run.start_step("one")
    run.await_input()

    run.end_wait("ghost", 30.0)

    assert run.status == RunStatus.RUNNING
    assert run.step("one").waiting_seconds == 0.0


def test_reopening_a_loop_counts_the_round_only_on_the_opener():
    run = _run(_running("review"), StepRecord(step_id="fix"), StepRecord(step_id="after"))
    run.step("review").deliver()

    run.reopen_loop(["review", "fix", "ghost"], opener_id="review")

    assert [step.status for step in run.steps] == [StepStatus.PENDING] * 3
    assert (run.step("review").rounds, run.step("fix").rounds) == (2, 1)
    assert run.step("after").rounds == 1


@pytest.mark.parametrize(
    ("opener_rounds", "status"), [(1, StepStatus.SKIPPED), (2, StepStatus.DONE)]
)
def test_closing_a_loop_settles_what_is_left_by_whether_the_opener_ran_before(
    opener_rounds: int, status: StepStatus
):
    """Steps that ran in an earlier round delivered something; ones that never ran did not."""
    run = _run(
        StepRecord(step_id="review", status=StepStatus.DONE, rounds=opener_rounds),
        StepRecord(step_id="fix"),
        StepRecord(step_id="check", status=StepStatus.SKIPPED),
    )

    run.close_loop(["fix", "check", "ghost"], opener_id="review")

    assert run.step("fix").status == status
    assert run.step("check").status == StepStatus.SKIPPED, "a settled step is left alone"


def test_elapsed_is_none_until_a_round_closes():
    assert StepRecord(step_id="one").elapsed_seconds() is None
    assert _running().elapsed_seconds() is None


def test_elapsed_sums_the_carried_rounds_and_the_closed_one_minus_waits():
    start = datetime(2026, 10, 1, 10, 0, tzinfo=UTC)
    step = StepRecord(
        step_id="review",
        status=StepStatus.DONE,
        started_at=start,
        ended_at=start + timedelta(minutes=10),
        waiting_seconds=240.0,
        carried_seconds=60.0,
    )

    assert step.elapsed_seconds() == 60.0 + 360.0


def test_elapsed_of_an_open_round_is_what_earlier_rounds_carried():
    assert StepRecord(step_id="one", carried_seconds=30.0).elapsed_seconds() == 30.0


def test_a_run_sums_each_step_that_already_has_time_and_skips_the_rest():
    """The flow total is the sidebar's frozen time, including a fan-out's tasks.

    An attempt still open contributes nothing until it closes. Zero is a real
    duration: a step that started and ended together still counts.
    """
    start = datetime(2026, 10, 1, 10, 0, tzinfo=UTC)
    closed = StepRecord(
        step_id="plan",
        status=StepStatus.DONE,
        started_at=start,
        ended_at=start + timedelta(minutes=10),
        waiting_seconds=240.0,
        carried_seconds=60.0,
    )
    instant = StepRecord(
        step_id="check",
        status=StepStatus.DONE,
        started_at=start,
        ended_at=start,
    )
    carried = StepRecord(step_id="review:T1", carried_seconds=30.0)
    running = StepRecord(step_id="build", status=StepStatus.RUNNING, started_at=start)

    assert _run(closed, carried, running).elapsed_seconds() == 60.0 + 360.0 + 30.0
    assert _run(instant).elapsed_seconds() == 0.0


def test_a_run_with_no_recorded_step_time_has_no_duration():
    assert _run(StepRecord(step_id="one"), _running("two")).elapsed_seconds() is None


def test_a_run_completes_only_when_every_step_settled():
    step = _running()
    run = _run(step)

    with pytest.raises(InvalidTransition):
        run.complete()

    step.deliver()
    run.complete()
    assert run.status == RunStatus.COMPLETED


def test_steps_the_definition_dropped_are_skipped_and_the_rest_left_alone():
    """An edited workflow must not hold a resumed run open forever.

    Only unsettled steps outside the definition change; fan-out children count as
    their base step, and history already settled is never rewritten.
    """
    dropped_failed = _running("gone")
    dropped_failed.fail()
    dropped_done = _running("old")
    dropped_done.deliver()
    run = _run(
        StepRecord(step_id="kept"),
        StepRecord(step_id="review:T1"),
        dropped_failed,
        StepRecord(step_id="gone:T1"),
        dropped_done,
    )

    run.retire_steps_outside({"kept", "review"})

    assert [(item.step_id, item.status) for item in run.steps] == [
        ("kept", StepStatus.PENDING),
        ("review:T1", StepStatus.PENDING),
        ("gone", StepStatus.SKIPPED),
        ("gone:T1", StepStatus.SKIPPED),
        ("old", StepStatus.DONE),
    ]


def test_a_retired_step_drops_its_summary_so_it_is_not_passed_on():
    step = _running("gone")
    step.record_reply(session_id="s", summary="half done")
    step.block()

    step.retire()

    assert (step.status, step.summary) == (StepStatus.SKIPPED, "")
    assert step.ended_at is not None


def test_a_running_step_cannot_be_retired():
    with pytest.raises(InvalidTransition):
        _running("gone").retire()


@pytest.mark.parametrize(
    ("code", "status"),
    [(RUN_STOPPED, RunStatus.STOPPED), (RUN_BLOCKED, RunStatus.BLOCKED), (1, RunStatus.FAILED)],
)
def test_end_maps_the_exit_code(code: int, status: RunStatus):
    run = _run()

    run.end(code)

    assert run.status == status


def test_a_clean_exit_must_go_through_complete():
    with pytest.raises(InvalidTransition):
        _run(StepRecord(step_id="one")).end(0)


def test_a_crash_fails_only_the_running_steps():
    running = _running("a")
    done = _running("b")
    done.deliver()
    run = _run(running, done)

    run.fail_running_steps()

    assert (running.status, done.status) == (StepStatus.FAILED, StepStatus.DONE)


def test_a_crashed_run_fails_with_its_running_step():
    """A crash must not leave a step `running` in history, nor the run looking alive."""
    running = _running("a")
    done = _running("b")
    done.deliver()
    run = _run(done, running)

    run.crash()

    assert (run.status, running.status, done.status) == (
        RunStatus.FAILED,
        StepStatus.FAILED,
        StepStatus.DONE,
    )


@pytest.mark.parametrize(
    "change",
    [
        lambda run: run.reopen_loop(["idle", "busy"], opener_id="idle"),
        lambda run: run.close_loop(["idle", "busy"], opener_id="idle"),
        lambda run: run.retire_steps_outside(set()),
    ],
    ids=["reopen_loop", "close_loop", "retire_steps_outside"],
)
def test_a_refused_change_to_several_steps_changes_none_of_them(change):
    """Found by `test_run_properties`: the steps before the running one were already changed.

    The next save would have persisted a loop or a retirement that was refused.
    """
    idle = StepRecord(step_id="idle")
    run = _run(idle, _running("busy"))

    with pytest.raises(InvalidTransition):
        change(run)

    assert (idle.status, idle.rounds, idle.ended_at) == (StepStatus.PENDING, 1, None)


def test_a_loop_over_a_repeated_step_id_changes_that_step_once():
    """A step listed twice is still one step: one more round, one settlement, no refusal.

    Otherwise closing settles it and then refuses the second copy, leaving the change half-applied.
    """
    reopened = StepRecord(step_id="loop")
    _run(reopened).reopen_loop(["loop", "loop"], opener_id="loop")
    closed = StepRecord(step_id="loop")
    _run(closed).close_loop(["loop", "loop"], opener_id="other")

    assert (reopened.status, reopened.rounds) == (StepStatus.PENDING, 2)
    assert closed.status == StepStatus.SKIPPED


def test_own_branch_names_the_workflow_and_the_short_run_id():
    run = RunRecord(id="0123456789abcdef", workflow_id="nova spec/v2", workspace_root="/repo")

    assert run.own_branch == "pulse/nova-spec-v2-01234567"


def test_a_workflow_id_with_no_safe_character_still_names_a_branch():
    run = RunRecord(id="0123456789abcdef", workflow_id="///", workspace_root="/repo")

    assert run.own_branch == "pulse/run-01234567"


@pytest.mark.parametrize(
    ("branch", "owned"),
    [
        ("pulse/demo-run-1", True),
        ("pulse/demo-run-1-2", True),
        ("main", False),
        ("", False),
        ("pulse/demo-run-12", False),
        ("pulse/other-run-1", False),
    ],
)
def test_a_run_owns_only_the_branch_it_created(branch: str, owned: bool):
    """Reattaching must never take over a branch of the project, like `main`.

    `add_worktree` may suffix the name (`-2`) when it is taken; that is still ours.
    """
    run = _run()
    run.work_in(worktree_path="", branch=branch)

    assert run.owns_branch is owned


def test_a_confirmed_branch_is_owned_whatever_its_name():
    run = _run()
    run.work_in(worktree_path="/wt", branch="corrigir-o-login", owns=True)

    assert run.owns_branch is True


def test_unknown_stored_statuses_load_as_pending():
    assert StepStatus.parse("") == StepStatus.PENDING
    assert RunStatus.parse("legacy") == RunStatus.PENDING
    assert RunStatus.parse("completed") == RunStatus.COMPLETED


def test_statuses_still_compare_as_the_stored_strings():
    assert StepStatus.DONE == "done"
    assert "awaiting_input" in {RunStatus.AWAITING_INPUT}


def test_daemon_run_state_finishes_once_with_the_mapped_status():
    state = RunState.open(run_id="r", workflow_id="demo", prompt="", workspace="")

    state.finish(RUN_BLOCKED)

    assert (state.status, state.exit_code, state.is_active()) == (
        RunStatus.BLOCKED,
        RUN_BLOCKED,
        False,
    )
    with pytest.raises(RuntimeError):
        state.finish(0)


def test_add_step_keeps_the_step_the_run_already_had():
    known = StepRecord(step_id="one", status=StepStatus.DONE)
    run = _run(known)

    assert run.add_step(StepRecord(step_id="one")) is known
    assert run.add_step(StepRecord(step_id="two")).step_id == "two"
    assert [step.step_id for step in run.steps] == ["one", "two"]


def test_expand_step_puts_the_children_where_the_base_was():
    run = _run(StepRecord(step_id="a"), StepRecord(step_id="fan"), StepRecord(step_id="z"))

    run.expand_step("fan", [StepRecord(step_id="fan:1"), StepRecord(step_id="fan:2")])

    assert [step.step_id for step in run.steps] == ["a", "fan:1", "fan:2", "z"]
    assert run.removed_step_ids() == {"fan"}


def test_expanding_again_on_resume_keeps_the_children_it_has():
    done = StepRecord(step_id="fan:1", status=StepStatus.DONE)
    run = _run(done, StepRecord(step_id="fan:2"))

    run.expand_step("fan", [StepRecord(step_id="fan:1"), StepRecord(step_id="fan:2")])

    assert run.steps[0] is done
    assert len(run.steps) == 2
    assert run.removed_step_ids() == frozenset()


@pytest.mark.parametrize(
    ("status", "settled", "ended", "retry"),
    [
        (StepStatus.PENDING, False, False, False),
        (StepStatus.RUNNING, False, False, False),
        (StepStatus.DONE, True, True, False),
        (StepStatus.SKIPPED, True, True, False),
        (StepStatus.FAILED, False, True, True),
        (StepStatus.BLOCKED, False, True, True),
    ],
)
def test_settled_ended_and_retry_split_the_statuses(
    status: StepStatus, settled: bool, ended: bool, retry: bool
):
    """Only an attempt that failed or blocked makes the next start a retry."""
    step = StepRecord(step_id="one", status=status)

    assert (step.settled, step.has_ended, step.starts_as_retry) == (settled, ended, retry)


def test_history_steps_share_the_domain_rule_for_settled():
    from pulse.history.models import HistoryStep

    assert HistoryStep(id="a", label="A", status=StepStatus.SKIPPED).settled
    assert not HistoryStep(id="b", label="B", status=StepStatus.BLOCKED).settled


def test_only_positive_waits_come_off_the_step():
    """A clock glitch must never add agent time back by subtracting a negative wait."""
    step = _running()
    step.add_wait(30.0)
    step.add_wait(12.5)
    step.add_wait(0.0)
    step.add_wait(-5.0)
    assert step.waiting_seconds == 42.5


def test_only_a_running_run_waits_for_input_and_only_a_waiting_one_resumes():
    run = _run(StepRecord(step_id="one"))
    assert run.await_input() is False, "a run that has not begun a step is not paused on anyone"
    assert run.status == RunStatus.PENDING

    run.start_step("one")
    assert run.await_input() is True
    assert run.status == RunStatus.AWAITING_INPUT
    assert run.await_input() is False, "a nested question is the same wait"

    assert run.resume_work() is True
    assert run.status == RunStatus.RUNNING
    assert run.resume_work() is False


def test_a_run_that_ended_during_a_question_keeps_its_ending():
    """Stopping while a question is open used to flip the run back to `running` when it closed."""
    run = _run(StepRecord(step_id="one"))
    run.start_step("one")
    run.await_input()
    run.end(RUN_STOPPED)

    assert run.resume_work() is False
    assert run.status == RunStatus.STOPPED


def _settled(step_id: str, summary: str, *, skip: bool = False) -> StepRecord:
    step = _running(step_id)
    step.record_reply(session_id="", summary=summary)
    if skip:
        step.skip()
    else:
        step.deliver()
    return step


def test_the_previous_delivery_is_the_last_settled_step_with_a_summary():
    blocked = _running("check")
    blocked.record_reply(session_id="", summary="não consegui")
    blocked.block()
    run = _run(
        _settled("plan", "plano"),
        _settled("spec", "", skip=True),
        blocked,
        StepRecord(step_id="build"),
    )

    previous = run.previous_delivery("build")

    assert previous is not None
    assert previous.step_id == "plan", (
        "a blocked text is not a delivery, an empty skip says nothing"
    )


def test_a_resumed_fan_out_still_sees_the_step_that_listed_the_items():
    """The scan stops at the first child, not at a base step the run no longer has."""
    run = _run(
        _settled("plan", "```pulse:items\nT1: um\n```"),
        _settled(fan_out_child_id("build", "T1"), "feito T1"),
        StepRecord(step_id=fan_out_child_id("build", "T2")),
    )

    previous = run.previous_delivery("build")

    assert previous is not None
    assert previous.step_id == "plan"


def test_fan_out_siblings_are_the_children_of_the_same_step():
    run = _run(
        StepRecord(step_id="plan"),
        StepRecord(step_id=fan_out_child_id("build", "T1")),
        StepRecord(step_id=fan_out_child_id("build", "T2")),
        StepRecord(step_id=fan_out_child_id("buildx", "T1")),
    )

    siblings = run.fan_out_siblings(fan_out_child_id("build", "T2"))

    assert [step.step_id for step in siblings] == ["build:T1", "build:T2"]
    assert run.fan_out_siblings("plan") == []


def test_step_ids_by_status_groups_every_step_in_run_order():
    run = _run(
        StepRecord(step_id="a", status=StepStatus.DONE),
        StepRecord(step_id="b", status=StepStatus.BLOCKED),
        StepRecord(step_id="c", status=StepStatus.DONE),
        StepRecord(step_id="d"),
    )

    grouped = run.step_ids_by_status()

    assert grouped[StepStatus.DONE] == ["a", "c"]
    assert grouped[StepStatus.BLOCKED] == ["b"]
    assert grouped[StepStatus.PENDING] == ["d"]
    assert grouped[StepStatus.FAILED] == [], "every status is present, even when empty"
