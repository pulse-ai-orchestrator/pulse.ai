from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Protocol, TypeAlias, TypedDict, TypeVar, runtime_checkable

from pulse.domain.git_options import NO_GIT_OPTIONS, GitOptions
from pulse.domain.run import RunRecord, StepRecord
from pulse.domain.task_brief import EMPTY_BRIEF, TaskBrief

JsonObject: TypeAlias = dict[str, object]
"""An ACP JSON-RPC payload. Its shape belongs to the runtime, so adapters narrow it at the edge."""

Choice = TypeVar("Choice")


class StepRow(TypedDict):
    """One step as the panel lists it; fan-out changes the list mid-run."""

    id: str
    label: str
    rounds: int


class Questionnaire(Protocol):
    """A questionnaire parsed from the agent's text; `pulse.replies` owns the concrete shape."""

    @property
    def title(self) -> str: ...

    @property
    def raw(self) -> str: ...


@runtime_checkable
class StreamSink(Protocol):
    """Where a run shows its progress: the cockpit over SSE, or a plain console.

    The engine calls every method unconditionally; an adapter with nothing to
    show for one implements it as a no-op instead of leaving it out.
    """

    def handle_update(self, params: JsonObject) -> None: ...

    def begin_phase(self, title: str, *, turn: int = 1) -> None:
        """A phase starts; `turn` above 1 is a later turn of the same phase."""
        ...

    def set_model(self, model: str) -> None:
        """The model the agent session runs on, as the agent names it."""
        ...

    def reset_capture(self) -> None: ...

    def agent_text(self) -> str: ...

    def finish(self) -> None: ...

    def finish_question_prompt(self) -> None: ...

    def begin_user_wait(self) -> None: ...

    def end_user_wait(self) -> None: ...

    def set_context(self, *, cwd: str, branch: str) -> None: ...

    def set_session_id(self, session_id: str) -> None: ...

    def info(self, title: str) -> None: ...

    def error(self, title: str, reason: str = "") -> None: ...

    def apply_phase_statuses(
        self,
        *,
        steps: Sequence[StepRow] = (),
        done_ids: Sequence[str] = (),
        skipped_ids: Sequence[str] = (),
        failed_ids: Sequence[str] = (),
        blocked_ids: Sequence[str] = (),
    ) -> None: ...


@runtime_checkable
class PromptPort(Protocol):
    def respond_to_ask_question(self, params: JsonObject) -> JsonObject: ...

    def respond_to_create_plan(self, params: JsonObject) -> JsonObject: ...

    def respond_to_permission(
        self,
        params: JsonObject,
        *,
        policy: str,
        allow_terminal: bool = False,
    ) -> JsonObject: ...

    def run_parsed_questionnaire(self, questionnaire: Questionnaire) -> str | None: ...

    def run_text_questionnaire(self, text: str) -> str | None: ...

    def ask_text(self, prompt: str, *, title: str = "") -> str | None: ...

    def select_choice(
        self,
        prompt: str,
        choices: list[tuple[str, Choice]],
        *,
        title: str = "",
    ) -> Choice | None: ...


@runtime_checkable
class RunRepository(Protocol):
    """Where a run lives between steps, so a stopped or crashed run can be resumed."""

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
        """A new running run whose steps are all pending, stored before it is returned.

        `brief` and `git` are copied onto the run, so a resume keeps what it
        started with even after the project settings change.
        """
        ...

    def load(self, run_id: str) -> RunRecord | None: ...

    def save(self, run: RunRecord) -> None:
        """Store the whole aggregate at once: the run and its steps never disagree."""
        ...

    def artifacts(self, run_id: str) -> list[str]:
        """Paths the agents wrote during the run, relative to where it worked."""
        ...

    def step_artifacts(self, run_id: str, step_id: str, *, since: datetime | None) -> list[str]:
        """Paths `step_id` wrote in the run from `since` on, in the order they were written.

        A path belongs to the step that wrote it first.
        """
        ...


class PhaseContinuation(Protocol):
    """The prompt after the user answered the approval questionnaire with anything but approve."""

    def __call__(self, *, phase_summary: str, questionnaire_answers: str, outcome: str) -> str: ...


class PromptContinuation(Protocol):
    """The next prompt in the same ACP session, from the turn so far; empty ends the step."""

    def __call__(self, *, result: JsonObject, turn: int) -> str: ...


@dataclass(frozen=True)
class AgentProfile:
    """What a step's agent runs with: the user's config over the agent definition.

    `permission_policy` stays text here; the session parses it at its edge and
    falls back to asking, never to allowing.
    """

    agent_id: str
    model: str | None
    permission_policy: str
    instructions: str = ""
    runtime_id: str = ""
    acp_command: tuple[str, ...] = ()
    dialect: RuntimeDialect | None = field(default=None, compare=False, hash=False)


@runtime_checkable
class AgentProfiles(Protocol):
    def profile(self, agent_id: str) -> AgentProfile: ...


@runtime_checkable
class AgentSession(Protocol):
    """The agent process a run talks to; every step opens its own session in it.

    One step's session never carries over to the next: the next step only gets
    the summary the engine forwards.
    """

    @property
    def prompts(self) -> PromptPort:
        """Where the engine asks its own questions, so they count as user waits."""
        ...

    @property
    def last_session_id(self) -> str: ...

    @property
    def last_answer_rounds(self) -> tuple[str, ...]:
        """The questionnaire answers that kept the last step's session going.

        Kept when the session fails mid-step, so a retry still hears them.
        """
        pass

    def bind_run(self, run_id: str, waits: UserWaitListener) -> None: ...

    def open(self, cwd: Path) -> None:
        """Start the agent in `cwd`, known only once the run has a place to work."""
        ...

    def close(self) -> None: ...

    def revive(self) -> bool:
        """Restart a dead or hung agent; `True` when it had to."""
        ...

    def use_agent(self, profile: AgentProfile) -> None: ...

    def run_isolated_phase(
        self,
        *,
        workflow: str,
        phase_label: str,
        initial_prompt: str,
        preferred_model: str | None = None,
        build_continuation: PhaseContinuation | None = None,
        phase_id: str = "",
    ) -> JsonObject:
        """A step that ends in the approval questionnaire."""
        ...

    def run_isolated_prompt(
        self,
        *,
        workflow: str,
        phase_label: str,
        prompt_text: str,
        preferred_model: str | None = None,
        phase_id: str = "",
        build_continuation: PromptContinuation | None = None,
    ) -> JsonObject:
        """A step that ends when the agent ends its turn."""
        ...

    def draft_pull_request(
        self,
        *,
        workflow: str,
        phase_label: str,
        prompt_text: str,
    ) -> JsonObject:
        """One session whose only job is to fill the pull request body."""
        ...


# The ports below sit between adapters, not between the engine and the world:
# the ACP session runner gets them from the daemon instead of importing the
# runtime registry, the MCP bridge or the store (AGENTS.md §2.1).


@dataclass(frozen=True)
class ModelRequest:
    """JSON-RPC call that applies a model to the session.

    Not every ACP agent implements `session/set_model` (Claude exposes the model
    as a config option), so each runtime returns the right call.
    """

    method: str
    params: JsonObject
    model_id: str


@runtime_checkable
class RuntimeDialect(Protocol):
    """How one runtime's ACP adapter differs from plain ACP, as the session runner needs it."""

    def auth_method(self, advertised: Sequence[str]) -> str | None:
        """`methodId` for `authenticate`, or `None` to skip the call."""
        ...

    def model_request(
        self, session: JsonObject, preferred_model: str | None, *, session_id: str
    ) -> ModelRequest | None: ...

    def resolve_mode(self, session: JsonObject, *, execute: bool) -> str | None: ...


@runtime_checkable
class QuestionChannel(Protocol):
    """Where the agent asks the user a question mid-turn (the MCP `AskQuestion` tool)."""

    def open(self, prompts: PromptPort, on_question: Callable[[], None]) -> list[JsonObject]:
        """Start listening; return the `mcpServers` entries the agent must be given."""
        ...

    def close(self) -> None: ...


@runtime_checkable
class SessionLog(Protocol):
    """What an agent session leaves in its run's log, so history shows what the screen showed.

    The runner tells where it is (`bind_run`, `enter_step`, `enter_session`) and
    what happened; the log decides what becomes a row. Writing must never end
    the session: an adapter swallows its own storage failures.
    """

    def bind_run(self, run_id: str) -> None: ...

    def enter_step(self, step_id: str) -> None: ...

    def enter_session(
        self, session_id: str, *, pulse_session_id: str, cwd: str, agent_id: str | None
    ) -> None:
        """A new ACP session opened in `cwd`; `pulse_session_id` is the runner's own id."""
        ...

    def update(self, params: JsonObject) -> None:
        """A `session/update` the screen just drew."""
        ...

    def phase(self, label: str, *, turn: int = 1) -> None:
        """A phase marker, so history does not merge consecutive turns."""
        ...

    def dialog(
        self, name: str, args: tuple[object, ...], kwargs: dict[str, object], result: object
    ) -> None:
        """A question the user answered through the prompt port."""
        ...

    def notice(self, title: str, detail: str) -> None:
        """A failure the session survived, recorded for whoever reads the run later."""
        ...

    def flush(self) -> None:
        """Close the agent's pending speech into one row."""
        ...


class WorkspaceError(RuntimeError):
    """The run could not get a place to work: a worktree that would not open."""


@runtime_checkable
class Workspace(Protocol):
    """The project a run works on, and the per-run worktrees it may open from it.

    `root` stays the run's identity (config and history resolve by it); a
    worktree only changes where the agent writes.
    """

    @property
    def root(self) -> Path: ...

    def is_repo(self) -> bool: ...

    def current_branch(self) -> str:
        """Empty on a detached HEAD or outside a repository."""
        ...

    def has_branch(self, branch: str) -> bool: ...

    def worktree_exists(self, path: str) -> bool: ...

    def attach_worktree(self, run_id: str, branch: str) -> Path:
        """Reopen the run's worktree on a branch it already owns."""
        ...

    def add_worktree(self, run_id: str, branch: str) -> tuple[Path, str]:
        """Open the run's worktree on `branch`. Raises when that name is taken."""
        ...

    def head(self, cwd: Path) -> str:
        """Commit the worktree is on, empty when it cannot be read."""
        ...

    def snapshot(self, cwd: Path) -> dict[str, str]:
        """Content digest of each dirty path, so a later snapshot shows what changed."""
        ...

    def commit(self, cwd: Path, paths: list[str], message: str) -> None:
        """Commit `paths` in `cwd` with `message`."""
        ...

    def commits_after(self, cwd: Path, base: str) -> list[str]:
        """Subjects of commits in `cwd` after `base`."""
        ...

    def publish_branch(self, branch: str) -> None:
        """Push `branch` to `origin` and set it as the upstream."""
        ...

    def remove_worktree(self, path: Path) -> None:
        """Remove the worktree directory. A dirty tree is refused."""
        ...

    def delete_local_branch(self, branch: str) -> None:
        """Delete the local branch once it is on its upstream. The remote stays."""
        ...

    def open_pull_request(self, *, branch: str, title: str, body: str) -> None:
        """Open a draft pull request or merge request for `branch` on `origin`."""
        ...

    def request_template(self, cwd: Path) -> str:
        """The project's pull or merge request template, or empty when it has none."""
        ...


@runtime_checkable
class UserWaitListener(Protocol):
    """Told when a question to the user opens and closes, so the run can pause its clock."""

    def user_wait_began(self) -> None: ...

    def user_wait_ended(self, step_id: str, seconds: float) -> None: ...


class NullStreamSink:
    def __init__(self) -> None:
        self._agent_text = ""

    def handle_update(self, params: JsonObject) -> None:
        update = params.get("update", {})
        if not isinstance(update, dict):
            return
        if update.get("sessionUpdate") != "agent_message_chunk":
            return
        content = update.get("content", {})
        if isinstance(content, dict) and content.get("type") == "text":
            self._agent_text += str(content.get("text", ""))

    def begin_phase(self, title: str, *, turn: int = 1) -> None:
        return None

    def set_model(self, model: str) -> None:
        return None

    def reset_capture(self) -> None:
        self._agent_text = ""

    def agent_text(self) -> str:
        return self._agent_text

    def finish(self) -> None:
        return None

    def finish_question_prompt(self) -> None:
        return None

    def begin_user_wait(self) -> None:
        return None

    def end_user_wait(self) -> None:
        return None

    def info(self, title: str) -> None:
        return None

    def error(self, title: str, reason: str = "") -> None:
        return None

    def apply_phase_statuses(
        self,
        *,
        steps: Sequence[StepRow] = (),
        done_ids: Sequence[str] = (),
        skipped_ids: Sequence[str] = (),
        failed_ids: Sequence[str] = (),
        blocked_ids: Sequence[str] = (),
    ) -> None:
        return None

    def set_session_id(self, session_id: str) -> None:
        return None

    def set_context(self, *, cwd: str, branch: str) -> None:
        return None


class NullUserWaitListener:
    def user_wait_began(self) -> None:
        return None

    def user_wait_ended(self, step_id: str, seconds: float) -> None:
        return None


class NullPromptPort:
    def respond_to_ask_question(self, params: JsonObject) -> JsonObject:
        return {"outcome": {"outcome": "cancelled"}}

    def respond_to_create_plan(self, params: JsonObject) -> JsonObject:
        return {"outcome": {"outcome": "cancelled"}}

    def respond_to_permission(
        self,
        params: JsonObject,
        *,
        policy: str,
        allow_terminal: bool = False,
    ) -> JsonObject:
        return {"outcome": {"outcome": "cancelled"}}

    def run_parsed_questionnaire(self, questionnaire: Questionnaire) -> str | None:
        return None

    def run_text_questionnaire(self, text: str) -> str | None:
        return None

    def ask_text(self, prompt: str, *, title: str = "") -> str | None:
        return None

    def select_choice(
        self,
        prompt: str,
        choices: list[tuple[str, Choice]],
        *,
        title: str = "",
    ) -> Choice | None:
        return None


class NullQuestionChannel:
    """No one to ask mid-turn (a probe, a test): the agent gets no MCP server."""

    def open(self, prompts: PromptPort, on_question: Callable[[], None]) -> list[JsonObject]:
        return []

    def close(self) -> None:
        return None


class NullRuntimeDialect:
    """Plain ACP, for a runtime with no dialect of its own: no auth, model or mode calls."""

    def auth_method(self, advertised: Sequence[str]) -> str | None:
        return None

    def model_request(
        self, session: JsonObject, preferred_model: str | None, *, session_id: str
    ) -> ModelRequest | None:
        return None

    def resolve_mode(self, session: JsonObject, *, execute: bool) -> str | None:
        return None


class NullSessionLog:
    """No run bound (a probe, a test): nothing is recorded."""

    def bind_run(self, run_id: str) -> None:
        return None

    def enter_step(self, step_id: str) -> None:
        return None

    def enter_session(
        self, session_id: str, *, pulse_session_id: str, cwd: str, agent_id: str | None
    ) -> None:
        return None

    def update(self, params: JsonObject) -> None:
        return None

    def phase(self, label: str, *, turn: int = 1) -> None:
        return None

    def dialog(
        self, name: str, args: tuple[object, ...], kwargs: dict[str, object], result: object
    ) -> None:
        return None

    def notice(self, title: str, detail: str) -> None:
        return None

    def flush(self) -> None:
        return None
