# Changelog

Todas as mudanças relevantes do Pulse ficam registradas neste arquivo.

O formato segue o [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) e
o projeto adota o [Versionamento Semântico](https://semver.org/lang/pt-BR/).

## [Unreleased]

## [0.1.0] - 2026-11-04

Primeira versão pública do Pulse: um orquestrador de agentes de IA via ACP,
terminal-first, que decide qual agente roda agora e quando.

### Adicionado

#### Runtimes

- Runtimes `cursor` (`agent acp`), `claude` (adapter
  `@agentclientprotocol/claude-agent-acp`) e `codex` (adapter
  `@agentclientprotocol/codex-acp`), com versões de adapter fixadas
  ([#59](https://github.com/pulse-ai-orchestrator/pulse.ai/pull/59)).
- Registry de runtimes extensível: uma subclasse de `AgentRuntime` registrada em
  `RUNTIMES` aparece em config, doctor e onboarding sem outra mudança.
- `pulse init` com wizard de onboarding e `pulse doctor` (com `--test-acp`) que
  reprova só o runtime ativo.

#### Workflows

- Workflows, steps e agentes como dado em SQLite (`~/.pulse/pulse.db`), com uma
  sessão ACP por step e só o resumo do step anterior passado adiante
  ([#26](https://github.com/pulse-ai-orchestrator/pulse.ai/pull/26),
  [#29](https://github.com/pulse-ai-orchestrator/pulse.ai/pull/29)).
- Loops de fábrica semeados com `INSERT OR IGNORE`: **Nova spec**, **Correção
  rápida**, **Review**, **Setup do projeto** e **Analisar codebase**, além do
  loop genérico `default`.
- Laços de revisão e correção (review ⇄ fix, verificar ⇄ corrigir lacunas) com
  limite de rodadas
  ([#33](https://github.com/pulse-ai-orchestrator/pulse.ai/pull/33),
  [#61](https://github.com/pulse-ai-orchestrator/pulse.ai/pull/61)).
- Aprovação humana por step, questionário de perguntas e política de permissões
  resolvida no daemon.

#### Worktree por run

- Git worktree por run em `~/.pulse/worktrees/<slug>`, com a branch visível na
  sessão ([#32](https://github.com/pulse-ai-orchestrator/pulse.ai/pull/32),
  [#73](https://github.com/pulse-ai-orchestrator/pulse.ai/pull/73)).
- Projeto em subpasta roda na mesma subpasta do worktree
  ([#72](https://github.com/pulse-ai-orchestrator/pulse.ai/pull/72)).
- Publicação da branch confirmada com commits e pull request (*Auto branch*,
  *Auto commit* e *Auto PR/MR*)
  ([#60](https://github.com/pulse-ai-orchestrator/pulse.ai/pull/60)).

#### Daemon e API

- Engine daemon (`pulse-engine`) como fonte única da verdade, com a CLI e a TUI
  como clientes finos ([#21](https://github.com/pulse-ai-orchestrator/pulse.ai/pull/21),
  [#29](https://github.com/pulse-ai-orchestrator/pulse.ai/pull/29)).
- Um contrato `/api/*` em dois transportes: socket Unix em `~/.pulse/daemon.sock`
  e HTTP em `127.0.0.1:8787`, descrito em
  [`contracts/openapi.yaml`](contracts/openapi.yaml).
- Listener TCP restrito a `127.0.0.1`, que recusa requests de navegador e exige
  o token do daemon ([#56](https://github.com/pulse-ai-orchestrator/pulse.ai/pull/56)).
- `pulse daemon start|status|stop` para gerenciar o daemon.

#### TUI

- Composer multilinha para descrever a tarefa, com `@` para citar arquivos do
  projeto ([#64](https://github.com/pulse-ai-orchestrator/pulse.ai/pull/64),
  [#68](https://github.com/pulse-ai-orchestrator/pulse.ai/pull/68)).
- Seletores no estilo de CLI de agente para nova sessão, histórico e
  configurações ([#65](https://github.com/pulse-ai-orchestrator/pulse.ai/pull/65),
  [#66](https://github.com/pulse-ai-orchestrator/pulse.ai/pull/66),
  [#67](https://github.com/pulse-ai-orchestrator/pulse.ai/pull/67)).
- Tokens de contexto ao vivo por step e total da run
  ([#58](https://github.com/pulse-ai-orchestrator/pulse.ai/pull/58)).
- Histórico de runs com o log de perguntas e respostas
  ([#31](https://github.com/pulse-ai-orchestrator/pulse.ai/pull/31)).

#### Qualidade e projeto

- Gates de qualidade no CI: ruff, mypy, cobertura por branch, mutation score dos
  parsers, contratos de import, vulture e deptry
  ([#42](https://github.com/pulse-ai-orchestrator/pulse.ai/pull/42),
  [#53](https://github.com/pulse-ai-orchestrator/pulse.ai/pull/53)).
- Invariantes de arquitetura como testes em `tests/architecture/`
  ([#43](https://github.com/pulse-ai-orchestrator/pulse.ai/pull/43)).
- Dependências travadas com `uv` e scanners de segurança (Bandit, Semgrep,
  pip-audit e Gitleaks) ([#69](https://github.com/pulse-ai-orchestrator/pulse.ai/pull/69)).
- Licença MIT, guia de contribuição, código de conduta, política de segurança e
  README em inglês ([#75](https://github.com/pulse-ai-orchestrator/pulse.ai/pull/75),
  [#76](https://github.com/pulse-ai-orchestrator/pulse.ai/pull/76),
  [#90](https://github.com/pulse-ai-orchestrator/pulse.ai/pull/90)).

[Unreleased]: https://github.com/pulse-ai-orchestrator/pulse.ai/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/pulse-ai-orchestrator/pulse.ai/releases/tag/v0.1.0
