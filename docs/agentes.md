# Agentes: onde vivem, como são carregados e como o loop roda

Documento de referência para entender o caminho completo de um agente no Pulse —
do arquivo `.md` no repositório até um turno de conversa com o Cursor ou o
Claude, e de volta ao banco.

Complementa [`ARCHITECTURE.md`](../ARCHITECTURE.md) (visão geral das camadas) e
[`workflows.md`](workflows.md) (o modelo de dado do pipeline). Aqui o recorte é
**o agente** e **o laço de execução**, passo a passo.

---

## 0. Desambiguação: duas coisas com nome parecido

Antes de tudo, porque isso confunde quem chega:

| Caminho | O que é |
| --- | --- |
| [`pulse/store/factory/agents/`](../pulse/store/factory/agents/) | Os `.md` de fábrica. **Semente do banco**, lida uma vez. |
| [`pulse/runtimes/`](../pulse/runtimes/) (plural) | Os **backends**: qual CLI executa um agente (`cursor`, `claude`, `codex`). |

E os dois sentidos da palavra "agente", que o código separa:

- **Agente Pulse** — uma linha em `agent_defs`: um papel (`prd`, `tasks`,
  `implement`) com instruções, política de permissão e preferências.
- **Runtime** — o processo que de fato roda (`agent acp`, `npx …claude-agent-acp`).

Um agente Pulse *usa* um runtime. Trocar de runtime não muda o papel.

---

## 1. Onde vive um agente — as quatro camadas

```
  ┌─ 1. SEMENTE (repositório, .md) ────────────────────────────┐
  │  pulse/store/factory/agents/<id>/AGENT.md   instruções     │
  │  pulse/store/factory/agents/<id>/PHASE.md   prompt do step │
  │  pulse/store/factory/shared/*.md            blocos comuns  │
  └────────────────────────────┬───────────────────────────────┘
                               │ seed(), uma vez, INSERT OR IGNORE
                               ▼
  ┌─ 2. DEFINIÇÃO (~/.pulse/pulse.db) ─────────────────────────┐
  │  agent_defs       id, label, runtime, model,               │
  │                   permission_policy, instructions          │
  │  workflow_steps   …, agent_id, prompt_template, fan_out    │
  └────────────────────────────┬───────────────────────────────┘
                               │ leitura a cada step
                               ▼
  ┌─ 3. AJUSTE DO USUÁRIO (~/.pulse/pulse.db) ─────────────────┐
  │  agent_settings   project_id, agent_id,                    │
  │                   runtime, model, permission_policy        │
  │  (tela de Configurações da TUI)                            │
  └────────────────────────────┬───────────────────────────────┘
                               │ resolve_config(pulse_agent=…)
                               ▼
  ┌─ 4. EXECUÇÃO (processo) ───────────────────────────────────┐
  │  pulse/runtimes/{cursor,claude,codex}.py → subprocess ACP  │
  └────────────────────────────────────────────────────────────┘
```

**A camada 1 nunca é lida durante uma run.** Depois da primeira abertura do
banco, quem responde "quais agentes existem" é a tabela, não o pacote. Isso é
verificado por teste
(`test_domain_markdown_lives_only_in_the_factory_seed`): nenhum módulo fora de
[`store/db.py`](../pulse/store/db.py) pode importar a fábrica.

### 1.1 Anatomia de um agente de fábrica

Cada pasta em `factory/agents/<id>/` tem exatamente dois arquivos:

**`AGENT.md`** — frontmatter + playbook. Vira `agent_defs.instructions`.

```markdown
---
name: tasks
description: Escreve tasks.md
runtime: cursor            ← preferência de quem escreveu; DESCARTADA no seed
model: Auto                ← idem
permission_policy: deny_writes
---

# Tasks
**Goal**: Break into GRANULAR, ATOMIC tasks…
```

`runtime` e `model` são deliberadamente **não gravados** ([`load_agents()`](../pulse/store/factory/__init__.py)).
Campo vazio em `agent_defs` significa "use o padrão da máquina"; gravar um valor
concreto congelaria a escolha feita no `pulse init`. `permission_policy` é
gravada, porque é uma propriedade do papel, não da máquina.

**`PHASE.md`** — o prompt da fase. Vira `workflow_steps.prompt_template`.

```markdown
Workspace: `{{workspace}}`
Original task: {{user_prompt}}

<!-- include: isolation -->
<!-- include: handoff -->

## Tasks phase — break into atomic tasks (do NOT implement)
…
<!-- include: approval -->
```

Os `<!-- include: nome -->` apontam para [`factory/shared/<nome>.md`](../pulse/store/factory/shared/)
e são expandidos **na semeadura**, não em runtime. A linha do banco sai
autossuficiente: o motor nunca precisa saber que `shared/` existe.

Por que `.md` em arquivo e não string Python? São ~8 mil linhas de playbook que
alguém precisa revisar em diff.

### 1.2 A tabela de agentes de fábrica

`AGENT_LABELS` em [`factory/__init__.py`](../pulse/store/factory/__init__.py) é a
lista canônica — id da pasta → rótulo na UI:

| id | Rótulo | Usado em |
| --- | --- | --- |
| `prd` | PRD | `new-issue` |
| `techspec` | Techspec | `new-issue` |
| `tasks` | Tasks | `new-issue` |
| `implement` | Implementar | `new-issue` (fan-out; e `verify-fix`, laço do verify, fase `FIX.md`) |
| `verify` | Verificar | `new-issue` (laço, depois da última task; fecha quando não sobra lacuna) |
| `review` | Review | `new-issue` (laço), `review` (fase `STANDALONE.md`) |
| `review-fix` | Fix review | `new-issue` (laço, fecha e pede a volta), `review` (fase `STANDALONE.md`) |
| `quick-plan` | Quick plan | `quick-fix` |
| `quick-implement` | Quick implement | `quick-fix` |
| `setup-interview` | Setup — entrevista | `setup-project` |
| `setup-artifacts` | Setup — artefatos | `setup-project` |
| `codebase-explore` | Explorar codebase | `analyze-codebase` |
| `codebase-docs` | Docs de codebase | `analyze-codebase` |
| `default` | Agente | `default` — sem playbook, prompt cru |

O `default` é acrescentado direto no `seed()`, sem pasta: é o escape, e o que o
usuário pedir vai cru para o runtime.

---

## 2. O carregamento, passo a passo

Acontece uma vez por banco, dentro de `connect()`.

```
qualquer código chama store.db.connect(path)
  │
  ├─ 1. mkdir do diretório, sqlite3.connect
  ├─ 2. executescript(SCHEMA)            CREATE TABLE IF NOT EXISTS …
  ├─ 3. _apply_added_columns()           ALTER TABLE para colunas novas
  ├─ 4. factory.is_seeded(connection)?   conta só os ids de fábrica
  │      └─ sim → pula para o commit
  └─ 5. factory.seed(connection)
         │
         ├─ load_agents()   (lru_cache)
         │    para cada id em AGENT_LABELS:
         │      ler AGENT.md   → parse_frontmatter() → (meta, corpo)
         │      ler PHASE.md   → _expand_includes()  → template resolvido
         │    devolve tuple[FactoryAgent]
         │
         ├─ INSERT OR IGNORE em agent_defs
         │    (id, label, runtime='', model='', policy, instructions)
         │
         ├─ INSERT OR IGNORE em workflow_defs
         │    a partir da constante WORKFLOWS
         │
         └─ INSERT OR IGNORE em workflow_steps
              (workflow_id, step_id, position, label, agent_id,
               prompt_template, requires_approval, fan_out)
```

Três decisões que valem entender:

- **`INSERT OR IGNORE`** — nunca desfaz edição. Quem já usava o Pulse e mudou um
  prompt não perde nada no upgrade. Em contrapartida, mudar um `.md` de fábrica
  **não** atualiza um banco existente: para ver a mudança, apague a linha (ela
  volta na próxima abertura) ou rode com `PULSE_DB` apontando para um banco novo.
- **`is_seeded()` conta só os ids de fábrica** — `connect()` roda a cada
  operação, e reler 8 mil linhas de playbook toda vez sairia caro. Linha criada
  pelo usuário não entra na conta; linha de fábrica apagada derruba o teste e
  volta.
- **Import tardio** — `db.py` importa `factory` dentro da função. Quem só abre o
  banco para ler uma run não paga o custo do pacote de semente.

---

## 3. Como o prompt de um step é montado

Este é o ponto onde as camadas se encontram. Em
[`_attempt_step`](../pulse/orchestrator/engine.py):

```
                 agent_defs.instructions        (o papel: playbook do agente)
                              +
                 "\n\n---\n\n"
                              +
     render(workflow_steps.prompt_template, contexto)   (a fase: o que fazer agora)
                              +
                 earlier_attempt_block(arquivos)  (só numa nova tentativa)
                              +
                 earlier_answers_block(respostas) (só numa nova tentativa)
                              +
                 guidance_block(orientação)     (só numa nova tentativa)
                              ║
                              ▼
                   session/prompt  →  runtime
```

As instruções vão **inline no prompt**, não viram arquivo no disco do usuário. É
o mesmo texto para qualquer runtime, e nenhum runtime precisa saber que o Pulse
existe.

### 3.1 O contexto do template

[`render()`](../pulse/orchestrator/render.py) troca `{{chave}}` e resolve
`{{#if chave}}…{{/if}}`. Chave desconhecida é `TemplateError`, não buraco
silencioso.

| Chave | Origem |
| --- | --- |
| `user_prompt` | `runs.user_prompt` |
| `workspace` | diretório resolvido da run |
| `workflow_id` / `run_id` / `step_id` / `step_label` | identidade do passo |
| `previous_summary` | `summary` do último step anterior que produziu resumo |
| `previous_status` | como **aquele** step fechou: `done` ou `skipped` |
| `artifacts` | `run_artifacts` da run, um caminho por linha |
| `item_id` / `item_label` / `item_index` / `item_total` | o item, num step de fan-out |

As `item_*` vêm **vazias** fora de um fan-out (não ausentes): o mesmo template
roda nos dois modos.

`previous_status` anda junto com `previous_summary` — é o desfecho do step de
onde aquele texto veio, não um canal novo. Existe porque pular é escolha do
usuário, e sem ela o step seguinte recebe o mesmo resumo tendo o anterior fechado
ou tendo sido dispensado: o pulo valeria só para quem o deu.

Note o que não existe: nenhuma chave com nome de artefato ou de fase. O motor não
tem nenhum para oferecer — ele não sabe o que é um PRD.

---

## 4. O loop do motor — passo a passo

Uma função pública: [`run_workflow`](../pulse/orchestrator/engine.py). Nenhum
`if workflow_id == …` no arquivo inteiro.

### 4.1 Pré-voo (antes de gastar qualquer sessão)

A primeira metade é do daemon, que monta as portas
([`run_engine`](../pulse/daemon/runs.py)); a segunda, do motor:

```
run_engine(workflow_id, user_prompt, workspace, stream, prompt_handler, control)
  │
  ├─ 1. get_workflow(id)                     None → UnknownWorkflow (API: 404)
  ├─ 2. resolve_config(workflow=id)          runtime, model, policy, workspace
  ├─ 3. check_runtime_ready(runtime.id)      só `fail` bloqueia; `warn` passa
  ├─ 4. AcpSessionRunner(...) + adapters     EnginePorts(session, stream, runs, workspace, agents)
  └─ run_workflow(definition, ports, …)
       ├─ 5. definição sem steps             → EmptyWorkflow
       ├─ 6. _resolve_run(...)               cria ou retoma a run (ports.runs)
       ├─ 7. prepare_workspace(...)          raiz ou worktree (ports.workspace)
       └─ 8. session.bind_run(run.id)
```

Toda recusa do pré-voo é exceção para quem chamou: o motor não sabe se há um
terminal ou uma tela do outro lado, e quem mostra a recusa é o adapter.

O passo 6 tem dois modos:

| Chamada | Efeito |
| --- | --- |
| sem `resume_run_id` | `runs.create`: linha em `runs` + N em `run_steps`, todas `pending` |
| `resume_run_id` | `runs.load`: volta a run existente; steps `done`/`skipped` são pulados |

Não há "refazer do zero". Rodar o pipeline inteiro de novo é começar uma run
nova — que é o que o usuário quer dizer quando pede isso, e deixa a tentativa
anterior intacta no histórico em vez de sobrescrevê-la.

`run_steps` copia `label` e `position` da definição **no início da run**. Editar
o workflow depois não reescreve o que já aconteceu.

A `position` é multiplicada por `POSITION_STRIDE` (1000): o step 4 vira 4000, e
o fan-out cabe no meio (4001, 4002…) sem renumerar o resto.

### 4.2 O laço

```
session.open(cwd)       ← sobe o subprocesso ACP + a ponte MCP AskQuestion
                          no worktree da run, faz o handshake e o login
_sync_steps()           ← manda a lista de fases para o painel

para cada definition_step em definition.steps:
  │
  ├─ units = expand(run, step, …)     ← 1 unidade, ou N se fan_out
  ├─ _sync_steps()                    ← o painel vê o fan-out expandir
  │
  └─ para cada (step, item) em units:
       │
       ├─ record = run.step(step_id)  ← step novo na definição entra como pending
       ├─ record.status ∈ SETTLED?    ← done/skipped: pula (é isso que faz retomada)
       ├─ control.checkpoint()        ◄── PONTO DE CORTE do parar, nada em voo
       ├─ _run_step(...)              ← tentativa + retry (§5); cada tentativa
       │                                 abre com run.start_step(step_id), que
       │                                 recusa um segundo step em execução
       ├─ _sync_steps()
       └─ exit_code ≠ 0 → grava status e sai

run.retire_steps_outside(ids da definição)  ← step que saiu da definição vira skipped
run.complete(); runs.save(run)
finally: session.close()
```

O `AcpSessionRunner` é **um só para a run inteira**. O subprocesso sobe no
runtime do pré-voo e, quando o agente do step resolve outro runtime, o runner
troca o processo (fecha, sobe o comando novo, refaz o handshake) antes da
sessão daquele step. O que muda sempre por step é a *sessão* dentro do processo.

### 4.3 O que muda por step

Antes de cada tentativa, o motor pede o perfil do agente à porta
`AgentProfiles` (adapter [`ConfiguredAgentProfiles`](../pulse/config/agent_profiles.py)):

```
agents.profile(step.agent_id)          ← resolve_config(pulse_agent=…) + agent_defs
  │
  ├─ session.use_agent(profile)        ← política deste step (texto desconhecido → ask)
  ├─ profile.model                     ← model do agente, ou o da run; aplicado na sessão nova
  └─ profile.instructions              ← prefixo do prompt
```

O perfil também leva o `runtime` e o `acp_command` resolvidos. `use_agent`
aplica a política na hora e, se o comando for outro, troca o processo antes do
`session/new` daquele step. Modelo, política e instruções continuam por step.

---

## 5. Dentro de um step

### 5.1 Dois caminhos

```
step.requires_approval ?
   │
   ├─ SIM → session.run_isolated_phase(...)    conversa com questionário
   └─ NÃO → session.run_isolated_prompt(...)   um turno, e acabou
```

Ambos, em [`session_runner.py`](../pulse/acp/session_runner.py), fazem a mesma
abertura e o mesmo fechamento:

```
session/new    (cwd, mcpServers=[ponte AskQuestion], _meta.pulse)
   ↓
apply_model()  dialeto do runtime: session/set_model (Cursor)
                                   session/set_config_option (Claude)
   ↓
apply_mode()   primeiro modo preferido que o agente realmente suporta
   ↓
session/prompt  ────────►  … turno …  ────────►  stopReason
   ↓
session/close   (no finally — a sessão morre com o step)
```

**Sessão isolada por step** é de propósito: o agente do step seguinte não herda
contexto, só o `previous_summary` que o Pulse repassa. É o que mantém o contexto
pequeno num pipeline longo e permite refazer um step sozinho.

### 5.2 O laço de aprovação (`run_isolated_phase`)

Até `MAX_PHASE_APPROVAL_TURNS` (12) rodadas:

```
1. stream.begin_phase(label) + reset_capture()
2. session/prompt(next_prompt)
3. phase_summary = stream.agent_text()          ← todo o texto do agente
4. parse_text_questionnaire(phase_summary)      ← achou bloco ```text?
     ├─ não achou  → break (sem questionário, o step fecha)
     └─ achou      → prompt_handler pergunta ao usuário (TUI/API)
5. classify_outcome(respostas)
     ├─ approve            → approved=True, break
     ├─ cancel / skip      → retorna imediatamente
     └─ adjust / continue  → guarda as respostas em answerRounds,
                             build_continuation_prompt(...) e volta ao passo 1
```

Se as 12 rodadas acabam sem aprovação, o resultado volta com
`turnsExhausted: true` e o menu de retry explica que o limite foi atingido. A
nova tentativa recebe `answerRounds` de todas as tentativas anteriores no
`earlier_answers_block`.

O agente pede aprovação num bloco cercado em português — é o bloco
[`shared/approval.md`](../pulse/store/factory/shared/approval.md), expandido em
todo `PHASE.md` que precisa dele:

````text
```text
Preciso de algumas informações antes de continuar.
1. Aprovar Tasks e avançar?
A) Sim, aprovar e continuar
B) Não, preciso de ajustes (descreva)
C) Cancelar workflow
```
````

Há uma variante com quatro opções,
[`shared/approval-skip.md`](../pulse/store/factory/shared/approval-skip.md), que
acrescenta `C) Pular` antes do cancelar. Hoje só o `review` a usa: a fase existe
para a pessoa decidir o que vira correção, e "nada" é uma das respostas. As
fases de spec continuam com três — pular o PRD é outra conversa.

[`classify_outcome`](../pulse/replies/approval.py) lê só as linhas que começam
com `→` (as escolhas do usuário). Texto livre é tratado como orientação, não como
escolha: "revise o fluxo de aprovação" não aprova o step só porque contém
"aprov". O rótulo do pulo precisa conter "Pular" ou "skip" — é por substring que
`SKIP_WORDS` casa, e um rótulo redigido de outro jeito renderizaria um menu que
promete algo que o motor não faz.

Ele nunca abre um arquivo que o agente escreveu, nunca valida formato, nunca
espera nome conhecido: o que o motor interpreta são os três blocos cercados que
ele mesmo especificou — este, o `pulse:items` do fan-out (§6) e o
`pulse:outcome` do desfecho (§5.3).

### 5.3 O laço do step sem aprovação (`run_isolated_prompt`)

Um step sem aprovação não tem pessoa atestando a entrega, então quem atesta é o
agente, no bloco de desfecho
([`outcome.py`](../pulse/domain/outcome.py)):

````text
```pulse:outcome
status: done
```
````

Antes desse bloco, "o step terminou bem" queria dizer só "o agente encerrou o
turno": quem respondia *"não consigo, falta a credencial"* fechava com
`end_turn` como qualquer outro, virava `done`, e o step seguinte rodava em cima
do nada — em cascata.

O laço tem até `MAX_PROMPT_TURNS` (2) rodadas:

```
1. stream.begin_phase(label) + reset_capture()
2. session/prompt(next_prompt)
3. phaseSummary = soma dos turnos            ← o bloco que vale é o do último
4. parse_outcome(phaseSummary)
     ├─ done                    → step fecha
     ├─ bloco ausente           → pede o desfecho e volta ao passo 1
     ├─ blocked sem needs: user → build_unblock_prompt() e volta ao passo 1
     └─ blocked com needs: user → escala direto, sem gastar o turno
```

A continuação roda **na mesma sessão ACP**, e é uma só por tentativa. Na mesma
sessão porque uma sessão nova perderia tudo que o agente já descobriu e o faria
recomeçar do zero — que é justamente o que não se quer de uma segunda chance.
Uma só porque quem repete o bloqueio depois de ser cutucado está dizendo que
precisa de gente.

Antes de tudo isso vem o degrau zero: falta um dado que só a pessoa tem? O
agente **pergunta** (`cursor/ask_question`, §4), o que não encerra o step.
Bloqueio é o último recurso, não o jeito de pedir informação.

### 5.4 Desfechos e retry

| Desfecho | `run_steps.status` | Efeito |
| --- | --- | --- |
| `approve` | `done` | segue |
| `skip` | `skipped` | segue — não é falha |
| `adjust` / `continue` | — | volta ao agente com as respostas |
| `cancel` / não aprovado / `stopReason` ruim | — | cai no menu de retry |
| `status: blocked` (ou sem bloco) | `blocked` | cai no menu de bloqueio |

O menu de falha ([`_offer_retry`](../pulse/orchestrator/menus.py)):

```
Refazer                      → nova tentativa, mesmo prompt + arquivos já gravados + respostas já dadas
Outro — dizer o que fazer    → ask_text() → guidance_block() no prompt seguinte
Parar                        → status FAILED, run encerra com exit 1
```

O menu de bloqueio ([`_offer_blocked`](../pulse/orchestrator/menus.py)) tem uma
opção a mais, porque bloqueio costuma ser legítimo e às vezes a resposta certa é
seguir sem aquele step:

```
Refazer — já resolvi         → nova tentativa
Outro — dizer o que fazer    → orientação do usuário no prompt seguinte
Pular este step              → status SKIPPED, e sem passar resumo adiante
Parar a run                  → status BLOCKED, run encerra com RUN_BLOCKED (131)
```

Sem `prompt_handler` capaz de perguntar (CLI, testes, daemon), o padrão é
`stop` nos dois. É a inversão que faltava: antes, o que ninguém via seguia
adiante sozinho.

`blocked` não é `failed`. Falha é quebra técnica — a sessão caiu, o prazo
estourou; bloqueio é o agente rodando bem e dizendo que não tinha como entregar.
O que se faz com cada um é diferente: falha se refaz, bloqueio se destrava.

### 5.5 Parar e retomar

Não dá para congelar um turno do agente no meio: ou ele termina, ou é descartado.
Por isso existe um comando só — não há pausa. O contrato
([`domain/control.py`](../pulse/domain/control.py)):

```
stop()   →  control.interrupted = True
             │
             ├─ dentro de _request("session/prompt"): manda session/cancel
             │   e espera CANCEL_GRACE_SECONDS (10s) o agente fechar o turno
             │
             └─ _run_step vê interrupted → _release_step()
                  step volta para `pending`  ← nem done nem failed: não terminou
                  encerra a run com exit RUN_STOPPED (130)
                  não é falha: o cockpit oferece retomar

retomar  →  run nova sobre o mesmo registro (`resume_run_id`)
             recomeça no primeiro step que não fechou
```

Step já `done` nunca é refeito — é o `if record.status in SETTLED: continue` do
laço.

Há **dois pontos de corte**: `checkpoint()` entre steps (nada em voo, corte
limpo) e o cancelamento dentro do `session/prompt` (corte no meio do turno).

---

## 6. Fan-out: um step que vira N

`workflow_steps.fan_out = 1` significa "rode este step uma vez por item que o
step anterior enumerou". Quantos são só se sabe **depois** que o step anterior
rodou — por isso a expansão acontece dentro do laço
([`expand`](../pulse/orchestrator/fanout.py)), não ao criar a run.

Quem enumera é o agente, num bloco cercado
([`fanout.py`](../pulse/orchestrator/fanout.py)):

````text
```pulse:items
T1 — Criar o endpoint de exportação
T2 — Montar o CSV a partir do relatório
```
````

```
step `implement` (fan_out, placeholder em run_steps)
  │
  ├─ parse_items(run.previous_delivery(step_id).summary)   ← o ÚLTIMO bloco do texto
  ├─ vazio? → roda uma vez, como se fan_out não existisse
  │
  └─ N itens:
       run.expand_step(placeholder, filhos)          ← o placeholder some no save(run)
       para cada item, no mesmo ponto da lista:
         step_id  = "implement:T1"
         position = base + 1, base + 2, …            ← cabe no stride de 1000
         StepRecord próprio                          ← sessão, retry e retomada próprios
```

Regras de robustez: id repetido é descartado (viraria `step_id` duplicado, e
`run_steps` tem chave `(run_id, step_id)`); teto de `MAX_ITEMS` = 40; bloco
ausente não derruba a run.

O motor continua sem ler artefato — ele não abre `tasks.md` nem conhece `### T1`.
Trocar `tasks.md` por outra coisa não muda uma linha do orquestrador.

---

## 7. O que o Pulse observa enquanto o agente trabalha

A thread leitora do `AcpSessionRunner` consome o stdout do subprocesso e
despacha cada mensagem JSON-RPC:

```
stdout do runtime (uma linha = um JSON-RPC)
  │
  ├─ tem method + id  → pedido DO AGENTE:
  │     cursor/ask_question            → prompt_handler pergunta ao usuário
  │     cursor/create_plan             → idem
  │     session/request_permission     → aplica a permission_policy do step
  │
  ├─ method = session/update           → notificação:
  │     stream.handle_update(params)   → cockpit / SSE
  │     session_log.update(params)     → run_events + run_artifacts
  │
  └─ só id                            → resposta a um request nosso (fila)
```

**Como artefato é descoberto:** um `tool_call` com `kind` ∈ {`edit`, `write`,
`create`} faz o log da sessão ([`RecordedSessionLog`](../pulse/history/session_log.py),
injetado pelo daemon) extrair o caminho de `locations[].path` ou do `rawInput`
(chaves `path`, `file_path`, `target_file`, `filePath`, `abs_path` — cada runtime
reporta de um jeito) e gravar em `run_artifacts`, uma linha por caminho e step.
Não há convenção de pasta nem de nome, e toda escrita é gravada; o painel de
artefatos é que mostra só os `.md` dentro do worktree.

**Contexto ocupado:** um `session/update` com `sessionUpdate: "usage_update"`
(`used`) vira o indicador `42k tokens` ao lado do tempo do step na barra lateral
e a soma no cabeçalho da run, ao vivo. O adaptador do Claude emite esse evento; runtime que
não emite simplesmente não mostra o indicador. A última leitura de cada step fica
em `run_steps.context_tokens`, e o histórico mostra os mesmos números.

**Por que o Pulse mantém log próprio (`run_events`):** ler o store do runtime não
serve — só o Cursor tem um, e o Pulse é agnóstico ao agente. Gravar eventos é
acessório e está sempre dentro de `try/except`: falha de log nunca derruba o
step.

---

## 8. A resolução de runtime/model/política

Duas cascatas, e é fácil confundi-las
([`config/resolved.py`](../pulse/config/resolved.py)):

**Por workflow** — o backend padrão da run (usado no pré-voo, define o
`acp_command`):

```
projeto.workflows[id] → global.workflows[id]
  → projeto.default_agent → global.default_agent → default do código (cursor)
```

**Por agente de step** — quem roda *este* step (`_resolve_pulse_agent`):

```
agent_defs[step.agent_id].{runtime,model,permission_policy}   vazio = "use o padrão"
  → agent_settings[project_id, agent_id]                      ajuste da TUI
  → cascata de defaults acima
  → _available_runtime_fallback()                             o declarado não está instalado
```

O **fallback de disponibilidade** existe porque runtime é preferência, não
requisito: quem só tem o Claude instalado não deve travar porque a preferência
diz `cursor`. O modelo é preservado — se o id não existir no runtime novo, o
próprio agente cai no default dele.

### 8.1 As diferenças entre os runtimes

`AgentRuntime` ([`runtimes/base.py`](../pulse/runtimes/base.py)) tem defaults de
ACP puro; cada backend sobrescreve só o que diverge.

| | Cursor | Claude Code |
| --- | --- | --- |
| Comando | `agent acp` (ACP nativo) | `npx -y @agentclientprotocol/claude-agent-acp@0.86.0` |
| Auth | `authenticate` com `cursor_login` | `authMethods` vazio — já autenticado pelo CLI |
| Modelo | `session/set_model` | `session/set_config_option` |
| Modos | `agent` para as duas fases | `default`/`acceptEdits` — **nunca** `plan` |
| Check de auth | `agent status` / `agent whoami` | `claude auth status` (JSON) |

O comentário sobre o modo `plan` no Claude vale ler
([`runtimes/claude.py`](../pulse/runtimes/claude.py)): em `plan` o Claude não
escreve o arquivo pedido — grava um plano em `~/.claude/plans` e espera
aprovação, e o artefato nunca aparece na sessão. Quem limita escrita é a
`permission_policy` do step.

Adicionar um agente novo = um módulo com a subclasse + uma entrada em `RUNTIMES`.
Config, doctor, onboarding e session runner passam a enxergá-lo sem mudanças.

---

## 9. O trajeto completo, ponta a ponta

```
 1. usuário: `pulse`
 2. cli/main.py garante o Engine de pé → abre a TUI (HomeScreen)
 3. Home lista os workflows de `workflow_defs`; usuário escolhe e descreve a tarefa
 4. Cockpit monta a sidebar de `workflow_steps` (mesmo caminho do motor)
 5. cliente → POST /api/workflows/{id}/runs
 6. daemon/runs.py abre uma thread com RunControl próprio → run_engine
 7. pré-voo: definição, config, doctor do runtime, portas; o motor cria a run
 8. session.open(cwd): sobe o subprocesso ACP + a ponte MCP AskQuestion
 9. por step: resolve o agente, monta instructions + prompt, abre sessão nova
10. agente trabalha → session/update → SSE → cockpit
      write/edit → run_artifacts     tudo → run_events
11. agente pergunta → prompt.request → dock na TUI → POST /prompts/{id}/answer
12. fim do turno → questionário → approve → step vira `done` → session/close
13. próximo step (ou N steps, se fan-out) → … → run.finished
14. o que permanece: os arquivos que o AGENTE escreveu. O Pulse não gera nenhum.
```

Reabrir pelo histórico usa as mesmas tabelas: `run_steps` dá a sidebar,
`run_events` dá o stream, `run_artifacts` dá o painel.

---

## 10. Onde tocar para mudar o quê

| Quero… | Mexo em… |
| --- | --- |
| Fazer um trecho se repetir | `repeat_from`/`repeat_max` no step que fecha o trecho + `next: repeat` no `PHASE.md` dele |
| Mudar o playbook de um agente | `factory/agents/<id>/AGENT.md` — e apagar a linha de `agent_defs` para re-semear |
| Mudar o prompt de uma fase | `factory/agents/<id>/PHASE.md` — idem, `workflow_steps` |
| Mudar um bloco repetido (aprovação, isolamento) | `factory/shared/<nome>.md` |
| Criar um agente novo de fábrica | pasta em `factory/agents/` + entrada em `AGENT_LABELS` |
| Criar/alterar um pipeline | `WORKFLOWS` (fábrica) ou `save_workflow()` em runtime |
| Adicionar um backend (Gemini, Codex…) | módulo em `pulse/runtimes/` + entrada em `RUNTIMES` |
| Mudar como o motor sequencia | `orchestrator/engine.py` |
| Mudar o protocolo de aprovação | `replies/approval.py` + `factory/shared/approval.md` |
| Mudar o protocolo de fan-out | `orchestrator/fanout.py` + o `PHASE.md` que emite o bloco |
| Adicionar uma chave de template | `_context()` em `engine.py` |

### Invariantes que valem checar depois de mexer

```bash
# arquivo não-Python só na semente de fábrica
find pulse -type f ! -name "*.py" -not -path "*__pycache__*" -not -path "pulse/store/factory/*"

# nenhum vocabulário de domínio fora da semente
grep -rniE "\bprd\b|techspec|new-issue|quick-fix|setup-project|analyze-codebase" \
  --include="*.py" pulse/ | grep -v "^pulse/store/factory/"
```

Ambos devem sair vazios. É o que garante que o motor continua sem saber o que os
agentes fazem.

---

## Referências

- Visão geral das camadas: [`ARCHITECTURE.md`](../ARCHITECTURE.md)
- Modelo de dado do pipeline: [`workflows.md`](workflows.md)
- Tabelas e caminhos em disco: [`armazenamento.md`](armazenamento.md)
- Perguntas e aprovação: [`questions.md`](questions.md)
- Logs ACP: [`logs.md`](logs.md)
- Contrato HTTP: [`../contracts/openapi.yaml`](../contracts/openapi.yaml)
