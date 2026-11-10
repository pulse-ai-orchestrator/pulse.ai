"""Commit a delivered step, then publish the branch when the run is over."""

from __future__ import annotations

from pathlib import Path

from pulse.domain.ports import WorkspaceError
from pulse.domain.run import RunRecord
from pulse.domain.workflow import StepDef
from pulse.orchestrator import wording
from pulse.orchestrator.fanout import Item
from pulse.orchestrator.render import TemplateError, render
from pulse.orchestrator.wiring import Wiring, notify

DEFAULT_PULL_REQUEST_TEMPLATE = "{{prompt}}\n\n{{commits}}"


def snapshot_if_committing(wiring: Wiring, run: RunRecord, step: StepDef) -> dict[str, str]:
    if not _will_commit(wiring, run, step):
        return {}
    return wiring.ports.workspace.snapshot(wiring.exec_dir)


def commit_delivery(
    wiring: Wiring,
    run: RunRecord,
    step: StepDef,
    *,
    delivered: bool,
    subject: str,
    item: Item | None,
    before: dict[str, str],
) -> None:
    if not delivered or not _will_commit(wiring, run, step):
        return
    after = wiring.ports.workspace.snapshot(wiring.exec_dir)
    paths = _changed(before, after)
    if not paths:
        return
    message = wording.commit_message(
        step.commit_type, subject, item_id=item.id if item is not None else ""
    )
    try:
        wiring.ports.workspace.commit(wiring.exec_dir, paths, message)
    except WorkspaceError as error:
        notify(wiring, wording.commit_failed(str(error)))


def publish_ready_request(wiring: Wiring, run: RunRecord, *, template: str) -> None:
    """Push and open the draft once, leaving the worktree for the steps still ahead.

    A push or forge failure is reported and the run goes on: the end of the run
    pushes again and opens the request if this attempt did not.
    """
    if run.request_opened or not wiring.auto_pull_request:
        return
    subjects = _subjects(wiring, run)
    if subjects is None:
        return
    try:
        wiring.ports.workspace.publish_branch(run.branch)
    except WorkspaceError as error:
        notify(wiring, wording.publish_failed(str(error)))
        return
    if _open_request(wiring, run, subjects, template):
        run.note_request_opened()
        wiring.runs.save(run)


def publish_finished_run(wiring: Wiring, run: RunRecord, *, template: str) -> int | None:
    """Push, open the request if it is not open yet, and drop the local worktree.

    `1` when the push fails. Push sits behind Autocommit: without it the user
    never opted into publishing, even if the agent committed on its own.
    """
    subjects = _subjects(wiring, run)
    if subjects is None:
        return None
    cwd = Path(run.worktree_path)
    try:
        wiring.ports.workspace.publish_branch(run.branch)
    except WorkspaceError as error:
        notify(wiring, wording.publish_failed(str(error)))
        return 1
    if not run.request_opened and _open_request(wiring, run, subjects, template):
        run.note_request_opened()
    _drop_local(wiring, run, cwd)
    return None


def _subjects(wiring: Wiring, run: RunRecord) -> list[str] | None:
    if not wiring.atomic_commits:
        return None
    if not run.owns_branch or not run.branch_base or not run.worktree_path:
        return None
    subjects = wiring.ports.workspace.commits_after(Path(run.worktree_path), run.branch_base)
    if not subjects:
        return None
    return subjects


def _will_commit(wiring: Wiring, run: RunRecord, step: StepDef) -> bool:
    return bool(wiring.atomic_commits and run.branch_owned and step.commit_type)


def pull_request_body(template: str, *, prompt: str, branch: str, commits: list[str]) -> str:
    """The workflow's `pull_request_template`, or the prompt and commits when it has none."""
    listed = "\n".join(f"- {subject}" for subject in commits)
    context = {"prompt": prompt.strip(), "branch": branch, "commits": listed}
    return render(template or DEFAULT_PULL_REQUEST_TEMPLATE, context)


def _open_request(wiring: Wiring, run: RunRecord, subjects: list[str], template: str) -> bool:
    if not wiring.auto_pull_request:
        return False
    try:
        body = pull_request_body(
            template, prompt=run.user_prompt, branch=run.branch, commits=subjects
        )
        wiring.ports.workspace.open_pull_request(
            branch=run.branch, title=run.title or run.branch, body=body
        )
    except (TemplateError, WorkspaceError) as error:
        notify(wiring, wording.pull_request_failed(str(error)))
        return False
    return True


def _drop_local(wiring: Wiring, run: RunRecord, cwd: Path) -> None:
    try:
        wiring.ports.workspace.remove_worktree(cwd)
    except WorkspaceError:
        notify(wiring, wording.worktree_left_dirty())
        return
    run.work_in(worktree_path="", branch=run.branch)
    try:
        wiring.ports.workspace.delete_local_branch(run.branch)
    except WorkspaceError as error:
        notify(wiring, wording.local_branch_kept(str(error)))


def _changed(before: dict[str, str], after: dict[str, str]) -> list[str]:
    """Dirty paths the step touched. One gone from `after` is back to HEAD or was an
    untracked file now deleted: nothing to stage, and naming it fails `git add`.
    """
    return sorted(path for path, digest in after.items() if before.get(path) != digest)
