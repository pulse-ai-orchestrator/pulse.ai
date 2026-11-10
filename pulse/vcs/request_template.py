"""The project's pull or merge request template, taken from the default branch.

GitHub and GitLab read that branch, not the one the run is publishing, so the
body follows the template a person would already see when opening the request.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from pulse.vcs import _read
from pulse.vcs.publish import forge_of, glab_host, origin_url

GITHUB_TEMPLATE_PATHS: tuple[str, ...] = (
    ".github/pull_request_template.md",
    ".github/PULL_REQUEST_TEMPLATE.md",
    "docs/pull_request_template.md",
    "docs/PULL_REQUEST_TEMPLATE.md",
    "pull_request_template.md",
    "PULL_REQUEST_TEMPLATE.md",
)
GITHUB_TEMPLATE_DIRECTORY = ".github/PULL_REQUEST_TEMPLATE"
GITLAB_DEFAULT_TEMPLATE = ".gitlab/merge_request_templates/Default.md"
_ORIGIN_HEAD = "refs/remotes/origin/HEAD"


def candidate_paths(*, forge: str, directory_file: str = "") -> tuple[str, ...]:
    """Paths checked for one forge. An unknown forge checks GitHub and then GitLab."""
    paths: list[str] = []
    if forge != "gitlab":
        paths.extend(GITHUB_TEMPLATE_PATHS)
        if directory_file:
            paths.append(directory_file)
    if forge != "github":
        paths.append(GITLAB_DEFAULT_TEMPLATE)
    return tuple(paths)


def select_template(files: Mapping[str, str], *, forge: str, directory_file: str = "") -> str:
    """First non-blank template in forge order, or empty when the project has none."""
    for path in candidate_paths(forge=forge, directory_file=directory_file):
        text = files.get(path, "").strip()
        if text:
            return text
    return ""


def lone_directory_template(names: list[str]) -> str:
    """The single markdown file in GitHub's template folder, or empty when it is not unique."""
    prefix = f"{GITHUB_TEMPLATE_DIRECTORY}/"
    markdown = [name for name in names if _directory_markdown(name, prefix)]
    if len(markdown) == 1:
        return markdown[0]
    return ""


def load_request_template(repo: Path) -> str:
    """Template text on the default branch. A missing file is an empty string, not an error."""
    ref = _template_ref(repo)
    forge = _forge(repo)
    directory = _directory_file(repo, ref, forge)
    files = {
        path: _read(["show", f"{ref}:{path}"], cwd=repo)
        for path in candidate_paths(forge=forge, directory_file=directory)
    }
    return select_template(files, forge=forge, directory_file=directory)


def _directory_markdown(name: str, prefix: str) -> bool:
    if not name.startswith(prefix):
        return False
    rest = name[len(prefix) :]
    if not rest or "/" in rest or rest in {".", ".."}:
        return False
    return rest.lower().endswith(".md")


def _template_ref(repo: Path) -> str:
    if _read(["rev-parse", "-q", "--verify", _ORIGIN_HEAD], cwd=repo):
        return _ORIGIN_HEAD
    return "HEAD"


def _forge(repo: Path) -> str:
    url = origin_url(repo)
    forge = forge_of(url)
    if forge or not url:
        return forge
    return forge_of(url, glab_host=glab_host())


def _directory_file(repo: Path, ref: str, forge: str) -> str:
    if forge == "gitlab":
        return ""
    listed = _read(["ls-tree", "--name-only", ref, GITHUB_TEMPLATE_DIRECTORY], cwd=repo)
    names = [line.strip() for line in listed.splitlines() if line.strip()]
    return lone_directory_template(names)
