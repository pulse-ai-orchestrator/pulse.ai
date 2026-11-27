"""What the settings screen shows and changes for a project, decided in the daemon.

The screen asks `/api/settings`, and these functions are the only place that
knows how a project default, a machine default and an agent's own setting combine.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, assert_never, get_args

from pulse import vcs
from pulse.config.global_config import load_global_config
from pulse.config.project_config import (
    ensure_project_workflows,
    init_project_config,
    load_project_config,
    update_project_defaults,
)
from pulse.config.resolved import DEFAULT_PERMISSION_POLICY
from pulse.domain.workflow import AgentDef
from pulse.runtimes import DEFAULT_RUNTIME_ID
from pulse.store.agent_settings import (
    apply_setting_to_all_agents,
    load_agent_settings,
    upsert_agent_settings,
)
from pulse.store.workflow_defs import get_agent, list_agents

AgentField = Literal["runtime", "model", "permission_policy"]
AGENT_FIELDS: tuple[AgentField, ...] = get_args(AgentField)

# What the screen shows when neither the project nor the machine chose.
FALLBACK_MODEL = "Auto"


@dataclass(frozen=True)
class AgentFields:
    runtime: str
    model: str
    permission_policy: str

    def to_dict(self) -> dict[str, str]:
        return {
            "runtime": self.runtime,
            "model": self.model,
            "permission_policy": self.permission_policy,
        }


@dataclass(frozen=True)
class AgentSettings:
    id: str
    label: str
    fields: AgentFields


class SettingsOrderError(ValueError):
    """A flag was turned on without the flag it depends on."""


@dataclass(frozen=True)
class ProjectSettings:
    is_repo: bool
    use_worktree: bool
    atomic_commits: bool
    auto_pull_request: bool
    defaults: AgentFields
    agents: tuple[AgentSettings, ...]


def open_project(workspace: Path) -> Path:
    """Make sure the project and its workflow rows exist before anything is edited."""
    ensure_project_workflows(workspace)
    return init_project_config(workspace)


def project_settings(workspace: Path) -> ProjectSettings:
    project = load_project_config(workspace)
    defaults = effective_defaults(workspace)
    return ProjectSettings(
        is_repo=vcs.is_repo(workspace),
        use_worktree=bool(project.use_worktree) if project is not None else False,
        atomic_commits=bool(project.atomic_commits) if project is not None else False,
        auto_pull_request=bool(project.auto_pull_request) if project is not None else False,
        defaults=defaults,
        agents=tuple(
            AgentSettings(id=agent.id, label=agent.label, fields=_agent_fields(agent, workspace))
            for agent in list_agents()
        ),
    )


def effective_defaults(workspace: Path) -> AgentFields:
    """Project, else machine, else Pulse's own default."""
    project = load_project_config(workspace)
    machine = load_global_config()
    return AgentFields(
        runtime=(project and project.default_agent)
        or (machine and machine.default_agent)
        or DEFAULT_RUNTIME_ID,
        model=(project and project.model) or (machine and machine.model) or FALLBACK_MODEL,
        permission_policy=(project and project.permission_policy)
        or (machine and machine.permission_policy)
        or DEFAULT_PERMISSION_POLICY,
    )


def agent_fields(workspace: Path, agent_id: str) -> AgentFields | None:
    agent = get_agent(agent_id)
    return _agent_fields(agent, workspace) if agent is not None else None


def _agent_fields(agent: AgentDef, workspace: Path) -> AgentFields:
    """Stored values for this agent: project settings, then its definition, then the defaults.

    Full resolution is avoided because it swaps an unavailable runtime for one
    the machine has, showing a value other than what the user picked.
    """
    runtime, model, policy = agent.runtime, agent.model, agent.permission_policy
    project = load_project_config(workspace)
    if project is not None:
        stored = load_agent_settings(project.project_id, agent.id)
        runtime = str(stored.get("runtime") or runtime)
        model = str(stored.get("model") or model)
        policy = str(stored.get("permission_policy") or policy)
    fallback = effective_defaults(workspace)
    return AgentFields(
        runtime=runtime or fallback.runtime,
        model=model or fallback.model,
        permission_policy=policy or fallback.permission_policy,
    )


def set_project_default(workspace: Path, field: AgentField, value: str) -> None:
    """A project-wide value, written into every agent too.

    A point-in-time write, not a layer: a later per-agent change applies only
    to that agent.
    """
    match field:
        case "runtime":
            update_project_defaults(workspace, agent=value)
        case "model":
            update_project_defaults(workspace, model=value)
        case "permission_policy":
            update_project_defaults(workspace, permission_policy=value)
        case _:
            assert_never(field)
    project = load_project_config(workspace)
    if project is None:
        return
    apply_setting_to_all_agents(
        project.project_id,
        field=field,
        value=value,
        agent_ids=[agent.id for agent in list_agents()],
    )


def set_agent_field(workspace: Path, agent_id: str, field: AgentField, value: str) -> None:
    init_project_config(workspace)
    project = load_project_config(workspace)
    if project is None:
        return
    match field:
        case "runtime":
            upsert_agent_settings(project.project_id, agent_id, runtime=value)
        case "model":
            upsert_agent_settings(project.project_id, agent_id, model=value)
        case "permission_policy":
            upsert_agent_settings(project.project_id, agent_id, permission_policy=value)
        case _:
            assert_never(field)


def set_worktree(workspace: Path, *, enabled: bool) -> None:
    if enabled:
        update_project_defaults(workspace, use_worktree=True)
        return
    update_project_defaults(workspace, use_worktree=False, auto_pull_request=False)


def set_atomic_commits(workspace: Path, *, enabled: bool) -> None:
    if enabled:
        update_project_defaults(workspace, atomic_commits=True)
        return
    update_project_defaults(workspace, atomic_commits=False, auto_pull_request=False)


def set_auto_pull_request(workspace: Path, *, enabled: bool) -> None:
    project = load_project_config(open_project(workspace))
    ready = project is not None and project.use_worktree and project.atomic_commits
    if enabled and not ready:
        raise SettingsOrderError("a pull request requires a worktree and atomic commits")
    update_project_defaults(workspace, auto_pull_request=enabled)
