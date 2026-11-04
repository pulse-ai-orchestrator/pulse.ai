from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from pulse.domain.ports import StepRow
from pulse.history.events import ContextUsage
from pulse.history.log_wording import QUESTIONNAIRE_NOTICE, phase_title
from pulse.history.tool_detail import (
    build_tool_labels,
    extract_paths,
    merge_tool_update,
)
from pulse.replies.text_questionnaire import (
    QUESTIONNAIRE_START,
    extract_questionnaire_block,
)
from pulse.tui import strings
from pulse.tui.artifacts import artifact_has_content
from pulse.tui.cursor_store import CursorStoreIndex
from pulse.tui.state import CockpitState, LogKind

_TOOL_KINDS = frozenset({"tool_call", "tool_call_update", "tool_result"})
_SETUP_READY = re.compile(r"SETUP_READY\s*", re.IGNORECASE)
_COUNT_ONLY_RE = re.compile(r"^\d+\s+files?$", re.IGNORECASE)
_PLACEHOLDER_TITLE = "…"

NotifyFn = Callable[[], None]
ContextFn = Callable[[str], None]


def _is_placeholder(title: str, detail: str = "") -> bool:
    text = title.strip()
    if text in {"", "…", "..."}:
        return not detail.strip()
    return False


def _is_vague_search(title: str) -> bool:
    return bool(_COUNT_ONLY_RE.match(title.strip()))


def _tool_done(update: dict[str, Any]) -> bool:
    status = str(update.get("status") or "").strip().lower()
    return status in {"completed", "failed"}


def _tool_failed(update: dict[str, Any]) -> bool:
    status = str(update.get("status") or "").strip().lower()
    if status in {"failed", "error"}:
        return True
    raw_output = update.get("rawOutput")
    if isinstance(raw_output, dict) and raw_output.get("error"):
        return True
    return False


@dataclass(frozen=True)
class _ToolView:
    """How one tool call reads in the log, before it is shown or refreshed."""

    log_kind: LogKind
    target: str
    detail: str
    done: bool

    @property
    def placeholder(self) -> bool:
        return _is_placeholder(self.target, self.detail)

    @property
    def pending(self) -> bool:
        return not self.done or self.placeholder

    @property
    def waiting_for_args(self) -> bool:
        return self.placeholder and not self.done

    @property
    def display_title(self) -> str:
        return _PLACEHOLDER_TITLE if self.placeholder else self.target

    @property
    def display_detail(self) -> str:
        return "" if self.placeholder else self.detail


class CockpitSink:
    def __init__(
        self,
        state: CockpitState,
        *,
        on_change: NotifyFn | None = None,
        cwd: str | None = None,
        session_id: str | None = None,
        on_replay_end: NotifyFn | None = None,
        on_context: ContextFn | None = None,
    ) -> None:
        self._state = state
        self._on_change = on_change
        self._on_replay_end = on_replay_end
        self._on_context = on_context
        self._cwd = cwd
        self._streaming_message = False
        self._agent_text = ""
        self._questionnaire_mode = False
        self._questionnaire_announced = False
        self._visible_tool_ids: set[str] = set()
        self._tool_payloads: dict[str, dict[str, Any]] = {}
        self._store = CursorStoreIndex(session_id)
        self._pending_session_phase = False
        self._update_handlers: dict[str, Callable[[dict[str, Any]], None]] = {
            "agent_message_chunk": self._on_message_chunk,
            "agent_thought_chunk": self._on_thought_chunk,
            "usage_update": self._on_usage_update,
            **dict.fromkeys(_TOOL_KINDS, self._handle_tool),
        }

    def set_cwd(self, cwd: str | None) -> None:
        self._cwd = cwd

    def set_context(self, *, cwd: str, branch: str) -> None:
        """Record where the run works; artifact paths resolve from there.

        With a worktree the agent writes outside the project root, so the pane
        must be repointed. `on_context` lets the cockpit forward the cwd to the
        pane, which keeps its own copy.
        """
        if cwd:
            self._cwd = cwd
        self._state.set_branch(branch)
        if self._on_context is not None:
            self._on_context(self._cwd or "")
        self._emit()

    def set_session_id(self, session_id: str | None) -> None:
        self._store.set_session(session_id)
        sid = session_id or ""
        self._state.acp_session_id = sid
        self._pending_session_phase = bool(sid)
        if not sid:
            return
        refs = self._state.acp_sessions
        if refs and refs[-1].get("session_id") == sid:
            return
        refs.append({"session_id": sid, "phase_id": ""})

    def reset_capture(self) -> None:
        self._agent_text = ""
        self._questionnaire_mode = False
        self._questionnaire_announced = False
        self._streaming_message = False

    def agent_text(self) -> str:
        return self._agent_text

    def has_text_questionnaire(self) -> bool:
        return extract_questionnaire_block(self._agent_text) is not None

    def handle_update(self, params: dict[str, Any]) -> None:
        update = params.get("update", params)
        if not isinstance(update, dict):
            return
        handler = self._update_handlers.get(str(update.get("sessionUpdate")))
        if handler is not None:
            handler(update)

    def _on_usage_update(self, update: dict[str, Any]) -> None:
        usage = ContextUsage.parse(update)
        if usage is not None and self._state.record_context_usage(usage):
            self._emit()

    def _on_message_chunk(self, update: dict[str, Any]) -> None:
        content = update.get("content", {})
        if content.get("type") != "text":
            return
        text = str(content.get("text", ""))
        if text:
            self._absorb_agent_text(text)

    def _absorb_agent_text(self, text: str) -> None:
        self._agent_text += text
        self._maybe_enter_questionnaire_mode()
        if self._questionnaire_mode:
            self._announce_questionnaire_once()
            return
        visible = _SETUP_READY.sub("", text)
        changed = self._backfill_vague_entries()
        if visible:
            self._state.append_assistant(visible)
            self._streaming_message = True
        if visible or changed:
            self._emit()

    def _on_thought_chunk(self, update: dict[str, Any]) -> None:
        if self._backfill_vague_entries():
            self._emit()

    def set_model(self, model: str) -> None:
        self._finish_message_line()
        self._state.set_model(model)
        self._backfill_vague_entries()
        self._emit()

    def begin_phase(self, title: str, *, turn: int = 1) -> None:
        self.finish()
        self.reset_capture()
        self._visible_tool_ids.clear()
        self._tool_payloads.clear()
        self._state.begin_phase(title, turn=turn)
        if self._pending_session_phase and self._state.acp_sessions:
            self._state.acp_sessions[-1]["phase_id"] = self._state._entry_phase_id()
            self._pending_session_phase = False
        self._state.add_info(phase_title(title, turn))
        self._emit()

    def apply_phase_statuses(
        self,
        *,
        steps: Sequence[StepRow] = (),
        done_ids: Sequence[str] = (),
        skipped_ids: Sequence[str] = (),
        failed_ids: Sequence[str] = (),
        blocked_ids: Sequence[str] = (),
    ) -> None:
        self._state.apply_phase_statuses(
            steps=steps,
            done_ids=done_ids,
            skipped_ids=skipped_ids,
            failed_ids=failed_ids,
            blocked_ids=blocked_ids,
        )
        self._emit()

    def replay_finished(self) -> None:
        """The run's past has been replayed; events from here on are live.

        Attachers use this cut to fix what replay cannot reproduce, namely step
        durations re-stamped by `phase.begin`.
        """
        self._finish_message_line()
        if self._on_replay_end is not None:
            self._on_replay_end()
        self._emit()

    def mark_awaiting(self, waiting: bool, *, since: float | None = None) -> None:
        """Question opened/closed: freeze or release the step timer.

        Driven by the engine, not this screen's dock, so every attached window
        pauses together. `since` (wall-clock) is when the wait actually began.
        """
        if waiting:
            self._state.begin_waiting(since=since)
        else:
            self._state.end_waiting()
        self._emit()

    def begin_user_wait(self) -> None:
        self.mark_awaiting(True)

    def end_user_wait(self) -> None:
        self.mark_awaiting(False)

    def mark_stopped(self) -> None:
        self._finish_message_line()
        self._state.mark_stopped()
        self._emit()

    def info(self, title: str) -> None:
        text = str(title or "").strip()
        if not text:
            return
        self._finish_message_line()
        self._state.add_info(text)
        self._emit()

    def error(self, title: str, reason: str = "") -> None:
        text = str(title or "").strip() or strings.ERROR
        self._finish_message_line()
        self._state.add_error(text, str(reason or "").strip())
        self._emit()

    def finish(self) -> None:
        self._finish_message_line()

    def finish_question_prompt(self) -> None:
        self._finish_message_line()
        self._state.finish_assistant()
        self._emit()

    def _enrich_from_store(
        self,
        merged: dict[str, Any],
        tool_id: str,
        *,
        force: bool = False,
    ) -> dict[str, Any]:
        if not tool_id:
            return merged
        raw_input = merged.get("rawInput")
        if isinstance(raw_input, dict) and raw_input and not force:
            return merged
        args = self._store.lookup_args(tool_id, force=force)
        if not args:
            return merged
        return merge_tool_update(merged, {"rawInput": args})

    def _backfill_vague_entries(self) -> bool:
        changed = False
        for entry in self._state.entries:
            if not entry.tool_id:
                continue
            needs = False
            if entry.kind == LogKind.SEARCH and _is_vague_search(entry.title):
                needs = True
            elif entry.kind in {
                LogKind.READ,
                LogKind.EDIT,
                LogKind.WRITE,
            } and entry.title.strip() in {
                "…",
                "...",
            }:
                needs = True
            if not needs:
                continue
            payload = self._tool_payloads.get(entry.tool_id, {"toolCallId": entry.tool_id})
            enriched = self._enrich_from_store(payload, entry.tool_id, force=True)
            self._tool_payloads[entry.tool_id] = enriched
            log_kind, target, detail = build_tool_labels(
                enriched,
                cwd=self._cwd,
                fallback_kind=entry.kind,
            )
            if _is_placeholder(target, detail):
                continue
            if entry.kind == LogKind.SEARCH and _is_vague_search(target):
                continue
            done = _tool_done(enriched)
            self._state.update_tool_entry(
                entry.tool_id,
                kind=log_kind,
                title=target,
                detail=detail,
                pending=not done,
            )
            self._record_tool_metrics(enriched, log_kind, target, ready=done)
            changed = True
        return changed

    def _handle_tool(self, update: dict[str, Any]) -> None:
        kind = str(update.get("sessionUpdate"))
        announced = kind == "tool_call"
        tool_id = str(update.get("toolCallId") or "")
        merged = self._remember_tool_payload(update, tool_id, force_store=not announced)
        existing_kind = self._entry_kind(tool_id)
        log_kind, target, detail = build_tool_labels(
            merged,
            cwd=self._cwd,
            fallback_kind=existing_kind,
        )
        view = _ToolView(
            log_kind=log_kind,
            target=target,
            detail=detail,
            done=_tool_done(merged) or kind == "tool_result",
        )
        changed = False
        if tool_id in self._visible_tool_ids:
            # A repeated announcement, or an update still without arguments,
            # can only be improved by the late store lookup in the backfill.
            if not announced and not view.waiting_for_args:
                changed = self._refresh_tool_entry(
                    tool_id, merged, view, kind=existing_kind or view.log_kind
                )
        elif announced or not view.waiting_for_args:
            self._show_tool_entry(
                tool_id, merged, view, pending=True if announced else view.pending
            )
            changed = True
        if self._backfill_vague_entries():
            changed = True
        if changed:
            self._emit()

    def _remember_tool_payload(
        self,
        update: dict[str, Any],
        tool_id: str,
        *,
        force_store: bool,
    ) -> dict[str, Any]:
        if not tool_id:
            return update
        merged = merge_tool_update(self._tool_payloads.get(tool_id, {}), update)
        merged = self._enrich_from_store(merged, tool_id, force=force_store)
        self._tool_payloads[tool_id] = merged
        return merged

    def _entry_kind(self, tool_id: str) -> LogKind | None:
        if not tool_id:
            return None
        return next(
            (entry.kind for entry in self._state.entries if entry.tool_id == tool_id),
            None,
        )

    def _refresh_tool_entry(
        self,
        tool_id: str,
        merged: dict[str, Any],
        view: _ToolView,
        *,
        kind: LogKind,
    ) -> bool:
        updated = self._state.update_tool_entry(
            tool_id,
            kind=kind,
            title=None if view.placeholder else view.target,
            detail=None if view.placeholder else view.detail,
            pending=view.pending,
        )
        if updated is None:
            return False
        self._record_tool_metrics(merged, kind, view.target, ready=not view.pending)
        return True

    def _show_tool_entry(
        self,
        tool_id: str,
        merged: dict[str, Any],
        view: _ToolView,
        *,
        pending: bool,
    ) -> None:
        if tool_id:
            self._visible_tool_ids.add(tool_id)
        self._finish_message_line()
        self._state.add_tool_entry(
            view.log_kind,
            view.display_title,
            view.display_detail,
            tool_id=tool_id,
            pending=pending,
        )
        self._record_tool_metrics(merged, view.log_kind, view.target, ready=not pending)

    def _record_tool_metrics(
        self,
        update: dict[str, Any],
        log_kind: LogKind,
        target: str,
        *,
        ready: bool,
    ) -> None:
        if _tool_failed(update):
            issue_key = str(update.get("toolCallId") or target or "").strip()
            if issue_key:
                self._state.record_issue(issue_key)

        paths = extract_paths(update, cwd=self._cwd)
        if not paths and log_kind in {
            LogKind.READ,
            LogKind.EDIT,
            LogKind.WRITE,
            LogKind.LIST,
        }:
            text = str(target or "").strip()
            if text and text not in {"…", "..."} and ("/" in text or "." in text):
                paths = [text]
        if paths:
            self._state.record_files(paths)
            if log_kind in {LogKind.WRITE, LogKind.EDIT}:
                for path in paths:
                    self._state.upsert_artifact(
                        path,
                        ready=ready,
                        has_content=artifact_has_content(path, self._cwd),
                        cwd=self._cwd,
                    )

    def _maybe_enter_questionnaire_mode(self) -> None:
        if self._questionnaire_mode:
            return
        if QUESTIONNAIRE_START.search(self._agent_text):
            self._questionnaire_mode = True
            self._finish_message_line()

    def _announce_questionnaire_once(self) -> None:
        if self._questionnaire_announced:
            return
        self._questionnaire_announced = True
        self._state.add_info(QUESTIONNAIRE_NOTICE)
        self._emit()

    def _finish_message_line(self) -> None:
        if self._streaming_message:
            self._streaming_message = False
            self._state.finish_assistant()

    def _emit(self) -> None:
        if self._on_change is not None:
            self._on_change()
