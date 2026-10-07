"""The orchestrator: which agent runs now, and when.

The only state machine in Pulse, agnostic of what agents do. A workflow is an
ordered list of steps from the DB ([pulse.store.workflow_defs]); for each step the
engine resolves the agent, renders `prompt_template`, opens an isolated ACP session
and records the outcome in `run_steps`.

Sessions are isolated per step on purpose: the next step only receives the summary
Pulse forwards, which allows switching runtimes between steps and redoing one step.
"""

from __future__ import annotations

import sys
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pulse import vcs
from pulse.acp.session_runner import AcpSessionRunner
from pulse.config import ResolvedConfig, resolve_config
from pulse.config.paths import worktrees_dir
from pulse.doctor.checks import check_runtime_ready
from pulse.orchestrator.cli_output import (
    print_workflow_banner,
    print_workflow_error,
    print_workflow_result,
)
from pulse.orchestrator.fanout import POSITION_STRIDE, Item, expand
from pulse.orchestrator.loops import close_loop, find_loops, repeat_loop
from pulse.orchestrator.outcome import LoopSignal, Outcome, OutcomeStatus, parse_outcome
from pulse.orchestrator.prompts import (
    build_continuation_prompt,
    build_outcome_reminder_prompt,
    build_unblock_prompt,
    guidance_block,
    outcome_protocol,
)
from pulse.orchestrator.waits import RunWaits
from pulse.ports import NullPromptPort, NullStreamSink
from pulse.prompts.approval import CANCEL, SKIP, format_summary
from pulse.prompts.permission import PermissionPolicy
from pulse.prompts.render import TemplateError, render
from pulse.runcontrol import RUN_BLOCKED, RUN_STOPPED, RunControl
from pulse.runtime.tty import is_cockpit_stream, is_interactive
from pulse.runtimes import get_runtime
from pulse.store import runs as run_store
from pulse.store.runs import (
    BLOCKED,
    DONE,
    FAILED,
    SKIPPED,
    StepRecord,
)
from pulse.store.workflow_defs import StepDef, WorkflowDef, get_agent, get_workflow

_SUCCESS_STOPS = frozenset({"end_turn", "end", "stop"})
_POLICIES: dict[str, PermissionPolicy] = {
    "ask": "ask",
    "auto_approve": "auto_approve",
    "deny_writes": "deny_writes",
}
_NEVER_INTERRUPTED = RunControl()


class UnknownWorkflow(ValueError):
    """Id that does not exist in `workflow_defs`."""


def run_workflow(
    *,
    workflow_id: str,
    user_prompt: str,
    workspace: Path | None = None,
    stream: Any | None = None,
    prompt_handler: Any | None = None,
    render_header: bool = True,
    resume_run_id: str | None = None,
    control: RunControl | None = None,
    run_id: str | None = None,
) -> int:
    cockpit = is_cockpit_stream(stream)
    if not cockpit and not is_interactive():
        print("[pulse] Workflow requer terminal interativo ou cliente Engine.", file=sys.stderr)
        return 1

    definition = get_workflow(workflow_id)
    if definition is None:
        raise UnknownWorkflow(f"workflow desconhecido: {workflow_id}")
    if not definition.steps:
        message = f"workflow `{workflow_id}` não tem step nenhum"
        if cockpit:
            raise UnknownWorkflow(message)
        print(f"[pulse] {message}", file=sys.stderr)
        return 1

    resolved = resolve_config(workspace=workspace, workflow=workflow_id)
    runtime = get_runtime(resolved.agent_name)
    blocking = check_runtime_ready(runtime.id)
    if blocking is not None:
        message = (
            f"Runtime `{runtime.id}` indisponível: {blocking.message}. "
            f"{blocking.detail or ''}".strip()
        )
        if cockpit:
            raise RuntimeError(message)
        print(f"[pulse] {message}", file=sys.stderr)
        return 1

    workspace_root = resolved.workspace_dir
    run = _resolve_run(
        definition,
        workspace_root,
        user_prompt,
        resume_run_id=resume_run_id,
        run_id=run_id,
    )

    try:
        exec_dir, branch = _prepare_workspace(run, workspace_root, resolved)
    except vcs.GitError as error:
        message = f"Não consegui abrir o worktree desta run: {error}"
        if cockpit:
            raise RuntimeError(message) from error
        print(f"[pulse] {message}", file=sys.stderr)
        return 1

    _announce_context(stream, exec_dir, branch)

    if render_header and not cockpit:
        lines = [
            f"Workspace: {exec_dir}",
            f"Run: {run.id}",
            f"Steps: {len(run.steps)}",
            f"Tarefa: {run.user_prompt.strip() or '—'}",
        ]
        if branch:
            lines.insert(1, f"Branch: {branch}")
        print_workflow_banner(title=definition.label, lines=lines)

    runner = AcpSessionRunner(
        resolved.acp_command,
        cwd=str(exec_dir),
        permission_policy=resolved.permission_policy,
        stream=stream or NullStreamSink(),
        prompt_handler=prompt_handler or NullPromptPort(),
        runtime=runtime,
        control=control,
    )
    runner.bind_run(run.id, RunWaits(run))

    try:
        return _execute(
            runner=runner,
            cockpit=cockpit,
            definition=definition,
            run=run,
            workspace=workspace_root,
            exec_dir=exec_dir,
            fallback_model=resolved.model,
        )
    except Exception as error:  # noqa: BLE001
        run.fail_running_steps()
        run.end(1)
        run_store.save(run)
        if cockpit:
            raise
        print_workflow_error(f"Falha na sessão ACP: {error}")
        return 1


def _resolve_run(
    definition: WorkflowDef,
    workspace: Path,
    user_prompt: str,
    *,
    resume_run_id: str | None,
    run_id: str | None = None,
) -> run_store.RunRecord:
    """The run in the DB. `run_id` lets the caller name it.

    The daemon passes its own id so the API and SQLite share one run id.
    """
    if resume_run_id:
        existing = run_store.load_run(resume_run_id)
        if existing is not None:
            return existing
    return run_store.create_run(
        run_id=run_id or str(uuid.uuid4()),
        workflow_id=definition.id,
        workspace=workspace,
        user_prompt=user_prompt,
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


def _prepare_workspace(
    run: run_store.RunRecord,
    workspace_root: Path,
    resolved: ResolvedConfig,
) -> tuple[Path, str]:
    """Where this run works, and on which branch.

    Four cases, in order:
    1. Resumed run with an existing worktree: reuse it.
    2. Resumed run that lost its worktree but still has its branch: reattach a
       worktree on that branch, regardless of the setting.
    3. No isolation (setting off, or not a git repo): run at the root on the
       project's current branch.
    4. Isolation on: `git worktree add` under `~/.pulse/worktrees/<run>` on a new
       branch from HEAD.

    `workspace_root` stays the run's identity (history looks it up by it); only
    where the agent writes changes.
    """
    if run.worktree_path and Path(run.worktree_path).exists():
        return Path(run.worktree_path), run.branch

    repo = vcs.repo_root(workspace_root)
    if repo is not None and _owns_branch(run) and vcs.branch_exists(repo, run.branch):
        target = worktrees_dir() / run.id
        vcs.attach_worktree(repo, target, run.branch)
        run.work_in(worktree_path=str(target), branch=run.branch)
        run_store.save(run)
        return target, run.branch

    if repo is None or not resolved.use_worktree:
        branch = vcs.current_branch(workspace_root)
        run.work_in(worktree_path="", branch=branch)
        run_store.save(run)
        return workspace_root, branch

    target = worktrees_dir() / run.id
    branch = vcs.add_worktree(repo, target, _branch_name(run))
    run.work_in(worktree_path=str(target), branch=branch)
    run_store.save(run)
    return target, branch


def _branch_name(run: run_store.RunRecord) -> str:
    """`pulse/<workflow>-<short run id>`.

    Uses the workflow name rather than the free-text task to avoid sanitizing it.
    """
    slug = "".join(char if char.isalnum() or char in "-_" else "-" for char in run.workflow_id)
    slug = slug.strip("-") or "run"
    return f"pulse/{slug}-{run.id[:8]}"


def _owns_branch(run: run_store.RunRecord) -> bool:
    """Whether the recorded branch was created by this run rather than the project's.

    Prevents reattaching e.g. `main` from the user's working tree. Only names from
    `_branch_name`, with or without the `add_worktree` suffix, count.
    """
    base = _branch_name(run)
    return run.branch == base or run.branch.startswith(f"{base}-")


def _announce_context(stream: Any | None, exec_dir: Path, branch: str) -> None:
    """Tell the UI where the run works, before any step starts.

    Must precede the first `phase.begin`: the artifact pane uses it to know which
    folder to watch.
    """
    set_context = getattr(stream, "set_context", None) if stream is not None else None
    if callable(set_context):
        set_context(cwd=str(exec_dir), branch=branch)


def _execute(
    *,
    runner: AcpSessionRunner,
    cockpit: bool,
    definition: WorkflowDef,
    run: run_store.RunRecord,
    workspace: Path,
    exec_dir: Path,
    fallback_model: str | None,
) -> int:
    runner.start()
    try:
        runner.initialize()
        runner.authenticate()
        _sync_steps(runner, run)

        loops = find_loops(definition)
        index = 0
        while index < len(definition.steps):
            definition_step = definition.steps[index]
            at = index
            index += 1
            previous = run.previous_delivery(definition_step.step_id)
            units = expand(run, definition_step, previous.summary if previous else "")
            run_store.save(run)
            _sync_steps(runner, run)

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

                if not _control(runner).checkpoint():
                    _notify(runner, "Run parada pelo usuário")
                    run.end(RUN_STOPPED)
                    run_store.save(run)
                    return RUN_STOPPED

                run.begin_step(step.step_id)
                run_store.save(run)
                opens_loop = at in loops and loops[at].start == at
                exit_code, signal = _run_step(
                    runner=runner,
                    cockpit=cockpit,
                    run=run,
                    step=step,
                    record=record,
                    workspace=workspace,
                    exec_dir=exec_dir,
                    fallback_model=fallback_model,
                    item=item,
                    may_close=opens_loop,
                )
                _sync_steps(runner, run)
                if exit_code != 0:
                    run.end(exit_code)
                    run_store.save(run)
                    return exit_code

                if signal == LoopSignal.CLOSE and opens_loop:
                    index = close_loop(run, definition, loops[at])
                    run_store.save(run)
                    _sync_steps(runner, run)
                    _notify(runner, f"{record.label}: nada a corrigir — laço encerrado")
                    break

                if signal == LoopSignal.REPEAT and at in loops and loops[at].end == at:
                    target, message = repeat_loop(run, definition, loops[at], record.label)
                    _notify(runner, message)
                    if target is not None:
                        index = target
                        run_store.save(run)
                        _sync_steps(runner, run)
                        break

        run.complete()
        run_store.save(run)
        if not cockpit:
            print_workflow_result(f"✓ {definition.label} concluído")
        return 0
    finally:
        runner.close()


def _run_step(
    *,
    runner: AcpSessionRunner,
    cockpit: bool,
    run: run_store.RunRecord,
    step: StepDef,
    record: StepRecord,
    workspace: Path,
    exec_dir: Path,
    fallback_model: str | None,
    item: Item | None = None,
    may_close: bool = False,
) -> tuple[int, LoopSignal | None]:
    """`(exit code, loop signal)`; how the step ended is in `record.status`."""
    guidance = ""
    while True:
        signal, reason = _attempt_step(
            runner=runner,
            cockpit=cockpit,
            run=run,
            step=step,
            record=record,
            workspace=workspace,
            exec_dir=exec_dir,
            fallback_model=fallback_model,
            guidance=guidance,
            item=item,
            may_close=may_close,
        )
        if record.settled:
            return 0, signal

        if _control(runner).interrupted:
            _release_step(runner, run=run, record=record, label=record.label)
            return RUN_STOPPED, None

        blocked = record.status == BLOCKED
        if blocked:
            choice, guidance = _offer_blocked(
                runner, f"{record.label} está bloqueado", reason
            )
        else:
            choice, guidance = _offer_retry(runner, f"Step {record.label} falhou", reason)
        if _control(runner).interrupted:
            _release_step(runner, run=run, record=record, label=record.label)
            return RUN_STOPPED, None

        if blocked:
            if choice == "skip":
                record.skip_blocked()
                run_store.save(run)
                _sync_steps(runner, run)
                _notify(runner, f"{record.label} pulado pelo usuário")
                return 0, None
            if choice != "retry":
                _close_after_menu(run, record)
                _notify(runner, f"Run bloqueada em {record.label}: {reason}")
                return RUN_BLOCKED, None
        elif choice != "retry":
            _close_after_menu(run, record)
            return 1, None
        _revive_session(runner)
        if guidance:
            _notify(runner, f"Refazendo {record.label} com orientação do usuário")
        else:
            _notify(runner, f"Refazendo {record.label}")


def _attempt_step(
    *,
    runner: AcpSessionRunner,
    cockpit: bool,
    run: run_store.RunRecord,
    step: StepDef,
    record: StepRecord,
    workspace: Path,
    exec_dir: Path,
    fallback_model: str | None,
    guidance: str,
    item: Item | None = None,
    may_close: bool = False,
) -> tuple[LoopSignal | None, str]:
    """`(loop signal, reason)`. How the attempt ended is the step's status;
    `reason` explains a failure or a block to the person deciding what next."""
    record.start()
    run_store.save(run)

    model, instructions = _activate_agent(runner, workspace, step, fallback_model)
    try:
        prompt_text = render(step.prompt_template, _context(run, step, exec_dir, item))
    except TemplateError as error:
        _fail(run, record)
        return None, str(error)
    if instructions:
        prompt_text = f"{instructions}\n\n---\n\n{prompt_text}"
    prompt_text += guidance_block(guidance)

    declares_outcome = step.requires_outcome and not step.requires_approval
    if declares_outcome:
        prompt_text += outcome_protocol()

    try:
        if step.requires_approval:
            result = runner.run_isolated_phase(
                workflow=run.workflow_id,
                phase_label=record.label or step.step_id,
                initial_prompt=prompt_text,
                preferred_model=model,
                build_continuation=lambda *, phase_summary, questionnaire_answers, outcome, **_: (
                    build_continuation_prompt(
                        step_id=step.step_id,
                        summary=phase_summary,
                        answers=questionnaire_answers,
                        outcome=outcome,
                    )
                ),
                phase_id=step.step_id,
            )
        else:
            result = runner.run_isolated_prompt(
                workflow=run.workflow_id,
                phase_label=record.label or step.step_id,
                prompt_text=prompt_text,
                preferred_model=model,
                phase_id=step.step_id,
                build_continuation=_unblock_continuation(step) if declares_outcome else None,
            )
    except Exception as error:  # noqa: BLE001
        _fail(run, record)
        return None, _session_error(error)

    agent_text = str(result.get("phaseSummary", ""))
    record.record_reply(
        session_id=runner.last_session_id or "", summary=format_summary(agent_text)
    )

    outcome = str(result.get("outcome", ""))
    if outcome in {CANCEL, "cancelled"} or result.get("stopReason") == "cancelled":
        _fail(run, record)
        return None, "step cancelado"

    if outcome == SKIP:
        record.skip()
        run_store.save(run)
        if not cockpit:
            print_workflow_result(f"⏭  {record.label} pulado")
        return None, ""

    if may_close and not result.get("approved") and parse_outcome(agent_text).closes:
        return _settle(run, record, cockpit, LoopSignal.CLOSE)

    if step.requires_approval and not bool(result.get("approved")):
        _fail(run, record)
        if not str(result.get("approvalAnswers", "")).strip():
            return None, "o agente encerrou sem o bloco de aprovação nem um desfecho válido"
        return None, "step não aprovado"

    if not step.requires_approval and not _prompt_succeeded(result):
        _fail(run, record)
        return None, str(result.get("stopReason") or "o agente não concluiu o step")

    repeats = False
    if declares_outcome:
        declared = parse_outcome(agent_text)
        if not declared.delivered:
            return _block(run, record, _blocked_reason(declared))
        repeats = bool(step.repeat_from) and declared.repeats
        if may_close and declared.closes:
            return _settle(run, record, cockpit, LoopSignal.CLOSE)

    return _settle(run, record, cockpit, LoopSignal.REPEAT if repeats else None)


def _settle(
    run: run_store.RunRecord, record: StepRecord, cockpit: bool, signal: LoopSignal | None
) -> tuple[LoopSignal | None, str]:
    """Record the step as delivered and pass the agent's loop signal on."""
    record.deliver()
    run_store.save(run)
    if not cockpit:
        print_workflow_result(f"✓ {record.label}")
    return signal, ""


def _unblock_continuation(step: StepDef) -> Callable[..., str]:
    """Give the agent one chance to unblock itself before involving the user.

    Runs in the same session (see `run_isolated_prompt`), once per attempt. Also
    covers a missing outcome block, usually just a forgotten declaration.
    """
    spent = False

    def build(*, result: dict[str, Any], turn: int = 0, **_kwargs: Any) -> str:
        nonlocal spent
        if spent:
            return ""
        declared = parse_outcome(str(result.get("phaseSummary", "")))
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
        return (
            "o agente encerrou sem declarar o desfecho do step — "
            "não dá para afirmar que ele entregou o que o step pede"
        )
    return declared.reason or "o agente declarou bloqueio sem dizer o motivo"


def _block(
    run: run_store.RunRecord, record: StepRecord, reason: str
) -> tuple[LoopSignal | None, str]:
    """Record the step as blocked: it ran, did not crash, did not deliver."""
    record.block()
    run_store.save(run)
    return None, reason


def _close_after_menu(run: run_store.RunRecord, record: StepRecord) -> None:
    record.close_after_wait()
    run_store.save(run)


def _fail(run: run_store.RunRecord, record: StepRecord) -> None:
    record.fail()
    run_store.save(run)


def _context(
    run: run_store.RunRecord,
    step: StepDef,
    exec_dir: Path,
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
    artifacts = [entry["path"] for entry in run_store.list_artifacts(run.id)]
    siblings = run.fan_out_siblings(step.step_id) if item is not None else []
    previous = run.previous_delivery(step.step_id)
    return {
        "user_prompt": run.user_prompt.strip(),
        "workspace": str(exec_dir),
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


def _activate_agent(
    runner: AcpSessionRunner,
    workspace: Path,
    step: StepDef,
    fallback_model: str | None,
) -> tuple[str | None, str]:
    """Apply the step agent's runtime/model/policy; return the model and instructions.

    Agent `instructions` are inlined into the prompt so they work with any runtime.
    """
    resolved = resolve_config(workspace=workspace, pulse_agent=step.agent_id)
    runner.use_agent(step.agent_id, _POLICIES.get(resolved.permission_policy, "ask"))
    definition = get_agent(step.agent_id)
    instructions = definition.instructions.strip() if definition is not None else ""
    return resolved.model or fallback_model, instructions


def _release_step(
    runner: AcpSessionRunner,
    *,
    run: run_store.RunRecord,
    record: StepRecord,
    label: str,
) -> None:
    """Release the step cut by a stop, returning it to pending.

    Pending makes `resume_run_id` restart from this step only; settled steps are
    not redone.
    """
    if record.release():
        run_store.save(run)
        _sync_steps(runner, run)
    _notify(runner, f"Run parada em {label}" if label else "Run parada pelo usuário")


def _offer_retry(runner: AcpSessionRunner, title: str, reason: str) -> tuple[str, str]:
    """Decide what to do with a failed step."""
    return _choose(
        runner,
        title,
        reason,
        [
            ("Refazer", "retry"),
            ("Outro — dizer o que fazer", "guidance"),
            ("Parar", "stop"),
        ],
    )


def _offer_blocked(runner: AcpSessionRunner, title: str, reason: str) -> tuple[str, str]:
    """Decide what to do with a step the agent could not complete.

    Adds a skip option, recorded as `skipped` rather than hidden as `done`.
    """
    return _choose(
        runner,
        title,
        reason,
        [
            ("Refazer — já resolvi", "retry"),
            ("Outro — dizer o que fazer", "guidance"),
            ("Pular este step", "skip"),
            ("Parar a run", "stop"),
        ],
    )


def _choose(
    runner: AcpSessionRunner,
    title: str,
    reason: str,
    choices: list[tuple[str, str]],
) -> tuple[str, str]:
    """Ask the user and return `(choice, guidance)`.

    "Outro" lets the user write what the agent should do. With nobody to ask
    (CLI, closed cockpit, daemon run), the answer is always stop.
    """
    handler = getattr(runner, "_prompt_handler", None)
    select = getattr(handler, "select_choice", None)
    prompt = reason.strip() or "O step não foi concluído."
    if not callable(select):
        _notify(runner, f"{title}: {prompt}")
        return "stop", ""
    choice = select(prompt, choices, title=title)
    if choice == "guidance":
        guidance = _ask_guidance(runner, title)
        if guidance:
            return "retry", guidance
        if _control(runner).interrupted:
            return "stop", ""
        return _choose(runner, title, reason, choices)
    if choice in {value for _label, value in choices}:
        return str(choice), ""
    return "stop", ""


def _session_error(error: BaseException) -> str:
    if isinstance(error, TimeoutError):
        return f"o agente parou de responder — {error}"
    if isinstance(error, RuntimeError | OSError):
        return f"a sessão do agente caiu — {error}"
    return f"o step quebrou — {type(error).__name__}: {error}"


def _revive_session(runner: AcpSessionRunner) -> None:
    """Restart the agent process before retrying the step.

    Retrying on a dead session would just fail again.
    """
    ensure = getattr(runner, "ensure_process", None)
    if not callable(ensure):
        return
    try:
        if ensure():
            _notify(runner, "Sessão do agente reiniciada")
    except (RuntimeError, TimeoutError, OSError) as error:
        _notify(runner, f"Não consegui reiniciar a sessão do agente: {error}")


def _ask_guidance(runner: AcpSessionRunner, title: str) -> str:
    handler = getattr(runner, "_prompt_handler", None)
    ask_text = getattr(handler, "ask_text", None)
    if not callable(ask_text):
        return ""
    answer = ask_text("O que o agente deve fazer nesta nova tentativa?", title=title)
    return str(answer or "").strip()


def _prompt_succeeded(result: dict[str, Any]) -> bool:
    return str(result.get("stopReason") or "") in _SUCCESS_STOPS


def _control(runner: AcpSessionRunner) -> RunControl:
    return getattr(runner, "control", None) or _NEVER_INTERRUPTED


def _notify(runner: AcpSessionRunner, message: str) -> None:
    stream = getattr(runner, "_stream", None)
    info = getattr(stream, "info", None) if stream is not None else None
    if callable(info):
        info(message)


def _sync_steps(runner: AcpSessionRunner, run: run_store.RunRecord) -> None:
    """Mirror `run_steps` to the panel, including the full step list.

    The list is sent because fan-out changes it mid-run.
    """
    stream = getattr(runner, "_stream", None)
    apply = getattr(stream, "apply_phase_statuses", None) if stream is not None else None
    if not callable(apply):
        return
    apply(
        steps=[
            {"id": item.step_id, "label": item.label, "rounds": item.rounds}
            for item in run.steps
        ],
        done_ids=[item.step_id for item in run.steps if item.status == DONE],
        skipped_ids=[item.step_id for item in run.steps if item.status == SKIPPED],
        failed_ids=[item.step_id for item in run.steps if item.status == FAILED],
        blocked_ids=[item.step_id for item in run.steps if item.status == BLOCKED],
    )
