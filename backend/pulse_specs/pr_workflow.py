from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx

from pulse_specs.discovery import SpecPhase
from pulse_specs.git_workflow import GitWorkflowError, _run_git


class PrWorkflowError(RuntimeError):
    pass


@dataclass(frozen=True)
class PullRequestResult:
    url: str
    title: str
    created: bool


_PR_HINT_PATTERN = re.compile(r"`([^`]+)`")


def resolve_github_token() -> str | None:
    for key in ("GITHUB_TOKEN", "GH_TOKEN", "GITHUB_PAT"):
        value = os.environ.get(key, "").strip()
        if value:
            return value
    return None


def resolve_remote_owner_repo(repo_root: Path) -> tuple[str, str]:
    result = _run_git(repo_root, "remote", "get-url", "origin")
    url = result.stdout.strip()
    if url.startswith("git@"):
        _, path = url.split(":", 1)
        path = path.removesuffix(".git")
        owner, repo = path.split("/", 1)
        return owner, repo
    parsed = urlparse(url)
    parts = parsed.path.strip("/").removesuffix(".git").split("/")
    if len(parts) < 2:
        raise PrWorkflowError(f"remote origin inválido: {url}")
    return parts[0], parts[1]


def extract_pr_title_hint(product_path: Path) -> str | None:
    for line in product_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped.startswith("**PR:**"):
            continue
        match = _PR_HINT_PATTERN.search(stripped)
        if match:
            return match.group(1).strip()
    return None


def build_pr_title(phase: SpecPhase, product_path: Path, repo_root: Path) -> str:
    hint = extract_pr_title_hint(product_path)
    if hint:
        normalized = _normalize_pr_title(hint, phase)
        if normalized:
            return normalized

    result = _run_git(repo_root, "log", "-1", "--pretty=%s")
    subject = result.stdout.strip()
    if subject and "backend" in subject:
        return subject
    return f"feat(backend/{phase.name}): implement phase {phase.number}"


def _normalize_pr_title(hint: str, phase: SpecPhase) -> str:
    if hint.startswith(("feat(", "fix(", "refactor(", "docs(", "chore(", "test(")):
        if "backend" in hint:
            return hint
        match = re.match(r"^(\w+)\(([^)]+)\):\s*(.+)$", hint)
        if match:
            kind, _scope, subject = match.groups()
            return f"{kind}(backend/{phase.name}): {subject}"
        match = re.match(r"^(\w+):\s*(.+)$", hint)
        if match:
            kind, subject = match.groups()
            return f"{kind}(backend/{phase.name}): {subject}"

    type_prefix = "feat"
    lowered = hint.lower()
    if lowered.startswith("refactor"):
        type_prefix = "refactor"
    elif lowered.startswith("fix"):
        type_prefix = "fix"
    elif lowered.startswith("docs"):
        type_prefix = "docs"
    return f"{type_prefix}(backend/{phase.name}): implement phase {phase.number}"


def read_pr_template(repo_root: Path) -> str:
    template = repo_root / ".github" / "pull_request_template.md"
    if template.is_file():
        return template.read_text(encoding="utf-8")
    fallback = (
        "## Resumo\n\n{resumo}\n\n"
        "## Motivação / Contexto\n\n{motivacao}\n\n"
        "## Notas de implementação (opcional)\n\n{notas}\n\n"
        "## Capturas de tela / gravações (se aplicável)\n\nN/A\n\n"
        "## Riscos e publicação\n\n{riscos}\n\n"
        "## Como testar\n\n{teste}\n"
    )
    return fallback


def build_pr_body(
    *,
    repo_root: Path,
    phase: SpecPhase,
    base_branch: str,
    status_path: Path | None,
) -> str:
    log_result = _run_git(
        repo_root,
        "log",
        f"{base_branch}..HEAD",
        "--oneline",
        check=False,
    )
    commits = log_result.stdout.strip() or "(sem commits novos)"
    status_note = ""
    if status_path and status_path.is_file():
        status_note = status_path.read_text(encoding="utf-8").strip()

    objective = _extract_section(phase.product_path, "## Objetivo")
    resumo = objective or f"Implementa a fase {phase.slug} do roadmap Pulse backend."
    motivacao = (
        f"Fase {phase.number} (`{phase.slug}`) do roadmap em `backend/docs/specs/`, "
        f"integrando sobre `{base_branch}`."
    )
    notas = f"Commits:\n\n```\n{commits}\n```"
    if status_note:
        notas += f"\n\nStatus da fase:\n\n```\n{status_note}\n```"
    riscos = "Verificar breaking changes documentados na spec da fase antes do merge."
    teste = (
        "1. `cd backend && .venv/bin/pip install -e \".[dev]\"`\n"
        "2. `.venv/bin/pytest tests/test_cursor_task.py tests/test_pulse_specs.py -q`\n"
        f"3. Validar critérios de aceite em `backend/docs/specs/phases/{phase.slug}/product.md`"
    )

    template = read_pr_template(repo_root)
    if "{resumo}" in template:
        return template.format(
            resumo=resumo,
            motivacao=motivacao,
            notas=notas,
            riscos=riscos,
            teste=teste,
        )

    return (
        f"## Resumo\n\n{resumo}\n\n"
        f"## Motivação / Contexto\n\n{motivacao}\n\n"
        f"## Notas de implementação (opcional)\n\n{notas}\n\n"
        f"## Capturas de tela / gravações (se aplicável)\n\nN/A\n\n"
        f"## Riscos e publicação\n\n{riscos}\n\n"
        f"## Como testar\n\n{teste}\n"
    )


def _extract_section(product_path: Path, heading: str) -> str:
    lines = product_path.read_text(encoding="utf-8").splitlines()
    capture = False
    collected: list[str] = []
    for line in lines:
        if line.startswith("## "):
            if capture:
                break
            if line.strip() == heading:
                capture = True
            continue
        if capture and line.strip():
            collected.append(line.strip())
    return " ".join(collected)


def find_existing_pr_url(
    *,
    owner: str,
    repo: str,
    head_branch: str,
    base_branch: str,
    token: str,
) -> str | None:
    response = httpx.get(
        f"https://api.github.com/repos/{owner}/{repo}/pulls",
        params={"head": f"{owner}:{head_branch}", "base": base_branch, "state": "all"},
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        },
        timeout=30.0,
    )
    if response.status_code != 200:
        return None
    pulls = response.json()
    if pulls:
        return pulls[0]["html_url"]
    return None


def create_pull_request_via_api(
    *,
    owner: str,
    repo: str,
    head_branch: str,
    base_branch: str,
    title: str,
    body: str,
    token: str,
) -> PullRequestResult:
    existing = find_existing_pr_url(
        owner=owner,
        repo=repo,
        head_branch=head_branch,
        base_branch=base_branch,
        token=token,
    )
    if existing:
        return PullRequestResult(url=existing, title=title, created=False)

    response = httpx.post(
        f"https://api.github.com/repos/{owner}/{repo}/pulls",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        },
        json={
            "title": title,
            "head": head_branch,
            "base": base_branch,
            "body": body,
        },
        timeout=30.0,
    )
    if response.status_code >= 400:
        detail = response.text.strip()
        raise PrWorkflowError(f"GitHub API falhou ({response.status_code}): {detail}")

    payload = response.json()
    return PullRequestResult(url=payload["html_url"], title=title, created=True)


def create_pull_request_via_gh(
    *,
    repo_root: Path,
    head_branch: str,
    base_branch: str,
    title: str,
    body: str,
) -> PullRequestResult:
    gh = shutil.which("gh")
    if not gh:
        raise PrWorkflowError("gh CLI não encontrado")

    view = subprocess.run(
        [gh, "pr", "view", "--head", head_branch, "--base", base_branch, "--json", "url"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if view.returncode == 0 and view.stdout.strip():
        payload = json.loads(view.stdout)
        return PullRequestResult(url=payload["url"], title=title, created=False)

    result = subprocess.run(
        [
            gh,
            "pr",
            "create",
            "--base",
            base_branch,
            "--head",
            head_branch,
            "--title",
            title,
            "--body",
            body,
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip() or result.stdout.strip()
        raise PrWorkflowError(f"gh pr create falhou: {stderr}")

    url = result.stdout.strip().splitlines()[-1]
    return PullRequestResult(url=url, title=title, created=True)


def create_phase_pull_request(
    *,
    repo_root: Path,
    phase: SpecPhase,
    head_branch: str,
    base_branch: str,
    status_path: Path | None = None,
) -> PullRequestResult:
    title = build_pr_title(phase, phase.product_path, repo_root)
    body = build_pr_body(
        repo_root=repo_root,
        phase=phase,
        base_branch=base_branch,
        status_path=status_path,
    )
    owner, repo = resolve_remote_owner_repo(repo_root)

    token = resolve_github_token()
    if token:
        return create_pull_request_via_api(
            owner=owner,
            repo=repo,
            head_branch=head_branch,
            base_branch=base_branch,
            title=title,
            body=body,
            token=token,
        )

    try:
        return create_pull_request_via_gh(
            repo_root=repo_root,
            head_branch=head_branch,
            base_branch=base_branch,
            title=title,
            body=body,
        )
    except PrWorkflowError as error:
        raise PrWorkflowError(
            f"{error}. Configure GITHUB_TOKEN (ou GH_TOKEN) ou instale/autentique o gh CLI."
        ) from error
