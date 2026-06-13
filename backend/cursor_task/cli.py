from __future__ import annotations

import argparse
import sys

from cursor_task.execute_runner import run_execute_tasks_loop
from cursor_task.runner import run_cursor_task
from cursor_task.types import ExecuteTasksOptions


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if args and args[0] in ("prd", "techspec", "tasks", "execute"):
        return _run_subcommand(args)

    parser = argparse.ArgumentParser(description="Executa tarefas Cursor com streaming e artefato final.")
    parser.add_argument("prompt", help="Instrução principal do usuário")
    parser.add_argument(
        "project_path",
        help="Caminho absoluto do repositório alvo (obrigatório)",
    )
    parser.add_argument("--output-file", dest="output_file", default=None, help="Arquivo .md de saída")
    parser.add_argument("--reference", default="create-prd")
    parser.add_argument("--model", default="composer-2.5")
    parser.add_argument(
        "--executor",
        choices=["auto", "sdk", "acp", "stream-cli"],
        default="auto",
    )
    parser.add_argument("--agent-bin", default=None)
    parsed = parser.parse_args(args)

    return _execute(
        prompt=parsed.prompt,
        project_path=parsed.project_path,
        output_file=parsed.output_file,
        reference=parsed.reference,
        task_kind="prd",
        input_file=None,
        model=parsed.model,
        executor=parsed.executor,
        agent_bin=parsed.agent_bin,
    )


def _run_subcommand(argv: list[str]) -> int:
    command = argv[0]
    if command == "execute":
        return _run_execute_subcommand(argv[1:])

    task_kind_map = {"prd": "prd", "techspec": "techspec", "tasks": "tasks"}
    task_kind = task_kind_map[command]
    default_reference = command

    parser = argparse.ArgumentParser(description=f"Executa fluxo {command}.")
    if task_kind == "techspec":
        parser.add_argument(
            "input_file",
            help="Caminho do PRD gerado (ex.: .workflow/tasks/<slug>/_prd.md)",
        )
    elif task_kind == "tasks":
        parser.add_argument(
            "input_file",
            help="Caminho do TechSpec gerado (ex.: .workflow/tasks/<slug>/_techspec.md)",
        )
    else:
        parser.add_argument("prompt", help="Instrução principal do usuário")
    parser.add_argument(
        "project_path",
        help="Caminho absoluto do repositório alvo (obrigatório)",
    )
    parser.add_argument("--output-file", dest="output_file", default=None, help="Arquivo .md de saída")
    parser.add_argument("--reference", default=default_reference)
    parser.add_argument("--model", default="composer-2.5")
    parser.add_argument(
        "--executor",
        choices=["auto", "sdk", "acp", "stream-cli"],
        default="auto",
    )
    parser.add_argument("--agent-bin", default=None)
    parsed = parser.parse_args(argv[1:])

    return _execute(
        prompt="" if task_kind in ("techspec", "tasks") else parsed.prompt,
        project_path=parsed.project_path,
        output_file=parsed.output_file,
        reference=parsed.reference,
        task_kind=task_kind,
        input_file=parsed.input_file if task_kind in ("techspec", "tasks") else None,
        model=parsed.model,
        executor=parsed.executor,
        agent_bin=parsed.agent_bin,
    )


def _execute(
    *,
    prompt: str,
    project_path: str,
    output_file: str | None,
    reference: str,
    task_kind: str,
    input_file: str | None,
    model: str,
    executor: str,
    agent_bin: str | None,
) -> int:
    try:
        result = run_cursor_task(
            prompt=prompt,
            project_path=project_path,
            output_file=output_file,
            reference=reference,
            task_kind=task_kind,
            input_file=input_file,
            model=model,
            executor=executor,
            agent_bin=agent_bin,
        )
    except Exception as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 1

    if result.output_file:
        print(f"[SUCCESS] Arquivo gerado: {result.output_file}")
    return 0


def _run_execute_subcommand(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Executa tasks pendentes em loop, uma por chat isolado."
    )
    parser.add_argument(
        "input_file",
        help="Caminho do _tasks.md gerado (ex.: .workflow/tasks/<slug>/_tasks.md)",
    )
    parser.add_argument(
        "project_path",
        help="Caminho absoluto do repositório alvo (obrigatório)",
    )
    parser.add_argument("--reference", default="execute-task")
    parser.add_argument("--model", default="composer-2.5")
    parser.add_argument(
        "--executor",
        choices=["auto", "sdk", "acp", "stream-cli"],
        default="auto",
    )
    parser.add_argument("--agent-bin", default=None)
    parser.add_argument(
        "--auto-commit",
        action="store_true",
        help="Permite commit local automático após cada task concluída",
    )
    parsed = parser.parse_args(argv)

    try:
        result = run_execute_tasks_loop(
            ExecuteTasksOptions(
                master_tasks_file=parsed.input_file,
                project_path=parsed.project_path,
                reference=parsed.reference,
                auto_commit=parsed.auto_commit,
                model=parsed.model,
                executor=parsed.executor,
                agent_bin=parsed.agent_bin,
            )
        )
    except Exception as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 1

    print(f"[SUCCESS] {result.completed_count} task(s) executada(s): {', '.join(result.executed_tasks)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
