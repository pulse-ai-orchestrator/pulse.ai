from __future__ import annotations

import argparse
import sys

from pulse_specs.runner import run_execute_specs_loop
from pulse_specs.types import ExecuteSpecsOptions


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Executa fases de spec do roadmap em loop, uma por chat isolado."
    )
    parser.add_argument(
        "project_path",
        nargs="?",
        default=None,
        help="Caminho absoluto do monorepo (padrão: raiz git detectada a partir de backend/)",
    )
    parser.add_argument(
        "--parent-branch",
        default="feat/pulse-backend",
        help=(
            "Branch raiz da cadeia (padrão: feat/pulse-backend). "
            "Somente a fase 1 parte dela."
        ),
    )
    parser.add_argument(
        "--branch-prefix",
        default="feat/pulse-specs",
        help=(
            "Prefixo das branches de fase (padrão: feat/pulse-specs). "
            "Deve ser diferente de --parent-branch para evitar conflito de refs no git."
        ),
    )
    parser.add_argument("--reference", default="execute-spec")
    parser.add_argument("--model", default="composer-2.5")
    parser.add_argument(
        "--executor",
        choices=["auto", "sdk", "acp", "stream-cli"],
        default="auto",
    )
    parser.add_argument("--agent-bin", default=None)
    parser.add_argument("--from-phase", type=int, default=None, dest="from_phase")
    parser.add_argument("--to-phase", type=int, default=None, dest="to_phase")
    parser.add_argument(
        "--only",
        nargs="+",
        default=None,
        help="Executar apenas fases específicas (slug ou nome, ex.: 01-agent-provider)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Lista fases e branches sem executar agentes nem alterar git",
    )
    parser.add_argument(
        "--skip-pr",
        action="store_true",
        help="Não cria PR automaticamente após push (útil para debug)",
    )
    parsed = parser.parse_args(argv)

    try:
        result = run_execute_specs_loop(
            ExecuteSpecsOptions(
                project_path=parsed.project_path,
                parent_branch=parsed.parent_branch,
                branch_prefix=parsed.branch_prefix,
                reference=parsed.reference,
                from_phase=parsed.from_phase,
                to_phase=parsed.to_phase,
                only=parsed.only,
                model=parsed.model,
                executor=parsed.executor,
                agent_bin=parsed.agent_bin,
                dry_run=parsed.dry_run,
                skip_pr=parsed.skip_pr,
            )
        )
    except Exception as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 1

    slugs = ", ".join(item.phase_slug for item in result.executed_phases)
    print(f"[SUCCESS] {result.completed_count} fase(s) executada(s): {slugs}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
