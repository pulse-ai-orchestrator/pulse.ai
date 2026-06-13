from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from cursor_task.artifact_writer import ArtifactWriter
from cursor_task.question_handler import QuestionHandler
from cursor_task.stream_renderer import StreamRenderer

ExecutionMode = Literal["artifact", "execute", "spec"]


@dataclass
class ExecutionContext:
    prompt: str
    renderer: StreamRenderer
    question_handler: QuestionHandler
    artifact_writer: ArtifactWriter
    artifact_label: str = "PRD"
    ready_for_artifact: bool = False
    awaiting_post_approval: bool = False
    execution_mode: ExecutionMode = "artifact"
    execute_task_file: Path | None = None
    execute_master_tasks_file: Path | None = None
    execute_task_number: str | None = None
    execute_spec_status_file: Path | None = None


@dataclass
class ExecutionOutcome:
    status: str
    agent_id: str | None = None
    session_id: str | None = None
    ready_for_artifact: bool = False


class AgentProvider(ABC):
    @abstractmethod
    def run(self, context: ExecutionContext) -> ExecutionOutcome:
        raise NotImplementedError


CursorExecutor = AgentProvider
