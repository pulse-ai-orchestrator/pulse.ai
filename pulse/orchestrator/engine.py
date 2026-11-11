"""The orchestrator: which agent runs now, and when.

The only state machine in Pulse, agnostic of what agents do. A workflow is an
ordered list of steps ([pulse.domain.workflow.WorkflowDef]); for each step the
engine resolves the agent, renders `prompt_template`, opens an isolated session
and records the outcome on the run.

Everything the engine does to the world goes through the ports in
[pulse.domain.ports], handed in as `EnginePorts`; only the daemon knows which
adapters stand behind them.

Sessions are isolated per step on purpose: the next step only receives the summary
Pulse forwards, which allows switching runtimes between steps and redoing one step.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import NamedTuple

from pulse.domain.control import RUN_STOPPED, RunControl
from pulse.domain.git_options import NO_GIT_OPTIONS, GitOptions
from pulse.domain.outcome import LoopSignal, Outcome, OutcomeStatus, parse_outcome
from pulse.domain.ports import (
    AgentProfile,
    JsonObject,
    PhaseContinuation,
    PromptContinuation,
    WorkspaceError,
)
from pulse.domain.run import RunRecord, StepRecord, StepStatus
from pulse.domain.task_brief import EMPTY_BRIEF, TaskBrief
from pulse.domain.workflow import Loop, StepDef, WorkflowDef
from pulse.orchestrator import wording
from pulse.orchestrator.agent_text import (
    build_continuation_prompt,
    build_outcome_reminder_prompt,
    build_unblock_prompt,
    earlier_answers_block,
    earlier_attempt_block,
    guidance_block,
    outcome_protocol,
)
from pulse.orchestrator.delivery import (
    commit_delivery,
    publish_finished_run,
    publish_ready_request,
    snapshot_if_committing,
)
from pulse.orchestrator.fanout import POSITION_STRIDE, Item, expand
from pulse.orchestrator.loops import close_loop, repeat_loop
from pulse.orchestrator.menus import end_without_retry, offer_next, revive_session
from pulse.orchestrator.render import TemplateError, render
from pulse.orchestrator.turn import TurnResult
from pulse.orchestrator.waits import RunWaits
from pulse.orchestrator.wiring import EnginePorts, Wiring, notify, sync_steps
from pulse.orchestrator.worktree import prepare_workspace
from pulse.replies.approval import format_summary


class EmptyWorkflow(ValueError):
    """A definition with no step: there is nothing to run."""


class UnitsResult(NamedTuple):
    """How one definition step ended.

    `exit_code` is set when the run must stop. A loop that breaks out leaves
    `finished` off, so the caller does not publish from it; `next_index` is where
    the walk over the definition goes next.
    """

    exit_code: int | None
    finished: bool
    next_index: int


def run_workflow(
    *,
    definition: WorkflowDef,
    user_prompt: str,
    ports: EnginePorts,
    git: GitOptions = NO_GIT_OPTIONS,
    brief: TaskBrief = EMPTY_BRIEF,
    branch: str = "",
    resume_run_id: str | None = None,
    control: RunControl | None = None,
    run_id: str | None = None,
) -> int:
    """Run the workflow to its end and return the run's exit code.

    A workflow with no step raises before any run is stored; once the run is
    stored, any failure (a worktree that will not open, a crash mid-run) is
    recorded on it, then raised. A resumed run keeps the git options it was
    stored with; `git` applies to new runs and to runs stored before runs kept
    their own.
    """
    if not definition.steps:
        raise EmptyWorkflow(f"workflow `{definition.id}` has no steps")

    run = _resolve_run(
        definition,
        ports,
        user_prompt,
        resume_run_id=resume_run_id,
        run_id=run_id,
        brief=brief,
        git=git,
    )
    git = run.git or git

    try:
        exec_dir = _open_workspace(run, ports, use_worktree=git.use_worktree, branch=branch)
        ports.session.bind_run(run.id, RunWaits(run, ports.runs))
        wiring = Wiring(
            ports=ports,
            control=control or RunControl(),
            exec_dir=exec_dir,
            atomic_commits=git.atomic_commits,
            auto_pull_request=git.auto_pull_request,
        )
        return _execute(wiring, definition=definition, run=run)
    # The run is stored, so it is the boundary: record the crash on it, then let
    # the caller report it.
    except Exception:  # noqa: BLE001
        run.crash()
        ports.runs.save(run)
        raise


def _open_workspace(run: RunRecord, ports: EnginePorts, *, use_worktree: bool, branch: str) -> Path:
    """Where the agent works, announced to the stream before any step begins."""
    try:
        exec_dir, branch = prepare_workspace(
            run, ports.workspace, ports.runs, use_worktree=use_worktree, branch=branch
        )
    except WorkspaceError as error:
        raise WorkspaceError(f"could not open the worktree for this run: {error}") from error
    # Must precede the first `phase.begin`: the artifact pane uses it to know
    # which folder to watch.
    ports.stream.set_context(cwd=str(exec_dir), branch=branch)
    return exec_dir


def _resolve_run(
    definition: WorkflowDef,
    ports: EnginePorts,
    user_prompt: str,
    *,
    resume_run_id: str | None,
    run_id: str | None = None,
    brief: TaskBrief = EMPTY_BRIEF,
    git: GitOptions = NO_GIT_OPTIONS,
) -> RunRecord:
    """The stored run. `run_id` lets the caller name it.

    The daemon passes its own id so the API and storage share one run id.
    """
    if resume_run_id:
        existing = ports.runs.load(resume_run_id)
        if existing is not None:
            # A killed daemon leaves its step `running`; one step runs at a time.
            existing.fail_running_steps()
            return existing
    return ports.runs.create(
        run_id=run_id or str(uuid.uuid4()),
        workflow_id=definition.id,
        workspace=ports.workspace.root,
        user_prompt=user_prompt,
        brief=brief,
        git=git,
        steps=[
            StepRecord(
                step_id=step.step_id,
                position=step.position * POSITION_STRIDE,
                label=step.label,
                agent_id=step.agent_id,
            )
            for step in definition.steps
        ],
    )


def _execute(wiring: Wiring, *, definition: WorkflowDef, run: RunRecord) -> int:
    try:
        wiring.session.open(wiring.exec_dir)
        sync_steps(wiring, run)

        loops = definition.loops()
        index = 0
        while index < len(definition.steps):
            definition_step = definition.steps[index]
            at = index
            index += 1
            previous = run.previous_delivery(definition_step.step_id)
            units = expand(run, definition_step, previous.summary if previous else "")
            wiring.runs.save(run)
            sync_steps(wiring, run)

            result = _run_units(
                wiring,
                definition=definition,
                run=run,
                units=units,
                loops=loops,
                at=at,
                index=index,
            )
            if result.exit_code is not None:
                return result.exit_code
            index = result.next_index
            if result.finished and definition_step.opens_request:
                publish_ready_request(wiring, run, template=definition.pull_request_template)

        run.retire_steps_outside({step.step_id for step in definition.steps})
        failed = publish_finished_run(wiring, run, template=definition.pull_request_template)
        if failed is not None:
            run.end(failed)
            wiring.runs.save(run)
            return failed
        run.complete()
        wiring.runs.save(run)
        sync_steps(wiring, run)
        return 0
    finally:
        wiring.session.close()


def _run_units(
    wiring: Wiring,
    *,
    definition: WorkflowDef,
    run: RunRecord,
    units: list[tuple[StepDef, Item | None]],
    loops: dict[int, Loop],
    at: int,
    index: int,
) -> UnitsResult:
    """Run every unit of one definition step."""
    for step, item in units:
        record = run.add_step(
            StepRecord(
                step_id=step.step_id,
                position=step.position,
                label=step.label,
                agent_id=step.agent_id,
            )
        )

        if record.settled:
            continue

        if not wiring.control.checkpoint():
            notify(wiring, wording.RUN_STOPPED_BY_USER)
            run.end(RUN_STOPPED)
            wiring.runs.save(run)
            return UnitsResult(RUN_STOPPED, finished=False, next_index=index)

        loop = loops.get(at)
        opens_loop = loop is not None and loop.opens(at)
        exit_code, signal = _run_step(
            wiring,
            run=run,
            step=step,
            record=record,
            item=item,
            may_close=opens_loop,
        )
        sync_steps(wiring, run)
        if exit_code != 0:
            run.end(exit_code)
            wiring.runs.save(run)
            return UnitsResult(exit_code, finished=False, next_index=index)

        if signal == LoopSignal.CLOSE and loop is not None and opens_loop:
            index = close_loop(run, definition, loop)
            wiring.runs.save(run)
            sync_steps(wiring, run)
            notify(wiring, wording.loop_closed(record.label))
            return UnitsResult(None, finished=False, next_index=index)

        if signal == LoopSignal.REPEAT and loop is not None and loop.closes(at):
            target, message = repeat_loop(run, definition, loop, record.label)
            wiring.runs.save(run)
            notify(wiring, message)
            if target is not None:
                sync_steps(wiring, run)
                return UnitsResult(None, finished=False, next_index=target)

    return UnitsResult(None, finished=True, next_index=index)


def _run_step(
    wiring: Wiring,
    *,
    run: RunRecord,
    step: StepDef,
    record: StepRecord,
    item: Item | None = None,
    may_close: bool = False,
) -> tuple[int, LoopSignal | None]:
    """`(exit code, loop signal)`; how the step ended is in `record.status`."""
    guidance = ""
    answered: list[str] = []
    while True:
        signal, reason = _attempt_step(
            wiring,
            run=run,
            step=step,
            record=record,
            guidance=guidance,
            answered=answered,
            item=item,
            may_close=may_close,
        )
        if record.settled:
            return 0, signal

        if wiring.control.interrupted:
            _release_step(wiring, run=run, record=record, label=record.label)
            return RUN_STOPPED, None

        choice, guidance = offer_next(wiring, record, reason)
        if wiring.control.interrupted:
            _release_step(wiring, run=run, record=record, label=record.label)
            return RUN_STOPPED, None

        exit_code = end_without_retry(wiring, run, record, choice, reason)
        if exit_code is not None:
            return exit_code, None
        revive_session(wiring)
        notify(
            wiring,
            wording.retrying_step_with_guidance(record.label)
            if guidance
            else wording.retrying_step(record.label),
        )


def _attempt_step(
    wiring: Wiring,
    *,
    run: RunRecord,
    step: StepDef,
    record: StepRecord,
    guidance: str,
    answered: list[str],
    item: Item | None = None,
    may_close: bool = False,
) -> tuple[LoopSignal | None, str]:
    """`(loop signal, reason)`. How the attempt ended is the step's status;
    `reason` explains a failure or a block to the person deciding what next.

    `answered` holds the questionnaire answers of the earlier attempts of this
    step; this attempt's answers are added to it for the next retry.
    """
    earlier = _earlier_attempt_files(wiring, run, record)
    run.start_step(record.step_id)
    wiring.runs.save(run)

    profile = wiring.ports.agents.profile(step.agent_id)
    wiring.session.use_agent(profile)
    before = snapshot_if_committing(wiring, run, step)
    try:
        prompt_text = _step_prompt(
            wiring,
            run,
            step,
            profile,
            item=item,
            guidance=guidance,
            earlier=earlier,
            answered=answered,
        )
    except TemplateError as error:
        _fail(wiring, run, record)
        return None, str(error)

    try:
        raw = _converse(wiring, run, step, record, profile, prompt_text)
    # The session is the boundary to the agent: any failure fails the attempt, not the run.
    except Exception as error:  # noqa: BLE001
        _fail(wiring, run, record)
        return None, _session_error(error)
    finally:
        answered.extend(wiring.session.last_answer_rounds)

    turn = TurnResult.parse(raw)
    record.record_reply(
        session_id=wiring.session.last_session_id, summary=format_summary(turn.summary)
    )
    signal, reason = _judge_turn(wiring, run, step, record, turn, may_close=may_close)
    commit_delivery(
        wiring,
        run,
        step,
        delivered=record.status == StepStatus.DONE,
        subject=parse_outcome(turn.summary).commit_subject,
        item=item,
        before=before,
    )
    return signal, reason


def _step_prompt(
    wiring: Wiring,
    run: RunRecord,
    step: StepDef,
    profile: AgentProfile,
    *,
    item: Item | None,
    guidance: str,
    earlier: list[str],
    answered: list[str],
) -> str:
    """The step's template rendered, wrapped in the agent's instructions and Pulse's protocol."""
    prompt_text = render(step.prompt_template, _template_values(wiring, run, step, item))
    # Inlined, not passed as a system prompt, so instructions work with any runtime.
    if profile.instructions:
        prompt_text = f"{profile.instructions}\n\n---\n\n{prompt_text}"
    prompt_text += earlier_attempt_block(earlier)
    prompt_text += earlier_answers_block(answered)
    prompt_text += guidance_block(guidance)
    if step.declares_outcome:
        prompt_text += outcome_protocol(ask_commit=bool(wiring.atomic_commits and step.commit_type))
    return prompt_text


def _earlier_attempt_files(wiring: Wiring, run: RunRecord, record: StepRecord) -> list[str]:
    """What the failed attempts of this round wrote; nothing on a first attempt.

    A retry runs in a fresh session; knowing these files keeps the agent from
    writing the same artifact again under another name. `started_at` survives
    retries but not a new loop round, whose files are meant to be new.
    """
    if not record.starts_as_retry:
        return []
    return wiring.runs.step_artifacts(run.id, record.step_id, since=record.started_at)


def _converse(
    wiring: Wiring,
    run: RunRecord,
    step: StepDef,
    record: StepRecord,
    profile: AgentProfile,
    prompt_text: str,
) -> JsonObject:
    """One ACP session for the step: an approval loop, or a single prompt and its follow-ups."""
    if step.requires_approval:
        return wiring.session.run_isolated_phase(
            workflow=run.workflow_id,
            phase_label=record.label or step.step_id,
            initial_prompt=prompt_text,
            preferred_model=profile.model,
            build_continuation=_approval_continuation(step),
            phase_id=step.step_id,
        )
    return wiring.session.run_isolated_prompt(
        workflow=run.workflow_id,
        phase_label=record.label or step.step_id,
        prompt_text=prompt_text,
        preferred_model=profile.model,
        phase_id=step.step_id,
        build_continuation=_unblock_continuation(step) if step.declares_outcome else None,
    )


def _judge_turn(
    wiring: Wiring,
    run: RunRecord,
    step: StepDef,
    record: StepRecord,
    turn: TurnResult,
    *,
    may_close: bool,
) -> tuple[LoopSignal | None, str]:
    """Settle, skip, fail or block the step from the agent's last turn."""
    if turn.cancelled:
        _fail(wiring, run, record)
        return None, wording.STEP_CANCELLED

    if turn.skipped:
        record.skip()
        wiring.runs.save(run)
        return None, ""

    outcome = parse_outcome(turn.summary)
    if may_close and not turn.approved and outcome.closes:
        return _settle(wiring, run, record, LoopSignal.CLOSE)

    unfinished = _unfinished_reason(step, turn)
    if unfinished is not None:
        _fail(wiring, run, record)
        return None, unfinished

    if not step.declares_outcome:
        return _settle(wiring, run, record, None)
    return _judge_outcome(wiring, run, step, record, outcome, may_close)


def _unfinished_reason(step: StepDef, turn: TurnResult) -> str | None:
    """Why the turn does not count as finished: not approved, or not ended cleanly."""
    if step.requires_approval and not turn.approved:
        if turn.turns_exhausted:
            return wording.APPROVAL_TURNS_EXHAUSTED
        if not turn.has_approval_answers:
            return wording.NO_APPROVAL_NOR_OUTCOME
        return wording.STEP_NOT_APPROVED
    if not step.requires_approval and not turn.ended_cleanly:
        return turn.stop_reason or wording.AGENT_DID_NOT_COMPLETE
    return None


def _judge_outcome(
    wiring: Wiring,
    run: RunRecord,
    step: StepDef,
    record: StepRecord,
    declared: Outcome,
    may_close: bool,
) -> tuple[LoopSignal | None, str]:
    """A step that declares its outcome is delivered only if the block says so."""
    if not declared.delivered:
        record.block()
        wiring.runs.save(run)
        return None, _blocked_reason(declared)
    if may_close and declared.closes:
        return _settle(wiring, run, record, LoopSignal.CLOSE)
    repeats = step.repeat is not None and declared.repeats
    return _settle(wiring, run, record, LoopSignal.REPEAT if repeats else None)


def _settle(
    wiring: Wiring, run: RunRecord, record: StepRecord, signal: LoopSignal | None
) -> tuple[LoopSignal | None, str]:
    """Record the step as delivered and pass the agent's loop signal on."""
    record.deliver()
    wiring.runs.save(run)
    return signal, ""


def _approval_continuation(step: StepDef) -> PhaseContinuation:
    """What to send after an approval answer that asked for more."""

    def build(*, phase_summary: str, questionnaire_answers: str, outcome: str) -> str:
        return build_continuation_prompt(
            step_id=step.step_id,
            summary=phase_summary,
            answers=questionnaire_answers,
            outcome=outcome,
        )

    return build


def _unblock_continuation(step: StepDef) -> PromptContinuation:
    """Give the agent one chance to unblock itself before involving the user.

    Runs in the same session (see `run_isolated_prompt`), once per attempt. Also
    covers a missing outcome block, usually just a forgotten declaration.
    """
    spent = False

    def build(*, result: JsonObject, turn: int) -> str:
        nonlocal spent
        if spent:
            return ""
        declared = parse_outcome(TurnResult.parse(result).summary)
        if declared.delivered:
            return ""
        spent = True
        if declared.status == OutcomeStatus.MISSING:
            return build_outcome_reminder_prompt(step_id=step.step_id)
        if declared.needs_user:
            return ""
        return build_unblock_prompt(step_id=step.step_id, reason=declared.reason)

    return build


def _blocked_reason(declared: Outcome) -> str:
    if declared.status == OutcomeStatus.MISSING:
        return wording.OUTCOME_NOT_DECLARED
    if declared.reason:
        return declared.reason
    if declared.unknown_status:
        return wording.unknown_outcome(declared.unknown_status)
    return wording.BLOCKED_WITHOUT_REASON


def _fail(wiring: Wiring, run: RunRecord, record: StepRecord) -> None:
    record.fail()
    wiring.runs.save(run)


def _template_values(
    wiring: Wiring,
    run: RunRecord,
    step: StepDef,
    item: Item | None = None,
) -> dict[str, str]:
    """Values `prompt_template` may reference.

    Keys are generic: the engine knows no artifact or phase names. `workspace` is
    where the agent works (the run's worktree, if any). `item_*` are empty strings
    outside fan-out, so the same template works in both modes. `previous_status`
    is the status (`done`/`skipped`) of the step `previous_summary` came from,
    empty when none. A skip from the blocked menu clears `summary`, so that step
    drops out and the earlier one is reported.
    """
    artifacts = wiring.runs.artifacts(run.id)
    siblings = run.fan_out_siblings(step.step_id) if item is not None else []
    previous = run.previous_delivery(step.step_id)
    return {
        "user_prompt": run.user_prompt.strip(),
        "workspace": str(wiring.exec_dir),
        "workflow_id": run.workflow_id,
        "run_id": run.id,
        "step_id": step.step_id,
        "step_label": step.label,
        "previous_summary": previous.summary if previous is not None else "",
        "previous_status": previous.status if previous is not None else "",
        "artifacts": "\n".join(f"- {path}" for path in artifacts),
        "item_id": item.id if item else "",
        "item_label": item.label if item else "",
        "item_index": str(_index_of(siblings, step.step_id)) if item else "",
        "item_total": str(len(siblings)) if item else "",
    }


def _index_of(records: list[StepRecord], step_id: str) -> int:
    for index, record in enumerate(records, start=1):
        if record.step_id == step_id:
            return index
    return 1


def _release_step(
    wiring: Wiring,
    *,
    run: RunRecord,
    record: StepRecord,
    label: str,
) -> None:
    """Release the step cut by a stop, returning it to pending.

    Pending makes `resume_run_id` restart from this step only; settled steps are
    not redone.
    """
    if record.release():
        wiring.runs.save(run)
        sync_steps(wiring, run)
    notify(wiring, wording.run_stopped_at(label) if label else wording.RUN_STOPPED_BY_USER)


def _session_error(error: BaseException) -> str:
    if isinstance(error, TimeoutError):
        return wording.agent_stopped_responding(str(error))
    if isinstance(error, RuntimeError | OSError):
        return wording.agent_session_dropped(str(error))
    return wording.step_crashed(f"{type(error).__name__}: {error}")
