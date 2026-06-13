from __future__ import annotations

from pathlib import Path

EXECUTE_SPEC_REFERENCE = "@references /execute-spec/SKILL.md"


def build_execute_spec_prompt(
    *,
    repo_root: Path,
    artifacts_path: Path,
    product_path: Path,
    technical_path: Path,
    shared_docs: list[Path],
    skills: list[str],
    phase_slug: str,
    phase_branch: str,
    parent_branch: str,
    pr_base_branch: str,
    status_path: Path,
    reference: str = "execute-spec",
) -> str:
    resolved = EXECUTE_SPEC_REFERENCE if reference == "execute-spec" else reference

    def _relative(path: Path) -> str:
        try:
            return path.relative_to(repo_root).as_posix()
        except ValueError:
            return path.as_posix()

    shared_lines = "\n".join(f"- `{_relative(doc)}`" for doc in shared_docs)
    skill_lines = "\n".join(f"- `{skill}`" for skill in skills)

    body = (
        f"Siga o fluxo completo da skill execute-spec.\n"
        f"Fase: `{phase_slug}`\n"
        f"Product spec: `{_relative(product_path)}`\n"
        f"Technical spec: `{_relative(technical_path)}`\n"
        f"Documentos compartilhados:\n{shared_lines}\n"
        f"Skills aplicáveis (ler antes de implementar):\n{skill_lines}\n"
        f"Repositório git (raiz do monorepo): `{repo_root}`\n"
        f"Código backend: `{artifacts_path}`\n"
        f"Branch atual (já criada pelo runner): `{phase_branch}`\n"
        f"Branch pai: `{parent_branch}`\n"
        f"Base do PR: `{pr_base_branch}`\n"
        f"Status file: `{_relative(status_path)}`\n"
        f"Esta execução roda em contexto isolado (novo chat) — implemente apenas esta fase.\n"
        f"Ao concluir: pytest em `backend/`, atualize o status file e faça commit local.\n"
        f"NÃO crie PR nem faça push — o runner `pulse_specs` cuida disso automaticamente após você concluir."
    )
    return f"{resolved}\n\n{body}"
