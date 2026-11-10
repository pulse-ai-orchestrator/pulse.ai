"""Which file is the project's pull or merge request template."""

from __future__ import annotations

from pathlib import Path

import pytest

from pulse import vcs
from pulse.vcs.request_template import (
    GITLAB_DEFAULT_TEMPLATE,
    load_request_template,
    lone_directory_template,
    select_template,
)
from tests.infra.test_worktree import make_repo

pytestmark = pytest.mark.skipif(not vcs.git_available(), reason="git is not on PATH")


def test_github_ignores_the_gitlab_default_and_gitlab_ignores_github():
    files = {
        ".github/pull_request_template.md": "github",
        GITLAB_DEFAULT_TEMPLATE: "gitlab",
    }

    assert select_template(files, forge="github") == "github"
    assert select_template(files, forge="gitlab") == "gitlab"
    assert select_template(files, forge="") == "github"


def test_a_single_file_in_the_template_folder_is_the_template():
    only = ".github/PULL_REQUEST_TEMPLATE/bug.md"

    assert lone_directory_template([only, ".github/PULL_REQUEST_TEMPLATE/notes.txt"]) == only
    assert select_template({}, forge="github", directory_file=only) == ""
    assert select_template({only: "um só"}, forge="github", directory_file=only) == "um só"


def test_several_files_in_the_template_folder_are_not_a_choice():
    names = [
        ".github/PULL_REQUEST_TEMPLATE/bug.md",
        ".github/PULL_REQUEST_TEMPLATE/feature.md",
        ".github/PULL_REQUEST_TEMPLATE/../escape.md",
    ]

    assert lone_directory_template(names) == ""


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
