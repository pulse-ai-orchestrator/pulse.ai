from __future__ import annotations

from pathlib import Path

from cursor_task.executor.base import ExecutionContext
from cursor_task.executor.factory import create_executor
from cursor_task.prompt_builder import build_execute_task_prompt, resolve_master_tasks_path_for_execute
from cursor_task.question_handler import QuestionHandler
from cursor_task.stream_renderer import StreamRenderer
from cursor_task.runner import _require_project_path
from cursor_task.task_tracker import (
    RunnableTask,
    all_tasks_completed,
    find_next_runnable,
    is_task_completed,
)
from cursor_task.types import ExecuteTasksOptions, ExecuteTasksResult, ExecutorKind


def run_execute_tasks_loop(options: ExecuteTasksOptions) -> ExecuteTasksResult:
    project = Path(_require_project_path(options.project_path)).expanduser().resolve()
    artifacts = Path(options.artifacts_path).expanduser().resolve()
    master_path = resolve_master_tasks_path_for_execute(artifacts, options.master_tasks_file)

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

    renderer = StreamRenderer()
    executed: list[str] = []

    while True:
        if all_tasks_completed(master_path):
            renderer.success("Todas as tasks foram concluídas.")
            break

        runnable = find_next_runnable(master_path)
        if runnable is None:
            raise RuntimeError(
                "existem tasks pendentes, mas nenhuma está executável; "
                "verifique dependências ou status inconsistentes em _tasks.md"
            )

        renderer.status(
            f"Executando task {runnable.entry.number} em novo chat: {runnable.entry.title}"
        )
        _run_single_task(
            runnable=runnable,
            project=project,
            artifacts=artifacts,
            reference=options.reference,
            auto_commit=options.auto_commit,
            model=options.model,
            executor_kind=options.executor,
            api_key=options.api_key,
            agent_bin=options.agent_bin,
            renderer=renderer,
        )

        if not is_task_completed(
            task_file=runnable.task_file,
            master_tasks_file=master_path,
            task_number=runnable.entry.number,
        ):
            raise RuntimeError(
                f"task {runnable.entry.number} não foi marcada como completed "
                f"em {runnable.task_file.name} e {master_path.name}"
            )

        executed.append(runnable.entry.number)
        renderer.success(f"Task {runnable.entry.number} concluída.")

    return ExecuteTasksResult(completed_count=len(executed), executed_tasks=executed)


def _run_single_task(
    *,
    runnable: RunnableTask,
    project: Path,
    artifacts: Path,
    reference: str,
    auto_commit: bool,
    model: str,
    executor_kind: ExecutorKind,
    api_key: str | None,
    agent_bin: str | None,
    renderer: StreamRenderer,
) -> None:
    prompt = build_execute_task_prompt(
        project_path=project,
        artifacts_path=artifacts,
        task_dir=runnable.task_dir,
        task_file=runnable.task_file,
        master_tasks_path=runnable.master_tasks_file,
        auto_commit=auto_commit,
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
            artifact_writer=_noop_artifact_writer(artifacts),
            artifact_label=f"Task {runnable.entry.number}",
            execution_mode="execute",
            execute_task_file=runnable.task_file,
            execute_master_tasks_file=runnable.master_tasks_file,
            execute_task_number=runnable.entry.number,
        )
    )

    if not outcome.ready_for_artifact:
        raise RuntimeError(
            f"execução da task {runnable.entry.number} terminou sem conclusão válida"
        )


def _noop_artifact_writer(artifacts: Path):
    from cursor_task.artifact_writer import ArtifactWriter

    return ArtifactWriter(artifacts_path=artifacts, artifact_kind="tasks")
