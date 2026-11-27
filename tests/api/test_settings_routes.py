"""Setup and settings routes: what the onboarding and settings screens read and write.

The screens are thin clients now; these routes are the only path from a screen
to config, runtimes and the doctor, so their payloads and their refusals are
the contract.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pulse.api.app import create_app
from pulse.config.agents import AgentConfig
from pulse.config.global_config import GlobalConfig, load_global_config, save_global_config
from pulse.config.project_config import init_project_config, load_project_config
from pulse.daemon.runs import RunManager
from pulse.runtimes import DEFAULT_RUNTIME_ID, all_runtimes, get_runtime
from pulse.store.agent_settings import load_agent_settings
from pulse.store.workflow_defs import list_agents
from tests.infra.test_worktree import make_repo


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(RunManager()), base_url="http://127.0.0.1")


def _onboarding(workspace: Path, **overrides: object) -> dict[str, object]:
    return {
        "runtime": DEFAULT_RUNTIME_ID,
        "workspace": str(workspace),
        "model": "Auto",
        "permission_policy": "ask",
        "auth_method": "login",
        "acp_test_passed": True,
        **overrides,
    }


def test_a_fresh_machine_is_not_configured(client: TestClient, tmp_path: Path) -> None:
    setup = client.get("/api/setup", params={"workspace": str(tmp_path)}).json()

    assert setup["configured"] is False
    assert setup["onboarded"] is False
    assert setup["ready"] is False
    assert setup["permission_policies"] == ["ask", "auto_approve", "deny_writes"]


def test_onboarding_saves_the_runtime_s_own_command_and_opens_the_project(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The argv comes from the runtime registry: a request cannot pick what the daemon spawns."""
    runtime = get_runtime(DEFAULT_RUNTIME_ID)
    monkeypatch.setattr(runtime, "find_binary", lambda: "/opt/bin/agent")

    response = client.post(
        "/api/setup/onboarding", json={**_onboarding(tmp_path), "acp_command": ["rm", "-rf"]}
    )

    assert response.status_code == 200
    saved = load_global_config()
    assert saved is not None
    assert list(saved.acp_command) == list(runtime.acp_command)
    assert saved.agent_binary == "/opt/bin/agent"
    assert saved.workspace_dir == tmp_path.resolve()
    assert load_project_config(tmp_path) is not None
    setup = client.get("/api/setup", params={"workspace": str(tmp_path)}).json()
    assert (setup["configured"], setup["onboarded"], setup["ready"]) == (True, True, True)


@pytest.mark.parametrize(
    ("override", "status"),
    [({"runtime": "nope"}, 404), ({"permission_policy": "yolo"}, 422)],
)
def test_onboarding_refuses_an_unknown_runtime_or_policy(
    client: TestClient, tmp_path: Path, override: dict[str, str], status: int
) -> None:
    response = client.post("/api/setup/onboarding", json=_onboarding(tmp_path, **override))

    assert response.status_code == status
    assert load_global_config() is None


def test_settings_lists_a_runtime_saved_before_it_was_registered(
    client: TestClient, tmp_path: Path
) -> None:
    """The picker reads `/api/settings`, which used to repeat `machine_agents` as saved."""
    save_global_config(
        GlobalConfig(
            version=1,
            agent_binary="agent",
            acp_command=["agent", "acp"],
            auth_method="cursor_login",
            workspace_dir=tmp_path,
            model="Auto",
            permission_policy="ask",
            completed_at="2026-06-21T12:00:00+00:00",
            default_agent="cursor",
            agents={
                "cursor": AgentConfig(
                    name="cursor",
                    binary="custom-agent",
                    acp_command=["custom-agent", "acp"],
                    models=["Auto"],
                ),
            },
        )
    )
    init_project_config(tmp_path)

    payload = client.get("/api/settings", params={"workspace": str(tmp_path)}).json()

    runtimes = {item["id"]: item["binary"] for item in payload["runtimes"]}
    assert {runtime.id for runtime in all_runtimes()} <= set(runtimes)
    assert runtimes["codex"] == get_runtime("codex").binary
    assert runtimes["cursor"] == "custom-agent"


def test_runtimes_list_every_registered_runtime_with_its_login(client: TestClient) -> None:
    payload = client.get("/api/runtimes").json()

    assert payload["default"] == DEFAULT_RUNTIME_ID
    assert [item["id"] for item in payload["runtimes"]] == [r.id for r in all_runtimes()]
    claude = next(item for item in payload["runtimes"] if item["id"] == "claude")
    assert claude["login_command"] == list(get_runtime("claude").login_command)


def test_checks_of_an_unknown_runtime_do_not_exist(client: TestClient) -> None:
    assert client.get("/api/runtimes/nope/checks").status_code == 404


def test_models_fall_back_to_what_the_runtime_declares(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An agent that lists nothing over ACP still offers its declared models."""
    monkeypatch.setattr("pulse.api.settings_routes.collect_available_models", lambda *_a, **_k: [])

    claude = client.get("/api/models", params={"workspace": str(tmp_path), "runtime": "claude"})

    assert claude.json()["models"] == list(get_runtime("claude").default_models)


def test_a_project_default_is_written_into_every_agent(client: TestClient, tmp_path: Path) -> None:
    init_project_config(tmp_path)

    response = client.patch(
        "/api/settings/defaults",
        json={"workspace": str(tmp_path), "field": "model", "value": "model-b"},
    )

    assert response.status_code == 200
    project = load_project_config(tmp_path)
    assert project is not None
    assert project.model == "model-b"
    for agent in list_agents():
        assert load_agent_settings(project.project_id, agent.id)["model"] == "model-b"
    settings = client.get("/api/settings", params={"workspace": str(tmp_path)}).json()
    assert settings["defaults"]["model"] == "model-b"
    assert {agent["model"] for agent in settings["agents"]} == {"model-b"}


def test_an_agent_field_changes_only_that_agent(client: TestClient, tmp_path: Path) -> None:
    init_project_config(tmp_path)
    params = {"workspace": str(tmp_path)}

    def policies() -> dict[str, str]:
        agents = client.get("/api/settings", params=params).json()["agents"]
        return {agent["id"]: agent["permission_policy"] for agent in agents}

    before = policies()
    target = next(agent_id for agent_id, policy in before.items() if policy != "deny_writes")

    client.patch(
        f"/api/settings/agents/{target}",
        json={"workspace": str(tmp_path), "field": "permission_policy", "value": "deny_writes"},
    )

    assert policies() == {**before, target: "deny_writes"}


@pytest.mark.parametrize(
    ("path", "body", "status"),
    [
        ("/api/settings/agents/nope", {"field": "model", "value": "m"}, 404),
        ("/api/settings/defaults", {"field": "permission_policy", "value": "yolo"}, 422),
        ("/api/settings/defaults", {"field": "model", "value": "  "}, 422),
        ("/api/settings/defaults", {"field": "workspace_root", "value": "/"}, 422),
    ],
)
def test_a_bad_settings_write_changes_nothing(
    client: TestClient, tmp_path: Path, path: str, body: dict[str, str], status: int
) -> None:
    init_project_config(tmp_path)

    response = client.patch(path, json={"workspace": str(tmp_path), **body})

    assert response.status_code == status
    project = load_project_config(tmp_path)
    assert project is not None
    assert (project.model, project.permission_policy) == (None, None)


def test_pull_requests_follow_the_worktree_and_atomic_commits(
    client: TestClient, tmp_path: Path
) -> None:
    init_project_config(tmp_path)
    body = {"workspace": str(tmp_path)}

    def put(path: str, *, enabled: bool) -> int:
        response = client.put(path, json={**body, "enabled": enabled})
        return response.status_code

    assert put("/api/settings/pull-request", enabled=True) == 422
    assert put("/api/settings/atomic-commits", enabled=True) == 200
    assert put("/api/settings/pull-request", enabled=True) == 422

    assert put("/api/settings/worktree", enabled=True) == 200
    assert put("/api/settings/atomic-commits", enabled=True) == 200
    assert put("/api/settings/pull-request", enabled=True) == 200
    settings = client.get("/api/settings", params=body).json()
    assert settings["use_worktree"] is True
    assert settings["atomic_commits"] is True
    assert settings["auto_pull_request"] is True

    assert put("/api/settings/worktree", enabled=False) == 200
    settings = client.get("/api/settings", params=body).json()
    assert settings["use_worktree"] is False
    assert settings["atomic_commits"] is True
    assert settings["auto_pull_request"] is False
    branch = client.get("/api/git/branch", params={**body, "name": "corrigir-o-login"}).json()
    assert branch == {"valid": True, "exists": False}
    invalid = client.get("/api/git/branch", params={**body, "name": " nome"}).json()
    assert invalid["valid"] is False


def test_the_worktree_switch_is_saved_on_the_project(client: TestClient, tmp_path: Path) -> None:
    init_project_config(tmp_path)

    client.put("/api/settings/worktree", json={"workspace": str(tmp_path), "enabled": True})

    project = load_project_config(tmp_path)
    assert project is not None
    assert project.use_worktree is True
    settings = client.get("/api/settings", params={"workspace": str(tmp_path)}).json()
    assert settings["use_worktree"] is True
    assert settings["is_repo"] is False


def test_workspace_files_lists_what_git_sees_in_the_project(
    client: TestClient, tmp_path: Path
) -> None:
    repo = make_repo(tmp_path / "repo")
    (repo / "notes.md").write_text("", encoding="utf-8")

    files = client.get("/api/workspace/files", params={"workspace": str(repo)}).json()

    assert files == {"files": ["README.md"], "untracked": ["notes.md"]}


def test_workspace_files_outside_a_repository_is_an_empty_list(
    client: TestClient, tmp_path: Path
) -> None:
    files = client.get("/api/workspace/files", params={"workspace": str(tmp_path)}).json()

    assert files == {"files": [], "untracked": []}
