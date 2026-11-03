"""In-memory adapters of the engine's ports, for tests that need no database, git or agent.

Each fake keeps the promise of its port, not just its method names: the
contract tests in `tests/infra/` run the same assertions against the fake and
the production adapter.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path

from pulse.domain import run as run_model
from pulse.domain.branch_name import worktree_folders
from pulse.domain.control import RunControl
from pulse.domain.git_options import NO_GIT_OPTIONS, GitOptions
from pulse.domain.ports import (
    AgentProfile,
    JsonObject,
    NullPromptPort,
    NullStreamSink,
    PromptPort,
    UserWaitListener,
    WorkspaceError,
)
from pulse.domain.run import RunRecord, RunStatus, StepRecord, StepStatus, utc_now
from pulse.domain.task_brief import EMPTY_BRIEF, TaskBrief


class InMemoryRunRepository:
    """[pulse.domain.ports.RunRepository] in a dict.

    Stores copies, like a database would: a run changed after `save` is not
    changed in storage until the next `save`.
    """

    def __init__(self) -> None:
        self._runs: dict[str, RunRecord] = {}
        self._artifacts: dict[str, list[tuple[str, str, datetime]]] = {}
        self.saves = 0

    def create(
        self,
        *,
        run_id: str,
        workflow_id: str,
        workspace: Path,
        user_prompt: str,
        steps: Sequence[StepRecord],
        brief: TaskBrief = EMPTY_BRIEF,
        git: GitOptions = NO_GIT_OPTIONS,
    ) -> RunRecord:
        now = utc_now().isoformat()
        run = RunRecord(
            id=run_id,
            workflow_id=workflow_id,
            workspace_root=str(Path(workspace).resolve()),
            user_prompt=user_prompt,
            status=RunStatus.RUNNING,
            current_step=steps[0].step_id if steps else "",
            created_at=now,
            updated_at=now,
            title=brief.title,
            description=brief.description,
            git=git,
            steps=[
                StepRecord(
                    step_id=step.step_id,
                    position=step.position or index,
                    label=step.label,
                    agent_id=step.agent_id,
                    status=StepStatus.PENDING,
                )
                for index, step in enumerate(steps, start=1)
            ],
        )
        self._runs[run_id] = copy.deepcopy(run)
        return run

    def load(self, run_id: str) -> RunRecord | None:
        stored = self._runs.get(run_id)
        return copy.deepcopy(stored) if stored is not None else None

    def save(self, run: RunRecord) -> None:
        run.forget_removed_steps()
        self._runs[run.id] = copy.deepcopy(run)
        self.saves += 1

    def artifacts(self, run_id: str) -> list[str]:
        return list(dict.fromkeys(path for path, _step_id, _at in self._artifacts.get(run_id, [])))

    def step_artifacts(self, run_id: str, step_id: str, *, since: datetime | None) -> list[str]:
        return [
            path
            for path, writer, at in self._artifacts.get(run_id, [])
            if writer == step_id and (since is None or at >= since)
        ]

    def add_artifact(self, run_id: str, path: str, *, step_id: str = "") -> None:
        """What the session runner does when an agent writes a file.

        One entry per path and step, as the `(run_id, path, step_id)` key does in
        the database; writing it again moves it to its latest write.
        """
        entries = self._artifacts.setdefault(run_id, [])
        entries[:] = [entry for entry in entries if entry[:2] != (path, step_id)]
        entries.append((path, step_id, run_model.utc_now()))

    def ids(self) -> list[str]:
        return list(self._runs)

    def only(self) -> RunRecord:
        """The single stored run, as the database would return it."""
        (run,) = self._runs.values()
        return copy.deepcopy(run)


class FakeWorkspace:
    """[pulse.domain.ports.Workspace] with branches and worktrees in memory, no git."""

    def __init__(self, root: Path, *, repo: bool = True, branch: str = "main") -> None:
        self._root = root
        self._repo = repo
        self._branch = branch if repo else ""
        self.branches: set[str] = {branch} if repo else set()
        self.worktrees: dict[Path, str] = {}
        self.files: dict[Path, dict[str, str]] = {}
        self.bases: dict[str, str] = {}
        self.log: dict[str, list[str]] = {}
        self.published: list[str] = []
        self.requests: list[dict[str, str]] = []
        self.deleted_branches: list[str] = []
        self.committed: list[tuple[str, list[str], str]] = []
        self.fail_push = False
        self.fail_request = False
        self.dirty = False

    @property
    def root(self) -> Path:
        return self._root

    def is_repo(self) -> bool:
        return self._repo

    def current_branch(self) -> str:
        return self._branch

    def has_branch(self, branch: str) -> bool:
        return branch in self.branches

    def worktree_exists(self, path: str) -> bool:
        return bool(path) and Path(path) in self.worktrees

    def attach_worktree(self, run_id: str, branch: str) -> Path:
        if not self.has_branch(branch):
            raise WorkspaceError(f"branch {branch} does not exist")
        target = self._target(run_id, branch)
        self.worktrees[target] = branch
        return target

    def add_worktree(self, run_id: str, branch: str) -> tuple[Path, str]:
        if not self._repo:
            raise WorkspaceError(f"{self._root} is not a repository")
        if branch in self.branches:
            raise WorkspaceError(f"branch `{branch}` already exists")
        self.branches.add(branch)
        self.bases[branch] = f"base-{branch}"
        self.log[branch] = []
        target = self._target(run_id, branch)
        self.worktrees[target] = branch
        return target, branch

    def head(self, cwd: Path) -> str:
        branch = self.worktrees.get(Path(cwd), "")
        return self.bases.get(branch, "")

    def snapshot(self, cwd: Path) -> dict[str, str]:
        return dict(self.files.get(Path(cwd), {}))

    def commit(self, cwd: Path, paths: list[str], message: str) -> None:
        branch = self.worktrees.get(Path(cwd))
        if branch is None:
            raise WorkspaceError(f"{cwd} is not a worktree")
        self.log.setdefault(branch, []).append(message)
        self.committed.append((branch, list(paths), message))

    def commits_after(self, cwd: Path, base: str) -> list[str]:
        branch = self.worktrees.get(Path(cwd))
        if branch is None or self.bases.get(branch) != base:
            return []
        return list(self.log.get(branch, []))

    def publish_branch(self, branch: str) -> None:
        if self.fail_push:
            raise WorkspaceError("origin rejected the push")
        self.published.append(branch)

    def remove_worktree(self, path: Path) -> None:
        if self.dirty:
            raise WorkspaceError("worktree has uncommitted changes")
        self.worktrees.pop(Path(path), None)

    def delete_local_branch(self, branch: str) -> None:
        if branch not in self.branches:
            raise WorkspaceError(f"branch `{branch}` is not merged")
        self.branches.discard(branch)
        self.deleted_branches.append(branch)

    def open_pull_request(self, *, branch: str, title: str, body: str) -> None:
        if self.fail_request:
            raise WorkspaceError("gh: not installed")
        self.requests.append({"branch": branch, "title": title, "body": body})

    def lose_worktree(self, path: Path) -> None:
        """The user deleted the folder; the branch stays."""
        del self.worktrees[path]

    def _target(self, run_id: str, branch: str) -> Path:
        folder, fallback = worktree_folders(branch, run_id)
        worktrees = self._root.parent / "worktrees"
        target = worktrees / folder
        return worktrees / fallback if target in self.worktrees else target


class FixedAgentProfiles:
    """[pulse.domain.ports.AgentProfiles] answering the same model and policy for every agent."""

    def __init__(
        self,
        *,
        model: str | None = "auto",
        policy: str = "ask",
        instructions: dict[str, str] | None = None,
    ) -> None:
        self._model = model
        self._policy = policy
        self._instructions = instructions or {}

    def profile(self, agent_id: str) -> AgentProfile:
        return AgentProfile(
            agent_id=agent_id,
            model=self._model,
            permission_policy=self._policy,
            instructions=self._instructions.get(agent_id, ""),
        )


class RecordingStream(NullStreamSink):
    """[pulse.domain.ports.StreamSink] that keeps what the engine showed."""

    def __init__(self) -> None:
        super().__init__()
        self.phases: list[str] = []
        self.turns: list[int] = []
        self.models: list[str] = []
        self.messages: list[str] = []
        self.statuses: list[dict] = []
        self.contexts: list[tuple[str, str]] = []

    def set_context(self, *, cwd: str, branch: str) -> None:
        self.contexts.append((cwd, branch))

    def begin_phase(self, title: str, *, turn: int = 1) -> None:
        self.phases.append(title)
        self.turns.append(turn)

    def info(self, title: str) -> None:
        self.messages.append(title)

    def set_model(self, model: str) -> None:
        self.models.append(model)

    def error(self, title: str, reason: str = "") -> None:
        self.messages.append(title)

    def apply_phase_statuses(self, **kwargs) -> None:
        self.statuses.append(kwargs)


class ScriptedPrompts(NullPromptPort):
    """[pulse.domain.ports.PromptPort] answering every menu with the same choice."""

    def __init__(self, choice: str = "stop") -> None:
        self.choice = choice
        self.asked: list[str] = []
        self.prompts: list[str] = []

    def select_choice(self, prompt, choices, *, title=""):
        self.asked.append(title)
        self.prompts.append(prompt)
        return self.choice

    def ask_text(self, prompt, *, title=""):
        return ""


class RecordingSessionLog:
    """[pulse.domain.ports.SessionLog] keeping every call the runner made, in order."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def bind_run(self, run_id: str) -> None:
        self.calls.append(("bind_run", (run_id,)))

    def enter_step(self, step_id: str) -> None:
        self.calls.append(("enter_step", (step_id,)))

    def enter_session(
        self, session_id: str, *, pulse_session_id: str, cwd: str, agent_id: str | None
    ) -> None:
        self.calls.append(("enter_session", (session_id, cwd, agent_id)))

    def update(self, params: JsonObject) -> None:
        self.calls.append(("update", (params,)))

    def phase(self, label: str, *, turn: int = 1) -> None:
        self.calls.append(("phase", (label, turn)))

    def dialog(
        self, name: str, args: tuple[object, ...], kwargs: dict[str, object], result: object
    ) -> None:
        self.calls.append(("dialog", (name, result)))

    def notice(self, title: str, detail: str) -> None:
        self.calls.append(("notice", (title, detail)))

    def flush(self) -> None:
        self.calls.append(("flush", ()))

    def named(self, name: str) -> list[tuple[object, ...]]:
        return [args for call, args in self.calls if call == name]


class FakeQuestionChannel:
    """[pulse.domain.ports.QuestionChannel] that hands out a fixed MCP server entry."""

    SERVER: JsonObject = {"type": "http", "name": "fake-ask", "url": "http://127.0.0.1:1/mcp"}

    def __init__(self) -> None:
        self.opened = 0
        self.closed = 0
        self.prompts: PromptPort | None = None
        self.on_question: Callable[[], None] | None = None

    def open(self, prompts: PromptPort, on_question: Callable[[], None]) -> list[JsonObject]:
        self.opened += 1
        self.prompts = prompts
        self.on_question = on_question
        return [dict(self.SERVER)]

    def close(self) -> None:
        self.closed += 1


Turn = dict | BaseException
BeforeTurn = Callable[[str], dict | None]


class FakeAgentSession:
    """[pulse.domain.ports.AgentSession] replaying scripted agent turns.

    Each turn pops the next result (or raises it, as a crashed session would);
    `before_turn(step_id)` may answer a turn itself, which is how a test acts
    at a precise point of the run.
    """

    def __init__(
        self,
        results: list[Turn],
        *,
        control: RunControl | None = None,
        before_turn: BeforeTurn | None = None,
    ) -> None:
        self._results = list(results)
        self._before_turn = before_turn
        self.control = control or RunControl()
        self.stream = RecordingStream()
        self.prompts: PromptPort = ScriptedPrompts()
        self.last_session_id = "sess-1"
        self.last_answer_rounds: tuple[str, ...] = ()
        self.run_id = ""
        self.opened_in: Path | None = None
        self.sent: list[str] = []
        self.agents: list[str] = []
        self.models: list[str | None] = []
        self.closed = False
        self.revivals = 0

    def bind_run(self, run_id: str, waits: UserWaitListener) -> None:
        self.run_id = run_id

    def open(self, cwd: Path) -> None:
        self.opened_in = cwd

    def close(self) -> None:
        self.closed = True

    def revive(self) -> bool:
        self.revivals += 1
        return True

    def use_agent(self, profile: AgentProfile) -> None:
        self.agents.append(profile.agent_id)
        self.models.append(profile.model)

    def run_isolated_phase(self, *, initial_prompt: str, phase_id: str = "", **_kwargs) -> dict:
        """A scripted `answerRounds` key stands for the rounds the user answered.

        A `before_turn` hook may set `last_answer_rounds` and return `None` to
        script answers given before the session crashes on the queued exception.
        """
        self.sent.append(initial_prompt)
        self.last_answer_rounds = ()
        result = self._next(phase_id, {"approved": True})
        self.last_answer_rounds += tuple(result.pop("answerRounds", ()))
        return result

    def run_isolated_prompt(
        self, *, prompt_text: str, phase_id: str = "", build_continuation=None, **_kwargs
    ) -> dict:
        """Mimic the real runner's turn loop, including the continuation.

        Without this, the agent's chance to unblock itself would not be exercised
        by any test: the engine only offers it through this callback.
        """
        self.sent.append(prompt_text)
        self.last_answer_rounds = ()
        result = self._next(phase_id, {"stopReason": "end_turn"})
        parts = [str(result.get("phaseSummary", ""))]
        turn = 0
        while build_continuation is not None and result.get("stopReason") != "cancelled":
            follow_up = str(build_continuation(result=result, turn=turn) or "").strip()
            if not follow_up:
                break
            self.sent.append(follow_up)
            result = self._next(phase_id, {"stopReason": "end_turn"})
            parts.append(str(result.get("phaseSummary", "")))
            result["phaseSummary"] = "\n\n".join(part for part in parts if part)
            turn += 1
        return result

    def _next(self, step_id: str, default: dict) -> dict:
        """Next queued result, or the exception the session would raise."""
        if self._before_turn is not None:
            answered = self._before_turn(step_id)
            if answered is not None:
                return answered
        result = self._results.pop(0) if self._results else default
        if isinstance(result, BaseException):
            raise result
        return result
