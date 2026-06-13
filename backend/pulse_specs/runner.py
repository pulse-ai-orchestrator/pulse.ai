from __future__ import annotations

from pathlib import Path

from cursor_task.artifact_writer import ArtifactWriter
from cursor_task.executor.base import ExecutionContext
from cursor_task.executor.factory import create_executor
from cursor_task.question_handler import QuestionHandler
from cursor_task.stream_renderer import StreamRenderer
from pulse_specs.discovery import (
    SpecPhase,
    discover_phases,
    phase_branch_name,
    phases_by_number,
    resolve_initial_parent_branch,
    resolve_specs_root,
    validate_branch_namespace,
)
from pulse_specs.git_workflow import (
    GitWorkflowError,
    ensure_committed,
    prepare_phase_branch,
    push_branch,
    resolve_repo_root,
)
from pulse_specs.pr_workflow import PrWorkflowError, create_phase_pull_request
from pulse_specs.prompt import build_execute_spec_prompt
from pulse_specs.skills import resolve_applicable_skills
from pulse_specs.tracker import ensure_spec_workflow_dir, is_spec_completed, spec_status_path
from pulse_specs.types import ExecuteSpecsOptions, ExecuteSpecsResult, ExecutorKind, SpecExecutionResult


def resolve_shared_docs(specs_root: Path) -> list[Path]:
    shared_dir = specs_root / "shared"
    if not shared_dir.is_dir():
        return []
    return sorted(path for path in shared_dir.glob("*.md") if path.is_file())


def run_execute_specs_loop(options: ExecuteSpecsOptions) -> ExecuteSpecsResult:
    artifacts = Path(options.artifacts_path).expanduser().resolve()
    repo_root = resolve_repo_root(artifacts)
    project = Path(options.project_path).expanduser().resolve() if options.project_path else repo_root
    specs_root = resolve_specs_root(artifacts)

    if not project.exists():
        raise FileNotFoundError(f"projectPath não encontrado: {project}")
    if not project.is_dir():
        raise NotADirectoryError(f"projectPath deve ser um diretório: {project}")
    if not specs_root.is_dir():
        raise FileNotFoundError(f"specs não encontradas em: {specs_root}")

    validate_branch_namespace(options.parent_branch, options.branch_prefix)

    all_phases = discover_phases(specs_root)
    phase_index = phases_by_number(all_phases)
    phases = discover_phases(
        specs_root,
        from_phase=options.from_phase,
        to_phase=options.to_phase,
        only=options.only,
    )
    shared_docs = resolve_shared_docs(specs_root)
    renderer = StreamRenderer()
    executed: list[SpecExecutionResult] = []
    parent_branch = resolve_initial_parent_branch(
        options.parent_branch,
        options.branch_prefix,
        phases[0],
        phase_index,
    )

    for phase in phases:
        phase_branch = phase_branch_name(options.branch_prefix, phase)
        renderer.status(
            f"Preparando fase {phase.number}: {phase.slug} "
            f"({parent_branch} → {phase_branch})"
        )

        if options.dry_run:
            renderer.success(
                f"[dry-run] {phase.slug} | branch: {phase_branch} | base: {parent_branch}"
            )
            executed.append(
                SpecExecutionResult(
                    phase_slug=phase.slug,
                    branch=phase_branch,
                    parent_branch=parent_branch,
                    status_path=spec_status_path(artifacts, phase.slug),
                )
            )
            parent_branch = phase_branch
            continue

        try:
            prepare_phase_branch(repo_root, parent_branch, phase_branch)
        except GitWorkflowError as error:
            raise RuntimeError(f"falha ao preparar branch para {phase.slug}: {error}") from error

        renderer.status(f"Executando fase {phase.number} em novo chat: {phase.slug}")
        result = _run_single_spec(
            phase=phase,
            repo_root=repo_root,
            project=project,
            artifacts=artifacts,
            shared_docs=shared_docs,
            phase_branch=phase_branch,
            parent_branch=parent_branch,
            pr_base_branch=parent_branch,
            reference=options.reference,
            model=options.model,
            executor_kind=options.executor,
            api_key=options.api_key,
            agent_bin=options.agent_bin,
            renderer=renderer,
        )

        status_path = spec_status_path(artifacts, phase.slug)
        if not is_spec_completed(status_path):
            raise RuntimeError(
                f"fase {phase.slug} não foi marcada como completed em {status_path.name}"
            )

        commit_message = f"feat(backend/{phase.name}): implement phase {phase.number}"
        pr_url: str | None = None
        try:
            committed = ensure_committed(repo_root, commit_message)
            if committed:
                renderer.success(f"Commit de fallback criado para {phase.slug}")
            push_branch(repo_root, phase_branch)
            renderer.success(f"Branch {phase_branch} enviada para origin")
            if not options.skip_pr:
                renderer.status(f"Criando PR para {phase.slug} (base: {parent_branch})...")
                pr = create_phase_pull_request(
                    repo_root=repo_root,
                    phase=phase,
                    head_branch=phase_branch,
                    base_branch=parent_branch,
                    status_path=status_path,
                )
                pr_url = pr.url
                verb = "criado" if pr.created else "já existia"
                renderer.success(f"PR {verb}: {pr_url}")
        except (GitWorkflowError, PrWorkflowError) as error:
            raise RuntimeError(f"falha pós-execução para {phase.slug}: {error}") from error

        result.pr_url = pr_url
        executed.append(result)
        renderer.success(f"Fase {phase.slug} concluída.")
        parent_branch = phase_branch

    return ExecuteSpecsResult(completed_count=len(executed), executed_phases=executed)


def _run_single_spec(
    *,
    phase: SpecPhase,
    repo_root: Path,
    project: Path,
    artifacts: Path,
    shared_docs: list[Path],
    phase_branch: str,
    parent_branch: str,
    pr_base_branch: str,
    reference: str,
    model: str,
    executor_kind: ExecutorKind,
    api_key: str | None,
    agent_bin: str | None,
    renderer: StreamRenderer,
) -> SpecExecutionResult:
    ensure_spec_workflow_dir(artifacts, phase.slug)
    status_path = spec_status_path(artifacts, phase.slug)
    skills = resolve_applicable_skills(phase, artifacts)

    prompt = build_execute_spec_prompt(
        repo_root=repo_root,
        artifacts_path=artifacts,
        product_path=phase.product_path,
        technical_path=phase.technical_path,
        shared_docs=shared_docs,
        skills=skills,
        phase_slug=phase.slug,
        phase_branch=phase_branch,
        parent_branch=parent_branch,
        pr_base_branch=pr_base_branch,
        status_path=status_path,
        reference=reference,
    )

    question_handler = QuestionHandler(renderer=renderer)
    executor = create_executor(
        project_path=project,
        kind=executor_kind,
        agent_bin=agent_bin,
        model=model,
        api_key=api_key,
    )

    outcome = executor.run(
        ExecutionContext(
            prompt=prompt,
            renderer=renderer,
            question_handler=question_handler,
            artifact_writer=ArtifactWriter(artifacts_path=artifacts, artifact_kind="tasks"),
            artifact_label=f"Spec {phase.slug}",
            execution_mode="spec",
            execute_spec_status_file=status_path,
        )
    )

    if not outcome.ready_for_artifact:
        raise RuntimeError(f"execução da fase {phase.slug} terminou sem conclusão válida")

    return SpecExecutionResult(
        phase_slug=phase.slug,
        branch=phase_branch,
        parent_branch=parent_branch,
        status_path=status_path,
        agent_id=outcome.agent_id,
    )
