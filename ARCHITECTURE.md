# Arquitetura do Pulse

Documento para quem está chegando no projeto (incluindo quem ainda não domina Python).

> **Prefere navegar?** [`docs/arquitetura.html`](docs/arquitetura.html) é o mesmo
> conteúdo como mapa clicável — camadas, modelo de dados e o fluxo de uma run.
> Abra o arquivo no navegador.

## O que é o Pulse

O **Pulse é um orquestrador de agentes de IA**. A responsabilidade dele é uma só:

> **apontar qual agente roda agora e quando.**

Ele não sabe o que o agente faz. Não lê o que o agente produziu, não valida
formato, não espera arquivo com nome conhecido. Workflows, steps e agentes são
**dado em SQLite**, não código — e é por isso que o pacote Python não contém
nenhum `.md`, `.yaml` ou prompt de domínio.

Você interage pela **TUI** (terminal, feita com Textual). Quem executa é o
**Engine** (processo em background, o *daemon*).

```
Você digita `pulse`
        │
        ▼
   CLI / TUI  ───HTTP/UDS──►  Engine (daemon)  ───ACP──►  runtime
   (só tela)                  (orquestrador)              (cursor | claude)
                                    │                          │
                                    ▼                          ▼
                              ~/.pulse/pulse.db          arquivos no workspace
                              (tudo do Pulse)            (só o agente escreve)
```

### Analogia rápida

| Peça | É como… |
|------|---------|
| CLI / TUI | App no celular |
| Engine | Servidor / backend |
| Contrato HTTP | API REST entre app e servidor |
| ACP | Canal de conversa com o agente |
| `~/.pulse/pulse.db` | Banco de dados da aplicação |
| Workflow | Uma receita gravada no banco, não um recurso do código |

---

## Princípios

1. **Agnóstico ao agente** — nenhum workflow, step ou prompt de domínio no
   pacote. O Pulse sequencia steps e lê um desfecho de aprovação; o resto é dado.
2. **Nada em arquivo, exceto artefato** — config, definições e estado vivem em
   `~/.pulse/pulse.db`. O único conteúdo em disco é o que o **agente** escreve, e
   desse o Pulse guarda só o caminho. A única exceção é o `git worktree` de uma
   run isolada (§Onde a run trabalha): diretório criado pelo git, em
   `~/.pulse/worktrees/`, e nunca conteúdo escrito pelo Pulse.
3. **Daemon = verdade única** — runs, config efetiva e estado vivem no Engine.
4. **CLI é cliente fino** — a TUI não importa `orchestrator/` nem `acp/` para
   executar; fala com a API.
5. **Um contrato, dois transportes** — mesmas rotas `/api/*` em **UDS**
   (`~/.pulse/daemon.sock`, CLI local) e **TCP** (`127.0.0.1:8787`, tooling e
   clientes futuros).
6. **Ports & Adapters** — o domínio depende de interfaces (`StreamSink`,
   `PromptPort`), não de Textual.

Contrato OpenAPI: [`contracts/openapi.yaml`](contracts/openapi.yaml).

---

## 1. O modelo: workflow é dado

Esta é a mudança que define a arquitetura atual. Um workflow **não existe no
código** — existe como linhas em três tabelas de definição, e uma run gera linhas
em quatro tabelas de estado.

```
  DEFINIÇÃO (o que existe)              ESTADO (o que aconteceu)
  ────────────────────────              ────────────────────────
  workflow_defs                         runs
    id, label, description                id, workflow_id, workspace_root
    is_default                            user_prompt, status, current_step
        │ 1..N                                │ 1..N
        ▼                                     ▼
  workflow_steps                        run_steps
    workflow_id, step_id                  run_id, step_id, position, label
    position, label                       agent_id, status, summary
    agent_id ──────┐                      acp_session_id, started_at, ended_at
    prompt_template│                          │
    requires_approval                         ├──► run_events
    requires_outcome, fan_out                 │
        ┌──────────┘                          │      kind, title, detail, tool_id
        ▼                                     │
  agent_defs                                  └──► run_artifacts
    id, label, runtime                               path, step_id
    model, permission_policy
    instructions
```

**Definição** é editável e vale para todas as runs futuras.
**Estado** é imutável depois do fato: `run_steps` copia `label` e `position` da
definição quando a run começa, para que editar o workflow depois não reescreva o
que já aconteceu.

### A configuração de fábrica é semente do banco

[`pulse/store/factory/`](pulse/store/factory/) roda com `INSERT OR IGNORE` na
primeira abertura do banco e grava os loops de fábrica (Nova spec, Correção
rápida, Setup do projeto, Analisar codebase, Executar) com os
agentes deles — sem runtime nem model fixos (vazio = "use o padrão da máquina").

`INSERT OR IGNORE` é o detalhe que importa: quem já editou não perde nada no
upgrade, e linha de fábrica apagada volta na abertura seguinte.

Os playbooks e templates são `.md` dentro de `store/factory/` — ~8 mil linhas
que precisam ser revisáveis em diff. **Semente não é catálogo:** eles viram linha
uma vez e nunca mais são lidos; o motor lê as tabelas, e nenhum módulo fora de
`store/db.py` importa a fábrica (`test_domain_markdown_lives_only_in_the_factory_seed`
falha se isso mudar).

### Id desconhecido não existe

Não há catálogo em código, nem fallback. `get_workflow(id)` devolve `None`, o
motor levanta `UnknownWorkflow` e a API responde `404`.

Detalhe completo do modelo: [`docs/workflows.md`](docs/workflows.md).

---

## 2. O motor

[`pulse/orchestrator/engine.py`](pulse/orchestrator/engine.py) — uma função
pública, `run_workflow`, e nenhum `if workflow_id == ...`:

```
run_workflow(workflow_id, user_prompt, …)
  │
  ├─ get_workflow(id)                  definição + steps, do banco
  ├─ resolve_config(workflow=id)       runtime, model, policy, cwd
  ├─ check_runtime_ready(runtime)      binário e auth antes de gastar sessão
  ├─ create_run | load_run             `runs` + N em `run_steps`
  └─ para cada step ainda pendente:
       │
       ├─ control.checkpoint()         ◄── ponto de corte do parar
       ├─ resolve_config(pulse_agent=step.agent_id)
       ├─ runner.use_agent(…)          o agente DESTE step
       ├─ render(step.prompt_template) com os valores da run
       ├─ requires_approval ? run_isolated_phase : run_isolated_prompt
       ├─ classify_outcome(…)          approve | adjust | skip | cancel
       ├─ parse_outcome(…)             done | blocked  (step sem aprovação)
       └─ record.deliver()/block()…   desfecho no agregado → save(run)
```

### Sessão ACP isolada por step

Cada step abre e fecha a própria sessão. O agente do step seguinte **não herda o
contexto** do anterior — recebe só o resumo que o Pulse repassa em
`{{previous_summary}}`.

É isso que permite retomar uma run refazendo um step só e manter o contexto
pequeno num pipeline longo — e é o que abriria caminho para trocar de runtime
entre steps, que hoje ainda não acontece (ver §Fora de escopo).

### O que o motor interpreta da resposta

Três blocos cercados que o próprio Pulse especificou — nunca o conteúdo do que o
agente produziu, nunca um arquivo que ele escreveu.

**1. O questionário de aprovação**
([`pulse/prompts/approval.py`](pulse/prompts/approval.py)):

| Desfecho | Efeito |
|----------|--------|
| `approve` | step vira `done`, segue |
| `adjust` / `continue` | devolve a conversa ao agente com as respostas |
| `skip` | step vira `skipped` — não é falha |
| `cancel` | step não fechou; cai no menu de retry |

**2. O desfecho do step sem aprovação**
([`pulse/orchestrator/outcome.py`](pulse/orchestrator/outcome.py)). Um step tem
um portão só: onde há aprovação quem atesta a entrega é a pessoa; onde não há, é
o agente, no bloco `pulse:outcome`:

````text
```pulse:outcome
status: blocked
reason: falta a credencial do banco
needs: user
```
````

Antes desse bloco, fechar o turno bastava para o step virar `done` — um agente
que dizia "não consigo" era registrado como concluído e o step seguinte rodava
em cima de uma entrega que não existiu, em cascata. Agora: bloqueio sem
`needs: user` (e bloco esquecido) voltam uma vez para o próprio agente, na mesma
sessão, para ele destravar o que estiver ao alcance dele; o que sobra vira
`blocked` e **para a run** (`RUN_BLOCKED`, 131), que não é falha — nada quebrou,
a entrega é que não aconteceu. `requires_outcome = 0` desliga o protocolo por
step e devolve o comportamento antigo. A tabela que transforma a resposta em `done`/`blocked`/
`failed`/`skipped` é uma função pura,
[`judge_attempt`](pulse/orchestrator/verdict.py); o engine só aplica o veredito
à run.

**3. A lista de itens do fan-out**
([`pulse/orchestrator/fanout.py`](pulse/orchestrator/fanout.py)).

Falha ou não-aprovação abre **Refazer / Outro — dizer o que fazer / Parar**;
bloqueio abre o mesmo menu com **Pular este step** a mais. "Outro" injeta a
orientação do usuário no prompt da tentativa seguinte. Sem ninguém para
perguntar (CLI, daemon), os dois param a run: o que ninguém vê não segue
adiante sozinho.

### Sair, voltar e parar

São três coisas diferentes, e só a última toca na run.

**Sair** (`q`/`Esc` no cockpit) fecha a tela. A run não é da tela: ela roda numa
thread do daemon, que é outro processo. Sair solta o stream SSE
([`EngineRunSession.detach`](pulse/client/run_session.py)) e **larga** a ponte de
prompts ([`PromptBridge.abandon`](pulse/tui/adapters/prompt_bridge.py)) em vez de
fechá-la — fechar resolveria a pergunta aberta com `None`, que para o agente é
"cancelado". Com `abandon` a pergunta continua pendente no daemon, esperando a
pessoa voltar; quem morre é a thread da tela, com `PromptAbandoned`.

É por isso que `PromptCorrelator.request` não tem prazo. O limite de uma hora que
existia ali matava a premissa: a pessoa saía, a pergunta expirava sozinha e o
agente recebia "cancelado" sem ninguém ter decidido nada.

**Voltar** é anexar à run viva, e a porta é o **Histórico** — que é onde as runs
já moravam. Ele passa a listar as `executando` no topo (`HistoryCatalog.list_items`
reordena, de forma estável, mantendo a mais recente primeiro dentro de cada
grupo) e abre ao vivo, em vez da página estática, aquela que o daemon ainda tem
(`GET /api/runs`). A Home não lista run nenhuma: ela é o menu do que se pode
começar, e uma lista que muda sozinha ali competia com isso.

Reabrir **não reidrata do banco**: o `EventBus` reenvia todo
o histórico da run antes do vivo, então o mesmo `CockpitSink` que desenharia a
run ao vivo a reconstrói inteira, pelo mesmo caminho. O marcador
`stream.replay_end` separa passado de presente, e serve para duas coisas:

- não reabrir pergunta já respondida — no replay o `prompt.request` é guardado e
  o `prompt.answered` o descarta; só o que sobra no fim está vivo;
- acertar o relógio ([`hydrate.stamp_live_elapsed`](pulse/tui/hydrate.py)), porque
  os `phase.begin` reaplicados marcariam "agora" como início de cada step.

Rodam **N runs ao mesmo tempo**. Daí o id da run ser único: `RunState.id` é o
mesmo `runs.id` do SQLite (o daemon batiza a run e passa o id ao motor em
`run_workflow(run_id=…)`). Antes eram dois ids diferentes, e "reabrir a run X"
só podia ser o chute "a mais recente deste workspace".

**Parar** (`s` no cockpit) é o único que mexe na run. Ele corta o turno em voo
(`session/cancel`), devolve o step em curso para `pending` — não terminou, logo
não é `done` nem `failed` — e encerra a run com exit code `RUN_STOPPED` (130),
que não é falha: o cockpit oferece retomar na hora.

Não existe pausa. Segurar a run viva esperando o usuário custava thread e sessão
ACP abertas por tempo indefinido e dava no mesmo: a sessão ACP não congela no
meio de um turno, então o step cortado é refeito do começo de qualquer jeito.

Retomar = rodar o primeiro step que não está `done`/`skipped` — `blocked` fica
de fora desse par de propósito: retomar uma run bloqueada refaz o step que
travou, e só ele. É a única porta
de volta a uma run: não existe "refazer do zero", porque rodar tudo de novo é
começar uma run nova — assim a tentativa anterior fica no histórico em vez de ser
sobrescrita.

O `run_id` é o mesmo, então o cockpit reabre com o passado da run:
[`hydrate.restore_run`](pulse/tui/hydrate.py) devolve log, tools e duração de
`run_events`/`run_steps` antes de o motor recomeçar. Sem isso a tela nascia vazia
e o que já tinha fechado voltava como "concluído" e nada mais.

Run que **falhou** também é retomável, e é o caso em que mais se quer voltar: o
que já fechou está em `run_steps`, então retomar roda só o que faltou. Quem
decide é o step, não o status da run — por isso um step que não fecha é gravado
como `failed` na hora, e nunca fica `running` no banco depois que a run acabou.

Contrato completo: [`pulse/runcontrol.py`](pulse/runcontrol.py).

### Esperar o usuário não é pausar a run — mas também não é trabalho do agente

Quando o agente pede algo a quem está na frente da tela (permissão de tool,
questionário, aprovação de step, menu de retry ou de bloqueio), a run não pausa:
ela continua viva, com a sessão ACP aberta, só que **parada**. Enquanto isso:

* a run é reportada com status `awaiting_input` (`/api/runs` e tabela `runs`), e
  o evento `run.awaiting` vai pelo barramento para toda tela anexada;
* o cronômetro do step congela, e o tempo esperado é somado em
  `run_steps.waiting_seconds` — a duração que a sidebar e o histórico mostram é
  sempre `ended_at - started_at - waiting_seconds`. Sem esse desconto, uma
  aprovação deixada para o dia seguinte aparecia como um step de doze horas;
* a Home anuncia a sessão no painel de avisos, com a mesma lista que o
  `pulse daemon status` imprime.

O ponto único onde isso é observado é
[`_WatchedPrompts`](pulse/acp/session_runner.py), o proxy que embrulha o
`PromptPort`: toda pergunta — do ACP ou do motor — passa por ele, então não há
caminho de pergunta que escape da contagem. O runner não grava nada: avisa a
porta `UserWaitListener` ([`pulse/ports.py`](pulse/ports.py)), e o motor liga a
ela o [`RunWaits`](pulse/orchestrator/waits.py), que aplica a intenção no
agregado (`run.await_input()`, `step.add_wait()`, `run.resume_work()`) e salva a
run inteira. Uma run que terminou com a pergunta aberta (parar) mantém o fim que
teve — fechar a pergunta não a devolve a `running`.

**O que a política resolve não é pergunta.** `auto_approve`, `deny_writes` e o
veto a terminal são regra, e regra o Pulse aplica onde a run roda:
[`decide_permission`](pulse/prompts/permission.py) devolve a resposta e só cai
no `None` — que é o que vira pergunta de verdade — quando a política é `ask`,
ou em `deny_writes` quando o kind não diz se escreve (`execute`, desconhecido).
Enquanto essa decisão morava só na TUI, uma run com o cockpit fechado parava
para sempre num `edit`: o daemon publicava a pergunta, não havia tela para
respondê-la, e a run ficava "precisando de você" para algo que já estava
decidido. Quem fecha a tela não pode travar a run; quem decide por política não
pode acordar ninguém.

### Onde a run trabalha

Por padrão, onde sempre trabalhou: a raiz do projeto. Quem liga **"Worktree"**
nas configurações do projeto (`project_settings.use_worktree`, e a opção só
aparece se o root for repositório git) passa a ter **uma run, um worktree**:

```
~/.pulse/worktrees/<run_id>        branch `pulse/<workflow>-<run curto>`
```

O que isso resolve é a mistura: duas runs simultâneas escreviam na mesma árvore
de trabalho, e qualquer run misturava a entrega do agente com o que a pessoa
estava editando no editor. Com o worktree, revisar a entrega de uma run é um
`git diff` de uma branch, e descartá-la é apagar um diretório.

Dois caminhos saem daqui, e confundi-los quebra coisas diferentes:

| Valor | É | Quem usa |
|---|---|---|
| `runs.workspace_root` | A **raiz do projeto** | histórico, `resolve_config`, `find_resumable` |
| `runs.worktree_path` | Onde o **agente** escreveu | `AcpSessionRunner(cwd=…)`, `{{workspace}}`, painel de artefatos |

`workspace_root` continua sendo a raiz mesmo com worktree porque é por ele que
o histórico casa a run ([`HistoryCatalog`](pulse/history/catalog.py)); gravar o
worktree ali sumiria com a run da lista do projeto. E a config é resolvida pela
raiz porque `load_project_config` procura o root registrado em `projects` — um
worktree não está lá, e resolver por ele faria as settings por agente sumirem
sem erro nenhum.

Quem decide é [`_prepare_workspace`](pulse/orchestrator/engine.py), em três
casos: run retomada **reusa** o worktree que já tem (abrir um segundo jogaria
fora o que os steps anteriores produziram); sem isolamento, roda na raiz; com
isolamento, `git worktree add`. Falhar ao abrir o worktree **para a run** —
rodar na árvore de trabalho da pessoa é justamente o que a chave pediu para não
acontecer.

A branch é lida nos três casos, inclusive sem worktree, e é isso que faz a
sessão mostrar `modelo · branch` na linha de meta do stream. Ela chega à tela
pelo evento `run.context` (cwd + branch), publicado antes do primeiro step:
como vai pelo barramento, o replay o entrega a quem anexa depois, e o painel de
artefatos reaponta sozinho para o diretório certo.

**O worktree não é limpo sozinho.** Ele é a entrega — o código está lá, na
branch onde foi escrito. Sai pelo detalhe do histórico (`w`), ou junto quando a
run é apagada, e em nenhum dos dois com `--force`: worktree com mudança não
commitada é mantido, porque quem apaga uma linha do histórico não está pedindo
para jogar trabalho fora. A branch sempre fica.

O git falado aqui é o CLI por `subprocess`, em [`pulse/vcs/`](pulse/vcs/).
Leitura nunca levanta (sem git no PATH, a sessão só fica sem branch); só
`worktree add` e `worktree remove` levantam.

### Valores disponíveis no `prompt_template`

`{{chave}}`, e `{{#if chave}}…{{/if}}` para trecho opcional
([`pulse/prompts/render.py`](pulse/prompts/render.py)). Chave sem valor é
**erro**, não buraco — instrução truncada sairia silenciosa e ninguém notaria até
a run sair errada.

| Chave | Conteúdo |
|-------|----------|
| `user_prompt` | o que o usuário pediu |
| `workspace` | diretório onde o agente trabalha (o worktree, quando há um) |
| `workflow_id` / `run_id` / `step_id` / `step_label` | identidade do passo |
| `previous_summary` | resposta do último step que produziu resumo |
| `previous_status` | como aquele step fechou: `done` ou `skipped` |
| `artifacts` | arquivos que a run já escreveu, um por linha |

Note o que **não** existe: nenhuma chave com nome de artefato ou de fase. O motor
não tem nenhum para oferecer.

---

## 3. Camadas (de fora para dentro)

### 3.1 Entrada — CLI

| Arquivo | Função |
|---------|--------|
| [`pulse/cli.py`](pulse/cli.py) | Lê o comando (`init`, `doctor`, `config`, `daemon`) ou abre a TUI |
| [`pulse/cli_daemon.py`](pulse/cli_daemon.py) | `pulse daemon start \| stop \| status` |
| [`pulse/__main__.py`](pulse/__main__.py) | Permite `python -m pulse` |

Entry points: `pulse` → CLI, `pulse-engine` → daemon em foreground,
`pulse-mcp-ask` → servidor MCP de perguntas.

### 3.2 Interface — TUI Textual

Só tela e interação. Não executa workflow no próprio processo.

| Caminho | Função |
|---------|--------|
| [`pulse/tui/app.py`](pulse/tui/app.py) | App Textual; abre home, cockpit, settings, onboarding, history |
| [`pulse/tui/screens/home.py`](pulse/tui/screens/home.py) | Menu; lista os workflows vindos do banco |
| [`pulse/tui/screens/cockpit.py`](pulse/tui/screens/cockpit.py) | Run ao vivo (steps, log, prompts, artefatos) |
| [`pulse/tui/screens/settings.py`](pulse/tui/screens/settings.py) | Runtime, modelo, permissões por agente; doctor |
| [`pulse/tui/screens/history*.py`](pulse/tui/screens/) | Runs passadas e detalhe |
| [`pulse/tui/state.py`](pulse/tui/state.py) | `CockpitState` — estado visual, só memória |
| [`pulse/tui/adapters/cockpit_sink.py`](pulse/tui/adapters/cockpit_sink.py) | Eventos do Engine → atualiza a tela |
| [`pulse/tui/adapters/prompt_bridge.py`](pulse/tui/adapters/prompt_bridge.py) | Perguntas/aprovações na TUI |
| [`pulse/tui/hydrate.py`](pulse/tui/hydrate.py) | Reconstrói a tela a partir de uma run gravada |

A sidebar é montada por `configure_workflow(id)`, que lê `workflow_steps` pelo
**mesmo caminho do motor**. Não há mapa de fases na UI.

### 3.3 Cliente do Engine

| Arquivo | Função |
|---------|--------|
| [`pulse/client/engine_client.py`](pulse/client/engine_client.py) | Cliente HTTP (UDS preferido; TCP fallback); pode auto-iniciar o daemon |
| [`pulse/client/run_session.py`](pulse/client/run_session.py) | Cria (ou **anexa**) → escuta SSE → responde `prompt.request` → devolve exit code |
| [`pulse/client/active_runs.py`](pulse/client/active_runs.py) | O que está rodando agora, para o Histórico oferecer voltar |

### 3.4 Engine — daemon (composition root)

| Arquivo | Função |
|---------|--------|
| [`pulse/daemon/server.py`](pulse/daemon/server.py) | Sobe Uvicorn em TCP + UDS; ancora o cwd em `~/.pulse` |
| [`pulse/daemon/runs.py`](pulse/daemon/runs.py) | `RunManager`: uma thread por run (N simultâneas); listar, cancelar, podar as encerradas |
| [`pulse/daemon/events.py`](pulse/daemon/events.py) | Barramento de eventos + correlator de prompts |
| [`pulse/daemon/adapters.py`](pulse/daemon/adapters.py) | `StreamSink`/`PromptPort` do domínio → eventos SSE |
| [`pulse/api/app.py`](pulse/api/app.py) | Rotas FastAPI |

O daemon **não** usa o diretório de quem o iniciou. Ele sobe destacado e ficaria
meses com esse cwd herdado; apagar o projeto de origem o deixaria parado numa
pasta da Lixeira, onde o macOS nega até `getcwd()` — e toda run nova morria aí,
antes do primeiro step. Por isso `run_daemon` faz `chdir` para `~/.pulse`, e
quem ainda precisa perguntar "onde estamos?" usa
[`safe_cwd`](pulse/config/paths.py), que cai no mesmo diretório em vez de
levantar. Nada se perde: a run sempre roda com `cwd` explícito — o workspace que
o cliente mandou, ou o worktree dela.

#### API (`/api`)

| Recurso | Rotas |
|---------|-------|
| Runtime | `GET /status`, `GET /doctor`, `POST /doctor/acp-probe` |
| Config | `GET /config`, `GET /config/resolved`, `PATCH /config/global`, `POST /config/project` |
| Workflows | `GET /workflows` (do banco, com os steps), `POST /workflows/{id}/runs` |
| Runs | `GET /runs` (o que está vivo), `GET /runs/{id}`, `POST /runs/{id}/cancel`, `GET /runs/{id}/events?after=N` (SSE) |
| Prompts | Engine emite `prompt.request` no SSE; cliente responde `POST /prompts/{id}/answer` |
| History | `GET /history`, `GET /history/{id}` |

#### Eventos no SSE

`run.started` · `run.stopped` ·
`run.cancel_requested` · `run.finished` · `run.context` · `phase.begin` ·
`phase.info` · `phase.error` · `phases.sync` · `session.update` · `session.id` ·
`stream.finish` · `stream.finish_question` · `prompt.request` · `prompt.answered` ·
`stream.replay_end` · `stream.ping`

`run.context` abre a run dizendo onde ela trabalha e em que branch (ver §Onde a
run trabalha). Vem antes de qualquer `phase.begin` de propósito: é por ele que o
painel de artefatos sabe em que pasta procurar arquivo.

Os dois últimos são do transporte, não da run: `stream.replay_end` marca onde o
passado reenviado acaba (ver §Sair, voltar e parar) e `stream.ping` é o
batimento do stream ocioso, que dá ao cliente um ponto de retorno regular para
largar o stream sem a run precisar emitir nada.

### 3.5 Domínio

Usado pelo Engine. A TUI **não** chama isso direto para executar.

| Arquivo | Função |
|---------|--------|
| [`pulse/ports.py`](pulse/ports.py) | `StreamSink`, `PromptPort` + implementações Null |
| [`pulse/orchestrator/engine.py`](pulse/orchestrator/engine.py) | `run_workflow` — o laço de steps, retry e parada |
| [`pulse/orchestrator/prompts.py`](pulse/orchestrator/prompts.py) | Os dois textos que o próprio Pulse escreve |
| [`pulse/prompts/render.py`](pulse/prompts/render.py) | Engine `{{placeholder}}` |
| [`pulse/prompts/approval.py`](pulse/prompts/approval.py) | Lê o desfecho do questionário |
| [`pulse/runcontrol.py`](pulse/runcontrol.py) | Parar uma run, seguro entre threads |

### 3.6 ACP e runtimes

| Arquivo | Função |
|---------|--------|
| [`pulse/acp/session_runner.py`](pulse/acp/session_runner.py) | Processo do agente, sessões, prompts, updates, artefatos |
| [`pulse/acp/client.py`](pulse/acp/client.py) | Cliente ACP + probe de conexão |
| [`pulse/runtimes/`](pulse/runtimes/) | `AgentRuntime` + backends `cursor` e `claude` |

Adicionar um agente novo é escrever um módulo com a subclasse de `AgentRuntime` e
registrá-lo em `RUNTIMES`. Config, doctor, onboarding e session runner passam a
enxergá-lo sem mudanças.

### 3.7 Store, config, history

| Pasta | Função |
|-------|--------|
| [`pulse/store/workflow_defs.py`](pulse/store/workflow_defs.py) | Definições de workflow, step e agente |
| [`pulse/domain/run.py`](pulse/domain/run.py) | Agregado da run: `RunRecord`/`StepRecord`, status e transições com guarda, sem I/O |
| [`pulse/store/runs.py`](pulse/store/runs.py) | Persistência da run, log e artefatos |
| [`pulse/store/db.py`](pulse/store/db.py) | Schema + disparo da semente |
| [`pulse/store/factory/`](pulse/store/factory/) | Semente: os loops e playbooks de fábrica, lidos uma vez |
| [`pulse/config/`](pulse/config/) | Config global e por projeto, resolve efetivo, catálogo de models |
| [`pulse/history/`](pulse/history/) | Runs passadas, lidas de `runs`/`run_steps` |
| [`pulse/doctor/`](pulse/doctor/) | Checks de binário/auth/ambiente |
| [`pulse/mcp/`](pulse/mcp/) | Ponte MCP AskQuestion |
| [`pulse/runtime/`](pulse/runtime/) | `is_interactive`, `is_pulse_ready` (não confundir com `runtimes/`) |
| [`pulse/vcs/`](pulse/vcs/) | O git que o Pulse fala: branch atual e worktree por run |

---

## 4. Como um agente é resolvido

Duas cascatas diferentes, e é fácil confundi-las.

**Por workflow** (qual backend a run usa por padrão):

```
projeto.workflows[id] → global.workflows[id] → projeto.defaults
                     → global.defaults → defaults do código
```

**Por agente de step** (quem roda *este* step):

```
agent_defs[step.agent_id]       runtime/model/policy declarados
  → agent_settings              o que o usuário ajustou na TUI (por projeto)
  → cascata de defaults acima
  → fallback de disponibilidade  runtime declarado não instalado nesta máquina
```

Campo vazio em `agent_defs` significa "use o padrão da máquina". Gravar um
runtime concreto na semente congelaria a escolha feita no `pulse init`.

`machine_workflows` e `project_workflows` guardam **override de agent/model por
id de workflow** — não definem pipeline, e nascem vazios.

Código: [`pulse/config/resolved.py`](pulse/config/resolved.py).

---

## 5. Artefatos

O Pulse **não gera arquivo nenhum**. O agente escreve onde o `prompt_template` do
step mandar.

A descoberta é pelos **tool-calls do ACP**: um `write`/`edit`/`create` faz o
`AcpSessionRunner` gravar o caminho em `run_artifacts`
([`_record_artifacts`](pulse/acp/session_runner.py)). O caminho vem de
`locations[].path` ou do `rawInput` — cada runtime reporta de um jeito.

Consequência: não há convenção de pasta, de nome nem de extensão. `src/main.rs` é
tão artefato quanto `docs/PLANO.md`.

O caminho é gravado **relativo ao diretório onde a run trabalhou**, que com
isolamento é o worktree dela (§Onde a run trabalha). Por isso o painel precisa
do `run.context`: é ele que diz a raiz sobre a qual esses caminhos se abrem.

---

## 6. Fluxo completo (uma run na TUI)

```
 1. Usuário: pulse
 2. cli.py garante o Engine up → abre PulseApp (HomeScreen)
 3. Home lista os workflows de `workflow_defs`; usuário escolhe e descreve a tarefa
 4. CockpitScreen monta a sidebar a partir de `workflow_steps` → EngineRunSession
 5. client: POST /api/workflows/{id}/runs
 6. daemon/runs.py abre uma thread → orchestrator/engine.py
 7. Cria a run (`runs` + `run_steps`) e entra no laço de steps
 8. Por step: resolve o agente, renderiza o prompt, abre sessão ACP isolada
 9. Agente responde → session/update → SSE → CockpitSink → tela;
    write/edit → run_artifacts; tudo → run_events
10. Agente pergunta → prompt.request → dock na TUI → POST /prompts/{id}/answer
11. Fim do turno → questionário de aprovação → step vira `done` → próximo step
12. run.finished → o que permanece são os arquivos que o agente escreveu
```

Em qualquer ponto de 8 a 11 o usuário pode sair (`q`): a run segue no daemon e o
Histórico a mostra no topo, como `executando`. Entrar de volta refaz os passos 9
a 11 desde o começo da run, reenviados pelo barramento — a tela volta como
estava, e só então o vivo continua.

Reabrir uma run **encerrada** pelo histórico usa as mesmas tabelas: `run_steps` dá a sidebar,
`run_events` dá o stream, `run_artifacts` dá o painel — sem ler o store do
runtime nem varrer pasta.

O que vai para `run_events` é o **mesmo rótulo** que a tela ao vivo mostra:
`acp/session_runner.py` acumula os updates de cada tool-call e passa por
`history/tool_detail.build_tool_labels` antes de gravar, então o tipo (`Read`,
`Shell`, `Write`…), o alvo e o detalhe são os da sessão viva — e o caminho do
artefato é gravado relativo ao workspace, que é como o painel o abre.

O **diálogo** segue junto: toda pergunta feita à pessoa — `AskQuestion`,
questionário, aprovação de fase, permissão, menu de retry — atravessa o proxy
`_WatchedPrompts` do `session_runner`, e de lá vai para `run_events` como o par
`Pergunta`/`Você` que a tela desenha, com o texto montado por
`history/prompt_detail.build_prompt_qa`. Quem grava é o daemon, não a TUI: a tela
só desenha, e duas janelas anexadas na mesma run gravariam a mesma resposta duas
vezes. Permissão que a política resolve sozinha não vira linha — não foi pergunta,
ninguém a viu. E o bloco de questionário que o agente escreve em texto não entra
como fala dele: vira a linha `Questionário interativo`, como no cockpit, senão as
mesmas perguntas apareceriam duas vezes.

---

## 7. O que pode / não pode misturar

| Pode | Não deve |
|------|----------|
| TUI chamar `pulse/client/` | TUI importar `orchestrator/` ou `acp/` para executar |
| Engine chamar `orchestrator/`, `acp/`, `config/` | Domínio importar Textual / widgets |
| Motor sequenciar steps | Motor interpretar o que o agente produziu |
| Motor ler o desfecho da aprovação | Motor esperar artefato com nome conhecido |
| Definição vir do banco | Definição vir de arquivo do pacote |
| `prompts/` parsear respostas | `prompts/` depender de UI |

---

## 8. Design patterns usados

| Pattern | Onde | Para quê |
|---------|------|----------|
| Composition Root | `daemon/` | Só o daemon monta o grafo de serviços |
| Ports & Adapters | `ports.py` + adapters TUI/API | Domínio independente da UI |
| Facade | `orchestrator/engine.py` | Uma entrada estável: `run_workflow` |
| Data-driven pipeline | `workflow_defs`/`workflow_steps` | Trocar o pipeline é `INSERT`, não release |
| Transport parity | UDS + TCP | Mesmo contrato para CLI e clients futuros |
| Correlated request/response | `prompt.request` + `POST /prompts/{id}/answer` | Aprovações sobre HTTP/SSE |
| Event sourcing (leve) | `run_events` | Reabrir uma run sem depender do runtime |

---

## 9. Comandos úteis

```bash
pip install -e ".[dev]"

pulse                  # TUI
pulse init             # onboarding (tela Textual)
pulse doctor           # via Engine (use --local para checks locais)
pulse config show
pulse config show --workflow default
pulse daemon start | status | stop
pulse-engine           # daemon em foreground

pytest
```

Duas invariantes que valem checar depois de mexer no pacote:

```bash
# arquivo não-Python só na semente de fábrica
find pulse -type f ! -name "*.py" -not -path "*__pycache__*" -not -path "pulse/store/factory/*"

# nenhum vocabulário de domínio fora da semente: o motor não conhece pipeline
grep -rniE "\bprd\b|techspec|new-issue|quick-fix|setup-project|analyze-codebase" \
  --include="*.py" pulse/ | grep -v "^pulse/store/factory/"
```

---

## Glossário

| Termo | Significado |
|-------|-------------|
| **Workflow** | Lista ordenada de steps, definida no banco |
| **Step** | Um passo: um agente, um prompt, uma sessão ACP isolada |
| **Run** | Uma execução concreta de um workflow |
| **Agente** | Linha em `agent_defs`: runtime + model + política + instruções |
| **Runtime** | O backend que executa um agente (`cursor`, `claude`) |
| **Artefato** | Arquivo que o agente escreveu, descoberto por tool-call |
| **Worktree** | Cópia de trabalho isolada do repositório, uma por run, em branch própria |
| **Daemon** | Processo em background (o Engine) |
| **UDS** | Unix Domain Socket — arquivo local (`daemon.sock`); HTTP por cima |
| **SSE** | Server-Sent Events — stream HTTP de eventos da run |
| **ACP** | Agent Client Protocol — JSON-RPC com o agente |
| **Port** | Interface (contrato) que o domínio espera |
| **Adapter** | Implementação da port (TUI, API, Null…) |
| **Composition root** | Único lugar que "liga" todas as peças |

---

## Fora de escopo atual

- **Tela de edição de workflow** — hoje o único caminho para criar um pipeline é
  `pulse.store.workflow_defs.save_workflow()`. É a lacuna mais visível do desenho.
- **Troca de runtime entre steps** — `resolve_config(pulse_agent=…)` já devolve um
  runtime por agente, mas o `acp_command` é fixado na construção do
  `AcpSessionRunner`, no pré-voo. Uma run inteira roda no mesmo backend; o que
  varia por step é modelo, política e instruções.
- **Gates de shell** — o Pulse não roda comando de verificação entre steps.
- **Replay sobrevive só enquanto o daemon vive** — o histórico de eventos de uma
  run está na memória do `EventBus`, e cresce sem teto durante a run. Daemon
  reiniciado (inclusive por divergência de `ENGINE_PROTOCOL` no
  `ensure_daemon`) derruba as runs vivas; o passado delas continua no banco, mas
  reabrir ao vivo deixa de existir.
- App Desktop (consumirá a mesma API HTTP), gateway remoto / pairing.
- Monorepo físico (`engine/` e `cli/` como packages separados).

---

## Referências rápidas

- Mapa interativo: [`docs/arquitetura.html`](docs/arquitetura.html)
- Uso do produto: [`README.md`](README.md)
- Agentes e o loop de execução, passo a passo: [`docs/agentes.md`](docs/agentes.md)
- Modelo de workflow: [`docs/workflows.md`](docs/workflows.md)
- Armazenamento: [`docs/armazenamento.md`](docs/armazenamento.md)
- Perguntas e aprovação: [`docs/questions.md`](docs/questions.md)
- Logs: [`docs/logs.md`](docs/logs.md)
- OpenAPI: [`contracts/openapi.yaml`](contracts/openapi.yaml)
