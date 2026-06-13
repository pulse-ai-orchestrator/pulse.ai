from __future__ import annotations

from pathlib import Path

from cursor_task.artifact_writer import ArtifactWriter
from cursor_task.executor.base import ExecutionContext
from cursor_task.executor.factory import create_executor
from cursor_task.prompt_builder import (
    augment_workflow_paths,
    build_prompt,
    build_tasks_prompt,
    build_techspec_prompt,
    resolve_prd_path,
    resolve_techspec_path,
)
from cursor_task.question_handler import QuestionHandler
from cursor_task.stream_renderer import StreamRenderer
from cursor_task.types import (
    DEFAULT_ARTIFACTS_PATH,
    RunCursorTaskOptions,
    RunCursorTaskResult,
    TaskKind,
)


def _require_project_path(project_path: str | None) -> str:
    if project_path is None or not str(project_path).strip():
        raise ValueError(
            "project_path é obrigatório; informe o caminho absoluto do repositório alvo "
            '(ex.: ./cursor-task.sh prd "minha feature" /caminho/do/projeto)'
        )
    return str(project_path).strip()


def run_cursor_task(
    prompt: str | RunCursorTaskOptions,
    project_path: str | None = None,
    output_file: str | None = None,
    **kwargs,
) -> RunCursorTaskResult:
    options = _normalize_options(prompt, project_path, output_file, kwargs)
    return _run_task(options)


def run_prd_task(
    prompt: str,
    project_path: str,
    **kwargs,
) -> RunCursorTaskResult:
    return run_cursor_task(
        prompt,
        project_path=project_path,
        task_kind="prd",
        reference=kwargs.pop("reference", "create-prd"),
        **kwargs,
    )


def run_techspec_task(
    prd_file: str,
    project_path: str,
    **kwargs,
) -> RunCursorTaskResult:
    return run_cursor_task(
        RunCursorTaskOptions(
            prompt="",
            project_path=_require_project_path(project_path),
            artifacts_path=kwargs.pop("artifacts_path", DEFAULT_ARTIFACTS_PATH),
            task_kind="techspec",
            input_file=prd_file,
            reference=kwargs.pop("reference", "create-techspec"),
            output_file=kwargs.pop("output_file", None),
            model=kwargs.pop("model", "composer-2.5"),
            executor=kwargs.pop("executor", "auto"),
            api_key=kwargs.pop("api_key", None),
            agent_bin=kwargs.pop("agent_bin", None),
        )
    )


def run_tasks_task(
    techspec_file: str,
    project_path: str,
    **kwargs,
) -> RunCursorTaskResult:
    return run_cursor_task(
        RunCursorTaskOptions(
            prompt="",
            project_path=_require_project_path(project_path),
            artifacts_path=kwargs.pop("artifacts_path", DEFAULT_ARTIFACTS_PATH),
            task_kind="tasks",
            input_file=techspec_file,
            reference=kwargs.pop("reference", "create-tasks"),
            output_file=kwargs.pop("output_file", None),
            model=kwargs.pop("model", "composer-2.5"),
            executor=kwargs.pop("executor", "auto"),
            api_key=kwargs.pop("api_key", None),
            agent_bin=kwargs.pop("agent_bin", None),
        )
    )


def _run_task(options: RunCursorTaskOptions) -> RunCursorTaskResult:
    project = Path(_require_project_path(options.project_path)).expanduser().resolve()
    artifacts = Path(options.artifacts_path).expanduser().resolve()

    if not project.exists():
        raise FileNotFoundError(
            f"project_path não encontrado: {project}; "
            "verifique se o caminho existe e está correto"
        )
    if not project.is_dir():
        raise NotADirectoryError(
            f"project_path deve ser um diretório: {project}"
        )
    if not artifacts.exists():
        raise FileNotFoundError(f"artifactsPath não encontrado: {artifacts}")
    if not artifacts.is_dir():
        raise NotADirectoryError(f"artifactsPath deve ser um diretório: {artifacts}")

    composed_prompt = _compose_prompt(options, project, artifacts)
    renderer = StreamRenderer()
    question_handler = QuestionHandler(renderer=renderer)

    destination = Path(options.output_file).expanduser().resolve() if options.output_file else None
    if destination is None and options.task_kind == "tasks" and options.input_file:
        techspec_path = resolve_techspec_path(artifacts, options.input_file)
        destination = techspec_path.parent / "_tasks.md"

    artifact_writer = ArtifactWriter(
        artifacts_path=artifacts,
        artifact_kind=options.task_kind,
        output_file=destination,
    )

    executor = create_executor(
        project_path=project,
        kind=options.executor,
        agent_bin=options.agent_bin,
        model=options.model,
        api_key=options.api_key,
    )

    artifact_labels = {"prd": "PRD", "techspec": "TechSpec", "tasks": "Tasks"}
    artifact_label = artifact_labels[options.task_kind]
    renderer.status("Inicializando agente...")
    outcome = executor.run(
        ExecutionContext(
            prompt=composed_prompt,
            renderer=renderer,
            question_handler=question_handler,
            artifact_writer=artifact_writer,
            artifact_label=artifact_label,
        )
    )

    renderer.status(f"Gerando {artifact_label}...")
    if not outcome.ready_for_artifact:
        hint = (
            "responda com aprovação (A/aprovado) ao breakdown apresentado para gerar os arquivos"
            if options.task_kind == "tasks"
            else "responda à revisão antes de gerar o arquivo"
        )
        raise RuntimeError(
            f"{artifact_label} ainda não aprovado ou não salvo pelo agente; {hint}"
        )
    saved_path, content = artifact_writer.write()
    renderer.success("Processamento concluído.")
    renderer.success(f"Arquivo gerado: {saved_path}")
    if options.task_kind == "tasks":
        task_files = artifact_writer.list_task_files()
        if task_files:
            renderer.success(f"Tasks individuais: {len(task_files)} arquivo(s) em {saved_path.parent}/")

    executor_name = executor.__class__.__name__.replace("Executor", "").lower()
    return RunCursorTaskResult(
        status=outcome.status,
        output_file=saved_path,
        artifact_content=content,
        executor_used=executor_name,
        agent_id=outcome.agent_id,
        session_id=outcome.session_id,
    )


def _compose_prompt(
    options: RunCursorTaskOptions,
    project: Path,
    artifacts: Path,
) -> str:
    if options.task_kind == "techspec":
        if not options.input_file:
            raise ValueError("informe o caminho do PRD para gerar a TechSpec")
        prd_path = resolve_prd_path(artifacts, options.input_file)
        return build_techspec_prompt(
            project_path=project,
            artifacts_path=artifacts,
            prd_path=prd_path,
            reference=options.reference,
        )
    if options.task_kind == "tasks":
        if not options.input_file:
            raise ValueError("informe o caminho do TechSpec para gerar as tasks")
        techspec_path = resolve_techspec_path(artifacts, options.input_file)
        return build_tasks_prompt(
            project_path=project,
            artifacts_path=artifacts,
            techspec_path=techspec_path,
            reference=options.reference,
        )
    if not options.prompt.strip():
        raise ValueError("prompt não pode ser vazio")
    base = build_prompt(options.prompt, options.reference)
    return augment_workflow_paths(base, project_path=project, artifacts_path=artifacts)


def _normalize_options(
    prompt: str | RunCursorTaskOptions,
    project_path: str | None,
    output_file: str | None,
    extra: dict,
) -> RunCursorTaskOptions:
    if isinstance(prompt, RunCursorTaskOptions):
        return prompt

    task_kind: TaskKind = extra.get("task_kind", "prd")
    default_references = {
        "prd": "create-prd",
        "techspec": "create-techspec",
        "tasks": "create-tasks",
    }
    default_reference = default_references.get(task_kind, "create-prd")

    return RunCursorTaskOptions(
        prompt=prompt,
        project_path=_require_project_path(project_path),
        artifacts_path=extra.get("artifacts_path", DEFAULT_ARTIFACTS_PATH),
        output_file=output_file,
        reference=extra.get("reference", default_reference),
        task_kind=task_kind,
        input_file=extra.get("input_file") or extra.get("prd_file") or extra.get("techspec_file"),
        model=extra.get("model", "composer-2.5"),
        executor=extra.get("executor", "auto"),
        api_key=extra.get("api_key"),
        agent_bin=extra.get("agent_bin"),
    )
