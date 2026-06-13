from __future__ import annotations

import os
import shutil
from pathlib import Path

from cursor_task.executor.acp_executor import AcpCliExecutor
from cursor_task.executor.base import AgentProvider
from cursor_task.executor.sdk_executor import SdkExecutor
from cursor_task.executor.stream_cli_executor import StreamCliExecutor
from cursor_task.types import ExecutorKind


def find_agent_binary(explicit: str | None = None) -> str | None:
    if explicit and Path(explicit).exists():
        return explicit
    for candidate in (
        explicit,
        os.environ.get("CURSOR_AGENT_BIN"),
        shutil.which("agent"),
        str(Path.home() / ".local" / "bin" / "agent"),
        "/usr/local/bin/agent",
    ):
        if candidate and Path(candidate).exists():
            return candidate
    return None


def sdk_available() -> bool:
    try:
        import cursor_sdk  # noqa: F401

        return True
    except ImportError:
        return False


def create_executor(
    *,
    project_path: Path,
    kind: ExecutorKind = "auto",
    agent_bin: str | None = None,
    model: str = "composer-2.5",
    api_key: str | None = None,
) -> AgentProvider:
    resolved_agent = find_agent_binary(agent_bin)

    if kind == "sdk":
        if not sdk_available():
            raise RuntimeError("cursor-sdk não está instalado")
        return SdkExecutor(project_path=project_path, model=model, api_key=api_key)

    if kind == "acp":
        if not resolved_agent:
            raise RuntimeError("binário 'agent' não encontrado para modo ACP")
        return AcpCliExecutor(project_path=project_path, agent_bin=resolved_agent, api_key=api_key)

    if kind == "stream-cli":
        if not resolved_agent:
            raise RuntimeError("binário 'agent' não encontrado para modo stream-cli")
        return StreamCliExecutor(
            project_path=project_path,
            agent_bin=resolved_agent,
            model=model,
            api_key=api_key,
        )

    if sdk_available():
        return SdkExecutor(project_path=project_path, model=model, api_key=api_key)
    if resolved_agent:
        return AcpCliExecutor(project_path=project_path, agent_bin=resolved_agent, api_key=api_key)
    raise RuntimeError(
        "nenhum executor disponível: instale cursor-sdk (Python >= 3.10) ou o Cursor CLI ('agent')"
    )
