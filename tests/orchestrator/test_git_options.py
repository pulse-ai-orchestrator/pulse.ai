"""Atomic commits, push and pull request at the end of a run that owns its branch."""

from __future__ import annotations

from pathlib import Path

from pulse.domain.git_options import GitOptions
from pulse.domain.run import RunStatus, StepRecord
from pulse.domain.task_brief import TaskBrief
from pulse.orchestrator.delivery import pull_request_body
from tests.conftest import make_workflow
from tests.fakes import FakeAgentSession
from tests.orchestrator.harness import EngineHarness, delivered_turn


def _delivered(summary: str = "feito") -> dict[str, object]:
    return {
        "stopReason": "end_turn",
        "phaseSummary": (
            f"{summary}\n\n```pulse:outcome\nstatus: done\ncommit: add email validation\n```"
        ),
    }


def _editing(harness: EngineHarness, session: FakeAgentSession):
    def before(_step_id: str) -> None:
        if session.opened_in is not None:
            harness.workspace.files[session.opened_in] = {"src/app.py": "changed"}
        return None

    return before


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


def test_a_workflow_without_a_template_gets_the_standard_body_and_the_commits():
    """An empty column is the Pulse template, with the task and the commits after it."""
    body = pull_request_body(
        "", prompt="Corrigir o login", branch="b", commits=["feat: add email validation"]
    )

    assert body.startswith("## Resumo\n")
    assert body.endswith("Corrigir o login\n\n- feat: add email validation\n")


def test_a_delivered_step_commits_only_what_changed_and_publishes_the_branch(tmp_path: Path):
    make_workflow(
        "demo",
        steps=[("implement", "Implementar")],
        requires_approval=False,
        commit_types={"implement": "feat"},
        pull_request_template=(
            "#### Descrição:\n{{prompt}}\n\n{{commits}}\n\n- [ ] Testado localmente"
        ),
    )
    harness = EngineHarness(tmp_path)
    harness.workspace = harness.workspace.__class__(tmp_path, repo=True)
    session = FakeAgentSession([_delivered()])
    session._before_turn = _editing(harness, session)

    code = harness.run(
        session,
        workflow_id="demo",
        user_prompt="Corrigir o login",
        use_worktree=True,
        atomic_commits=True,
        auto_pull_request=True,
    )

    run = harness.runs.only()
    assert code == 0
    assert run.status == RunStatus.COMPLETED
    assert run.worktree_path == ""
    assert run.branch == "corrigir-o-login"
    assert harness.workspace.committed == [
        ("corrigir-o-login", ["src/app.py"], "feat: add email validation")
    ]
    assert harness.workspace.published == ["corrigir-o-login"]
    assert harness.workspace.deleted_branches == ["corrigir-o-login"]
    assert "corrigir-o-login" not in harness.workspace.branches
    body = harness.workspace.requests[0]["body"]
    assert "#### Descrição:\nCorrigir o login" in body
    assert "- feat: add email validation" in body
    assert "- [ ] Testado localmente" in body
    assert "- [x]" not in body
    assert "commit: add email validation" in session.sent[0]


def test_without_atomic_commits_the_worktree_stays_local(tmp_path: Path):
    make_workflow("demo", steps=[("implement", "Implementar")], requires_approval=False)
    harness = EngineHarness(tmp_path)
    harness.workspace = harness.workspace.__class__(tmp_path, repo=True)
    session = FakeAgentSession([delivered_turn()])

    code = harness.run(
        session,
        workflow_id="demo",
        user_prompt="Corrigir o login",
        use_worktree=True,
    )

    run = harness.runs.only()
    assert code == 0
    assert run.worktree_path
    assert harness.workspace.published == []
    assert harness.workspace.committed == []
    assert harness.workspace.requests == []


def test_a_rejected_push_fails_the_run_and_keeps_the_worktree(tmp_path: Path):
    make_workflow(
        "demo",
        steps=[("implement", "Implementar")],
        requires_approval=False,
        commit_types={"implement": "fix"},
    )
    harness = EngineHarness(tmp_path)
    harness.workspace = harness.workspace.__class__(tmp_path, repo=True)
    harness.workspace.fail_push = True
    session = FakeAgentSession([_delivered()])
    session._before_turn = _editing(harness, session)

    code = harness.run(
        session,
        workflow_id="demo",
        user_prompt="Corrigir o login",
        use_worktree=True,
        atomic_commits=True,
    )

    run = harness.runs.only()
    assert code == 1
    assert run.status == RunStatus.FAILED
    assert run.worktree_path
    assert harness.workspace.deleted_branches == []
    assert harness.workspace.requests == []


def test_a_dirty_worktree_is_kept_after_a_successful_push(tmp_path: Path):
    make_workflow(
        "demo",
        steps=[("implement", "Implementar")],
        requires_approval=False,
        commit_types={"implement": "feat"},
    )
    harness = EngineHarness(tmp_path)
    harness.workspace = harness.workspace.__class__(tmp_path, repo=True)
    harness.workspace.dirty = True
    session = FakeAgentSession([_delivered()])
    session._before_turn = _editing(harness, session)

    code = harness.run(
        session,
        workflow_id="demo",
        user_prompt="Corrigir o login",
        use_worktree=True,
        atomic_commits=True,
        auto_pull_request=True,
    )

    run = harness.runs.only()
    assert code == 0
    assert run.worktree_path
    assert harness.workspace.published == ["corrigir-o-login"]
    assert harness.workspace.deleted_branches == []


def test_without_atomic_commits_a_commit_the_agent_made_is_not_pushed(tmp_path: Path):
    """Push sits behind Autocommit: a Worktree-only run never publishes, even when the
    agent ran `git commit` itself, and its worktree and local branch stay.
    """
    make_workflow("demo", steps=[("implement", "Implementar")], requires_approval=False)
    harness = EngineHarness(tmp_path)
    harness.workspace = harness.workspace.__class__(tmp_path, repo=True)
    session = FakeAgentSession([delivered_turn()])

    def agent_commits(_step_id: str) -> None:
        branch = harness.workspace.worktrees[session.opened_in]
        harness.workspace.log.setdefault(branch, []).append("feat: the agent committed")

    session._before_turn = agent_commits

    code = harness.run(
        session, workflow_id="demo", user_prompt="Corrigir o login", use_worktree=True
    )

    run = harness.runs.only()
    assert code == 0
    assert run.worktree_path
    assert harness.workspace.published == []
    assert harness.workspace.deleted_branches == []
    assert harness.workspace.requests == []


def test_a_path_gone_after_the_step_is_left_out_of_its_commit(tmp_path: Path):
    """A leftover file the delivering step deleted has nothing to stage; asking git to
    add it failed the whole commit and lost the step's real change.
    """
    make_workflow(
        "demo",
        steps=[("plan", "Plano"), ("implement", "Implementar")],
        requires_approval=False,
        commit_types={"implement": "feat"},
    )
    harness = EngineHarness(tmp_path)
    harness.workspace = harness.workspace.__class__(tmp_path, repo=True)
    session = FakeAgentSession([delivered_turn(), _delivered()])

    def edit(step_id: str) -> None:
        files = harness.workspace.files
        if step_id == "plan":
            files[session.opened_in] = {"scratch.txt": "notes"}
        else:
            files[session.opened_in] = {"src/app.py": "changed"}

    session._before_turn = edit

    code = harness.run(
        session,
        workflow_id="demo",
        user_prompt="Corrigir o login",
        use_worktree=True,
        atomic_commits=True,
    )

    assert code == 0
    assert harness.workspace.committed == [
        ("corrigir-o-login", ["src/app.py"], "feat: add email validation")
    ]


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
    session = FakeAgentSession([_delivered()])
    session._before_turn = _editing(harness, session)

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
    session = FakeAgentSession([_delivered()])
    session._before_turn = _editing(harness, session)

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
    from pulse.orchestrator.delivery import pull_request_title

    assert (
        pull_request_title(
            title="Corrigir o login",
            branch="corrigir-o-login",
            commits=["fix: keep the session", "feat: add email validation"],
        )
        == "feat: add email validation"
    )


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
    session = FakeAgentSession([_delivered()])
    session.pull_request_turn = {
        "stopReason": "end_turn",
        "phaseSummary": f"antes\n\n```pulse:pull-request\n{filled}```\n",
    }
    session._before_turn = _editing(harness, session)

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
    session = FakeAgentSession([_delivered()])
    session.pull_request_turn = RuntimeError("caiu")
    session._before_turn = _editing(harness, session)

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


def test_a_resumed_run_keeps_the_git_options_it_started_with(tmp_path: Path):
    """Options chosen for one run are not overwritten by the project's on resume."""
    make_workflow("demo", steps=[("implement", "Implementar")], requires_approval=False)
    harness = EngineHarness(tmp_path)
    harness.workspace = harness.workspace.__class__(tmp_path, repo=True)
    stored = harness.runs.create(
        run_id="run-1",
        workflow_id="demo",
        workspace=tmp_path,
        user_prompt="Corrigir o login",
        steps=[StepRecord(step_id="implement", position=1000, label="Implementar", agent_id="")],
        git=GitOptions(),
    )

    code = harness.run(
        FakeAgentSession([delivered_turn()]),
        workflow_id="demo",
        user_prompt="Corrigir o login",
        resume_run_id=stored.id,
        use_worktree=True,
    )

    run = harness.runs.only()
    assert code == 0
    assert run.worktree_path == ""
    assert harness.workspace.worktrees == {}


def _items_turn() -> dict[str, object]:
    return {
        "stopReason": "end_turn",
        "phaseSummary": (
            "lista\n\n```pulse:items\nT1 — Um\nT2 — Dois\n```\n\n"
            "```pulse:outcome\nstatus: done\n```"
        ),
    }


def _touch(harness: EngineHarness, session: FakeAgentSession):
    def edit(step_id: str) -> None:
        if session.opened_in is None or step_id == "plan":
            return None
        name = step_id.replace(":", "-")
        harness.workspace.files[session.opened_in] = {f"src/{name}.py": "x"}
        return None

    return edit


def test_the_draft_opens_when_the_last_fan_out_unit_finishes(tmp_path: Path):
    """Later steps still commit onto the branch; the request is not opened again."""
    make_workflow(
        "demo",
        steps=[("plan", "Planejar"), ("run", "Implementar"), ("verify", "Verificar")],
        requires_approval=False,
        fan_out=("run",),
        opens_request=("run",),
        commit_types={"run": "feat", "verify": "docs"},
    )
    harness = EngineHarness(tmp_path)
    harness.workspace = harness.workspace.__class__(tmp_path, repo=True)
    session = FakeAgentSession([_items_turn(), _delivered(), _delivered(), _delivered()])
    session._before_turn = _touch(harness, session)

    code = harness.run(
        session,
        workflow_id="demo",
        user_prompt="Corrigir o login",
        use_worktree=True,
        atomic_commits=True,
        auto_pull_request=True,
    )

    assert code == 0
    assert harness.workspace.events == [
        "commit",
        "commit",
        "publish",
        "request",
        "commit",
        "publish",
        "remove",
    ]
    assert len(harness.workspace.requests) == 1
    run = harness.runs.only()
    assert run.request_opened is True
    assert run.worktree_path == ""


def test_a_resumed_run_does_not_open_a_second_request(tmp_path: Path):
    """The draft opened with the last task stays the only one after a resume."""
    make_workflow(
        "demo",
        steps=[("implement", "Implementar"), ("verify", "Verificar")],
        requires_approval=False,
        opens_request=("implement",),
        commit_types={"implement": "feat", "verify": "docs"},
    )
    harness = EngineHarness(tmp_path)
    harness.workspace = harness.workspace.__class__(tmp_path, repo=True)
    session = FakeAgentSession([_delivered(), RuntimeError("caiu")])
    session._before_turn = _touch(harness, session)

    code = harness.run(
        session,
        workflow_id="demo",
        user_prompt="Corrigir o login",
        use_worktree=True,
        atomic_commits=True,
        auto_pull_request=True,
    )

    assert code == 1
    run_id = harness.runs.only().id
    assert harness.runs.only().request_opened is True
    assert harness.runs.only().worktree_path
    assert len(harness.workspace.requests) == 1

    resumed = FakeAgentSession([_delivered()])
    resumed._before_turn = _touch(harness, resumed)
    code = harness.run(
        resumed,
        workflow_id="demo",
        user_prompt="Corrigir o login",
        resume_run_id=run_id,
        use_worktree=True,
        atomic_commits=True,
        auto_pull_request=True,
    )

    assert code == 0
    assert harness.workspace.events.count("request") == 1
    assert harness.runs.only().worktree_path == ""


def _heal_on_verify(harness: EngineHarness, session: FakeAgentSession):
    touch = _touch(harness, session)

    def before(step_id: str) -> None:
        if step_id == "verify":
            harness.workspace.fail_push = False
            harness.workspace.fail_request = False
        return touch(step_id)

    return before


def _implement_then_verify() -> None:
    make_workflow(
        "demo",
        steps=[("implement", "Implementar"), ("verify", "Verificar")],
        requires_approval=False,
        opens_request=("implement",),
        commit_types={"implement": "feat", "verify": "docs"},
    )


def test_a_push_rejected_mid_run_warns_and_the_end_of_the_run_opens_the_draft(tmp_path: Path):
    """Only the final push decides the run: a mid-run rejection is a warning, not a failure."""
    _implement_then_verify()
    harness = EngineHarness(tmp_path)
    harness.workspace = harness.workspace.__class__(tmp_path, repo=True)
    harness.workspace.fail_push = True
    session = FakeAgentSession([_delivered(), _delivered()])
    session._before_turn = _heal_on_verify(harness, session)

    code = harness.run(
        session,
        workflow_id="demo",
        user_prompt="Corrigir o login",
        use_worktree=True,
        atomic_commits=True,
        auto_pull_request=True,
    )

    assert code == 0
    assert "Não publiquei a branch: origin rejected the push" in session.stream.messages
    assert harness.workspace.events == ["commit", "commit", "publish", "request", "remove"]
    run = harness.runs.only()
    assert run.status == RunStatus.COMPLETED
    assert run.request_opened is True


def test_a_request_refused_mid_run_is_opened_by_the_end_of_the_run(tmp_path: Path):
    """The flag stays off until a request really exists, so the end of the run retries it."""
    _implement_then_verify()
    harness = EngineHarness(tmp_path)
    harness.workspace = harness.workspace.__class__(tmp_path, repo=True)
    harness.workspace.fail_request = True
    session = FakeAgentSession([_delivered(), _delivered()])
    session._before_turn = _heal_on_verify(harness, session)
    opened_mid_run: list[bool] = []
    touch = session._before_turn

    def before(step_id: str) -> None:
        if step_id == "verify":
            opened_mid_run.append(harness.runs.only().request_opened)
        return touch(step_id)

    session._before_turn = before

    code = harness.run(
        session,
        workflow_id="demo",
        user_prompt="Corrigir o login",
        use_worktree=True,
        atomic_commits=True,
        auto_pull_request=True,
    )

    assert code == 0
    assert opened_mid_run == [False]
    assert "Não abri o pedido: gh: not installed" in session.stream.messages
    assert harness.workspace.events == [
        "commit",
        "publish",
        "commit",
        "publish",
        "request",
        "remove",
    ]
    assert len(harness.workspace.requests) == 1
    assert harness.runs.only().request_opened is True
