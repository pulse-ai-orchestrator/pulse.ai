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
GITLAB_TEMPLATE_DIRECTORY = ".gitlab/merge_request_templates"
GITLAB_DEFAULT_NAME = "default.md"
_ORIGIN_HEAD = "refs/remotes/origin/HEAD"


def candidate_paths(*, forge: str, gitlab_default: str = "") -> tuple[str, ...]:
    """Paths checked for one forge. An unknown forge checks GitHub and then GitLab."""
    paths: list[str] = []
    if forge != "gitlab":
        paths.extend(GITHUB_TEMPLATE_PATHS)
    if forge != "github" and gitlab_default:
        paths.append(gitlab_default)
    return tuple(paths)


def select_template(files: Mapping[str, str], *, forge: str, gitlab_default: str = "") -> str:
    """First non-blank template in forge order, or empty when the project has none."""
    for path in candidate_paths(forge=forge, gitlab_default=gitlab_default):
        text = files.get(path, "").strip()
        if text:
            return text
    return ""


def gitlab_default_template(names: list[str]) -> str:
    """GitLab's `Default.md` in its template folder, whatever its case, or empty."""
    prefix = f"{GITLAB_TEMPLATE_DIRECTORY}/"
    for name in names:
        if name.startswith(prefix) and name[len(prefix) :].lower() == GITLAB_DEFAULT_NAME:
            return name
    return ""


def load_request_template(repo: Path) -> str:
    """Template text on the default branch. A missing file is an empty string, not an error."""
    ref = _template_ref(repo)
    forge = _forge(repo)
    gitlab_default = _gitlab_default(repo, ref, forge)
    files = {
        path: _read(["show", f"{ref}:{path}"], cwd=repo)
        for path in candidate_paths(forge=forge, gitlab_default=gitlab_default)
    }
    return select_template(files, forge=forge, gitlab_default=gitlab_default)


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


def _gitlab_default(repo: Path, ref: str, forge: str) -> str:
    if forge == "github":
        return ""
    listed = _read(["ls-tree", "--name-only", ref, f"{GITLAB_TEMPLATE_DIRECTORY}/"], cwd=repo)
    return gitlab_default_template([line.strip() for line in listed.splitlines()])
