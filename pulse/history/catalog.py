"""History: this workspace's runs, read from the database.

The list is `runs` + `run_steps`, so any workflow shows up without Pulse
knowing what it does.
"""

from __future__ import annotations

from pathlib import Path

from pulse import vcs
from pulse.domain.run import RunRecord, RunStatus
from pulse.history.models import LIVE_STATUSES, HistoryItem, HistoryStatus, HistoryStep
from pulse.store import runs as run_store
from pulse.store.workflow_defs import get_workflow

_RUN_TO_HISTORY = {
    RunStatus.PENDING: HistoryStatus.PENDING,
    RunStatus.RUNNING: HistoryStatus.IN_PROGRESS,
    RunStatus.AWAITING_INPUT: HistoryStatus.AWAITING_INPUT,
    RunStatus.COMPLETED: HistoryStatus.DONE,
    RunStatus.FAILED: HistoryStatus.FAILED,
    RunStatus.STOPPED: HistoryStatus.STOPPED,
    RunStatus.BLOCKED: HistoryStatus.BLOCKED,
}


class HistoryCatalog:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace

    def list_items(self) -> list[HistoryItem]:
        """This workspace's runs, live ones first.

        Within each group the order stays newest-first, as `run_store.list_runs`
        returns it. A run awaiting input counts as live.
        """
        items = [_item(record) for record in run_store.list_runs(self.workspace)]
        return sorted(items, key=lambda item: item.status not in LIVE_STATUSES)

    def search(self, query: str = "") -> list[HistoryItem]:
        items = self.list_items()
        needle = query.strip().lower()
        if not needle:
            return items
        return [item for item in items if _matches(item, needle)]

    def get(self, item_id: str) -> HistoryItem | None:
        record = run_store.load_run(item_id)
        if record is None or record.workspace_root != str(self.workspace.resolve()):
            return None
        return _item(record)

    def delete(self, item_id: str) -> bool:
        """Delete a run from history. `False` means it is not from this workspace.

        The run's worktree goes too, but only if clean: a dirty worktree is kept
        (`remove_worktree` refuses without `--force`) and the run is still removed.
        """
        item = self.get(item_id)
        if item is None:
            return False
        self.remove_worktree(item)
        return run_store.delete_run(item_id)

    def remove_worktree(self, item: HistoryItem, *, force: bool = False) -> bool:
        """Remove the run's worktree. `False` means there was none, or git refused.

        The stored path is cleared even when the directory is already gone, so
        the UI stops offering to remove something that no longer exists.
        """
        path = item.worktree_path
        if not path:
            return False
        repo = vcs.repo_root(self.workspace)
        removed = False
        if repo is not None and Path(path).exists():
            try:
                vcs.remove_worktree(repo, path, force=force)
                removed = True
            except vcs.GitError:
                return False
        run_store.clear_worktree(item.run_id)
        item.worktree_path = ""
        return removed or not Path(path).exists()


def search_history(workspace: Path, query: str = "") -> list[HistoryItem]:
    return HistoryCatalog(workspace).search(query)


def _item(record: RunRecord) -> HistoryItem:
    definition = get_workflow(record.workflow_id)
    return HistoryItem(
        run_id=record.id,
        workflow_id=record.workflow_id,
        workflow_label=definition.label if definition else record.workflow_id,
        title=record.title or record.user_prompt.strip() or record.workflow_id,
        prompt=record.user_prompt,
        status=_RUN_TO_HISTORY.get(record.status, HistoryStatus.PENDING),
        updated_at=record.updated_at or record.created_at,
        steps=[
            HistoryStep(
                id=step.step_id,
                label=step.label or step.step_id,
                status=step.status,
                acp_session_id=step.acp_session_id,
            )
            for step in record.steps
        ],
        artifacts=list(
            dict.fromkeys(entry["path"] for entry in run_store.list_artifacts(record.id))
        ),
        branch=record.branch,
        worktree_path=record.worktree_path,
        duration_seconds=record.elapsed_seconds(),
    )


def _matches(item: HistoryItem, needle: str) -> bool:
    haystack = " ".join(
        [
            item.title,
            item.prompt,
            item.workflow_id,
            item.workflow_label,
            item.status.value,
            item.status_label,
        ]
    ).lower()
    return needle in haystack
