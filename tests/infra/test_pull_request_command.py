import subprocess
from pathlib import Path

import pytest

from pulse.vcs import GitError
from pulse.vcs.publish import forge_of, glab_host, open_request, remote_host, request_command


@pytest.mark.parametrize(
    ("url", "forge"),
    [
        ("git@github.com:acme/app.git", "github"),
        ("https://github.com/acme/app.git", "github"),
        ("https://gitlab.com/acme/app.git", "gitlab"),
        ("git@gitlab.example.com:acme/app.git", "gitlab"),
        ("https://git.internal.example/acme/app.git", ""),
    ],
)
def test_the_forge_comes_from_the_origin_url(url: str, forge: str):
    assert forge_of(url) == forge


def test_a_self_hosted_gitlab_matches_the_host_glab_already_uses():
    url = "https://git.internal.example/acme/app.git"
    assert forge_of(url, glab_host="git.internal.example") == "gitlab"


def test_github_and_gitlab_get_the_same_title_and_body():
    body = "#### Descrição:\ncorrigir o login\n"
    github = request_command(
        forge="github", branch="corrigir-o-login", base="main", title="corrigir-o-login", body=body
    )
    gitlab = request_command(
        forge="gitlab", branch="corrigir-o-login", base="main", title="corrigir-o-login", body=body
    )

    assert github[:3] == ["gh", "pr", "create"]
    assert "--body" in github
    assert "--draft" in github
    assert body in github
    assert gitlab[:3] == ["glab", "mr", "create"]
    assert "--description" in gitlab
    assert "--draft" in gitlab
    assert body in gitlab
    assert "--force" not in github
    assert "--force" not in gitlab


@pytest.mark.parametrize(
    ("url", "host"),
    [
        ("", ""),
        ("not a url", ""),
        ("https:///missing-host/repo.git", ""),
        ("ssh://git@gitlab.example/acme/app.git", "gitlab.example"),
    ],
)
def test_a_remote_url_without_a_host_does_not_invent_one(url: str, host: str) -> None:
    assert remote_host(url) == host


def test_an_unknown_forge_has_no_command() -> None:
    with pytest.raises(GitError, match="unknown"):
        request_command(forge="", branch="b", base="main", title="t", body="body")


def test_glab_host_is_empty_when_the_cli_fails_or_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _missing(*_args, **_kwargs):
        raise OSError("glab ausente")

    monkeypatch.setattr(subprocess, "run", _missing)
    assert glab_host() == ""

    def _refused(*_args, **_kwargs):
        return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="no")

    monkeypatch.setattr(subprocess, "run", _refused)
    assert glab_host() == ""

    def _ok(*_args, **_kwargs):
        return subprocess.CompletedProcess(
            args=[], returncode=0, stdout="gitlab.example\n", stderr=""
        )

    monkeypatch.setattr(subprocess, "run", _ok)
    assert glab_host() == "gitlab.example"


def test_opening_a_request_uses_the_forge_command_and_reports_its_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[list[str]] = []

    monkeypatch.setattr("pulse.vcs.publish.origin_url", lambda _repo: "git@github.com:acme/app.git")
    monkeypatch.setattr("pulse.vcs.publish.glab_host", lambda: "")

    def _ok(command, **_kwargs):
        seen.append(command)
        return subprocess.CompletedProcess(args=command, returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", _ok)
    open_request(tmp_path, branch="corrigir-o-login", title="t", body="corpo", base="main")
    assert seen[0][:3] == ["gh", "pr", "create"]
    assert "--draft" in seen[0]
    assert "corpo" in seen[0]

    def _fail(command, **_kwargs):
        return subprocess.CompletedProcess(args=command, returncode=1, stdout="", stderr="denied")

    monkeypatch.setattr(subprocess, "run", _fail)
    with pytest.raises(GitError, match="denied"):
        open_request(tmp_path, branch="corrigir-o-login", title="t", body="corpo", base="main")

    def _down(*_args, **_kwargs):
        raise subprocess.SubprocessError("quebrou")

    monkeypatch.setattr(subprocess, "run", _down)
    with pytest.raises(GitError, match="quebrou"):
        open_request(tmp_path, branch="corrigir-o-login", title="t", body="corpo", base="main")

    monkeypatch.setattr(
        "pulse.vcs.publish.origin_url", lambda _repo: "https://example.com/acme/app.git"
    )
    with pytest.raises(GitError, match="unknown"):
        open_request(tmp_path, branch="corrigir-o-login", title="t", body="corpo", base="main")
