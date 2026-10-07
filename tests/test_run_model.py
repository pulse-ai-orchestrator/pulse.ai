from __future__ import annotations

import pytest

from pulse.daemon.runs import RunState
from pulse.domain.run import (
    InvalidTransition,
    RunRecord,
    RunStatus,
    StepRecord,
    StepStatus,
    fan_out_child_id,
)
from pulse.runcontrol import RUN_BLOCKED, RUN_STOPPED


def _running(step_id: str = "one") -> StepRecord:
    step = StepRecord(step_id=step_id)
    step.start()
    return step


def _run(*steps: StepRecord) -> RunRecord:
    return RunRecord(id="run-1", workflow_id="demo", workspace_root="/tmp", steps=list(steps))


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
    step = StepRecord(step_id="one", status=status, ended_at="2026-01-01T00:00:00+00:00")

    assert step.release() is True
    assert step.status == StepStatus.PENDING
    assert step.ended_at == ""


def test_release_leaves_a_settled_step_alone():
    step = StepRecord(step_id="one", status=StepStatus.DONE, ended_at="x")

    assert step.release() is False
    assert step.status == StepStatus.DONE


def test_reopening_a_round_clears_the_attempt_without_counting_it():
    """Counting rounds is the run's call: only the loop's opener counts them."""
    opener = _running("review")
    opener.record_reply(session_id="s1", summary="ok")
    opener.deliver()

    opener.reopen_round()

    assert opener.rounds == 1
    assert opener.status == StepStatus.PENDING
    assert (opener.summary, opener.acp_session_id, opener.started_at, opener.ended_at) == (
        "",
        "",
        "",
        "",
    )


def test_each_round_carries_its_net_time_into_the_next():
    """A round of 10min with 4min waiting adds 6min; the wait does not follow the step."""
    step = StepRecord(
        step_id="review",
        status=StepStatus.DONE,
        started_at="2026-10-01T10:00:00+00:00",
        ended_at="2026-10-01T10:10:00+00:00",
        waiting_seconds=240.0,
        carried_seconds=60.0,
    )

    step.reopen_round()

    assert step.carried_seconds == 60.0 + 360.0
    assert step.waiting_seconds == 0.0


def test_a_round_that_never_ran_carries_nothing():
    step = StepRecord(step_id="fix", carried_seconds=30.0)
    step.reopen_round()
    assert step.carried_seconds == 30.0


def test_a_running_step_cannot_be_reopened():
    with pytest.raises(InvalidTransition):
        _running().reopen_round()


def test_closing_with_the_loop_depends_on_whether_the_step_ran_before():
    ran = StepRecord(step_id="a")
    never = StepRecord(step_id="b")

    ran.close_with_loop(ran_before=True)
    never.close_with_loop(ran_before=False)

    assert (ran.status, never.status) == (StepStatus.DONE, StepStatus.SKIPPED)


def test_begin_step_points_the_run_at_a_known_step():
    run = _run(StepRecord(step_id="one"))

    run.begin_step("one")

    assert (run.status, run.current_step) == (RunStatus.RUNNING, "one")
    with pytest.raises(InvalidTransition):
        run.begin_step("ghost")


def test_a_run_completes_only_when_every_step_settled():
    step = _running()
    run = _run(step)

    with pytest.raises(InvalidTransition):
        run.complete()

    step.deliver()
    run.complete()
    assert run.status == RunStatus.COMPLETED


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

    failed = run.fail_running_steps()

    assert failed == [running]
    assert (running.status, done.status) == (StepStatus.FAILED, StepStatus.DONE)


def test_unknown_stored_statuses_load_as_pending():
    assert StepStatus.parse("") == StepStatus.PENDING
    assert RunStatus.parse("legacy") == RunStatus.PENDING
    assert RunStatus.parse("completed") == RunStatus.COMPLETED


def test_statuses_still_compare_as_the_stored_strings():
    assert StepStatus.DONE == "done"
    assert "awaiting_input" in {RunStatus.AWAITING_INPUT}


def test_daemon_run_state_finishes_once_with_the_mapped_status():
    state = RunState(id="r", workflow_id="demo", prompt="", workspace="")

    state.finish(RUN_BLOCKED)

    assert (state.status, state.exit_code, state.is_active()) == (RunStatus.BLOCKED, RUN_BLOCKED, False)
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
    ("status", "settled", "ended"),
    [
        (StepStatus.PENDING, False, False),
        (StepStatus.RUNNING, False, False),
        (StepStatus.DONE, True, True),
        (StepStatus.SKIPPED, True, True),
        (StepStatus.FAILED, False, True),
        (StepStatus.BLOCKED, False, True),
    ],
)
def test_settled_and_ended_split_the_statuses(status: StepStatus, settled: bool, ended: bool):
    step = StepRecord(step_id="one", status=status)

    assert (step.settled, step.has_ended) == (settled, ended)


def test_history_steps_share_the_domain_rule_for_settled():
    from pulse.history.models import HistoryStep

    assert HistoryStep(id="a", label="A", status="skipped").settled
    assert not HistoryStep(id="b", label="B", status="blocked").settled


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

    run.begin_step("one")
    assert run.await_input() is True
    assert run.status == RunStatus.AWAITING_INPUT
    assert run.await_input() is False, "a nested question is the same wait"

    assert run.resume_work() is True
    assert run.status == RunStatus.RUNNING
    assert run.resume_work() is False


def test_a_run_that_ended_during_a_question_keeps_its_ending():
    """Stopping while a question is open used to flip the run back to `running` when it closed."""
    run = _run(StepRecord(step_id="one"))
    run.begin_step("one")
    run.await_input()
    run.end(RUN_STOPPED)

    assert run.resume_work() is False
    assert run.status == RunStatus.STOPPED


def test_dropping_the_worktree_keeps_the_branch():
    run = _run()
    run.work_in(worktree_path="/wt/run-1", branch="pulse/demo-run-1")
    run.drop_worktree()
    assert (run.worktree_path, run.branch) == ("", "pulse/demo-run-1")
    assert run.exec_root == "/tmp"


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
    assert previous.step_id == "plan", "a blocked text is not a delivery, an empty skip says nothing"


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


def test_a_completed_run_cannot_begin_another_step():
    """Only a resume over an unfinished run may run steps again; a completed run is history."""
    step = _running()
    step.deliver()
    run = _run(step, StepRecord(step_id="two", status=StepStatus.SKIPPED))
    run.complete()

    with pytest.raises(InvalidTransition):
        run.begin_step("one")
    assert run.status == RunStatus.COMPLETED


def test_a_run_cannot_begin_a_step_that_already_settled():
    done = _running("one")
    done.deliver()
    run = _run(done, StepRecord(step_id="two"))

    with pytest.raises(InvalidTransition):
        run.begin_step("one")
    assert run.current_step == ""


@pytest.mark.parametrize("status", [RunStatus.STOPPED, RunStatus.BLOCKED, RunStatus.FAILED])
def test_a_resumed_run_begins_its_next_step_again(status: RunStatus):
    run = _run(StepRecord(step_id="one"))
    run.status = status

    run.begin_step("one")

    assert run.status == RunStatus.RUNNING


@pytest.mark.parametrize("code", [RUN_STOPPED, RUN_BLOCKED, 1])
def test_a_completed_run_keeps_its_completion(code: int):
    """A late stop or crash handler must not rewrite a run that already finished cleanly."""
    run = _run()
    run.complete()

    with pytest.raises(InvalidTransition):
        run.end(code)
    assert run.status == RunStatus.COMPLETED


def _loop_run(*statuses: StepStatus) -> RunRecord:
    steps = [StepRecord(step_id=f"s{index}", status=status) for index, status in enumerate(statuses)]
    return _run(*steps)


def test_reopening_a_loop_counts_the_round_only_on_its_opener():
    run = _loop_run(StepStatus.DONE, StepStatus.DONE, StepStatus.DONE)

    run.reopen_loop(["s0", "s1"])

    assert [step.rounds for step in run.steps] == [2, 1, 1]
    assert [step.status for step in run.steps] == [
        StepStatus.PENDING,
        StepStatus.PENDING,
        StepStatus.DONE,
    ]


def test_the_loop_round_is_the_opener_round_count():
    run = _loop_run(StepStatus.DONE, StepStatus.DONE)
    assert run.loop_round("s0") == 1

    run.reopen_loop(["s0", "s1"])

    assert run.loop_round("s0") == 2
    assert run.loop_round("ghost") == 1, "a loop whose opener the run lacks is on its first round"


@pytest.mark.parametrize(("reopens", "allowed"), [(0, True), (1, True), (2, False)])
def test_a_loop_repeats_until_its_opener_reaches_the_ceiling(reopens: int, allowed: bool):
    run = _loop_run(StepStatus.DONE, StepStatus.DONE)
    for _ in range(reopens):
        run.reopen_loop(["s0", "s1"])

    assert run.can_repeat("s0", ceiling=3) is allowed


def test_closing_a_loop_on_its_first_round_skips_what_never_ran():
    run = _loop_run(StepStatus.DONE, StepStatus.PENDING, StepStatus.PENDING)

    run.close_loop(["s0", "s1", "s2"])

    assert [step.status for step in run.steps] == [
        StepStatus.DONE,
        StepStatus.SKIPPED,
        StepStatus.SKIPPED,
    ]


def test_closing_a_loop_after_a_round_marks_the_rest_done():
    run = _loop_run(StepStatus.DONE, StepStatus.DONE)
    run.reopen_loop(["s0"])
    run.steps[0].start()
    run.steps[0].deliver()

    run.close_loop(["s0", "s1"])

    assert run.steps[1].status == StepStatus.DONE


def test_step_times_come_from_the_injected_clock():
    ticks = iter(["2026-10-07T10:00:00+00:00", "2026-10-07T10:05:00+00:00"])
    step = StepRecord(step_id="one", clock=lambda: next(ticks))

    step.start()
    step.deliver()

    assert (step.started_at, step.ended_at) == (
        "2026-10-07T10:00:00+00:00",
        "2026-10-07T10:05:00+00:00",
    )
