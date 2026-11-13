"""`Workspace`: the git adapter and the in-memory fake keep the same promise.

Engine tests open worktrees on the fake; these assertions run on both, against
a real repository for the git side.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from pulse import vcs
from pulse.domain.ports import Workspace, WorkspaceError
from pulse.vcs.workspace import GitWorkspace
from tests.fakes import FakeWorkspace
from tests.infra.test_worktree import make_repo

pytestmark = pytest.mark.skipif(not vcs.git_available(), reason="git is not on PATH")


def _git(tmp_path: Path, *, repo: bool) -> GitWorkspace:
    root = make_repo(tmp_path / "repo") if repo else tmp_path / "repo"
    root.mkdir(exist_ok=True)
    return GitWorkspace(root, worktrees=tmp_path / "worktrees")


def _fake(tmp_path: Path, *, repo: bool) -> FakeWorkspace:
    return FakeWorkspace(tmp_path / "repo", repo=repo)


def _lose(workspace: Workspace, path: Path) -> None:
    if isinstance(workspace, FakeWorkspace):
        workspace.lose_worktree(path)
    else:
        shutil.rmtree(path)


@pytest.fixture(params=[_git, _fake], ids=["git", "fake"])
def make(request, tmp_path: Path):
    return lambda *, repo=True: request.param(tmp_path, repo=repo)


def test_both_adapters_implement_the_port(make):
    assert isinstance(make(), Workspace)


def test_without_a_template_file_the_request_template_is_empty(make):
    workspace = make()

    assert workspace.request_template(workspace.root) == ""


def test_a_repository_reports_its_branch(make):
    workspace = make()

    assert workspace.is_repo() is True
    assert workspace.current_branch() == "main"
    assert workspace.has_branch("main") is True
    assert workspace.has_branch("nope") is False


def test_a_taken_branch_name_is_refused(make):
    """The caller confirmed the name, so a suffix would publish a different branch."""
    workspace = make()

    first, first_branch = workspace.add_worktree("run-a", "corrigir-o-login")

    with pytest.raises(WorkspaceError, match="already exists"):
        workspace.add_worktree("run-b", "corrigir-o-login")

    assert first_branch == "corrigir-o-login"
    assert first.name == "corrigir-o-login"
    assert workspace.worktree_exists(str(first)) is True
    assert workspace.current_branch() == "main", "the project root stays where it was"


def test_the_worktree_folder_is_the_branch_with_slashes_as_dashes(make):
    """One folder per branch, flat under the worktrees dir, named as the user typed it."""
    workspace = make()

    target, branch = workspace.add_worktree("run-a", "feat/fix-login")

    assert branch == "feat/fix-login"
    assert target.name == "feat-fix-login"
    assert target.parent.name == "worktrees"


def test_a_folder_held_by_another_branch_gets_the_run_id_as_suffix(make):
    """`feat/x` and `feat-x` are different branches but would share one folder."""
    workspace = make()
    first, _ = workspace.add_worktree("run-aaaaaaaa-1", "feat/x")

    second, branch = workspace.add_worktree("run-bbbbbbbb-2", "feat-x")

    assert first.name == "feat-x"
    assert second.name == "feat-x-run-bbbb"
    assert branch == "feat-x"
    assert workspace.worktree_exists(str(second)) is True


def test_a_folder_left_on_disk_gets_the_run_id_as_suffix(tmp_path: Path):
    """A stray folder is not a worktree git can reuse; adding over it would fail the run."""
    workspace = _git(tmp_path, repo=True)
    (tmp_path / "worktrees" / "feat-x").mkdir(parents=True)

    target, branch = workspace.add_worktree("run-bbbbbbbb-2", "feat/x")

    assert target == tmp_path / "worktrees" / "feat-x-run-bbbb"
    assert branch == "feat/x"
    assert vcs.current_branch(target) == "feat/x"


def test_a_lost_worktree_reopens_on_its_branch(make):
    """Finished steps' work lives on the branch; a new one from HEAD would leave it out."""
    workspace = make()
    target, branch = workspace.add_worktree("run-a", "pulse/demo")
    _lose(workspace, target)
    assert workspace.worktree_exists(str(target)) is False

    reopened = workspace.attach_worktree("run-a", branch)

    assert reopened == target
    assert workspace.worktree_exists(str(target)) is True


def test_outside_a_repository_nothing_is_opened(make):
    workspace = make(repo=False)

    assert workspace.is_repo() is False
    assert workspace.current_branch() == ""
    with pytest.raises(WorkspaceError):
        workspace.add_worktree("run-a", "pulse/demo")


def test_no_path_is_no_worktree(make):
    assert make().worktree_exists("") is False
