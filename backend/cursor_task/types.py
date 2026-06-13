from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


ExecutorKind = Literal["sdk", "acp", "stream-cli", "auto"]
TaskKind = Literal["prd", "techspec", "tasks"]
ArtifactKind = Literal["prd", "techspec", "tasks"]

_PACKAGE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARTIFACTS_PATH = str(_PACKAGE_ROOT)


@dataclass(frozen=True)
class RunCursorTaskOptions:
    prompt: str
    project_path: str
    artifacts_path: str = DEFAULT_ARTIFACTS_PATH
    output_file: str | None = None
    reference: str = "@references /create-prd/SKILL.md"
    task_kind: TaskKind = "prd"
    input_file: str | None = None
    model: str = "composer-2.5"
    executor: ExecutorKind = "auto"
    api_key: str | None = None
    agent_bin: str | None = None


@dataclass
class RunCursorTaskResult:
    status: str
    output_file: Path | None
    artifact_content: str
    executor_used: str
    agent_id: str | None = None
    session_id: str | None = None


@dataclass(frozen=True)
class ExecuteTasksOptions:
    master_tasks_file: str
    project_path: str
    artifacts_path: str = DEFAULT_ARTIFACTS_PATH
    reference: str = "execute-task"
    auto_commit: bool = False
    model: str = "composer-2.5"
    executor: ExecutorKind = "auto"
    api_key: str | None = None
    agent_bin: str | None = None


@dataclass
class ExecuteTasksResult:
    completed_count: int
    executed_tasks: list[str]


@dataclass
class ClarifyingQuestion:
    text: str
    options: list[str] = field(default_factory=list)
    allow_multiple: bool = False
    raw: dict | None = None
