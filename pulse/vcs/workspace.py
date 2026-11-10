"""[pulse.domain.ports.Workspace] over git: the project root and per-run worktrees."""

from __future__ import annotations

from pathlib import Path

from pulse import vcs
from pulse.domain.branch_name import worktree_folders
from pulse.vcs import changes, publish
from pulse.vcs.request_template import load_request_template


class GitWorkspace:
    """A project on disk; a run's worktree goes under `worktrees/`, named after its branch.

    The project root and the repository root may differ (a project in a
    subfolder of a repo): branches and worktrees belong to the repository, and
    a run works in the project's subfolder of its worktree, as it would
    without one.
    """

    def __init__(self, root: Path, *, worktrees: Path) -> None:
        self._root = root
        self._worktrees = worktrees

    @property
    def root(self) -> Path:
        return self._root

    def is_repo(self) -> bool:
        return vcs.is_repo(self._root)

    def current_branch(self) -> str:
        return vcs.current_branch(self._root)

    def has_branch(self, branch: str) -> bool:
        repo = vcs.repo_root(self._root)
        return repo is not None and vcs.branch_exists(repo, branch)

    def worktree_exists(self, path: str) -> bool:
        return bool(path) and Path(path).exists()

    def attach_worktree(self, run_id: str, branch: str) -> Path:
        # Only the project subfolder may be gone: git refuses a second worktree
        # on a branch the remaining one still has checked out.
        for folder in worktree_folders(branch, run_id):
            held = self._worktrees / folder
            if held.exists() and vcs.current_branch(held) == branch:
                return self._project_in(held)
        target = self._target(run_id, branch)
        vcs.attach_worktree(self._repo(), target, branch)
        return self._project_in(target)

    def add_worktree(self, run_id: str, branch: str) -> tuple[Path, str]:
        target = self._target(run_id, branch)
        created = vcs.add_worktree(self._repo(), target, branch)
        return self._project_in(target), created

    def _target(self, run_id: str, branch: str) -> Path:
        """The branch's folder, or its fallback when another worktree or a leftover holds it."""
        folder, fallback = worktree_folders(branch, run_id)
        target = self._worktrees / folder
        return self._worktrees / fallback if target.exists() else target

    def head(self, cwd: Path) -> str:
        return vcs.head_sha(cwd)

    def snapshot(self, cwd: Path) -> dict[str, str]:
        return changes.snapshot(cwd)

    def commit(self, cwd: Path, paths: list[str], message: str) -> None:
        changes.commit_paths(cwd, paths, message)

    def commits_after(self, cwd: Path, base: str) -> list[str]:
        return vcs.commits_after(cwd, base)

    def publish_branch(self, branch: str) -> None:
        vcs.push_branch(self._repo(), branch)

    def remove_worktree(self, path: Path) -> None:
        vcs.remove_worktree(self._repo(), path)

    def delete_local_branch(self, branch: str) -> None:
        vcs.delete_local_branch(self._repo(), branch)

    def open_pull_request(self, *, branch: str, title: str, body: str) -> None:
        repo = self._repo()
        base = changes.default_branch(repo)
        if not base:
            raise vcs.GitError("origin has no default branch (`git remote set-head origin -a`)")
        publish.open_request(repo, branch=branch, title=title, body=body, base=base)

    def request_template(self, cwd: Path) -> str:
        repo = vcs.repo_root(cwd)
        if repo is None:
            return ""
        return load_request_template(repo)

    def _project_in(self, worktree: Path) -> Path:
        """The project's folder inside `worktree`, created when the checkout lacks it."""
        project = worktree / self._root.resolve().relative_to(self._repo())
        project.mkdir(parents=True, exist_ok=True)
        return project

    def _repo(self) -> Path:
        repo = vcs.repo_root(self._root)
        if repo is None:
            raise vcs.GitError(f"{self._root} is not a git repository")
        return repo
