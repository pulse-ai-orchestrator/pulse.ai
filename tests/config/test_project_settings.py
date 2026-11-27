"""Which value the settings screen shows: the agent's own, the project's, the machine's.

This used to be computed inside the screen; the daemon now decides it, so the
order of precedence is pinned here.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from pulse.config.global_config import mark_onboarding_complete
from pulse.config.project_config import init_project_config, load_project_config
from pulse.config.project_settings import (
    FALLBACK_MODEL,
    AgentField,
    AgentFields,
    SettingsOrderError,
    agent_fields,
    effective_defaults,
    project_settings,
    set_agent_field,
    set_atomic_commits,
    set_auto_pull_request,
    set_project_default,
    set_worktree,
)
from pulse.config.resolved import DEFAULT_PERMISSION_POLICY
from pulse.runtimes import DEFAULT_RUNTIME_ID
from pulse.store.workflow_defs import list_agents


def _machine(workspace: Path, *, model: str = "machine-model") -> None:
    mark_onboarding_complete(
        agent_binary="claude",
        acp_command=["claude-acp"],
        auth_method="login",
        workspace_dir=workspace,
        model=model,
        permission_policy="deny_writes",
        acp_test_passed=True,
        default_agent="claude",
    )


def test_without_any_choice_the_defaults_are_pulse_s_own(tmp_path: Path) -> None:
    assert effective_defaults(tmp_path) == AgentFields(
        DEFAULT_RUNTIME_ID, FALLBACK_MODEL, DEFAULT_PERMISSION_POLICY
    )


def test_the_project_overrides_the_machine_field_by_field(tmp_path: Path) -> None:
    _machine(tmp_path)
    init_project_config(tmp_path)

    set_project_default(tmp_path, "model", "project-model")

    assert effective_defaults(tmp_path) == AgentFields("claude", "project-model", "deny_writes")


def test_an_agent_s_own_setting_wins_over_the_project_default(tmp_path: Path) -> None:
    init_project_config(tmp_path)
    first, second = list_agents()[:2]
    set_project_default(tmp_path, "model", "everyone")

    set_agent_field(tmp_path, first.id, "model", "only-me")

    assert agent_fields(tmp_path, first.id) == AgentFields(
        DEFAULT_RUNTIME_ID, "only-me", DEFAULT_PERMISSION_POLICY
    )
    second_fields = agent_fields(tmp_path, second.id)
    assert second_fields is not None
    assert second_fields.model == "everyone"


def test_a_later_project_default_overwrites_every_agent(tmp_path: Path) -> None:
    """A point-in-time write, not a layer: setting the default again resets the agents."""
    init_project_config(tmp_path)
    first = list_agents()[0]
    set_agent_field(tmp_path, first.id, "model", "only-me")

    set_project_default(tmp_path, "model", "everyone")

    fields = agent_fields(tmp_path, first.id)
    assert fields is not None
    assert fields.model == "everyone"


def test_an_unknown_agent_has_no_fields(tmp_path: Path) -> None:
    assert agent_fields(tmp_path, "nope") is None


def test_the_settings_list_every_agent_and_the_worktree_switch(tmp_path: Path) -> None:
    init_project_config(tmp_path)

    settings = project_settings(tmp_path)

    assert [agent.id for agent in settings.agents] == [agent.id for agent in list_agents()]
    project = load_project_config(tmp_path)
    assert project is not None
    assert settings.use_worktree is project.use_worktree is False
    assert settings.atomic_commits is settings.auto_pull_request is False


def test_git_options_need_what_they_build_on_and_turn_off_what_needs_them(
    tmp_path: Path,
) -> None:
    init_project_config(tmp_path)

    with pytest.raises(SettingsOrderError):
        set_auto_pull_request(tmp_path, enabled=True)
    set_atomic_commits(tmp_path, enabled=True)
    with pytest.raises(SettingsOrderError):
        set_auto_pull_request(tmp_path, enabled=True)
    project = load_project_config(tmp_path)
    assert project is not None
    assert (project.use_worktree, project.atomic_commits, project.auto_pull_request) == (
        False,
        True,
        False,
    )

    set_worktree(tmp_path, enabled=True)
    set_atomic_commits(tmp_path, enabled=True)
    set_auto_pull_request(tmp_path, enabled=True)
    set_atomic_commits(tmp_path, enabled=False)
    project = load_project_config(tmp_path)
    assert project is not None
    assert (project.use_worktree, project.atomic_commits, project.auto_pull_request) == (
        True,
        False,
        False,
    )

    set_worktree(tmp_path, enabled=True)
    set_atomic_commits(tmp_path, enabled=True)
    set_auto_pull_request(tmp_path, enabled=True)
    set_worktree(tmp_path, enabled=False)
    project = load_project_config(tmp_path)
    assert project is not None
    assert (project.use_worktree, project.atomic_commits, project.auto_pull_request) == (
        False,
        True,
        False,
    )


def test_a_field_the_settings_do_not_know_is_refused_not_written_as_the_policy(
    tmp_path: Path,
) -> None:
    """A new field with no column of its own must fail loudly, not land in another one."""
    init_project_config(tmp_path)
    agent = list_agents()[0]
    unknown = cast(AgentField, "budget")

    with pytest.raises(AssertionError):
        set_project_default(tmp_path, unknown, "deny_writes")
    with pytest.raises(AssertionError):
        set_agent_field(tmp_path, agent.id, unknown, "deny_writes")

    assert effective_defaults(tmp_path).permission_policy == DEFAULT_PERMISSION_POLICY
    fields = agent_fields(tmp_path, agent.id)
    assert fields is not None
    assert fields.permission_policy == DEFAULT_PERMISSION_POLICY
