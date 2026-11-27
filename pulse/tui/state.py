from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from pulse.domain.control import RUN_BLOCKED, RUN_STOPPED
from pulse.domain.run import RunStatus
from pulse.history import log_wording
from pulse.history.events import (
    ArtifactItem,
    ContextUsage,
    LogEntry,
    LogKind,
    PhaseItem,
    PhaseStatus,
    format_tokens,
)
from pulse.tui import strings
from pulse.tui.artifact_tab import ArtifactTab

Listener = Callable[[], None]
_FOCUS_CYCLE = ("phases", "stream", "artifact")
NAV_PHASE = "phase"
FANOUT_SEP = ":"


@dataclass
class CockpitState(ArtifactTab):
    workflow_id: str = ""
    workflow_label: str = ""
    surface_title: str = strings.STREAM_DEFAULT_SURFACE
    agent_label: str = strings.AGENT
    model_label: str = ""
    branch_label: str = ""
    phases: list[PhaseItem] = field(default_factory=list)
    entries: list[LogEntry] = field(default_factory=list)
    artifacts: list[ArtifactItem] = field(default_factory=list)
    selected_phase_index: int = 0
    selected_artifact_path: str = ""
    follow_artifact: bool = True
    artifact_pane_open: bool = False
    focus_target: str = "phases"
    running: bool = False
    stopped: bool = False
    awaiting_input: bool = False
    can_stop: bool = False
    exit_code: int | None = None
    acp_session_id: str = ""
    acp_sessions: list[dict[str, str]] = field(default_factory=list)
    _listeners: list[Listener] = field(default_factory=list, repr=False)
    _next_entry_id: int = 1
    _active_assistant_id: int | None = None
    _follow_live: bool = True
    base_labels: dict[str, str] = field(default_factory=dict, repr=False)

    def subscribe(self, listener: Listener) -> None:
        self._listeners.append(listener)

    def unsubscribe(self, listener: Listener) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    def notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    def configure_workflow(
        self, workflow_id: str, *, label: str = "", steps: Sequence[tuple[str, str]] = ()
    ) -> None:
        """Start a run of `workflow_id`; `steps` draws the sidebar before the run reports them.

        An unknown shape (no `steps`) leaves the sidebar empty: it fills in as
        steps start.
        """
        self.workflow_id = workflow_id
        self.workflow_label = (label or workflow_id).upper()
        self.base_labels = dict(steps)
        self.phases = [PhaseItem(id=step_id, label=name) for step_id, name in steps]
        self.selected_phase_index = 0
        self.entries = []
        self.artifacts = []
        self.selected_artifact_path = ""
        self.follow_artifact = True
        self.artifact_pane_open = False
        self.focus_target = "phases"
        self._next_entry_id = 1
        self._active_assistant_id = None
        self._follow_live = True
        self.running = False
        self.stopped = False
        self.awaiting_input = False
        self.can_stop = True
        self.exit_code = None
        self.notify()

    def done_count(self) -> int:
        return sum(
            1 for phase in self.phases if phase.status in {PhaseStatus.DONE, PhaseStatus.SKIPPED}
        )

    def total_count(self) -> int:
        return len(self.phases)

    def run_status(self) -> RunStatus:
        """The one status that names the whole run, most urgent first.

        Read from the steps too, so a run reopened from history (never
        `running`, no exit code) still names itself.
        """
        statuses = {phase.status for phase in self.phases}
        if self.awaiting_input or any(phase.awaiting_since is not None for phase in self.phases):
            return RunStatus.AWAITING_INPUT
        if self.stopped:
            return RunStatus.STOPPED
        if self.exit_code == RUN_BLOCKED or PhaseStatus.BLOCKED in statuses:
            return RunStatus.BLOCKED
        if PhaseStatus.FAILED in statuses or self.exit_code not in {None, 0}:
            return RunStatus.FAILED
        if PhaseStatus.RUNNING in statuses:
            return RunStatus.RUNNING
        if self.phases and self.done_count() == self.total_count():
            return RunStatus.COMPLETED
        return RunStatus.PENDING

    def elapsed_seconds(self, now: float | None = None) -> float:
        """Agent time of the run: every step's clock, net of waiting on the user."""
        return sum(phase.elapsed_seconds(now) or 0.0 for phase in self.phases)

    def begin_phase(self, title: str, *, turn: int = 1) -> None:
        """`title` names the phase; a later `turn` shows as its continuation."""
        self.finish_assistant()
        matched = self._match_phase(title)
        now = time.monotonic()
        matched_index = self.phases.index(matched) if matched is not None else None
        for phase in self.phases:
            if matched is not None and phase is matched:
                continue
            if phase.status == PhaseStatus.RUNNING:
                phase.finish(now)
        if matched is not None:
            if matched.status != PhaseStatus.RUNNING or matched.started_at is None:
                matched.started_at = now - matched.closed_seconds()
                matched.ended_at = None
                matched.waiting_total = 0.0
            matched.status = PhaseStatus.RUNNING
            if matched_index is not None and self._follow_live:
                self.selected_phase_index = matched_index
                self.follow_artifact = True
        self.surface_title = log_wording.phase_title(title, turn).upper()
        self.running = True
        self.notify()

    def sync_phases(self, steps: Sequence[Mapping[str, object]]) -> None:
        """Rebuild the phase list from what the engine is actually running.

        The list changes mid-run (a fan-out step becomes N steps). Existing
        phases are preserved by id so status, duration and counters survive.
        """
        if not steps:
            return
        existing = {phase.id: phase for phase in self.phases}
        selected = self.selected_phase()
        self.phases = [
            existing.get(str(step["id"]))
            or PhaseItem(id=str(step["id"]), label=str(step.get("label", "")))
            for step in steps
        ]
        for phase, step in zip(self.phases, steps, strict=True):
            phase.label = str(step.get("label", "")) or phase.label
            rounds = step.get("rounds", phase.rounds)
            phase.rounds = max(1, rounds or 1) if isinstance(rounds, int) else phase.rounds
        if selected is not None:
            for index, phase in enumerate(self.phases):
                if phase.id == selected.id:
                    self.selected_phase_index = index
                    break
            else:
                self.selected_phase_index = min(
                    self.selected_phase_index, max(0, len(self.phases) - 1)
                )

    def apply_phase_statuses(
        self,
        *,
        steps: Sequence[Mapping[str, object]] = (),
        done_ids: Sequence[str] = (),
        skipped_ids: Sequence[str] = (),
        failed_ids: Sequence[str] = (),
        blocked_ids: Sequence[str] = (),
    ) -> None:
        self.sync_phases(steps)
        done = set(done_ids)
        skipped = set(skipped_ids)
        failed = set(failed_ids)
        blocked = set(blocked_ids)
        now = time.monotonic()
        for phase in self.phases:
            if phase.id in blocked:
                phase.end_as(PhaseStatus.BLOCKED, now)
            elif phase.id in failed:
                phase.end_as(PhaseStatus.FAILED, now)
            elif phase.id in skipped:
                phase.end_as(PhaseStatus.SKIPPED, now)
            elif phase.id in done and phase.status != PhaseStatus.RUNNING:
                phase.status = PhaseStatus.DONE
        self.notify()

    def begin_waiting(self, *, since: float | None = None) -> None:
        """A question opened: freeze the running step's timer.

        If no step is running (e.g. a question between steps), only the run flag
        is set. `since` is the wall-clock time the wait began; when given, the
        timer freezes where the run actually stopped, even for late attachers.
        """
        self.awaiting_input = True
        now = time.monotonic()
        if since is not None:
            now -= max(0.0, time.time() - since)
        for phase in self.phases:
            if phase.status == PhaseStatus.RUNNING:
                phase.begin_waiting(now)
        self.notify()

    def end_waiting(self) -> None:
        self.awaiting_input = False
        now = time.monotonic()
        for phase in self.phases:
            phase.end_waiting(now)
        self.notify()

    def complete_active_phase(self) -> None:
        now = time.monotonic()
        for phase in self.phases:
            if phase.status == PhaseStatus.RUNNING:
                phase.finish(now)
        self.notify()

    def fail_active(self) -> None:
        now = time.monotonic()
        self.awaiting_input = False
        for phase in self.phases:
            phase.end_waiting(now)
            if phase.status == PhaseStatus.RUNNING:
                phase.end_as(PhaseStatus.FAILED, now)
        self.notify()

    def mark_stopped(self) -> None:
        """Stop interrupted the in-flight step: reset it to pending and clear its timer.

        The interrupted step restarts from scratch on resume, so its spent time
        no longer counts.
        """
        self.stopped = True
        self.awaiting_input = False
        for item in self.phases:
            if item.status == PhaseStatus.RUNNING:
                item.restart()
            else:
                item.awaiting_since = None
        self.notify()

    def mark_finished(self, exit_code: int = 0) -> None:
        if exit_code == 0:
            self.complete_active_phase()
        elif exit_code == RUN_STOPPED:
            self.mark_stopped()
        else:
            self.fail_active()
        self.running = False
        self.awaiting_input = False
        self.exit_code = exit_code
        self.notify()

    def set_model(self, model: str) -> None:
        self.model_label = model
        self.notify()

    def set_agent(self, agent: str) -> None:
        self.agent_label = agent
        self.notify()

    def set_branch(self, branch: str) -> None:
        self.branch_label = branch
        self.notify()

    def add_tool_entry(
        self,
        kind: LogKind,
        title: str,
        detail: str = "",
        *,
        tool_id: str = "",
        pending: bool = False,
    ) -> LogEntry:
        self._clear_active_flags()
        self._active_assistant_id = None
        entry = LogEntry(
            kind=kind,
            title=title,
            detail=detail,
            active=True,
            pending=pending,
            entry_id=self._next_entry_id,
            tool_id=tool_id,
            phase_id=self._entry_phase_id(),
        )
        self._next_entry_id += 1
        self.entries.append(entry)
        self.notify()
        return entry

    def record_files(self, paths: list[str] | tuple[str, ...]) -> bool:
        active = self._active_phase()
        targets = [active] if active is not None else []
        if not targets:
            return False
        changed = False
        for path in paths:
            key = str(path or "").strip()
            if not key or key in {"…", "..."}:
                continue
            for active in targets:
                if key in active._seen_files:
                    continue
                active._seen_files.add(key)
                active.files = len(active._seen_files)
                changed = True
        if changed:
            self.notify()
        return changed

    def record_context_usage(self, usage: ContextUsage) -> bool:
        active = self._active_phase()
        if active is None or active.context == usage:
            return False
        active.context = usage
        self.notify()
        return True

    def context_total(self) -> int:
        """Sum of each step's last reading: one ACP session per step, none shared."""
        return sum(phase.context.used for phase in self.phases if phase.context is not None)

    def run_context_label(self) -> str:
        total = self.context_total()
        return strings.CONTEXT_LABEL.format(tokens=format_tokens(total)) if total else ""

    @staticmethod
    def context_label(phase: PhaseItem) -> str:
        if phase.context is None:
            return ""
        return strings.CONTEXT_LABEL.format(tokens=format_tokens(phase.context.used))

    def record_issue(self, key: str) -> bool:
        active = self._active_phase()
        targets = [active] if active is not None else []
        if not targets:
            return False
        token = str(key or "").strip()
        if not token:
            return False
        changed = False
        for active in targets:
            if token in active._seen_issues:
                continue
            active._seen_issues.add(token)
            active.issues = len(active._seen_issues)
            changed = True
        if changed:
            self.notify()
        return True

    def update_tool_entry(
        self,
        tool_id: str,
        *,
        kind: LogKind | None = None,
        title: str | None = None,
        detail: str | None = None,
        pending: bool | None = None,
    ) -> LogEntry | None:
        if not tool_id:
            return None
        for entry in self.entries:
            if entry.tool_id != tool_id:
                continue
            if kind is not None:
                entry.kind = kind
            if title is not None and title.strip():
                entry.title = title.strip()
            if detail is not None:
                entry.detail = detail.strip()
            if pending is not None:
                entry.pending = pending
            self._clear_active_flags()
            entry.active = True
            self._active_assistant_id = None
            self.notify()
            return entry
        return None

    def add_info(self, title: str) -> None:
        self._clear_active_flags()
        self._active_assistant_id = None
        entry = LogEntry(
            kind=LogKind.INFO,
            title=title,
            detail=title,
            active=True,
            entry_id=self._next_entry_id,
            phase_id=self._entry_phase_id(),
        )
        self._next_entry_id += 1
        self.entries.append(entry)
        self.notify()

    def add_error(self, title: str, reason: str = "") -> None:
        text = str(title or strings.ERROR).strip() or strings.ERROR
        detail = str(reason or "").strip()
        self._clear_active_flags()
        self._active_assistant_id = None
        entry = LogEntry(
            kind=LogKind.ERROR,
            title=text,
            detail=detail or text,
            active=True,
            entry_id=self._next_entry_id,
            phase_id=self._entry_phase_id(),
        )
        self._next_entry_id += 1
        self.entries.append(entry)
        self.notify()

    def has_error(self) -> bool:
        return any(entry.kind == LogKind.ERROR for entry in self.entries)

    def append_assistant(self, text: str) -> None:
        if not text:
            return
        if self._active_assistant_id is not None:
            for entry in self.entries:
                if entry.entry_id == self._active_assistant_id:
                    entry.body += text
                    entry.active = True
                    self.notify()
                    return
        self._clear_active_flags()
        entry = LogEntry(
            kind=LogKind.ASSISTANT,
            title=strings.ENTRY_ASSISTANT_TITLE,
            body=text,
            active=True,
            entry_id=self._next_entry_id,
            phase_id=self._entry_phase_id(),
        )
        self._next_entry_id += 1
        self._active_assistant_id = entry.entry_id
        self.entries.append(entry)
        self.notify()

    def finish_assistant(self) -> None:
        self._active_assistant_id = None
        self._clear_active_flags()
        self.notify()

    def add_qa(self, prompt: str, answer: str) -> None:
        question = str(prompt or "").strip()
        reply = str(answer or "").strip() or strings.CANCELLED
        if not question:
            return
        self._active_assistant_id = None
        self._clear_active_flags()
        self.entries.append(
            LogEntry(
                kind=LogKind.QUESTION,
                title=strings.QUESTION,
                body=question,
                active=False,
                entry_id=self._next_entry_id,
                phase_id=self._entry_phase_id(),
            )
        )
        self._next_entry_id += 1
        self.entries.append(
            LogEntry(
                kind=LogKind.ANSWER,
                title=strings.ANSWER,
                body=reply,
                active=True,
                entry_id=self._next_entry_id,
                phase_id=self._entry_phase_id(),
            )
        )
        self._next_entry_id += 1
        self.notify()

    def selected_phase(self) -> PhaseItem | None:
        if not self.phases:
            return None
        index = max(0, min(self.selected_phase_index, len(self.phases) - 1))
        return self.phases[index]

    def selected_nav_item(self) -> PhaseItem | None:
        return self.selected_phase()

    def base_step_label(self, step_id: str) -> str:
        """Step label as named by the workflow definition (`implement` → Implementar).

        Fan-out replaces the parent step with N children, so the parent's name
        only exists in the workflow definition.
        """
        return self.base_labels.get(step_id, "")

    def phase_groups(self) -> list[tuple[str, list[tuple[int, PhaseItem]]]]:
        """Phases in order, with fan-out children grouped under their parent.

        An empty key means a standalone phase. Indices are included because
        navigation still operates on `phases`; grouping is display-only.
        """
        groups: list[tuple[str, list[tuple[int, PhaseItem]]]] = []
        for index, phase in enumerate(self.phases):
            base, sep, _ = phase.id.partition(FANOUT_SEP)
            key = base if sep else ""
            if key and groups and groups[-1][0] == key:
                groups[-1][1].append((index, phase))
            else:
                groups.append((key, [(index, phase)]))
        return groups

    def visible_entries(self) -> list[LogEntry]:
        phase = self.selected_phase()
        if phase is None:
            return list(self.entries)
        pid = phase.id
        return [entry for entry in self.entries if entry.phase_id == pid]

    def select_phase(self, index: int) -> None:
        if not self.phases:
            return
        self.selected_phase_index = max(0, min(index, len(self.phases) - 1))
        self._sync_follow_and_artifact()

    def move_phase(self, delta: int) -> None:
        self.move_nav(delta)

    def move_nav(self, delta: int) -> None:
        items = self.nav_items()
        if not items:
            return
        current = (NAV_PHASE, self._selected_nav_index())
        try:
            position = items.index(current)
        except ValueError:
            position = 0
        position = max(0, min(position + delta, len(items) - 1))
        _kind, index = items[position]
        self.select_phase(index)

    def nav_items(self) -> list[tuple[str, int]]:
        return [(NAV_PHASE, index) for index in range(len(self.phases))]

    def _sync_follow_and_artifact(self) -> None:
        live = self._live_target()
        self._follow_live = live is None or live == (NAV_PHASE, self._selected_nav_index())
        visible = self.visible_artifacts()
        if self._follow_live:
            self.follow_artifact = True
            if visible:
                self.selected_artifact_path = visible[-1].path
        elif visible:
            paths = {item.path for item in visible}
            if self.selected_artifact_path not in paths:
                self.selected_artifact_path = visible[-1].path
        self.notify()

    def toggle_focus(self) -> None:
        if not self.artifact_pane_open:
            if self.focus_target == "artifact":
                self.focus_target = "stream"
            else:
                self.focus_target = "stream" if self.focus_target == "phases" else "phases"
            self.notify()
            return
        try:
            index = _FOCUS_CYCLE.index(self.focus_target)
        except ValueError:
            index = 0
        self.focus_target = _FOCUS_CYCLE[(index + 1) % len(_FOCUS_CYCLE)]
        self.notify()

    def snapshot(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "done": self.done_count(),
            "total": self.total_count(),
            "entries": len(self.entries),
            "running": self.running,
        }

    def _running_index(self) -> int | None:
        for index, phase in enumerate(self.phases):
            if phase.status == PhaseStatus.RUNNING:
                return index
        return None

    def _live_target(self) -> tuple[str, int] | None:
        phase_index = self._running_index()
        if phase_index is not None:
            return (NAV_PHASE, phase_index)
        return None

    def _selected_nav_index(self) -> int:
        return self.selected_phase_index

    def _active_phase(self) -> PhaseItem | None:
        index = self._running_index()
        if index is None:
            return None
        return self.phases[index]

    def _entry_phase_id(self) -> str:
        active = self._active_phase()
        if active is not None:
            return active.id
        started = [phase for phase in self.phases if phase.started_at is not None]
        if started:
            return started[-1].id
        selected = self.selected_phase()
        if selected is not None:
            return selected.id
        return ""

    def _clear_active_flags(self) -> None:
        for entry in self.entries:
            entry.active = False

    def _match_phase(self, title: str) -> PhaseItem | None:
        base = title.lower()
        exact = [phase for phase in self.phases if base in {phase.id.lower(), phase.label.lower()}]
        if exact:
            for status in (PhaseStatus.RUNNING, PhaseStatus.PENDING):
                for phase in exact:
                    if phase.status == status:
                        return phase
            return exact[0]
        for phase in self.phases:
            if phase.id.lower() in base or phase.label.lower() in base:
                return phase
        pending = [phase for phase in self.phases if phase.status == PhaseStatus.PENDING]
        if pending:
            return pending[0]
        return None
