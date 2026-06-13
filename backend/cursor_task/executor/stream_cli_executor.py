from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from cursor_task.executor.run_continuation import is_unattended_execution, resolve_finished_iteration
from cursor_task.executor.base import AgentProvider, ExecutionContext, ExecutionOutcome
from cursor_task.question_handler import QuestionHandler
from cursor_task.types import ClarifyingQuestion


class StreamCliExecutor(AgentProvider):
    def __init__(
        self,
        *,
        project_path: Path,
        agent_bin: str,
        model: str = "composer-2.5",
        api_key: str | None = None,
    ) -> None:
        self.project_path = project_path
        self.agent_bin = agent_bin
        self.model = model
        self.api_key = api_key or os.environ.get("CURSOR_API_KEY")

    def run(self, context: ExecutionContext) -> ExecutionOutcome:
        context.renderer.status("Inicializando agente CLI...")
        current_prompt = context.prompt
        session_id: str | None = None

        while True:
            context.renderer.status("Analisando projeto...")
            command = [
                self.agent_bin,
                "-p",
                "--output-format",
                "stream-json",
                "--stream-partial-output",
                "--model",
                self.model,
            ]
            if session_id:
                command.extend(["--resume", session_id])
            command.append(current_prompt)
            env = os.environ.copy()
            if self.api_key:
                env["CURSOR_API_KEY"] = self.api_key

            process = subprocess.Popen(
                command,
                cwd=str(self.project_path),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
            )
            assert process.stdout is not None

            assistant_segments: list[str] = []
            pending_question: ClarifyingQuestion | None = None
            final_result = ""

            for raw_line in process.stdout:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                event_type = event.get("type")
                if event.get("session_id"):
                    session_id = event["session_id"]

                if event_type == "assistant":
                    if event.get("model_call_id"):
                        continue
                    text = self._extract_assistant_text(event)
                    if not text:
                        continue
                    if event.get("timestamp_ms") is not None:
                        context.renderer.output(text, delta=True)
                    else:
                        context.renderer.output(text)
                    assistant_segments.append(text)
                    context.artifact_writer.track_assistant_text(text)
                    continue

                if event_type == "tool_call":
                    subtype = event.get("subtype")
                    tool_call = event.get("tool_call") or {}
                    if subtype == "started":
                        question = self._extract_question_from_tool_call(tool_call)
                        if question:
                            pending_question = question
                    continue

                if event_type == "result":
                    final_result = str(event.get("result") or "")
                    if event.get("is_error"):
                        raise RuntimeError(final_result or "execução CLI falhou")
                    continue

            stderr = process.stderr.read() if process.stderr else ""
            return_code = process.wait()
            if return_code != 0:
                raise RuntimeError(stderr.strip() or f"CLI encerrou com código {return_code}")

            if pending_question:
                if is_unattended_execution(context):
                    current_prompt = (
                        "Continue a execução da task conforme a skill execute-task. "
                        "Não solicite input do usuário."
                    )
                else:
                    current_prompt = self._prompt_and_track(context, pending_question, display=True)
                continue

            combined = final_result or "".join(assistant_segments)
            if final_result:
                context.artifact_writer.track_assistant_text(final_result)

            ready, next_prompt = resolve_finished_iteration(
                context,
                combined_text=combined,
            )
            if next_prompt:
                current_prompt = next_prompt
                continue
            context.ready_for_artifact = ready
            break

        return ExecutionOutcome(
            status="finished",
            session_id=session_id,
            ready_for_artifact=context.ready_for_artifact,
        )

    def _prompt_and_track(
        self,
        context: ExecutionContext,
        question: ClarifyingQuestion,
        *,
        display: bool,
    ) -> str:
        answer = context.question_handler.prompt_user(question, display=display)
        if context.question_handler.is_approval_prompt(question):
            context.awaiting_post_approval = context.question_handler.is_approval_granted(answer)
        return answer

    @staticmethod
    def _extract_assistant_text(event: dict) -> str:
        message = event.get("message") or {}
        content = message.get("content") or []
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
        return "".join(parts)

    def _extract_question_from_tool_call(self, tool_call: dict) -> ClarifyingQuestion | None:
        function = tool_call.get("function")
        if isinstance(function, dict):
            name = str(function.get("name") or "")
            arguments = function.get("arguments")
            return QuestionHandler().extract_from_tool_call(name, arguments, "running")
        serialized = json.dumps(tool_call)
        if "ask" in serialized.lower() and "question" in serialized.lower():
            return ClarifyingQuestion(text="Informe sua resposta para continuar:")
        return None
