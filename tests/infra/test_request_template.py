"""Which file is the project's pull or merge request template."""

from __future__ import annotations

from pathlib import Path

import pytest

from pulse import vcs
from pulse.vcs.request_template import (
    gitlab_default_template,
    load_request_template,
    select_template,
)
from tests.infra.test_worktree import make_repo

pytestmark = pytest.mark.skipif(not vcs.git_available(), reason="git is not on PATH")

GITLAB_DEFAULT = ".gitlab/merge_request_templates/Default.md"


def test_github_ignores_the_gitlab_default_and_gitlab_ignores_github():
    files = {
        ".github/pull_request_template.md": "github",
        GITLAB_DEFAULT: "gitlab",
    }

    assert select_template(files, forge="github", gitlab_default=GITLAB_DEFAULT) == "github"
    assert select_template(files, forge="gitlab", gitlab_default=GITLAB_DEFAULT) == "gitlab"
    assert select_template(files, forge="", gitlab_default=GITLAB_DEFAULT) == "github"


def test_a_file_in_the_github_template_folder_is_not_the_template():
    """GitHub fills the body from that folder only through the `template` query parameter."""
    files = {".github/PULL_REQUEST_TEMPLATE/bug.md": "um só"}

    assert select_template(files, forge="github") == ""


@pytest.mark.parametrize("name", ["Default.md", "default.md", "DEFAULT.MD"])
def test_the_gitlab_default_template_matches_in_any_case(name: str):
    folder = ".gitlab/merge_request_templates"

    assert gitlab_default_template([f"{folder}/bug.md", f"{folder}/{name}"]) == f"{folder}/{name}"


def test_a_gitlab_folder_without_a_default_has_no_template():
    names = [
        ".gitlab/merge_request_templates/bug.md",
        ".gitlab/merge_request_templates/nested/default.md",
        ".gitlab/other/default.md",
    ]

    assert gitlab_default_template(names) == ""


def test_the_default_branch_template_is_read_from_git(tmp_path: Path):
    repo = make_repo(tmp_path / "repo")
    folder = repo / ".github"
    folder.mkdir()
    (folder / "pull_request_template.md").write_text(
        "## Resumo\n\ndo repositório\n", encoding="utf-8"
    )
    _git(repo, "add", ".github")
    _git(repo, "commit", "-q", "-m", "template")

    assert load_request_template(repo) == "## Resumo\n\ndo repositório"


def test_a_lowercase_gitlab_default_is_read_from_git(tmp_path: Path):
    repo = make_repo(tmp_path / "repo")
    folder = repo / ".gitlab" / "merge_request_templates"
    folder.mkdir(parents=True)
    (folder / "default.md").write_text("## O que muda\n", encoding="utf-8")
    _git(repo, "add", ".gitlab")
    _git(repo, "commit", "-q", "-m", "template")

    assert load_request_template(repo) == "## O que muda"


def test_a_repository_without_a_template_reads_as_empty(tmp_path: Path):
    repo = make_repo(tmp_path / "repo")

    assert load_request_template(repo) == ""


def _git(repo: Path, *args: str) -> None:
    import subprocess

    subprocess.run(  # noqa: S603 - fixed git argv in a temp repo
        ["git", *args],  # noqa: S607 - git resolved from PATH
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
