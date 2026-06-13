from __future__ import annotations

import json
import os
import subprocess
import threading
from pathlib import Path
from queue import Empty, Queue
from typing import Any

from cursor_task.executor.base import AgentProvider, ExecutionContext, ExecutionOutcome
from cursor_task.types import ClarifyingQuestion


class AcpCliExecutor(AgentProvider):
    def __init__(
        self,
        *,
        project_path: Path,
        agent_bin: str,
        api_key: str | None = None,
    ) -> None:
        self.project_path = project_path
        self.agent_bin = agent_bin
        self.api_key = api_key or os.environ.get("CURSOR_API_KEY")

    def run(self, context: ExecutionContext) -> ExecutionOutcome:
        context.renderer.status("Inicializando agente ACP...")
        env = os.environ.copy()
        if self.api_key:
            env["CURSOR_API_KEY"] = self.api_key

        process = subprocess.Popen(
            [self.agent_bin, "acp"],
            cwd=str(self.project_path),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env,
        )
        if process.stdin is None or process.stdout is None:
            raise RuntimeError("falha ao iniciar processo ACP")

        pending: dict[int, Queue[Any]] = {}
        next_id = 1
        lock = threading.Lock()
        session_id: str | None = None
        stop_reason = "unknown"
        pending_question: ClarifyingQuestion | None = None
        stderr_lines: list[str] = []

        def send(method: str, params: dict | None = None) -> Any:
            nonlocal next_id
            with lock:
                request_id = next_id
                next_id += 1
                queue: Queue[Any] = Queue()
                pending[request_id] = queue
            payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}
            process.stdin.write(json.dumps(payload) + "\n")
            process.stdin.flush()
            try:
                return queue.get(timeout=600)
            finally:
                pending.pop(request_id, None)

        def respond(request_id: int, result: dict) -> None:
            process.stdin.write(json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result}) + "\n")
            process.stdin.flush()

        def reader() -> None:
            nonlocal session_id, stop_reason, pending_question
            assert process.stdout is not None
            for raw_line in process.stdout:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if "id" in message and ("result" in message or "error" in message):
                    queue = pending.get(message["id"])
                    if queue is not None:
                        if "error" in message:
                            queue.put(message["error"])
                        else:
                            queue.put(message.get("result"))
                    continue

                method = message.get("method")
                params = message.get("params") or {}
                request_id = message.get("id")

                if method == "session/update":
                    update = params.get("update") or {}
                    session_update = update.get("sessionUpdate") or update.get("type")
                    content = update.get("content") or {}
                    text = content.get("text") if isinstance(content, dict) else None
                    if session_update in ("agent_message_chunk", "agent_message") and text:
                        context.renderer.output(str(text), delta=True)
                        context.artifact_writer.track_assistant_text(str(text))
                    continue

                if method == "session/request_permission" and request_id is not None:
                    respond(
                        request_id,
                        {"outcome": {"outcome": "selected", "optionId": "allow-once"}},
                    )
                    continue

                if method == "cursor/ask_question" and request_id is not None:
                    pending_question = context.question_handler.extract_from_acp(params)
                    answer = context.question_handler.prompt_user(pending_question)
                    response = context.question_handler.format_acp_response(pending_question, answer)
                    respond(request_id, response)
                    pending_question = None
                    continue

                if method == "cursor/create_plan" and request_id is not None:
                    overview = params.get("overview") or params.get("name") or "Plano gerado"
                    context.renderer.output(str(overview))
                    respond(request_id, {"outcome": {"outcome": "accepted"}})
                    continue

        stderr_thread = threading.Thread(
            target=self._consume_stderr,
            args=(process, stderr_lines),
            daemon=True,
        )
        io_thread = threading.Thread(target=reader, daemon=True)
        stderr_thread.start()
        io_thread.start()

        try:
            send(
                "initialize",
                {
                    "protocolVersion": 1,
                    "clientCapabilities": {
                        "fs": {"readTextFile": False, "writeTextFile": False},
                        "terminal": False,
                    },
                    "clientInfo": {"name": "pulse-cursor-task", "version": "0.1.0"},
                },
            )
            send("authenticate", {"methodId": "cursor_login"})
            session = send(
                "session/new",
                {"cwd": str(self.project_path), "mcpServers": []},
            )
            session_id = session.get("sessionId") if isinstance(session, dict) else None

            context.renderer.status("Gerando PRD...")
            prompt_result = send(
                "session/prompt",
                {
                    "sessionId": session_id,
                    "prompt": [{"type": "text", "text": context.prompt}],
                },
            )
            if isinstance(prompt_result, dict):
                stop_reason = str(prompt_result.get("stopReason") or "finished")
                if prompt_result.get("error"):
                    raise RuntimeError(str(prompt_result["error"]))
        finally:
            if process.stdin:
                process.stdin.close()
            process.wait(timeout=30)
            io_thread.join(timeout=2)
            stderr_thread.join(timeout=2)

        if process.returncode not in (0, None) and stop_reason != "finished":
            detail = "\n".join(stderr_lines[-5:]).strip()
            raise RuntimeError(detail or f"processo ACP encerrou com código {process.returncode}")

        return ExecutionOutcome(
            status="finished",
            session_id=session_id,
            ready_for_artifact=context.artifact_writer.has_artifact_on_disk(),
        )

    @staticmethod
    def _consume_stderr(process: subprocess.Popen[str], sink: list[str]) -> None:
        if process.stderr is None:
            return
        for line in process.stderr:
            cleaned = line.rstrip()
            if cleaned:
                sink.append(cleaned)
