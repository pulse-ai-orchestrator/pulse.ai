from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

ExecutorKind = Literal["sdk", "acp", "stream-cli", "auto"]

_PACKAGE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARTIFACTS_PATH = str(_PACKAGE_ROOT)


@dataclass(frozen=True)
class ExecuteSpecsOptions:
    project_path: str | None = None
    artifacts_path: str = DEFAULT_ARTIFACTS_PATH
    parent_branch: str = "feat/pulse-backend"
    branch_prefix: str = "feat/pulse-specs"
    reference: str = "execute-spec"
    from_phase: int | None = None
    to_phase: int | None = None
    only: list[str] | None = None
    model: str = "composer-2.5"
    executor: ExecutorKind = "auto"
    api_key: str | None = None
    agent_bin: str | None = None
    dry_run: bool = False
    skip_pr: bool = False


@dataclass
class SpecExecutionResult:
    phase_slug: str
    branch: str
    parent_branch: str
    status_path: Path
    pr_url: str | None = None
    agent_id: str | None = None


@dataclass
class ExecuteSpecsResult:
    completed_count: int
    executed_phases: list[SpecExecutionResult]
