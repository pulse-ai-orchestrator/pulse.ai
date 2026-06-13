from __future__ import annotations

import os
from pathlib import Path

from cursor_task.executor.run_continuation import is_unattended_execution, resolve_finished_iteration
from cursor_task.executor.base import AgentProvider, ExecutionContext, ExecutionOutcome
from cursor_task.types import ClarifyingQuestion


class SdkExecutor(AgentProvider):
    def __init__(
        self,
        *,
        project_path: Path,
        model: str = "composer-2.5",
        api_key: str | None = None,
    ) -> None:
        self.project_path = project_path
        self.model = model
        self.api_key = api_key or os.environ.get("CURSOR_API_KEY")

    def run(self, context: ExecutionContext) -> ExecutionOutcome:
        from cursor_sdk import Agent, CursorAgentError, LocalAgentOptions

        if not self.api_key:
            raise RuntimeError("CURSOR_API_KEY não configurada")

        context.renderer.status("Inicializando agente...")
        pending_question: ClarifyingQuestion | None = None
        current_prompt = context.prompt
        agent_id: str | None = None

        try:
            with Agent.create(
                model=self.model,
                api_key=self.api_key,
                local=LocalAgentOptions(cwd=str(self.project_path)),
            ) as agent:
                agent_id = agent.agent_id

                while True:
                    context.renderer.status("Analisando projeto...")
                    run = agent.send(current_prompt)
                    pending_question = None
                    assistant_buffer = {"text": ""}

                    for message in run.messages():
                        pending_question = (
                            self._handle_message(message, context, assistant_buffer)
                            or pending_question
                        )

                    result = run.wait()

                    if pending_question:
                        if is_unattended_execution(context):
                            current_prompt = (
                                "Continue a execução da task conforme a skill execute-task. "
                                "Não solicite input do usuário."
                            )
                        else:
                            current_prompt = self._prompt_and_track(
                                context, pending_question, display=True
                            )
                        continue

                    if result.status == "error":
                        raise RuntimeError(f"execução falhou: run={run.id}")

                    if result.status == "cancelled":
                        raise RuntimeError("execução cancelada pelo agente")

                    if result.result:
                        context.artifact_writer.track_assistant_text(result.result)

                    if result.status == "finished":
                        combined = result.result or assistant_buffer["text"]
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
                    agent_id=agent_id,
                    ready_for_artifact=context.ready_for_artifact,
                )
        except CursorAgentError as error:
            raise RuntimeError(f"falha ao iniciar agente Cursor: {error.message}") from error

    def _prompt_and_track(
        self,
        context: ExecutionContext,
        question: ClarifyingQuestion,
        *,
        display: bool,
    ) -> str:
        answer = context.question_handler.prompt_user(question, display=display)
        if context.question_handler.is_approval_prompt(question):
            if context.question_handler.is_approval_granted(answer):
                context.awaiting_post_approval = True
            else:
                context.awaiting_post_approval = False
        return answer

    def _handle_message(
        self,
        message: object,
        context: ExecutionContext,
        assistant_buffer: dict[str, str],
    ) -> ClarifyingQuestion | None:
        message_type = getattr(message, "type", None) or (
            message.get("type") if isinstance(message, dict) else None
        )
        pending: ClarifyingQuestion | None = None

        if message_type == "status":
            status = getattr(message, "status", "") or ""
            detail = getattr(message, "message", "") or ""
            label = detail or status
            if label:
                context.renderer.status(label)
            return None

        if message_type == "thinking":
            text = getattr(message, "text", "") or ""
            context.renderer.thinking(text, delta=True)
            return None

        if message_type == "assistant":
            chunks: list[str] = []
            content = getattr(getattr(message, "message", None), "content", ())
            for block in content:
                block_type = getattr(block, "type", "")
                if block_type == "text":
                    text = getattr(block, "text", "") or ""
                    if text:
                        chunks.append(text)
                        context.renderer.output(text, delta=True)
                elif block_type == "tool_use":
                    name = getattr(block, "name", "") or ""
                    args = getattr(block, "input", None)
                    question = context.question_handler.extract_from_tool_call(name, args, "running")
                    if question:
                        pending = question
            combined = "".join(chunks)
            assistant_buffer["text"] += combined
            if combined:
                context.artifact_writer.track_assistant_text(combined)
            return pending

        if message_type == "tool_call":
            name = getattr(message, "name", "") or ""
            status = getattr(message, "status", "") or ""
            args = getattr(message, "args", None)
            question = context.question_handler.extract_from_tool_call(name, args, status)
            if question:
                return question
            if status == "running":
                context.renderer.status(f"Executando {name}...")
            return None

        if message_type == "task":
            text = getattr(message, "text", "") or ""
            if text:
                context.renderer.status(text)
            return None

        if message_type == "request":
            if is_unattended_execution(context):
                return None
            context.renderer.status("Aguardando entrada do usuário...")
            return ClarifyingQuestion(text="Informe sua resposta para continuar:")

        return None
