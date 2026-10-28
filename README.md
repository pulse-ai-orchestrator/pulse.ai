<div align="center">

<img src="https://avatars.githubusercontent.com/u/339804102?s=200&v=4" alt="Pulse" width="96" height="96">

# Pulse

**Orquestrador de agentes de IA via ACP, terminal-first.**

Decide qual agente roda agora — e quando. O resto é dado.

[![CI](https://github.com/pulse-ai-orchestrator/pulse.ai/actions/workflows/ci.yml/badge.svg)](https://github.com/pulse-ai-orchestrator/pulse.ai/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.14-blue)
![Protocolo](https://img.shields.io/badge/protocolo-ACP-6f42c1)
![Runtimes](https://img.shields.io/badge/runtimes-Cursor%20%7C%20Claude%20Code%20%7C%20Codex-informational)
[![Licença: MIT](https://img.shields.io/badge/licen%C3%A7a-MIT-green)](LICENSE)
[![Estrelas](https://img.shields.io/github/stars/pulse-ai-orchestrator/pulse.ai?style=flat&label=estrelas)](https://github.com/pulse-ai-orchestrator/pulse.ai/stargazers)
[![Discussions](https://img.shields.io/github/discussions/pulse-ai-orchestrator/pulse.ai?label=discussions)](https://github.com/pulse-ai-orchestrator/pulse.ai/discussions)

Se o Pulse for útil pra você, deixe uma ⭐: é o que ajuda o projeto a ser encontrado.

</div>

---

O Pulse coordena os agentes de IA que você já usa — **Cursor**, **Claude Code** e
**OpenAI Codex** — por meio do [Agent Client Protocol](https://agentclientprotocol.com)
(ACP). Ele tem uma única responsabilidade: **apontar qual agente roda agora e
quando**.

O Pulse não sabe o que o agente faz, não lê o que ele produziu e não espera
arquivos com nomes conhecidos. Workflows, steps e agentes são **dados em
SQLite** — o pacote não traz pipeline, prompt de domínio nem skill embutida.

## Sumário

- [Destaques](#destaques)
- [Como funciona](#como-funciona)
- [Instalação](#instalação)
- [Primeiros passos](#primeiros-passos)
- [Runtimes suportados](#runtimes-suportados)
- [Workflows](#workflows)
- [Configuração](#configuração)
- [Worktree por run](#worktree-por-run)
- [Daemon e API](#daemon-e-api)
- [Referência de comandos](#referência-de-comandos)
- [Documentação](#documentação)
- [Desenvolvimento](#desenvolvimento)
- [Comunidade](#comunidade)
- [Contribuindo](#contribuindo)
- [Licença](#licença)

## Destaques

- **Workflows como dado.** Um workflow é uma linha em `workflow_defs` mais N
  steps em `workflow_steps`. Nenhum `if workflow_id == ...` no motor.
- **Uma sessão ACP por step.** O step seguinte recebe só o resumo do anterior,
  o que permite trocar de runtime no meio da run e retomar refazendo um step só.
- **Aprovação humana onde importa.** Cada step declara se o Pulse espera
  aprovação antes de seguir; decisões cobertas pela política de permissões são
  resolvidas no daemon e nunca viram pergunta.
- **Runs sobrevivem ao terminal.** O estado pertence ao daemon: fechar a TUI não
  congela nem perde a run.
- **Isolamento por git worktree.** Cada run pode trabalhar na própria branch, sem
  tocar a árvore do editor — revisar a entrega vira um `git diff`.
- **Local-first e seguro por padrão.** SQLite em `~/.pulse/pulse.db`, socket Unix
  com permissão só do usuário e HTTP preso a `127.0.0.1` com token por início.
- **Extensível sem tocar no motor.** Um runtime novo é uma subclasse de
  `AgentRuntime`; config, doctor e onboarding o enxergam sem mudanças.

## Como funciona

```
┌─────────────┐  HTTP / UDS  ┌──────────────────┐     ACP     ┌──────────────────────────┐
│  CLI / TUI  │ ───────────▶ │  Engine (daemon) │ ──────────▶ │  Cursor | Claude | Codex │
│ cliente fino│              │  fonte da verdade│             │         runtime          │
└─────────────┘              └────────┬─────────┘             └──────────────────────────┘
                                      │
                                      ▼
                              ~/.pulse/pulse.db
                     (workflows, agentes, runs, config)
```

| Componente | Executável | Papel | Código |
| --- | --- | --- | --- |
| Engine | `pulse-engine` | Composition root: dono do estado, das definições e das runs | [`pulse/daemon/`](pulse/daemon/), [`pulse/api/`](pulse/api/) |
| CLI | `pulse` | Cliente fino com TUI Textual; nunca executa um workflow no próprio processo | [`pulse/cli/`](pulse/cli/), [`pulse/tui/`](pulse/tui/), [`pulse/client/`](pulse/client/) |

O daemon expõe **um contrato em dois transportes**: Unix Domain Socket em
`~/.pulse/daemon.sock` (usado pela CLI) e HTTP em `127.0.0.1:8787` (tooling). O
contrato está em [`contracts/openapi.yaml`](contracts/openapi.yaml).

Camadas, fluxos e glossário: [`ARCHITECTURE.md`](ARCHITECTURE.md).

## Instalação

**Requisitos**

- macOS ou Linux. O Windows nativo não é suportado, porque a CLI fala com o
  daemon por socket Unix; no Windows, use o [WSL2](https://learn.microsoft.com/windows/wsl/)
- Python 3.11 ou superior
- [pipx](https://pipx.pypa.io)
- Ao menos um runtime instalado e autenticado (veja
  [Runtimes suportados](#runtimes-suportados))
- Node.js 18+ (`npx`) no PATH, para os runtimes `claude` e `codex`

```bash
pipx install git+https://github.com/pulse-ai-orchestrator/pulse.ai.git
```

O pipx instala o Pulse num ambiente isolado e coloca os comandos `pulse` e
`pulse-engine` no PATH.

| Ação | Comando |
| --- | --- |
| Atualizar | `pipx upgrade pulse` |
| Fixar uma versão ou branch | `pipx install git+https://github.com/pulse-ai-orchestrator/pulse.ai.git@<tag-ou-branch>` |
| Desinstalar | `pipx uninstall pulse` |

Para desenvolver no próprio Pulse, instale a partir do clone em modo editável:

```bash
git clone https://github.com/pulse-ai-orchestrator/pulse.ai.git
cd pulse.ai
pipx install -e .
```

## Primeiros passos

```bash
pulse init
```

O wizard pergunta qual runtime será o padrão e verifica:

- o binário do runtime no PATH (`agent`, `claude` ou `codex`, além de `npx` quando necessário);
- a autenticação do runtime;
- a conexão ACP, com um prompt de teste;
- diretório padrão, modelo e política de permissões.

Ao final, a configuração da máquina é salva em `~/.pulse/pulse.db` e o workspace
atual é registrado no SQLite (se ainda não existir). Depois, basta rodar:

```bash
pulse
```

Para iniciar uma tarefa (ex.: **Correção rápida**, **Nova spec**), só a
**descrição** é obrigatória:

| Tecla | Ação |
| --- | --- |
| `Enter` | Inicia com a config do projeto |
| `Ctrl+J` ou `\` + `Enter` | Quebra linha |
| `@` | Lista os arquivos do projeto não ignorados pelo git; `↑`/`↓` escolhem e `Enter`/`Tab` inserem o caminho |
| `Ctrl+O` | Abre **▸ Mais opções**: título, slug (nome da branch) e config da run |
| `Tab` / `Espaço` | Mudam de campo / marcam uma opção |

Em **Mais opções**, a config da run — *Auto branch*, *Auto commit* e *Auto PR/MR* —
começa com o que está em *Configurações* e vale só para aquela run. O modo
escolhido vale para as próximas tarefas até fechar o Pulse.

## Runtimes suportados

Um *runtime* é o backend que executa um agente do Pulse. Cada um declara binário,
comando ACP, checagens de ambiente e como aplicar modo e modelo.

| Runtime | Binário | Comando ACP | Autenticação |
| --- | --- | --- | --- |
| `cursor` | `agent` | `agent acp` | `agent login` ou `CURSOR_API_KEY` |
| `claude` | `claude` | `npx -y @agentclientprotocol/claude-agent-acp@0.86.0` | `claude /login` ou `ANTHROPIC_API_KEY` |
| `codex` | `codex` | `npx -y @agentclientprotocol/codex-acp@2.1.1` | `codex login`, `CODEX_API_KEY` ou `OPENAI_API_KEY` |

Claude Code e Codex não falam ACP nativamente: o Pulse usa os adapters oficiais
distribuídos via npm, com versão fixada. Cada adapter herda o login do CLI
correspondente — não há passo de autenticação separado.

Modelos padrão do runtime `claude`: `default`, `opus[1m]`, `claude-fable-5-1`,
`sonnet`, `haiku`.

O `pulse doctor` reprova apenas o runtime ativo; os demais aparecem como aviso.
Uma máquina que só tem o Claude não falha por não ter o Cursor instalado.

**Adicionando um runtime.** O registry fica em
[`pulse/runtimes/`](pulse/runtimes/): escreva um módulo com a subclasse de
`AgentRuntime` e registre-a em `RUNTIMES`. Config, doctor, onboarding e session
runner passam a enxergá-lo sem nenhuma outra mudança.

## Workflows

Um workflow é uma linha em `workflow_defs` mais N em `workflow_steps`, no
`~/.pulse/pulse.db`. Cada step diz **qual agente** roda, **qual prompt** ele
recebe e se o Pulse deve **esperar aprovação** antes de seguir.

O banco nasce semeado ([`pulse/store/factory/`](pulse/store/factory/)) com os
loops de fábrica, que aparecem no menu **Nova sessão**:

| Loop | Steps |
| --- | --- |
| Nova spec | PRD → Techspec → Tasks → Implementar → Verificar ⇄ Corrigir lacunas → Review ⇄ Fix review (dois laços, até 3 rodadas cada) |
| Correção rápida | Quick plan → Quick implement |
| Review | Review ⇄ Fix review (laço, até 3 rodadas) da branch atual vs `main`, roda direto |
| Setup do projeto | Entrevista → Artefatos (roda direto, sem aprovar) |
| Analisar codebase | Exploração → Documentação (roda direto, sem aprovar) |

Há ainda o loop genérico `default` ("Executar", um step sem pipeline). Ele não
entra no menu, mas continua no banco e em `/api/workflows` para quem chama o
daemon diretamente.

Princípios que valem para todo workflow:

- **A semeadura é `INSERT OR IGNORE`.** Edições do usuário nunca são sobrescritas
  no upgrade, e uma linha de fábrica apagada volta na abertura seguinte.
- **Definição é mutável, estado é imutável.** A run copia rótulo e posição dos
  steps ao iniciar; editar um workflow nunca reescreve o histórico.
- **Sem convenção de pasta.** O que o agente escreve fica onde o prompt do step
  mandar; o Pulse descobre pelos tool-calls do ACP e guarda só o caminho.

Ainda não há tela para editar workflows: um pipeline novo é escrito no banco via
`pulse.store.workflow_defs`. Modelo completo em [`docs/workflows.md`](docs/workflows.md).

## Configuração

Cada projeto tem um `project_id` no SQLite da máquina. A configuração efetiva é
resolvida em camadas:

```
defaults do código → machine (SQLite) → project_* (mesmo SQLite, por root_path)
```

Por workflow, a ordem é:

```
projeto.workflows[id] → global.workflows[id] → projeto.defaults → global.defaults → defaults do código
```

| Escopo | Campos |
| --- | --- |
| Projeto | `agent`, `model`, `permission_policy`, `workspace`, `use_worktree` |
| Workflow | `workflows.*` — override de agent/model por id de workflow (não definem pipeline) |
| Agentes | Agentes do projeto sobrescrevem ou estendem os da máquina (`binary`, `models`, `acp_command`) |

`pulse init` e `pulse config init` cadastram o projeto sem agent, model nem
`permission_policy`: campo vazio herda da máquina, que é onde o onboarding grava
a escolha.

```bash
pulse config show
pulse config show --workflow default
```

## Worktree por run

Um projeto que é repositório git pode ligar **Worktree** em *Configurações*. Com
a chave ligada, cada run abre a própria cópia de trabalho:

```
~/.pulse/worktrees/<slug>     branch  <slug>
```

O slug confirmado nomeia os dois: a branch fica como foi digitada e a pasta troca
`/` por `-` (slug `feat/fix-login` → pasta `feat-fix-login`, branch
`feat/fix-login`). Se outra run já ocupa a pasta, ela ganha o id curto da run
como sufixo.

- A árvore de trabalho do editor fica intocada e runs simultâneas não se atropelam.
- O worktree **permanece** quando a run acaba — ele é a entrega. Sai pelo detalhe
  da run no Histórico (tecla `w`) ou junto quando a run é apagada.
- Um worktree com mudança não commitada é mantido e o Pulse avisa. A branch
  sempre fica.

Com a chave desligada (o padrão), a run roda na raiz do projeto. Nos dois casos
a sessão mostra a branch atual ao lado do modelo.

## Daemon e API

```bash
pulse daemon start|status|stop
pulse-engine                                  # foreground (= python -m pulse.daemon serve)
pulse-engine --host 127.0.0.1 --port 8787
```

Garantias de segurança do listener:

- `--host` aceita apenas `127.0.0.1` ou `localhost`, e a API recusa requests de
  navegador ([ADR 0003](docs/adr/0003-listeners-locais-recusam-navegador.md)).
- Por TCP, toda request leva o token do daemon, que muda a cada início
  ([ADR 0005](docs/adr/0005-tcp-exige-token-do-daemon.md)).

```bash
curl -H "Authorization: Bearer $(jq -r .token ~/.pulse/daemon.json)" \
  http://127.0.0.1:8787/api/status
```

## Referência de comandos

Toda run é iniciada pelo menu interativo do `pulse` — não há subcomando de workflow.

| Comando | Descrição |
| --- | --- |
| `pulse` | Welcome + menu interativo (ou wizard no primeiro uso) |
| `pulse init` | Wizard de onboarding |
| `pulse init --force` | Reconfigurar |
| `pulse doctor` | Verificar o ambiente |
| `pulse doctor --test-acp` | Verificar o ambiente, incluindo teste ACP |
| `pulse config` | Mostrar a config efetiva (global + projeto) |
| `pulse config init` | Registrar o projeto atual no SQLite |
| `pulse daemon start\|status\|stop` | Gerenciar o daemon |

## Documentação

| Documento | Conteúdo |
| --- | --- |
| [Arquitetura](ARCHITECTURE.md) | Camadas, fluxos, eventos SSE e glossário |
| [Armazenamento](docs/armazenamento.md) | O que é persistido e onde |
| [Agentes](docs/agentes.md) | Agentes e o loop de execução, passo a passo |
| [Workflows](docs/workflows.md) | Workflow como dado: definição, motor e retomada |
| [Logs](docs/logs.md) | ACP bruto vs stream do cockpit |
| [Questions](docs/questions.md) | Questionário ` ```text `, `ask_question` e MCP |
| [Quality scorecard](docs/quality-scorecard.md) | Avaliação de qualidade do projeto |
| [ADRs](docs/adr/) | Decisões de arquitetura registradas |

## Desenvolvimento

```bash
uv sync && pre-commit install
```

O mesmo conjunto de checagens roda localmente e no CI
([`.github/workflows/ci.yml`](.github/workflows/ci.yml)):

```bash
pytest --cov                                   # suíte completa + piso de cobertura por branch
ruff check . && ruff format --check .
mypy
vulture                                        # código morto
lint-imports                                   # contratos de import entre camadas
deptry .                                       # dependências não usadas, ausentes ou transitivas
mutmut run && mutmut export-cicd-stats && python scripts/mutation_gate.py --min 80
```

Além disso, o CI roda a suíte três vezes em ordem aleatória no Python 3.11,
mede o mutation score dos parsers e executa os scanners de segurança (Bandit,
Semgrep, pip-audit e Gitleaks). Invariantes de arquitetura — seed de fábrica,
contrato OpenAPI, contratos de import, tamanho de arquivo, links da documentação —
são testes em [`tests/architecture/`](tests/architecture/).

## Comunidade

| Quero… | Onde |
| --- | --- |
| Tirar uma dúvida | [Discussions → Q&A](https://github.com/pulse-ai-orchestrator/pulse.ai/discussions/categories/q-a) |
| Sugerir uma ideia ou um workflow | [Discussions → Ideas](https://github.com/pulse-ai-orchestrator/pulse.ai/discussions/categories/ideas) |
| Mostrar como uso o Pulse | [Discussions → Show and tell](https://github.com/pulse-ai-orchestrator/pulse.ai/discussions/categories/show-and-tell) |
| Reportar um bug | [Issues](https://github.com/pulse-ai-orchestrator/pulse.ai/issues/new/choose) |
| Fazer a primeira contribuição | [`good first issue`](https://github.com/pulse-ai-orchestrator/pulse.ai/labels/good%20first%20issue) |

Quem participa concorda com o
[Código de Conduta](https://github.com/pulse-ai-orchestrator/pulse.ai/blob/main/CODE_OF_CONDUCT.md).

## Contribuindo

Contribuições são bem-vindas. O passo a passo completo está no
[guia de contribuição](https://github.com/pulse-ai-orchestrator/pulse.ai/blob/main/CONTRIBUTING.md).
Antes de abrir um PR:

1. Leia [`AGENTS.md`](AGENTS.md) — as regras que valem para humanos e agentes.
2. Faça branch a partir de `main` e use [conventional commits](https://www.conventionalcommits.org/).
3. Todo comportamento novo ou bug corrigido vem com um teste que falha sem a mudança.
4. Preencha o [template de PR](.github/pull_request_template.md), apontando o
   teste que prova cada afirmação.

Questões de segurança: use o kit em
[`.claude/skills/security-audit/`](.claude/skills/security-audit/SKILL.md) e
reporte vulnerabilidades em canal privado, não em issue pública, seguindo a
[política de segurança](https://github.com/pulse-ai-orchestrator/pulse.ai/blob/main/SECURITY.md).

## Licença

Distribuído sob a licença MIT. Veja [`LICENSE`](LICENSE).
