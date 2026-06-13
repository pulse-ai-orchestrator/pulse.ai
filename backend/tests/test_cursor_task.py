from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cursor_task.artifact_writer import ArtifactWriter
from cursor_task.executor.base import AgentProvider, ExecutionContext
from cursor_task.executor.completion import resolve_completion
from cursor_task.executor.run_continuation import resolve_finished_iteration
from cursor_task.prompt_builder import (
    build_execute_task_prompt,
    build_prompt,
    build_tasks_prompt,
    build_techspec_prompt,
    resolve_prd_path,
    resolve_reference,
    resolve_techspec_path,
)
from cursor_task.task_tracker import (
    all_tasks_completed,
    find_next_runnable,
    is_task_completed,
    parse_master_tasks,
)
from cursor_task.question_handler import QuestionHandler
from cursor_task.stream_renderer import StreamRenderer
from cursor_task.runner import _normalize_options, _require_project_path, _run_task
from cursor_task.types import (
    DEFAULT_ARTIFACTS_PATH,
    ClarifyingQuestion,
    RunCursorTaskOptions,
)


class PromptBuilderTests(unittest.TestCase):
    def test_build_prompt_includes_reference(self) -> None:
        composed = build_prompt("Criar PRD para login social", "create-prd")
        self.assertTrue(composed.startswith("@references /create-prd/SKILL.md"))
        self.assertIn("Criar PRD para login social", composed)

    def test_resolve_reference_alias(self) -> None:
        self.assertEqual(resolve_reference("create-prd"), "@references /create-prd/SKILL.md")
        self.assertEqual(resolve_reference("create-techspec"), "@references /create-techspec/SKILL.md")
        self.assertEqual(resolve_reference("create-tasks"), "@references /create-tasks/SKILL.md")
        self.assertEqual(resolve_reference("execute-task"), "@references /execute-task/SKILL.md")

    def test_build_techspec_prompt_includes_prd_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            prd_path = project / ".workflow" / "tasks" / "login" / "_prd.md"
            prd_path.parent.mkdir(parents=True)
            prd_path.write_text("# PRD\n", encoding="utf-8")
            composed = build_techspec_prompt(
                project_path=Path("/tmp/target"),
                artifacts_path=project,
                prd_path=prd_path,
            )
            self.assertIn("@references /create-techspec/SKILL.md", composed)
            self.assertIn(".workflow/tasks/login/_prd.md", composed)
            self.assertIn("/tmp/target", composed)
            self.assertIn("question-protocol.md", composed)
            self.assertIn("NÃO escreva", composed)
            self.assertNotIn("Salve o artefato final", composed)

    def test_resolve_prd_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            prd_path = project / ".workflow" / "tasks" / "login" / "_prd.md"
            prd_path.parent.mkdir(parents=True)
            prd_path.write_text("# PRD\n", encoding="utf-8")
            resolved = resolve_prd_path(project, ".workflow/tasks/login/_prd.md")
            self.assertEqual(resolved, prd_path.resolve())

    def test_build_tasks_prompt_includes_techspec_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            techspec_path = project / ".workflow" / "tasks" / "login" / "_techspec.md"
            techspec_path.parent.mkdir(parents=True)
            techspec_path.write_text("# TechSpec\n", encoding="utf-8")
            prd_path = techspec_path.parent / "_prd.md"
            prd_path.write_text("# PRD\n", encoding="utf-8")
            composed = build_tasks_prompt(
                project_path=Path("/tmp/target"),
                artifacts_path=project,
                techspec_path=techspec_path,
            )
            self.assertIn("@references /create-tasks/SKILL.md", composed)
            self.assertIn(".workflow/tasks/login/_techspec.md", composed)
            self.assertIn("/tmp/target", composed)
            self.assertIn("task-template.md", composed)
            self.assertIn("NÃO escreva", composed)
            self.assertIn("**A)** Aprovado", composed)

    def test_resolve_techspec_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            techspec_path = project / ".workflow" / "tasks" / "login" / "_techspec.md"
            techspec_path.parent.mkdir(parents=True)
            techspec_path.write_text("# TechSpec\n", encoding="utf-8")
            resolved = resolve_techspec_path(project, ".workflow/tasks/login/_techspec.md")
            self.assertEqual(resolved, techspec_path.resolve())

    def test_build_execute_task_prompt_includes_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            task_dir = project / ".workflow" / "tasks" / "login"
            task_dir.mkdir(parents=True)
            master_path = task_dir / "_tasks.md"
            master_path.write_text(
                "| # | Title | Status | Complexity | Dependencies |\n"
                "|---|-------|--------|------------|--------------|\n"
                "| 01 | Login base | pending | medium | — |\n",
                encoding="utf-8",
            )
            task_path = task_dir / "task_01.md"
            task_path.write_text("---\nstatus: pending\n---\n", encoding="utf-8")
            (task_dir / "_techspec.md").write_text("# TechSpec\n", encoding="utf-8")
            composed = build_execute_task_prompt(
                project_path=Path("/tmp/target"),
                artifacts_path=project,
                task_dir=task_dir,
                task_file=task_path,
                master_tasks_path=master_path,
                auto_commit=True,
            )
            self.assertIn("@references /execute-task/SKILL.md", composed)
            self.assertIn(".workflow/tasks/login/task_01.md", composed)
            self.assertIn("/tmp/target", composed)
            self.assertIn("Auto-commit mode: enabled", composed)
            self.assertIn("novo chat", composed)


class TaskTrackerTests(unittest.TestCase):
    def _write_master(self, task_dir: Path) -> Path:
        master_path = task_dir / "_tasks.md"
        master_path.write_text(
            "# Tasks\n\n"
            "| # | Title | Status | Complexity | Dependencies |\n"
            "|---|-------|--------|------------|--------------|\n"
            "| 01 | First | pending | medium | — |\n"
            "| 02 | Second | pending | high | task_01 |\n",
            encoding="utf-8",
        )
        return master_path

    def test_find_next_runnable_respects_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            task_dir = Path(tmp) / ".workflow" / "tasks" / "feature"
            task_dir.mkdir(parents=True)
            master_path = self._write_master(task_dir)
            (task_dir / "task_01.md").write_text("---\nstatus: pending\n---\n", encoding="utf-8")
            (task_dir / "task_02.md").write_text("---\nstatus: pending\n---\n", encoding="utf-8")

            runnable = find_next_runnable(master_path)
            self.assertIsNotNone(runnable)
            assert runnable is not None
            self.assertEqual(runnable.entry.number, "01")

    def test_is_task_completed_requires_master_and_frontmatter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            task_dir = Path(tmp) / ".workflow" / "tasks" / "feature"
            task_dir.mkdir(parents=True)
            master_path = self._write_master(task_dir)
            task_path = task_dir / "task_01.md"
            task_path.write_text("---\nstatus: completed\n---\n", encoding="utf-8")

            self.assertFalse(
                is_task_completed(
                    task_file=task_path,
                    master_tasks_file=master_path,
                    task_number="01",
                )
            )

            master_path.write_text(
                master_path.read_text(encoding="utf-8").replace(
                    "| 01 | First | pending | medium | — |",
                    "| 01 | First | completed | medium | — |",
                ),
                encoding="utf-8",
            )
            self.assertTrue(
                is_task_completed(
                    task_file=task_path,
                    master_tasks_file=master_path,
                    task_number="01",
                )
            )
            self.assertFalse(all_tasks_completed(master_path))

    def test_parse_master_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            task_dir = Path(tmp) / ".workflow" / "tasks" / "feature"
            task_dir.mkdir(parents=True)
            master_path = self._write_master(task_dir)
            entries = parse_master_tasks(master_path)
            self.assertEqual(len(entries), 2)
            self.assertEqual(entries[1].dependencies, ("01",))


class QuestionHandlerTests(unittest.TestCase):
    def test_extract_technical_clarification_question(self) -> None:
        handler = QuestionHandler()
        text = (
            "Com base no PRD e no código, preciso alinhar a abordagem.\n\n"
            "Qual estratégia de observabilidade prefere para o MVP?\n\n"
            "A) Apenas console em dev e JSON em prod\n"
            "B) Integração com Sentry desde o MVP\n"
            "C) Endpoint backend dedicado\n"
            "D) Outro — descreva\n"
        )
        question = handler.extract_pending_question(text)
        self.assertIsNotNone(question)
        assert question is not None
        self.assertEqual(len(question.options), 4)
        self.assertIn("observabilidade", question.text.lower())

    def test_extract_acp_question(self) -> None:
        handler = QuestionHandler()
        question = handler.extract_from_acp(
            {
                "title": "Escopo",
                "questions": [
                    {
                        "id": "q1",
                        "prompt": "Qual módulo priorizar?",
                        "options": [
                            {"id": "auth", "label": "Autenticação"},
                            {"id": "billing", "label": "Billing"},
                        ],
                    }
                ],
            }
        )
        self.assertIn("Qual módulo priorizar?", question.text)
        self.assertEqual(len(question.options), 2)

    def test_detect_tasks_breakdown_approval(self) -> None:
        handler = QuestionHandler()
        text = (
            "Conforme solicitado, **não gerei** `_tasks.md` nem `task_NN.md` — "
            "aguardo sua aprovação do breakdown abaixo.\n\n"
            "## Breakdown proposto (9 tasks)\n\n"
            "### Task 01 — Fundação de domínio\n\n"
            "**Próximo passo (após sua aprovação):** gerar `_tasks.md`.\n\n"
            "Responda com **aprovação**, **ajustes** ou **rejeição** com feedback."
        )
        question = handler.extract_approval_question(text)
        self.assertIsNotNone(question)
        assert question is not None
        self.assertTrue(handler.is_approval_prompt(question))
        self.assertTrue(handler.is_approval_granted("A"))
        self.assertTrue(handler.is_approval_granted("aprovado"))

    def test_detect_approval_in_long_prd(self) -> None:
        handler = QuestionHandler()
        long_prd = "# PRD\n\n" + ("## Section\nConteúdo.\n\n" * 300)
        long_prd += (
            "\nRevise o rascunho e informe:\n\n"
            "**A)** Aprovado — salvar como está\n"
            "**B)** Ajustar seções específicas\n"
        )
        question = handler.extract_pending_question(long_prd)
        self.assertIsNotNone(question)
        assert question is not None
        self.assertTrue(handler.is_approval_prompt(question))
        self.assertTrue(handler.is_approval_granted("A"))
        self.assertFalse(handler.is_approval_granted("B"))

    def test_map_answer_letter(self) -> None:
        handler = QuestionHandler()
        response = handler.format_acp_response(
            handler.extract_from_acp(
                {
                    "questions": [
                        {
                            "id": "q1",
                            "prompt": "Escolha",
                            "options": [{"id": "auth", "label": "Autenticação"}],
                        }
                    ]
                }
            ),
            "A",
        )
        self.assertEqual(response["outcome"]["answers"][0]["selectedOptionIds"], ["auth"])

    def test_extract_pending_question_strips_options_from_text(self) -> None:
        handler = QuestionHandler()
        text = (
            "Contexto anterior.\n\n"
            "**Qual opção prefere?**\n\n"
            "A) Primeira opção\n"
            "B) Segunda opção\n"
        )
        question = handler.extract_pending_question(text)
        self.assertIsNotNone(question)
        assert question is not None
        self.assertEqual(question.options, ["Primeira opção", "Segunda opção"])
        self.assertNotIn("A) Primeira", question.text)
        self.assertNotIn("B) Segunda", question.text)
        self.assertIn("Qual opção prefere?", question.text)

    def test_format_question_prompt_lists_options_once(self) -> None:
        handler = QuestionHandler()
        question = handler.extract_pending_question(
            "Escolha:\n\nA) Alpha\nB) Beta\n"
        )
        assert question is not None
        prompt = handler._format_question_prompt(question)
        self.assertEqual(prompt.count("A) Alpha"), 1)
        self.assertEqual(prompt.count("B) Beta"), 1)

    def test_prompt_user_skips_display_when_already_shown(self) -> None:
        import io

        buffer = io.StringIO()
        renderer = StreamRenderer(out=buffer)
        handler = QuestionHandler(
            input_fn=lambda _: "A",
            renderer=renderer,
        )
        question = ClarifyingQuestion(
            text="Qual opção?",
            options=["Alpha", "Beta"],
        )
        handler.prompt_user(question, display=False)
        output = buffer.getvalue()
        self.assertNotIn("[QUESTION]", output)
        self.assertNotIn("[OUTPUT]", output)
        self.assertIn("resposta do usuário: A", output)

    def test_optional_typescript_syntax_does_not_trigger_question(self) -> None:
        handler = QuestionHandler()
        text = "Estender `HttpErrorBody` com campo opcional `payload?: unknown`."
        self.assertIsNone(handler.extract_pending_question(text))


class CompletionTests(unittest.TestCase):
    def test_requires_approval_before_completion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = Path(tmp)
            spec_path = artifacts / ".workflow" / "tasks" / "login" / "_techspec.md"
            spec_path.parent.mkdir(parents=True)
            spec_path.write_text("# TechSpec\n", encoding="utf-8")
            writer = ArtifactWriter(artifacts_path=artifacts, artifact_kind="techspec")
            context = ExecutionContext(
                prompt="",
                renderer=StreamRenderer(),
                question_handler=QuestionHandler(),
                artifact_writer=writer,
                artifact_label="TechSpec",
            )
            ready, next_prompt = resolve_completion(context)
            self.assertFalse(ready)
            self.assertIsNotNone(next_prompt)

    def test_completes_after_tasks_breakdown_approval_and_save(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = Path(tmp)
            task_dir = artifacts / ".workflow" / "tasks" / "login"
            task_dir.mkdir(parents=True)
            tasks_path = task_dir / "_tasks.md"
            tasks_path.write_text("# Tasks\n", encoding="utf-8")
            (task_dir / "task_01.md").write_text("# Task 1\n", encoding="utf-8")
            writer = ArtifactWriter(
                artifacts_path=artifacts,
                artifact_kind="tasks",
                output_file=tasks_path,
            )
            writer.track_assistant_text("aguardo sua aprovação do breakdown abaixo")
            context = ExecutionContext(
                prompt="",
                renderer=StreamRenderer(),
                question_handler=QuestionHandler(),
                artifact_writer=writer,
                artifact_label="Tasks",
                awaiting_post_approval=True,
            )
            ready, next_prompt = resolve_completion(context)
            self.assertTrue(ready)
            self.assertIsNone(next_prompt)

    def test_tasks_missing_save_after_breakdown_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = Path(tmp)
            writer = ArtifactWriter(artifacts_path=artifacts, artifact_kind="tasks")
            context = ExecutionContext(
                prompt="",
                renderer=StreamRenderer(),
                question_handler=QuestionHandler(),
                artifact_writer=writer,
                artifact_label="Tasks",
                awaiting_post_approval=True,
            )
            ready, next_prompt = resolve_completion(context)
            self.assertFalse(ready)
            self.assertIsNotNone(next_prompt)
            assert next_prompt is not None
            self.assertIn("_tasks.md", next_prompt)

    def test_completes_after_approval_and_save(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = Path(tmp)
            spec_path = artifacts / ".workflow" / "tasks" / "login" / "_techspec.md"
            spec_path.parent.mkdir(parents=True)
            spec_path.write_text("# TechSpec\n", encoding="utf-8")
            writer = ArtifactWriter(artifacts_path=artifacts, artifact_kind="techspec")
            context = ExecutionContext(
                prompt="",
                renderer=StreamRenderer(),
                question_handler=QuestionHandler(),
                artifact_writer=writer,
                artifact_label="TechSpec",
                awaiting_post_approval=True,
            )
            ready, next_prompt = resolve_completion(context)
            self.assertTrue(ready)
            self.assertIsNone(next_prompt)

    def test_execute_completion_requires_tracking_updates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = Path(tmp)
            task_dir = artifacts / ".workflow" / "tasks" / "login"
            task_dir.mkdir(parents=True)
            master_path = task_dir / "_tasks.md"
            master_path.write_text(
                "| # | Title | Status | Complexity | Dependencies |\n"
                "|---|-------|--------|------------|--------------|\n"
                "| 01 | First | pending | medium | — |\n",
                encoding="utf-8",
            )
            task_path = task_dir / "task_01.md"
            task_path.write_text("---\nstatus: pending\n---\n", encoding="utf-8")
            writer = ArtifactWriter(artifacts_path=artifacts, artifact_kind="tasks")
            context = ExecutionContext(
                prompt="",
                renderer=StreamRenderer(),
                question_handler=QuestionHandler(),
                artifact_writer=writer,
                artifact_label="Task 01",
                execution_mode="execute",
                execute_task_file=task_path,
                execute_master_tasks_file=master_path,
                execute_task_number="01",
            )
            ready, next_prompt = resolve_completion(context)
            self.assertFalse(ready)
            self.assertIsNotNone(next_prompt)

    def test_execute_finished_iteration_skips_interactive_prompts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = Path(tmp)
            task_dir = artifacts / ".workflow" / "tasks" / "login"
            task_dir.mkdir(parents=True)
            master_path = task_dir / "_tasks.md"
            master_path.write_text(
                "| # | Title | Status | Complexity | Dependencies |\n"
                "|---|-------|--------|------------|--------------|\n"
                "| 01 | First | completed | medium | — |\n",
                encoding="utf-8",
            )
            task_path = task_dir / "task_01.md"
            task_path.write_text("---\nstatus: completed\n---\n", encoding="utf-8")
            writer = ArtifactWriter(artifacts_path=artifacts, artifact_kind="tasks")
            context = ExecutionContext(
                prompt="",
                renderer=StreamRenderer(),
                question_handler=QuestionHandler(),
                artifact_writer=writer,
                artifact_label="Task 01",
                execution_mode="execute",
                execute_task_file=task_path,
                execute_master_tasks_file=master_path,
                execute_task_number="01",
            )
            combined = "Implementado `payload?: unknown`.\n\nVeredito: APROVADO"
            ready, next_prompt = resolve_finished_iteration(context, combined_text=combined)
            self.assertTrue(ready)
            self.assertIsNone(next_prompt)


class ArtifactWriterTests(unittest.TestCase):
    def test_write_prd_from_disk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            prd_path = project / ".workflow" / "tasks" / "login" / "_prd.md"
            prd_path.parent.mkdir(parents=True)
            prd_path.write_text("# PRD: Login\n\n## Visão geral\n\nTeste\n", encoding="utf-8")
            writer = ArtifactWriter(artifacts_path=project, artifact_kind="prd")
            saved, content = writer.write()
            self.assertTrue(content.startswith("# PRD: Login"))
            self.assertTrue(saved.exists())

    def test_write_techspec_from_disk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            spec_path = project / ".workflow" / "tasks" / "login" / "_techspec.md"
            spec_path.parent.mkdir(parents=True)
            spec_path.write_text("# TechSpec: Login\n\n## Sumário executivo\n\nTeste\n", encoding="utf-8")
            writer = ArtifactWriter(artifacts_path=project, artifact_kind="techspec")
            saved, content = writer.write()
            self.assertTrue(content.startswith("# TechSpec: Login"))
            self.assertEqual(saved, spec_path)

    def test_write_tasks_from_disk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            task_dir = project / ".workflow" / "tasks" / "login"
            task_dir.mkdir(parents=True)
            tasks_path = task_dir / "_tasks.md"
            tasks_path.write_text("# Login — Task List\n", encoding="utf-8")
            (task_dir / "task_01.md").write_text("# Task 1\n", encoding="utf-8")
            writer = ArtifactWriter(
                artifacts_path=project,
                artifact_kind="tasks",
                output_file=tasks_path,
            )
            saved, content = writer.write()
            self.assertTrue(content.startswith("# Login — Task List"))
            self.assertEqual(saved, tasks_path)
            self.assertTrue(writer.has_artifact_on_disk())
            self.assertEqual(len(writer.list_task_files()), 1)

    def test_tasks_requires_individual_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            task_dir = project / ".workflow" / "tasks" / "login"
            task_dir.mkdir(parents=True)
            tasks_path = task_dir / "_tasks.md"
            tasks_path.write_text("# Login — Task List\n", encoding="utf-8")
            writer = ArtifactWriter(
                artifacts_path=project,
                artifact_kind="tasks",
                output_file=tasks_path,
            )
            self.assertFalse(writer.has_artifact_on_disk())

    def test_default_artifacts_path(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        self.assertEqual(Path(DEFAULT_ARTIFACTS_PATH), repo_root)


class ProjectPathValidationTests(unittest.TestCase):
    def test_require_project_path_raises_when_omitted(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            _require_project_path(None)
        self.assertIn("project_path é obrigatório", str(ctx.exception))

    def test_require_project_path_raises_when_empty(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            _require_project_path("   ")
        self.assertIn("project_path é obrigatório", str(ctx.exception))

    def test_normalize_options_raises_when_project_path_omitted(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            _normalize_options("Criar PRD", None, None, {})
        self.assertIn("project_path é obrigatório", str(ctx.exception))

    def test_run_task_raises_when_path_not_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = Path(tmp)
            options = RunCursorTaskOptions(
                prompt="Criar PRD",
                project_path=str(artifacts / "inexistente"),
                artifacts_path=str(artifacts),
            )
            with self.assertRaises(FileNotFoundError) as ctx:
                _run_task(options)
            self.assertIn("project_path não encontrado", str(ctx.exception))

    def test_run_task_raises_when_path_is_not_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = Path(tmp)
            file_path = artifacts / "arquivo.txt"
            file_path.write_text("x", encoding="utf-8")
            options = RunCursorTaskOptions(
                prompt="Criar PRD",
                project_path=str(file_path),
                artifacts_path=str(artifacts),
            )
            with self.assertRaises(NotADirectoryError) as ctx:
                _run_task(options)
            self.assertIn("project_path deve ser um diretório", str(ctx.exception))

    def test_normalize_options_accepts_valid_project_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            options = _normalize_options("Criar PRD", tmp, None, {})
            self.assertEqual(options.project_path, tmp)


class StreamRendererTests(unittest.TestCase):
    def test_renders_prefixes(self) -> None:
        import io

        buffer = io.StringIO()
        renderer = StreamRenderer(out=buffer)
        renderer.status("Inicializando")
        renderer.thinking("Analisando")
        renderer.output("Gerando")
        output = buffer.getvalue()
        self.assertIn("[STATUS]", output)
        self.assertIn("[THINKING]", output)
        self.assertIn("[OUTPUT]", output)


class ExecutorFactoryTests(unittest.TestCase):
    def test_create_executor_returns_agent_provider(self) -> None:
        from unittest.mock import patch

        from cursor_task.executor.factory import create_executor
        from cursor_task.executor.sdk_executor import SdkExecutor

        with tempfile.TemporaryDirectory() as tmp:
            with patch("cursor_task.executor.factory.sdk_available", return_value=True):
                executor = create_executor(project_path=Path(tmp), kind="sdk")
            self.assertIsInstance(executor, AgentProvider)
            self.assertIsInstance(executor, SdkExecutor)


if __name__ == "__main__":
    unittest.main()
