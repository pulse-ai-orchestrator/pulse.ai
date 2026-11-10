"""Open a pull request or merge request for a branch already on `origin`."""

from __future__ import annotations

import subprocess
from pathlib import Path
from urllib.parse import urlparse

from pulse.vcs import GitError, _quiet_git_env, _read

REQUEST_TIMEOUT = 60.0


def remote_host(url: str) -> str:
    text = url.strip()
    if not text:
        return ""
    if "://" in text:
        return urlparse(text).hostname or ""
    if text.startswith("git@") and ":" in text:
        return text.split("@", 1)[1].split(":", 1)[0]
    return ""


def forge_of(url: str, *, glab_host: str = "") -> str:
    host = remote_host(url).lower()
    if host == "github.com" or host.endswith(".github.com"):
        return "github"
    if not host:
        return ""
    if host == "gitlab.com" or "gitlab" in host:
        return "gitlab"
    if glab_host and host == glab_host.lower():
        return "gitlab"
    return ""


def request_command(*, forge: str, branch: str, base: str, title: str, body: str) -> list[str]:
    if forge == "github":
        return [
            "gh",
            "pr",
            "create",
            "--base",
            base,
            "--head",
            branch,
            "--title",
            title,
            "--body",
            body,
            "--draft",
        ]
    if forge == "gitlab":
        return [
            "glab",
            "mr",
            "create",
            "--source-branch",
            branch,
            "--target-branch",
            base,
            "--title",
            title,
            "--description",
            body,
            "--yes",
            "--draft",
        ]
    raise GitError(f"no pull request command for `{forge or 'unknown'}`")


def origin_url(repo: Path) -> str:
    return _read(["remote", "get-url", "origin"], cwd=repo)


def glab_host() -> str:
    try:
        result = subprocess.run(  # noqa: S603 - fixed argv, glab from PATH
            ["glab", "config", "get", "host"],  # noqa: S607 - glab resolved from PATH
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            env=_quiet_git_env(),
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def open_request(repo: Path, *, branch: str, title: str, body: str, base: str) -> None:
    forge = forge_of(origin_url(repo), glab_host=glab_host())
    command = request_command(forge=forge, branch=branch, base=base, title=title, body=body)
    try:
        result = subprocess.run(  # noqa: S603 - argv list, gh or glab from PATH
            command,
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=REQUEST_TIMEOUT,
            check=False,
            env=_quiet_git_env(),
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise GitError(f"{command[0]}: {error}") from error
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise GitError(f"{command[0]}: {detail or 'failed'}")
