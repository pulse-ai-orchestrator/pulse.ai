"""The run aggregate: a run and the steps it executes.

`RunRecord` is the aggregate root and `StepRecord` its child entity. Every
status change goes through an intent method that checks the transition is
legal, so the engine asks for what it wants (`record.block()`) instead of
writing fields. Persistence lives in [pulse.store.runs]; this module has no I/O.

Statuses are `StrEnum`s: they compare and hash like the plain strings already
stored in SQLite, so no migration is needed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from pulse.domain.control import RUN_BLOCKED, RUN_STOPPED
from pulse.domain.git_options import GitOptions
from pulse.domain.task_brief import TaskBrief


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
BRANCH_PREFIX = "pulse/"
SHORT_ID_CHARS = 8


def fan_out_child_id(base_step_id: str, item_id: str) -> str:
    """Id of the step a fan-out runs for one item: `review:T1` for `review`."""
    return f"{base_step_id}{FAN_OUT_SEPARATOR}{item_id}"


class InvalidTransition(RuntimeError):
    """A status change the run or step does not allow from its current state."""


def utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


@dataclass
class StepRecord:
    step_id: str
    position: int = 0
    label: str = ""
    agent_id: str = ""
    status: StepStatus = StepStatus.PENDING
    summary: str = ""
    acp_session_id: str = ""
    started_at: datetime | None = None
    ended_at: datetime | None = None
    waiting_seconds: float = 0.0
    rounds: int = 1
    carried_seconds: float = 0.0
    # Written by the session log as the agent reports it; the engine never sets it.
    context_tokens: int = 0

    @property
    def settled(self) -> bool:
        return self.status in SETTLED

    @property
    def has_ended(self) -> bool:
        """Settled, or its last attempt failed or blocked: it has a closed attempt to show."""
        return self.status in ENDED

    @property
    def starts_as_retry(self) -> bool:
        """Its last attempt failed or blocked: starting it again repeats that attempt.

        A new loop round reopens the step as pending, so it is not a retry.
        """
        return self.has_ended and not self.settled

    def round_seconds(self) -> float | None:
        """Net time of the current round (wall time minus wait); `None` while it is open."""
        if self.started_at is None or self.ended_at is None:
            return None
        wall = (self.ended_at - self.started_at).total_seconds()
        return max(0.0, wall - max(0.0, self.waiting_seconds))

    def elapsed_seconds(self) -> float | None:
        """Net time across loop rounds; `None` when no round has closed yet."""
        current = self.round_seconds()
        if current is None:
            return self.carried_seconds or None
        return self.carried_seconds + current

    def add_wait(self, seconds: float) -> None:
        """Time spent waiting for the user: it comes off the step's duration."""
        if seconds <= 0:
            return
        self.waiting_seconds += seconds

    def start(self) -> None:
        """Begin an attempt. Retries keep the first `started_at` of the round."""
        self._require_not(SETTLED, "start")
        self.status = StepStatus.RUNNING
        self.started_at = self.started_at or utc_now()

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
        self.ended_at = utc_now()

    def release(self) -> bool:
        """Return a step cut by a stop to `pending` so a resume restarts it.

        Settled steps are left alone. Returns whether anything changed.
        """
        if self.status not in _INTERRUPTED:
            return False
        self.status = StepStatus.PENDING
        self.ended_at = None
        return True

    def reopen_round(self, *, opener: bool) -> None:
        """Start a new loop round on the same row; the opener counts the rounds.

        The round's net time (wall time minus wait) moves to `carried_seconds`
        before its start and end are cleared, so panel and history show the sum.
        """
        self._require_not({StepStatus.RUNNING}, "reopen")
        if opener:
            self.rounds += 1
        self.carried_seconds += self.round_seconds() or 0.0
        self.waiting_seconds = 0.0
        self.status = StepStatus.PENDING
        self.summary = ""
        self.started_at = None
        self.ended_at = None
        self.acp_session_id = ""

    def close_with_loop(self, *, ran_before: bool) -> None:
        """Settle a step the loop no longer needs, without running it.

        A step that ran in an earlier round is `done`; one that never ran is `skipped`.
        """
        status = StepStatus.DONE if ran_before else StepStatus.SKIPPED
        self._settle_unrun(status, "close with the loop")

    def retire(self) -> None:
        """Skip a step the workflow no longer has: the engine will never reach it again."""
        self._settle_unrun(StepStatus.SKIPPED, "retire")

    def _settle_unrun(self, status: StepStatus, action: str) -> None:
        self._require_not(SETTLED | {StepStatus.RUNNING}, action)
        self.status = status
        self.summary = ""
        self.ended_at = self.ended_at or utc_now()

    def _end_as(self, status: StepStatus, *, allowed: set[StepStatus]) -> None:
        self._require(allowed, f"mark as {status}")
        self.status = status
        self.ended_at = utc_now()

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
    branch_owned: bool = False
    branch_base: str = ""
    title: str = ""
    description: str = ""
    # None for a run stored before runs kept their own options: it follows the project.
    git: GitOptions | None = None
    request_opened: bool = False
    steps: list[StepRecord] = field(default_factory=list)
    _removed: set[str] = field(default_factory=set, init=False, repr=False, compare=False)

    @property
    def exec_root(self) -> str:
        """Where the agent worked: the worktree, or the root when there was none."""
        return self.worktree_path or self.workspace_root

    @property
    def brief(self) -> TaskBrief:
        return TaskBrief(title=self.title, description=self.description)

    def elapsed_seconds(self) -> float | None:
        """Net time of every step that already has some; `None` when none does.

        An open attempt stays out until it closes, the same number the sidebar
        freezes. Time waiting on the user is already out of each step's total,
        and a fan-out adds each task.
        """
        recorded = [
            seconds for step in self.steps if (seconds := step.elapsed_seconds()) is not None
        ]
        if not recorded:
            return None
        return sum(recorded)

    @property
    def own_branch(self) -> str:
        """`pulse/<workflow>-<short run id>`: the branch this run's worktree is created on.

        Uses the workflow id rather than the free-text task to avoid sanitizing it.
        """
        slug = "".join(char if char.isalnum() or char in "-_" else "-" for char in self.workflow_id)
        return f"{BRANCH_PREFIX}{slug.strip('-') or 'run'}-{self.id[:SHORT_ID_CHARS]}"

    @property
    def owns_branch(self) -> bool:
        """The recorded branch was created by this run rather than the project's.

        Prevents reattaching e.g. `main` from the user's working tree. A run that
        recorded `branch_owned` owns whatever name it confirmed. Older runs own
        `own_branch`, with or without the suffix git used to add when it was taken.
        """
        if self.branch_owned and self.branch:
            return True
        base = self.own_branch
        return self.branch == base or self.branch.startswith(f"{base}-")

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

    def step_ids_by_status(self) -> dict[StepStatus, list[str]]:
        """Step ids per status, in run order; every status is a key."""
        grouped: dict[StepStatus, list[str]] = {status: [] for status in StepStatus}
        for item in self.steps:
            grouped[item.status].append(item.step_id)
        return grouped

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

    def note_request_opened(self) -> None:
        """The draft for this branch is already on the forge."""
        self.request_opened = True

    def work_in(
        self, *, worktree_path: str, branch: str, owns: bool = False, base: str = ""
    ) -> None:
        """Where the agent works for this run: a worktree, or the root when empty."""
        self.worktree_path = worktree_path
        self.branch = branch
        if owns:
            self.branch_owned = True
        if base:
            self.branch_base = base

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

    def start_step(self, step_id: str) -> StepRecord:
        """Run this step now; a retry starts the same step again.

        One step runs at a time: each has its own ACP session.
        """
        record = self.step(step_id)
        if record is None:
            raise InvalidTransition(f"run {self.id}: unknown step {step_id}")
        running = [item.step_id for item in self.steps if item.status == StepStatus.RUNNING]
        if running and running != [step_id]:
            raise InvalidTransition(f"run {self.id}: cannot start {step_id} while {running} runs")
        record.start()
        self.status = RunStatus.RUNNING
        self.current_step = step_id
        return record

    def end_wait(self, step_id: str, seconds: float) -> None:
        """The user answered: the wait comes off the step and the run works again.

        A wait with no step (the resume menu) only resumes the run.
        """
        record = self.step(step_id)
        if record is not None:
            record.add_wait(seconds)
        self.resume_work()

    def reopen_loop(self, step_ids: list[str], *, opener_id: str) -> None:
        """Start another loop round on these steps; only the opener counts it."""
        records = self._records(step_ids)
        self._require_none_running(records, "reopen the loop")
        for record in records:
            record.reopen_round(opener=record.step_id == opener_id)

    def close_loop(self, step_ids: list[str], *, opener_id: str) -> None:
        """Settle the loop's remaining steps without running them.

        Whether they delivered before depends on the opener having run more than one round.
        """
        opener = self.step(opener_id)
        ran_before = opener is not None and opener.rounds > 1
        records = [record for record in self._records(step_ids) if not record.settled]
        self._require_none_running(records, "close the loop")
        for record in records:
            record.close_with_loop(ran_before=ran_before)

    def retire_steps_outside(self, defined_ids: set[str]) -> None:
        """Skip the unsettled steps of a definition edited since the run started.

        Fan-out children belong to their defined base step and are kept.
        """
        dropped = []
        for item in self.steps:
            base, separator, _item = item.step_id.rpartition(FAN_OUT_SEPARATOR)
            if item.step_id in defined_ids or (separator and base in defined_ids):
                continue
            if not item.settled:
                dropped.append(item)
        self._require_none_running(dropped, "retire steps")
        for item in dropped:
            item.retire()

    def _records(self, step_ids: list[str]) -> list[StepRecord]:
        """Each listed step once: a repeated id must not change its step twice."""
        unique = dict.fromkeys(step_ids)
        return [record for step_id in unique if (record := self.step(step_id)) is not None]

    def _require_none_running(self, records: list[StepRecord], action: str) -> None:
        """Checked before any step changes, so a refused change leaves the run as it was.

        A half-applied change would be persisted by the next save.
        """
        running = [record.step_id for record in records if record.status == StepStatus.RUNNING]
        if running:
            raise InvalidTransition(f"run {self.id}: cannot {action} while {running} runs")

    def complete(self) -> None:
        """Every step settled; the workflow is over."""
        if self.is_incomplete():
            raise InvalidTransition(f"run {self.id}: cannot complete with unsettled steps")
        self.status = RunStatus.COMPLETED

    def end(self, exit_code: int) -> None:
        """Record why the run stopped early (stop, block or failure)."""
        if exit_code == 0:
            raise InvalidTransition(f"run {self.id}: a clean exit must go through complete()")
        self.status = RunStatus.for_exit_code(exit_code)

    def crash(self) -> None:
        """The run broke mid-step: the step that was running and the run both fail."""
        self.fail_running_steps()
        self.status = RunStatus.FAILED

    def fail_running_steps(self) -> None:
        """Fail the steps a crash left `running`."""
        for item in self.steps:
            if item.status == StepStatus.RUNNING:
                item.fail()
