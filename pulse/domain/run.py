"""The run aggregate: a run and the steps it executes.

`RunRecord` is the aggregate root and `StepRecord` its child entity. Every
status change goes through an intent method that checks the transition is
legal, so the engine asks for what it wants (`record.block()`) instead of
writing fields. Persistence lives in [pulse.store.runs]; this module has no I/O.

Statuses are `StrEnum`s: they compare and hash like the plain strings already
stored in SQLite, so no migration is needed.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from pulse.runcontrol import RUN_BLOCKED, RUN_STOPPED


class StepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    SKIPPED = "skipped"
    FAILED = "failed"
    BLOCKED = "blocked"

    @classmethod
    def parse(cls, value: str) -> StepStatus:
        """Status read from storage; unknown or empty values fall back to `PENDING`."""
        try:
            return cls(value)
        except ValueError:
            return cls.PENDING


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    AWAITING_INPUT = "awaiting_input"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"
    BLOCKED = "blocked"

    @classmethod
    def parse(cls, value: str) -> RunStatus:
        """Status read from storage; unknown or empty values fall back to `PENDING`."""
        try:
            return cls(value)
        except ValueError:
            return cls.PENDING

    @classmethod
    def for_exit_code(cls, exit_code: int) -> RunStatus:
        """Status of a run that ended with `exit_code`.

        Blocked is not failed: history must tell them apart to offer the right action.
        """
        if exit_code == 0:
            return cls.COMPLETED
        if exit_code == RUN_STOPPED:
            return cls.STOPPED
        if exit_code == RUN_BLOCKED:
            return cls.BLOCKED
        return cls.FAILED


SETTLED = frozenset({StepStatus.DONE, StepStatus.SKIPPED})
ENDED = SETTLED | {StepStatus.FAILED, StepStatus.BLOCKED}
_INTERRUPTED = frozenset({StepStatus.RUNNING, StepStatus.FAILED, StepStatus.BLOCKED})


FAN_OUT_SEPARATOR = ":"


def fan_out_child_id(base_step_id: str, item_id: str) -> str:
    """Id of the step a fan-out runs for one item: `review:T1` for `review`."""
    return f"{base_step_id}{FAN_OUT_SEPARATOR}{item_id}"


class InvalidTransition(RuntimeError):
    """A status change the run or step does not allow from its current state."""


@dataclass(frozen=True)
class LoopRange:
    """Steps that may run again as a group, opener first, for at most `ceiling` rounds."""

    step_ids: tuple[str, ...]
    ceiling: int

    def __post_init__(self) -> None:
        if not self.step_ids:
            raise ValueError("a loop range needs an opener")

    @property
    def opener_id(self) -> str:
        return self.step_ids[0]


@dataclass(frozen=True)
class RoundDecision:
    """Answer to a request for another round: `round` is the one now on."""

    round: int
    granted: bool
    last: bool


Clock = Callable[[], str]


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _system_clock() -> str:
    # Looked up on each call so tests that patch `utc_now` still drive every step.
    return utc_now()


def net_seconds(started_at: str, ended_at: str, waiting_seconds: float) -> float:
    """Wall time minus wait; zero when the round has no recorded start and end."""
    try:
        start = datetime.fromisoformat(started_at)
        end = datetime.fromisoformat(ended_at)
    except ValueError:
        return 0.0
    return max(0.0, (end - start).total_seconds() - max(0.0, waiting_seconds))


@dataclass
class StepRecord:
    step_id: str
    position: int = 0
    label: str = ""
    agent_id: str = ""
    status: StepStatus = StepStatus.PENDING
    summary: str = ""
    acp_session_id: str = ""
    started_at: str = ""
    ended_at: str = ""
    waiting_seconds: float = 0.0
    rounds: int = 1
    carried_seconds: float = 0.0
    clock: Clock = field(default=_system_clock, repr=False, compare=False)

    @property
    def settled(self) -> bool:
        return self.status in SETTLED

    @property
    def has_ended(self) -> bool:
        """Settled, or its last attempt failed or blocked: it has a closed attempt to show."""
        return self.status in ENDED

    def add_wait(self, seconds: float) -> None:
        """Time spent waiting for the user: it comes off the step's duration."""
        if seconds <= 0:
            return
        self.waiting_seconds += seconds

    def start(self) -> None:
        """Begin an attempt. Retries keep the first `started_at` of the round."""
        self._require_not(SETTLED, "start")
        self.status = StepStatus.RUNNING
        self.started_at = self.started_at or self.clock()

    def record_reply(self, *, session_id: str, summary: str) -> None:
        """Keep what the agent answered; an empty `session_id` keeps the previous one."""
        self._require({StepStatus.RUNNING}, "record a reply")
        self.acp_session_id = session_id or self.acp_session_id
        self.summary = summary

    def deliver(self) -> None:
        """The agent delivered what the step asks for."""
        self._end_as(StepStatus.DONE, allowed={StepStatus.RUNNING})

    def skip(self) -> None:
        """The agent declared the step does not apply; its summary is kept."""
        self._end_as(StepStatus.SKIPPED, allowed={StepStatus.RUNNING})

    def skip_blocked(self) -> None:
        """The user skips a blocked step.

        The summary is cleared so the next step reports the earlier delivery
        instead of this one's blocked text.
        """
        self._end_as(StepStatus.SKIPPED, allowed={StepStatus.BLOCKED})
        self.summary = ""

    def block(self) -> None:
        """It ran and did not crash, but did not deliver."""
        self._end_as(StepStatus.BLOCKED, allowed={StepStatus.RUNNING})

    def fail(self) -> None:
        """Record the attempt as failed before asking what to do.

        Prevents a step stuck as `running` in history if the process dies while
        the retry menu is open. Retrying calls `start` again.
        """
        self._end_as(StepStatus.FAILED, allowed={StepStatus.RUNNING})

    def close_after_wait(self) -> None:
        """Re-stamp `ended_at` after the user answered the retry/blocked menu.

        Menu wait time is subtracted from the step (`waiting_seconds`), so
        `ended_at` must cover it or the recorded duration shrinks or goes negative.
        """
        self._require({StepStatus.FAILED, StepStatus.BLOCKED}, "close after the menu")
        self.ended_at = self.clock()

    def release(self) -> bool:
        """Return a step cut by a stop to `pending` so a resume restarts it.

        Settled steps are left alone. Returns whether anything changed.
        """
        if self.status not in _INTERRUPTED:
            return False
        self.status = StepStatus.PENDING
        self.ended_at = ""
        return True

    def reopen_round(self) -> None:
        """Start a new loop round on the same row.

        The round's net time (wall time minus wait) moves to `carried_seconds`
        before its start and end are cleared, so panel and history show the sum.
        """
        self._require_not({StepStatus.RUNNING}, "reopen")
        self.carried_seconds += net_seconds(self.started_at, self.ended_at, self.waiting_seconds)
        self.waiting_seconds = 0.0
        self.status = StepStatus.PENDING
        self.summary = ""
        self.started_at = ""
        self.ended_at = ""
        self.acp_session_id = ""

    def open_next_round(self) -> None:
        """Reopen as the loop's opener: only the opener counts the rounds."""
        self.reopen_round()
        self.rounds += 1

    def close_with_loop(self, *, ran_before: bool) -> None:
        """Settle a step the loop no longer needs, without running it.

        A step that ran in an earlier round is `done`; one that never ran is `skipped`.
        """
        self._require_not(SETTLED | {StepStatus.RUNNING}, "close with the loop")
        self.status = StepStatus.DONE if ran_before else StepStatus.SKIPPED
        self.summary = ""
        self.ended_at = self.ended_at or self.clock()

    def _end_as(self, status: StepStatus, *, allowed: set[StepStatus]) -> None:
        self._require(allowed, f"mark as {status}")
        self.status = status
        self.ended_at = self.clock()

    def _require(self, allowed: set[StepStatus], action: str) -> None:
        if self.status not in allowed:
            raise InvalidTransition(f"step {self.step_id}: cannot {action} while {self.status}")

    def _require_not(self, forbidden: set[StepStatus] | frozenset[StepStatus], action: str) -> None:
        if self.status in forbidden:
            raise InvalidTransition(f"step {self.step_id}: cannot {action} while {self.status}")


@dataclass
class RunRecord:
    id: str
    workflow_id: str
    workspace_root: str
    user_prompt: str = ""
    status: RunStatus = RunStatus.PENDING
    current_step: str = ""
    created_at: str = ""
    updated_at: str = ""
    worktree_path: str = ""
    branch: str = ""
    steps: list[StepRecord] = field(default_factory=list)
    _removed: set[str] = field(default_factory=set, init=False, repr=False, compare=False)

    @property
    def exec_root(self) -> str:
        """Where the agent worked: the worktree, or the root when there was none."""
        return self.worktree_path or self.workspace_root

    def step(self, step_id: str) -> StepRecord | None:
        for item in self.steps:
            if item.step_id == step_id:
                return item
        return None

    def previous_delivery(self, step_id: str) -> StepRecord | None:
        """The last step before this one that settled with a summary.

        Failed or blocked steps are excluded so their text is not passed on as a
        delivery. The scan stops at the step or its first fan-out child, so a
        resumed fan-out still sees the step that listed the items.
        """
        children = f"{step_id}{FAN_OUT_SEPARATOR}"
        previous: StepRecord | None = None
        for item in self.steps:
            if item.step_id == step_id or item.step_id.startswith(children):
                break
            if item.summary and item.settled:
                previous = item
        return previous

    def fan_out_siblings(self, child_id: str) -> list[StepRecord]:
        """Every step the same fan-out produced, in run order, `child_id` included."""
        base, separator, _item = child_id.rpartition(FAN_OUT_SEPARATOR)
        if not separator:
            return []
        prefix = f"{base}{FAN_OUT_SEPARATOR}"
        return [item for item in self.steps if item.step_id.startswith(prefix)]

    def next_pending(self) -> StepRecord | None:
        for item in self.steps:
            if not item.settled:
                return item
        return None

    def is_incomplete(self) -> bool:
        return any(not item.settled for item in self.steps)

    def add_step(self, record: StepRecord) -> StepRecord:
        """Append a step the run did not know yet; returns the one it already had."""
        existing = self.step(record.step_id)
        if existing is not None:
            return existing
        self.steps.append(record)
        self._removed.discard(record.step_id)
        return record

    def expand_step(self, step_id: str, children: list[StepRecord]) -> None:
        """Replace a fan-out step with one child per item, in its place.

        Children already present (a resumed fan-out) are kept as they are.
        """
        at = len(self.steps)
        base = self.step(step_id)
        if base is not None:
            at = self.steps.index(base)
            self.steps.remove(base)
            self._removed.add(step_id)
        for offset, child in enumerate(children):
            if self.step(child.step_id) is None:
                self.steps.insert(at + offset, child)
                self._removed.discard(child.step_id)

    def removed_step_ids(self) -> frozenset[str]:
        """Steps dropped since the last save, which storage must delete."""
        return frozenset(self._removed)

    def forget_removed_steps(self) -> None:
        """Called by storage once the deletions are committed."""
        self._removed.clear()

    def work_in(self, *, worktree_path: str, branch: str) -> None:
        """Where the agent works for this run: a worktree, or the root when empty."""
        self.worktree_path = worktree_path
        self.branch = branch

    def await_input(self) -> bool:
        """A question is open: the run is alive but paused on the user.

        Only a running run waits. A question outside it (the resume menu) leaves
        the status alone. Returns whether anything changed.
        """
        if self.status != RunStatus.RUNNING:
            return False
        self.status = RunStatus.AWAITING_INPUT
        return True

    def resume_work(self) -> bool:
        """The question was answered and the run is working again.

        A run that ended while the question was open (a stop) keeps its ending.
        Returns whether anything changed.
        """
        if self.status != RunStatus.AWAITING_INPUT:
            return False
        self.status = RunStatus.RUNNING
        return True

    def drop_worktree(self) -> None:
        """The worktree directory is gone; the branch stays, it still holds the work."""
        self.worktree_path = ""

    def begin_step(self, step_id: str) -> None:
        """Point the run at the step about to execute.

        A stopped, blocked or failed run begins again when resumed; a completed
        one is history, and a settled step is never run twice.
        """
        self._require_not_completed("begin a step")
        step = self.step(step_id)
        if step is None:
            raise InvalidTransition(f"run {self.id}: unknown step {step_id}")
        if step.settled:
            raise InvalidTransition(f"run {self.id}: step {step_id} already {step.status}")
        self.status = RunStatus.RUNNING
        self.current_step = step_id

    def complete(self) -> None:
        """Every step settled; the workflow is over."""
        if self.is_incomplete():
            raise InvalidTransition(f"run {self.id}: cannot complete with unsettled steps")
        self.status = RunStatus.COMPLETED

    def end(self, exit_code: int) -> None:
        """Record why the run stopped early (stop, block or failure)."""
        if exit_code == 0:
            raise InvalidTransition(f"run {self.id}: a clean exit must go through complete()")
        self._require_not_completed("end")
        self.status = RunStatus.for_exit_code(exit_code)

    def fail_running_steps(self) -> list[StepRecord]:
        """Fail the steps a crash left `running`; returns them so they can be saved."""
        running = [item for item in self.steps if item.status == StepStatus.RUNNING]
        for item in running:
            item.fail()
        return running

    def repeat_loop(self, loop: LoopRange) -> RoundDecision:
        """Grant another round below the ceiling and return the loop's steps to `pending`.

        On the last round only the opener reopens, so the closer never gets the
        final word on its own fix. Rounds reuse the same rows so the panel keeps
        one line per step; the count is persisted, so it survives a resume.
        """
        current = self._loop_round(loop)
        if current >= loop.ceiling:
            return RoundDecision(round=current, granted=False, last=True)
        upcoming = current + 1
        last = upcoming >= loop.ceiling
        for step in self._known(loop.step_ids[:1] if last else loop.step_ids):
            if step.step_id == loop.opener_id:
                step.open_next_round()
            else:
                step.reopen_round()
        return RoundDecision(round=upcoming, granted=True, last=last)

    def close_loop(self, loop: LoopRange) -> None:
        """Settle the loop's remaining steps without running them.

        After an earlier round the rest ran before and is `done`; on the first
        round it never ran and is `skipped`.
        """
        ran_before = self._loop_round(loop) > 1
        for step in self._known(loop.step_ids[1:]):
            if not step.settled:
                step.close_with_loop(ran_before=ran_before)

    def _loop_round(self, loop: LoopRange) -> int:
        opener = self.step(loop.opener_id)
        return opener.rounds if opener is not None else 1

    def _known(self, step_ids: Sequence[str]) -> list[StepRecord]:
        return [step for step_id in step_ids if (step := self.step(step_id)) is not None]

    def _require_not_completed(self, action: str) -> None:
        if self.status == RunStatus.COMPLETED:
            raise InvalidTransition(f"run {self.id}: cannot {action} once completed")
