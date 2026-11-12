"""Title and body of the draft pull request a run opens at its end."""

from __future__ import annotations

from pathlib import Path

import pytest

from pulse.domain.control import RUN_STOPPED
from pulse.domain.task_brief import TaskBrief
from pulse.orchestrator import wording
from pulse.orchestrator.delivery import pull_request_body, pull_request_title
from tests.conftest import make_workflow
from tests.fakes import FakeAgentSession
from tests.orchestrator.harness import EngineHarness, committing_turn, editing_a_file


def test_the_pull_request_body_renders_the_workflow_template():
    """The body is data on the workflow, so the engine knows no team's template."""
    body = pull_request_body(
        "Tarefa: {{prompt}}\nBranch {{branch}}\n{{commits}}",
        prompt="Corrigir o login",
        branch="corrigir-o-login",
        commits=["feat: add email validation", "fix: keep the session"],
    )

    assert body == (
        "Tarefa: Corrigir o login\nBranch corrigir-o-login\n"
        "- feat: add email validation\n- fix: keep the session"
    )


def test_a_workflow_without_a_template_gets_the_prompt_and_the_commits():
    """An empty column has no structure to follow; the body still says what changed."""
    body = pull_request_body(
        "", prompt="Corrigir o login", branch="b", commits=["feat: add email validation"]
    )

    assert body == "Corrigir o login\n\n- feat: add email validation"


def test_a_template_without_keys_gets_the_prompt_and_the_commits_after_it():
    body = pull_request_body(
        "## Resumo\n\n<!-- livre -->\n",
        prompt="Corrigir o login",
        branch="b",
        commits=["feat: add email validation"],
    )

    assert body == "## Resumo\n\n<!-- livre -->\n\nCorrigir o login\n\n- feat: add email validation"


def test_the_pull_request_is_titled_with_the_run_title(tmp_path: Path):
    """A Conventional Commits title the user wrote is the request title."""
    make_workflow(
        "demo",
        steps=[("implement", "Implementar")],
        requires_approval=False,
        commit_types={"implement": "feat"},
    )
    harness = EngineHarness(tmp_path)
    harness.workspace = harness.workspace.__class__(tmp_path, repo=True)
    session = FakeAgentSession([committing_turn()])
    session._before_turn = editing_a_file(harness, session)

    code = harness.run(
        session,
        workflow_id="demo",
        user_prompt="Corrigir o login\n\nerro 500",
        use_worktree=True,
        atomic_commits=True,
        auto_pull_request=True,
        branch="fix-login",
        brief=TaskBrief(title="fix: correct the login", description="erro 500"),
    )

    assert code == 0
    assert [(item["branch"], item["title"]) for item in harness.workspace.requests] == [
        ("fix-login", "fix: correct the login")
    ]


def test_a_run_without_a_title_names_its_pull_request_after_the_commit(tmp_path: Path):
    """The commit subject is already a Conventional Commits title in English."""
    make_workflow(
        "demo",
        steps=[("implement", "Implementar")],
        requires_approval=False,
        commit_types={"implement": "feat"},
    )
    harness = EngineHarness(tmp_path)
    harness.workspace = harness.workspace.__class__(tmp_path, repo=True)
    session = FakeAgentSession([committing_turn()])
    session._before_turn = editing_a_file(harness, session)

    harness.run(
        session,
        workflow_id="demo",
        user_prompt="Corrigir o login",
        use_worktree=True,
        atomic_commits=True,
        auto_pull_request=True,
    )

    assert [item["title"] for item in harness.workspace.requests] == ["feat: add email validation"]


def test_a_portuguese_run_title_yields_the_commit_subject():
    """The history keeps the user's words; the request a reviewer reads does not."""
    assert (
        pull_request_title(
            title="Corrigir o login",
            branch="corrigir-o-login",
            commits=["fix: keep the session", "feat: add email validation"],
        )
        == "feat: add email validation"
    )


@pytest.mark.parametrize(
    "subject",
    [
        "ci: create the GitHub release with its assets attached",
        "chore: add [project.urls] to pyproject.toml",
        "feat: implement T1",
        "Fix(API)!: keep `session` alive: retry once",
    ],
)
def test_any_conventional_commit_subject_titles_the_request(subject: str):
    """Conventional Commits is case-insensitive and its description is free text."""
    assert pull_request_title(title="Corrigir o login", branch="b", commits=[subject]) == subject


@pytest.mark.parametrize(
    "title",
    ["Corrigir o login", "feat:missing space", "feat: ", "wip: something", "feat: one\ntwo"],
)
def test_a_title_outside_the_convention_is_not_the_request_title(title: str):
    assert pull_request_title(title=title, branch="b", commits=[]) == (title.strip() or "b")


def test_the_agent_fills_the_project_template_and_leaves_the_workflow_one(tmp_path: Path):
    """The project file is the structure. The draft body is the markdown the agent returned."""
    filled = "## Resumo\n\nCorrige o login.\n\n## Capturas de tela\n\nN/A\n"
    make_workflow(
        "demo",
        steps=[("implement", "Implementar")],
        requires_approval=False,
        commit_types={"implement": "feat"},
        pull_request_template="#### Só o workflow\n{{prompt}}",
    )
    harness = EngineHarness(tmp_path)
    harness.workspace = harness.workspace.__class__(tmp_path, repo=True)
    harness.workspace.template_files = {
        ".github/pull_request_template.md": "## Resumo\n\n<!-- do projeto -->\n"
    }
    session = FakeAgentSession([committing_turn()])
    session.pull_request_turn = {
        "stopReason": "end_turn",
        "phaseSummary": f"antes\n\n```pulse:pull-request\n{filled}```\n",
    }
    session._before_turn = editing_a_file(harness, session)

    code = harness.run(
        session,
        workflow_id="demo",
        user_prompt="Corrigir o login",
        use_worktree=True,
        atomic_commits=True,
        auto_pull_request=True,
    )

    assert code == 0
    assert harness.workspace.requests[0]["body"] == filled.strip()
    prompt = session.sent[-1]
    assert "<!-- do projeto -->" in prompt
    assert "Só o workflow" not in prompt
    assert "Não invente captura" in prompt
    assert "Implementar:" in prompt


def test_a_missing_pull_request_block_still_opens_the_draft(tmp_path: Path):
    """The agent can fail to answer. The request still opens from the template."""
    make_workflow(
        "demo",
        steps=[("implement", "Implementar")],
        requires_approval=False,
        commit_types={"implement": "feat"},
    )
    harness = EngineHarness(tmp_path)
    harness.workspace = harness.workspace.__class__(tmp_path, repo=True)
    harness.workspace.template_files = {
        ".github/pull_request_template.md": "## Resumo\n\n<!-- vazio -->\n"
    }
    session = FakeAgentSession([committing_turn()])
    session.pull_request_turn = RuntimeError("caiu")
    session._before_turn = editing_a_file(harness, session)

    code = harness.run(
        session,
        workflow_id="demo",
        user_prompt="Corrigir o login",
        use_worktree=True,
        atomic_commits=True,
        auto_pull_request=True,
    )

    assert code == 0
    body = harness.workspace.requests[0]["body"]
    assert body.startswith("## Resumo\n\n<!-- vazio -->")
    assert "Corrigir o login" in body
    assert "- feat: add email validation" in body
    assert wording.pull_request_draft_failed("caiu") in session.stream.messages


class _StoppedWhileDescribing(FakeAgentSession):
    """The user stops the run while the agent writes the request body."""

    def draft_pull_request(self, *, prompt_text: str, **_kwargs) -> dict:
        self.sent.append(prompt_text)
        self.control.stop()
        return {"stopReason": "cancelled", "phaseSummary": ""}


def test_a_stop_during_the_request_turn_stops_the_run_without_opening_it(tmp_path: Path):
    """A stop is a stop: no draft goes out, and the worktree stays for the resume."""
    make_workflow(
        "demo",
        steps=[("implement", "Implementar")],
        requires_approval=False,
        commit_types={"implement": "feat"},
    )
    harness = EngineHarness(tmp_path)
    harness.workspace = harness.workspace.__class__(tmp_path, repo=True)
    session = _StoppedWhileDescribing([committing_turn()])
    session._before_turn = editing_a_file(harness, session)

    code = harness.run(
        session,
        workflow_id="demo",
        user_prompt="Corrigir o login",
        use_worktree=True,
        atomic_commits=True,
        auto_pull_request=True,
    )

    assert code == RUN_STOPPED
    assert harness.workspace.requests == []
    assert list(harness.workspace.worktrees.values()) == ["corrigir-o-login"]
    assert wording.RUN_STOPPED_BY_USER in session.stream.messages


def test_a_stop_before_the_request_turn_does_not_start_it(tmp_path: Path):
    """A step that opens the request mid-run, then a stop: the end of the run asks nothing."""
    make_workflow(
        "demo",
        steps=[("implement", "Implementar")],
        requires_approval=False,
        commit_types={"implement": "feat"},
        opens_request={"implement"},
    )
    harness = EngineHarness(tmp_path)
    harness.workspace = harness.workspace.__class__(tmp_path, repo=True)
    session = _StoppedWhileDescribing([committing_turn()])
    session._before_turn = editing_a_file(harness, session)

    code = harness.run(
        session,
        workflow_id="demo",
        user_prompt="Corrigir o login",
        use_worktree=True,
        atomic_commits=True,
        auto_pull_request=True,
    )

    assert code == RUN_STOPPED
    assert harness.workspace.requests == []
    assert sum("pulse:pull-request" in text for text in session.sent) == 1
