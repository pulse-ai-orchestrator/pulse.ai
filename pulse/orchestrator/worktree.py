"""Where a run works: the project root, or a git worktree of its own.

The decision lives here; the git behind it is the [pulse.domain.ports.Workspace]
port, so the engine never runs git itself.
"""

from __future__ import annotations

from pathlib import Path

from pulse.domain.branch_name import task_slug
from pulse.domain.ports import RunRepository, Workspace, WorkspaceError
from pulse.domain.run import RunRecord


def prepare_workspace(
    run: RunRecord,
    workspace: Workspace,
    runs: RunRepository,
    *,
    use_worktree: bool,
    branch: str = "",
) -> tuple[Path, str]:
    """Where this run works, and on which branch.

    Four cases, in order:
    1. Resumed run with an existing worktree: reuse it.
    2. Resumed run that lost its worktree but still has its branch: reattach a
       worktree on that branch, regardless of the setting.
    3. No isolation (setting off, or not a git repo): run at the root on the
       project's current branch.
    4. Isolation on: a new worktree for the run, on `branch` or the task slug.

    `workspace.root` stays the run's identity (history looks it up by it); only
    where the agent writes changes.
    """
    if workspace.worktree_exists(run.worktree_path):
        return Path(run.worktree_path), run.branch

    repo = workspace.is_repo()
    if repo and run.owns_branch and workspace.has_branch(run.branch):
        target = workspace.attach_worktree(run.id, run.branch)
        return _work_in(run, runs, target, run.branch)

    if not repo or not use_worktree:
        branch = workspace.current_branch()
        # Where the run started, kept across resumes: what it committed since is
        # what the end of the run publishes.
        base = (run.branch_base or workspace.head(workspace.root)) if repo else ""
        run.work_in(worktree_path="", branch=branch, base=base)
        runs.save(run)
        return workspace.root, branch

    name = _branch_name(run, branch)
    target, created = workspace.add_worktree(run.id, name)
    return _work_in(run, runs, target, created, owns=True, base=workspace.head(target))


def _branch_name(run: RunRecord, requested: str) -> str:
    if run.branch_owned and run.branch:
        return run.branch
    name = requested.strip() or task_slug(run.user_prompt)
    if not name:
        raise WorkspaceError("the run needs a branch name")
    return name


def _work_in(
    run: RunRecord,
    runs: RunRepository,
    target: Path,
    branch: str,
    *,
    owns: bool = False,
    base: str = "",
) -> tuple[Path, str]:
    run.work_in(worktree_path=str(target), branch=branch, owns=owns, base=base)
    runs.save(run)
    return target, branch
