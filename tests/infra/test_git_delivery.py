"""Commits, snapshots and the push that publishes a run's branch."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from pulse import vcs
from pulse.vcs import changes
from pulse.vcs.workspace import GitWorkspace
from tests.infra.test_worktree import make_repo

pytestmark = pytest.mark.skipif(not vcs.git_available(), reason="git is not on PATH")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(  # noqa: S603 - fixed git argv on a temp repo
        ["git", *args],  # noqa: S607 - git resolved from PATH
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def test_a_snapshot_hashes_only_dirty_paths_and_a_commit_keeps_the_subject(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo")
    workspace = GitWorkspace(repo, worktrees=tmp_path / "worktrees")
    target, branch = workspace.add_worktree("run-1", "corrigir-o-login")
    base = workspace.head(target)
    (target / "novo.txt").write_text("novo\n", encoding="utf-8")
    _git(target, "mv", "README.md", "LEIA.md")

    before = workspace.snapshot(target)
    assert set(before) == {"novo.txt", "LEIA.md", "README.md"}
    assert before["novo.txt"]
    assert before["LEIA.md"]
    assert before["README.md"] == ""
    assert before["LEIA.md"]

    workspace.commit(target, ["novo.txt"], "feat: add the file")

    assert workspace.commits_after(target, base) == ["feat: add the file"]
    after = workspace.snapshot(target)
    assert "novo.txt" not in after
    (target / "novo.txt").unlink()
    assert workspace.snapshot(target)["novo.txt"] == ""
    assert branch == "corrigir-o-login"


def test_a_commit_at_the_root_leaves_what_the_user_staged_out_and_staged(
    tmp_path: Path,
) -> None:
    """At the project root the index is the user's: a step commit records only its
    own paths, and what was already staged stays staged for the user's commit.
    """
    repo = make_repo(tmp_path / "repo")
    workspace = GitWorkspace(repo, worktrees=tmp_path / "worktrees")
    base = workspace.head(repo)
    (repo / "README.md").write_text("trabalho do usuário\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    (repo / "agente.txt").write_text("mudança do agente\n", encoding="utf-8")

    workspace.commit(repo, ["agente.txt"], "feat: agent step")

    assert workspace.commits_after(repo, base) == ["feat: agent step"]
    assert _git(repo, "show", "--name-only", "--format=", "HEAD").split() == ["agente.txt"]
    assert _git(repo, "diff", "--cached", "--name-only").split() == ["README.md"]


def test_a_commit_refuses_an_empty_list_and_a_path_outside_the_worktree(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo")
    workspace = GitWorkspace(repo, worktrees=tmp_path / "worktrees")
    target, _branch = workspace.add_worktree("run-1", "corrigir-o-login")

    with pytest.raises(vcs.GitError, match="nothing to commit"):
        changes.commit_paths(target, [], "feat: nothing")
    with pytest.raises(vcs.GitError, match="escapes"):
        changes.commit_paths(target, ["../fora.txt"], "feat: escape")
    with pytest.raises(vcs.GitError, match="escapes"):
        changes.commit_paths(target, ["/etc/passwd"], "feat: absolute")


def test_a_missing_or_unreadable_status_is_an_empty_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(*_args, **_kwargs):
        raise OSError("git sumiu")

    monkeypatch.setattr(changes, "_run", _boom)
    assert changes.snapshot(tmp_path) == {}
    assert changes.branch_name_ok(tmp_path, "ok") is False


def test_branch_names_and_the_remote_default(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo")
    assert changes.branch_name_ok(repo, "corrigir-o-login") is True
    assert changes.branch_name_ok(repo, " nome ruim") is False
    assert changes.branch_name_ok(repo, "") is False
    assert changes.default_branch(repo) == ""

    bare = tmp_path / "origin.git"
    _git(tmp_path, "init", "--bare", "-q", str(bare))
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "push", "-u", "origin", "main")
    _git(repo, "remote", "set-head", "origin", "main")
    assert changes.default_branch(repo) == "main"


def test_publishing_pushes_the_branch_and_deletes_only_the_local_one(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo")
    bare = tmp_path / "origin.git"
    _git(tmp_path, "init", "--bare", "-q", str(bare))
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "push", "-u", "origin", "main")
    workspace = GitWorkspace(repo, worktrees=tmp_path / "worktrees")
    target, branch = workspace.add_worktree("run-1", "corrigir-o-login")
    (target / "novo.txt").write_text("novo\n", encoding="utf-8")
    workspace.commit(target, ["novo.txt"], "feat: add the file")

    workspace.publish_branch(branch)
    workspace.remove_worktree(target)
    workspace.delete_local_branch(branch)

    assert not target.exists()
    assert vcs.branch_exists(repo, branch) is False
    assert vcs.branch_exists(bare, branch) is True


def test_a_snapshot_lists_each_file_inside_an_untracked_directory(tmp_path: Path) -> None:
    """A directory left untracked by an earlier step collapsed into one `docs/` entry,
    so the files a later step added or edited inside it never reached a commit.
    """
    repo = make_repo(tmp_path / "repo")
    workspace = GitWorkspace(repo, worktrees=tmp_path / "worktrees")
    target, _branch = workspace.add_worktree("run-1", "corrigir-o-login")
    (target / "docs").mkdir()
    (target / "docs" / "prd.md").write_text("prd\n", encoding="utf-8")

    before = workspace.snapshot(target)
    (target / "docs" / "prd.md").write_text("prd editado\n", encoding="utf-8")
    (target / "docs" / "tasks.md").write_text("tasks\n", encoding="utf-8")
    after = workspace.snapshot(target)

    assert set(before) == {"docs/prd.md"}
    assert set(after) == {"docs/prd.md", "docs/tasks.md"}
    assert before["docs/prd.md"] != after["docs/prd.md"]


def test_a_subfolder_project_snapshots_and_commits_paths_relative_to_itself(
    tmp_path: Path,
) -> None:
    """`git status --porcelain` names paths from the top of the repo; committing them
    from the project subfolder would stage `service/service/...` and fail.
    """
    repo = make_repo(tmp_path / "repo")
    (repo / "service").mkdir()
    (repo / "service" / "main.py").write_text("print()\n", encoding="utf-8")
    _git(repo, "add", "service/main.py")
    _git(repo, "commit", "-q", "-m", "service")
    workspace = GitWorkspace(repo / "service", worktrees=tmp_path / "worktrees")
    target, _branch = workspace.add_worktree("run-1", "corrigir-o-login")
    base = workspace.head(target)
    (target / "main.py").write_text("print('novo')\n", encoding="utf-8")
    (target / "pkg").mkdir()
    (target / "pkg" / "util.py").write_text("x = 1\n", encoding="utf-8")
    (target.parent / "fora.txt").write_text("fora do projeto\n", encoding="utf-8")

    before = workspace.snapshot(target)
    assert set(before) == {"main.py", "pkg/util.py"}

    workspace.commit(target, sorted(before), "feat: change the service")

    assert workspace.commits_after(target, base) == ["feat: change the service"]
    assert set(workspace.snapshot(target)) == set()
    assert vcs.has_changes(target) is True, "the file outside the project is still dirty"


def test_removing_a_subfolder_worktree_removes_its_root(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo")
    (repo / "service").mkdir()
    workspace = GitWorkspace(repo / "service", worktrees=tmp_path / "worktrees")
    target, _branch = workspace.add_worktree("run-1", "corrigir-o-login")

    workspace.remove_worktree(target)

    assert not (tmp_path / "worktrees" / "corrigir-o-login").exists()


def test_a_pull_request_without_a_known_default_branch_is_refused(tmp_path: Path) -> None:
    """Without `origin/HEAD` the base was guessed (`main`, or whatever the root had
    checked out), which can target a branch that does not exist.
    """
    repo = make_repo(tmp_path / "repo")
    workspace = GitWorkspace(repo, worktrees=tmp_path / "worktrees")

    with pytest.raises(vcs.GitError, match="default branch"):
        workspace.open_pull_request(branch="corrigir-o-login", title="t", body="corpo")
