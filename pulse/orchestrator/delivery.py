"""Commit a delivered step, then publish the branch when the run is over."""

from __future__ import annotations

import re
from pathlib import Path

from pulse.domain.control import RUN_STOPPED
from pulse.domain.ports import WorkspaceError
from pulse.domain.run import RunRecord
from pulse.domain.workflow import StepDef
from pulse.orchestrator import wording
from pulse.orchestrator.agent_text import build_pull_request_prompt
from pulse.orchestrator.fanout import Item
from pulse.orchestrator.render import PLACEHOLDER, fill_present
from pulse.orchestrator.turn import TurnResult
from pulse.orchestrator.wiring import Wiring, notify
from pulse.replies.pull_request import parse_pull_request

_COMMIT_TYPES = "feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert"
_CONVENTIONAL_TITLE = re.compile(rf"(?:{_COMMIT_TYPES})(?:\([^()\s]+\))?!?: \S.*", re.IGNORECASE)
_PULL_REQUEST_KEYS = frozenset({"prompt", "branch", "commits"})


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

    `1` when the push fails, `RUN_STOPPED` when the user stopped the run while
    the request was being written: the worktree stays for the resume. Push sits
    behind Autocommit: without it the user never opted into publishing, even if
    the agent committed on its own.
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
    if not wiring.control.checkpoint():
        notify(wiring, wording.RUN_STOPPED_BY_USER)
        return RUN_STOPPED
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
    """The template with the keys Pulse knows, or that text plus the prompt and commits.

    A template that already names `prompt`, `branch` or `commits` is filled and
    left as it is. One that does not gets those two facts after it, so a quiet
    agent still opens a request that says what changed.
    """
    listed = "\n".join(f"- {subject}" for subject in commits)
    context = {"prompt": prompt.strip(), "branch": branch, "commits": listed}
    filled = fill_present(template, context)
    if _mentions_pull_request_key(template):
        return filled
    return "\n\n".join(part for part in (filled.strip(), context["prompt"], listed) if part)


def pull_request_title(*, title: str, branch: str, commits: list[str]) -> str:
    """A Conventional Commits subject. The run title wins when it already is one.

    Commit subjects come back newest first, so the oldest match is the change
    that opened the branch. Anything else keeps the title the user wrote, then
    the branch.
    """
    chosen = title.strip()
    if _conventional(chosen):
        return chosen
    for subject in reversed(commits):
        text = subject.strip()
        if _conventional(text):
            return text
    return chosen or branch


def _open_request(wiring: Wiring, run: RunRecord, subjects: list[str], template: str) -> bool:
    if not wiring.auto_pull_request or not wiring.control.checkpoint():
        return False
    try:
        chosen = _request_template(wiring, template)
        body = _describe_request(wiring, run, chosen, subjects)
        if not wiring.control.checkpoint():
            return False
        wiring.ports.workspace.open_pull_request(
            branch=run.branch,
            title=pull_request_title(title=run.title, branch=run.branch, commits=subjects),
            body=body,
        )
    except WorkspaceError as error:
        notify(wiring, wording.pull_request_failed(str(error)))
        return False
    return True


def _request_template(wiring: Wiring, workflow_template: str) -> str:
    return wiring.ports.workspace.request_template(wiring.exec_dir).strip() or workflow_template


def _describe_request(wiring: Wiring, run: RunRecord, template: str, commits: list[str]) -> str:
    fallback = pull_request_body(
        template, prompt=run.user_prompt, branch=run.branch, commits=commits
    )
    try:
        raw = wiring.session.draft_pull_request(
            workflow=run.workflow_id,
            phase_label=wording.describing_pull_request(),
            prompt_text=build_pull_request_prompt(
                template=template,
                prompt=run.user_prompt,
                branch=run.branch,
                commits=commits,
                summaries=_settled_summaries(run),
            ),
        )
    except Exception as error:  # noqa: BLE001 - the agent session is the boundary; the draft still opens
        notify(wiring, wording.pull_request_draft_failed(str(error)))
        return fallback
    filled = parse_pull_request(TurnResult.parse(raw).summary)
    return filled or fallback


def _settled_summaries(run: RunRecord) -> list[str]:
    return [
        f"{step.label}: {step.summary.strip()}"
        for step in run.steps
        if step.settled and step.summary.strip()
    ]


def _mentions_pull_request_key(template: str) -> bool:
    mentioned = {match.group(1).lower() for match in PLACEHOLDER.finditer(template)}
    return bool(mentioned & _PULL_REQUEST_KEYS)


def _conventional(text: str) -> bool:
    return _CONVENTIONAL_TITLE.fullmatch(text) is not None


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
