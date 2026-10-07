# Como o Pulse carrega e interpreta workflows

O Pulse **não conhece nenhum workflow por código**. Não há catálogo em Python
nem `if workflow_id == …` em lugar nenhum. Um workflow é um conjunto de linhas
no SQLite, e a única responsabilidade do Pulse é apontar **qual agente roda
agora** e **quando**.

O pacote traz a **semente** desses loops — ver §1.1 — mas nada dela é lido
durante uma run.

## 1. Onde um workflow é definido

Tabelas em `~/.pulse/pulse.db` (ver [armazenamento.md](armazenamento.md)):

```
workflow_defs     id, label, description, is_default, default_prompt
workflow_steps    workflow_id, step_id, position, label,
                  agent_id, prompt_template, requires_approval, fan_out
agent_defs        id, label, runtime, model, permission_policy, instructions
```

Acesso: [`pulse/store/workflow_defs.py`](../pulse/store/workflow_defs.py).

Id que não está em `workflow_defs` não existe: `run_workflow` levanta
`UnknownWorkflow`, e a API responde 404.

`default_prompt` é a tarefa que o loop já sabe qual é — "Analisar codebase" e
"Setup do projeto" olham o repositório, não um pedido. Preenchido, o menu entra
direto na run; vazio, ele abre o campo para o usuário descrever a tarefa.

## 1.1 A semente de fábrica

[`pulse/store/factory/`](../pulse/store/factory/) roda uma vez, na primeira
abertura do banco, com `INSERT OR IGNORE` — quem já editou não perde nada no
upgrade, e linha de fábrica apagada volta na abertura seguinte.

| Loop | Steps |
| --- | --- |
| `new-issue` — Nova spec | prd → techspec → tasks → implement (uma vez por task) → review ⇄ review-fix (laço, até 3 rodadas) |
| `quick-fix` — Correção rápida | quick-plan → quick-implement |
| `review` — Review | review ⇄ review-fix (laço, até 3 rodadas) sobre a branch atual vs `main` + não commitado; fase `STANDALONE.md`, rodadas em `.pulse/reviews/NNN-slug/` |
| `setup-project` — Setup do projeto | setup-interview → setup-artifacts |
| `analyze-codebase` — Analisar codebase | codebase-explore → codebase-docs |
| `default` — Executar | um step, sem pipeline (fora do menu) |

`setup-project` e `analyze-codebase` rodam **do começo ao fim**: nenhum step
deles aprova, e `default_prompt` já traz a tarefa. Os dois olham o repositório,
não um pedido — não há o que perguntar nem o que revisar no meio. Os outros
pipelines existem para serem revisados e continuam parando em cada aprovação.

`is_default` marca o loop genérico, e a home usa a marca para **não** listá-lo
em "Nova sessão": aquele menu é de pipeline. Ele segue no banco e na API.

Os playbooks são `.md` em `factory/agents/<id>/AGENT.md` (vira
`agent_defs.instructions`) e `PHASE.md` (vira `workflow_steps.prompt_template`).
Os blocos repetidos — isolamento, clarify, aprovação, idioma de saída — ficam em
`factory/shared/` e são expandidos **na semeadura**, via
`<!-- include: nome -->`, para a linha do banco ser autossuficiente.

Ficam em arquivo, e não em string Python, porque são ~8 mil linhas que alguém
precisa revisar em diff. Isso **não** reintroduz catálogo em código: o motor lê
as tabelas, nunca o pacote, e `test_domain_markdown_lives_only_in_the_factory_seed`
falha se qualquer módulo fora de `store/db.py` passar a importar a fábrica.

`runtime` e `model` nascem **vazios** de propósito, mesmo onde o playbook declara
uma preferência: vazio significa "use o padrão da máquina", e um valor concreto
congelaria a escolha feita no `pulse init`. Quem quiser fixar o par por agente
usa a tela de configurações, que grava em `agent_settings`.

Não há ramificação nem condição sobre id de workflow: `workflow_steps` é uma
lista, e o motor a percorre. Quem escolhe entre spec completa e correção rápida é
o usuário, no menu **Nova sessão** — e o `quick-plan` refaz a checagem de escopo,
então um pedido grande que entrou pelo loop errado para no primeiro step em vez
de seguir.

O único desvio do caminho reto é o **laço**, e ele também é dado: um step com
`repeat_from` preenchido pode mandar a run voltar a um step anterior e repetir o
trecho. Quem pede a volta é o agente, no campo `next` do bloco de desfecho; quem
permite é a coluna, e `repeat_max` é o teto. Ver §2.3.

## 2. O laço do motor

[`pulse/orchestrator/engine.py`](../pulse/orchestrator/engine.py) — uma função
pública, `run_workflow`, e nenhum `if workflow_id == ...`:

```
run_workflow(workflow_id, user_prompt, …)
  │
  ├─ get_workflow(id)                 definição + steps, do banco
  ├─ resolve_config(workflow=id)      runtime, model, policy, cwd
  ├─ create_run | load_run            linha em `runs` + N em `run_steps`
  └─ para cada step pendente:
       control.checkpoint()           ponto de corte do parar
       resolve_config(pulse_agent=…)  o agente DESTE step
       runner.use_agent(…)
       render(step.prompt_template)   valores da run
       run_isolated_phase | run_isolated_prompt
       record.deliver()/block()…      desfecho no agregado → save(run)
```

A sessão ACP é **isolada por step**. O agente do step seguinte não herda o
contexto do anterior — só o resumo que o Pulse repassa. É isso que permite
retomar uma run refazendo um step só e manter o contexto pequeno.

Detalhe do agente e do laço, passo a passo: [`agentes.md`](agentes.md).

### 2.1 Fan-out: um step que vira N

`workflow_steps.fan_out = 1` significa **"rode este step uma vez por item que o
step anterior enumerou"**. É o que faz cada task ter agente isolado e linha
própria no painel, sem o motor saber o que é uma task.

Quem enumera é o agente, num bloco cercado que o Pulse acha
([`pulse/orchestrator/fanout.py`](../pulse/orchestrator/fanout.py)) — é o segundo
dos três protocolos que o motor lê da resposta, ao lado do questionário de
aprovação e do bloco de desfecho (§2.2):

````text
```pulse:items
T1 — Criar o endpoint de exportação
T2 — Montar o CSV a partir do relatório
```
````

O que o motor faz com isso:

```
step `implement` (fan_out)          →   run_steps
  lê o resumo do step anterior            implement:T1   Criar o endpoint…
  parse_items(...)                        implement:T2   Montar o CSV…
  o placeholder some                      (cada um: sessão ACP própria,
                                           retry próprio, retomada própria)
```

- **Sem bloco, ou bloco vazio** → o step roda uma vez, como se `fan_out` não
  existisse. Protocolo que o agente não seguiu não derruba a run.
- **Id repetido** é descartado: viraria `step_id` duplicado, e `run_steps` tem
  chave `(run_id, step_id)` — o segundo sobrescreveria o primeiro em silêncio.
- **Teto de 40 itens**: abrir 200 sessões ACP sairia caro antes de alguém notar.
- A posição usa passo de 1000 (`POSITION_STRIDE`), então o step 4 vira
  4001, 4002… e continua antes do step 5. Sem isso `T10` cairia entre `T1` e
  `T2`, que é como o `step_id` ordena.
- Os N vão para `run_steps` **na expansão**, não quando cada um começa. Filho
  que só existisse na memória sumiria se a run caísse no meio do fan-out, e o
  histórico reabriria com as tasks que já rodaram e mais nenhuma.
- Ao retomar, o bloco relido é o do step **anterior** ao fan-out — o pai já não
  existe na run, e a busca pelo resumo para no primeiro filho.

O motor continua sem ler artefato: ele não abre `tasks.md` nem conhece `### T1`.
Trocar `tasks.md` por outra coisa não muda uma linha do orquestrador.

### 2.2 Desfecho: como um step fecha como concluído

Antes, "o step terminou bem" queria dizer apenas **"o agente encerrou o turno"**.
Um agente que respondia *"não consigo, falta a credencial"* encerrava o turno
como qualquer outro (`end_turn`), o step ia para o banco como `done` e o step
seguinte rodava em cima de uma entrega que não existiu — em cascata, até o fim
do workflow.

Um step tem **um portão só**:

| Step | Quem atesta a entrega |
| --- | --- |
| `requires_approval = 1` | a pessoa, no questionário de aprovação |
| `requires_approval = 0` e `requires_outcome = 1` | o agente, no bloco `pulse:outcome` |
| `requires_outcome = 0` | ninguém — encerrar o turno basta (comportamento antigo) |

O motor anexa a instrução do protocolo ao prompt sozinho
([`pulse/orchestrator/prompts.py`](../pulse/orchestrator/prompts.py)): nenhum
`prompt_template` precisa ser editado. O agente encerra com:

````text
```pulse:outcome
status: done
```
````

ou, quando não entregou:

````text
```pulse:outcome
status: blocked
reason: falta a credencial do banco (DATABASE_URL não está no ambiente)
needs: user
```
````

`needs: user` só quando depender de outra pessoa, de um acesso ou de uma
permissão. Ele é o que decide se o motor gasta ou não a tentativa de
auto-resolução.

**Os três degraus**, nesta ordem
([`pulse/orchestrator/outcome.py`](../pulse/orchestrator/outcome.py)):

1. **O agente pergunta.** Falta um dado que só a pessoa tem? O canal de pergunta
   (`cursor/ask_question`) entrega na tela **sem encerrar o step**. Bloqueio não
   é o jeito de pedir informação.
2. **O agente tenta resolver sozinho, uma vez.** Bloqueio sem `needs: user` — e
   bloco esquecido — voltam para ele numa continuação **na mesma sessão ACP**,
   para ele não recomeçar do zero. Uma só: quem repete o bloqueio depois de ser
   cutucado está dizendo que precisa de gente.
3. **Só então escala.** O step vai para `blocked`, a run para (`RUN_BLOCKED`) e
   o menu oferece *Refazer · Outro · Pular este step · Parar*. Sem ninguém para
   perguntar (CLI, cockpit fechado, daemon), a run **para** — o default seguro é
   nunca seguir adiante.

`blocked` é estado próprio, e não `failed`: nada quebrou, a entrega é que não
aconteceu. Fica fora de `SETTLED`, então retomar refaz o step que travou e só
ele. Pular é registrado como `skipped`, nunca como `done`, e o step pulado não
passa resumo nenhum ao seguinte — `previous_summary` só enxerga step que fechou.

### 2.3 Laço: um trecho que se repete até ninguém pedir mais

Duas colunas em `workflow_steps`, e nenhuma delas conhece fase por nome:

| Coluna | O que faz |
| --- | --- |
| `repeat_from` | `step_id` de um step **anterior** deste loop. Vazio = não repete. |
| `repeat_max` | teto de voltas de quem **abre** a faixa, contando a primeira. Na última, só ele roda. |

Quem **pede** a volta é o agente, no mesmo bloco de desfecho da §2.2:

````text
```pulse:outcome
status: done
next: repeat
```
````

Quem **permite** é a coluna. Os dois são necessários: um agente não cria laço
onde a definição não abriu um, e uma definição não repete um step que entregou e
ficou quieto. É o que o `new-issue` usa na camada de merge — `review-fix` aponta
para `review` com teto 3, e todo fix que trabalhou uma rodada leva a run de volta
ao revisor. Quem encerra o laço é o review, nunca o fix.

**Encerrar é de quem abre a faixa.** Sem nada a corrigir — review limpo, todo ID
já terminal numa volta seguinte, ou a última volta —, o review não pede
aprovação: declara o fim no mesmo bloco.

````text
```pulse:outcome
status: done
next: close
```
````

O motor fecha o step `done` e não roda o resto da faixa: o que nunca rodou nesta
run vira `skipped`, o que já rodou numa volta anterior continua `done`. Num step
com aprovação, `next: close` só dispensa o portão em quem abre um laço — em
qualquer outro step, resposta sem aprovação continua sendo falha.

```
step `review-fix` fechou com `next: repeat`
  │
  ├─ está dentro de uma faixa repetível?        não → segue a lista
  ├─ quem abre a faixa já rodou `repeat_max`?   sim → avisa e segue a lista
  ├─ a próxima volta é a última?                sim → reabre SÓ quem abre a faixa
  └─ devolve os steps da faixa para `pending`
       incrementa `run_steps.rounds` de quem ABRE a faixa
       guarda o tempo da volta em `run_steps.carried_seconds`
       volta o índice para o step de `repeat_from`
```

**A última palavra é de quem abre a faixa.** Quem fecha o laço pede a volta
porque mexeu em algo que ninguém conferiu; se ele rodasse também na última
volta, a run acabaria num reparo sem conferência. Com teto 3, o `new-issue` roda
review → fix → review → fix → review. O teto conta pelo `rounds` gravado no
banco, então retomar a run no meio do laço não devolve voltas que já foram
gastas.

**O tempo soma entre as voltas.** Reabrir zera `started_at`/`ended_at`, então a
duração líquida da volta anterior vai antes para `carried_seconds`, e a espera
(`waiting_seconds`) zera junto — já foi descontada ali. O painel e o histórico
mostram a soma, e o cronômetro de uma volta nova parte de onde a anterior parou.

**A volta reusa os mesmos `step_id`** — não há `review#2`. É o oposto do
fan-out, e de propósito: o fan-out numera porque cada item é um trabalho
diferente, enquanto as voltas de um laço são o mesmo trabalho repetido. Reusar o
id é o que mantém **uma linha por step** no painel, com o contador do lado, e o
que deixa o log e os artefatos de todas as voltas sob o mesmo step —
`visible_artifacts()` filtra por `phase_id`, então é assim que `Review` mostra
`round-001.md` e `round-002.md` lado a lado, navegáveis.

O preço é explícito: `run_steps` guarda o estado da **última** volta, não de cada
uma — o tempo é a exceção, e soma. O que de fato distingue uma rodada da outra está no arquivo que ela escreveu
e nos eventos da run, que são append-only.

O contador (`run_steps.rounds`) vai no step que **abre** a faixa, não no que a
fecha: é ele que tem um artefato por volta para a pessoa abrir, e no outro o
número seria ruído. Quem está fora da faixa fica em `rounds = 1`.

`repeat_from` que aponte para a frente, ou para um id que não existe, é ignorado
em silêncio: um laço que não fecha travaria a run, e rodar a lista reta é o
comportamento menos pior. O mesmo vale para uma faixa que contém um step com
`fan_out`: o fan-out troca a linha dele por uma por item, e o laço não teria
quem contasse as voltas (o teto nunca chegaria) nem como reabrir os itens.

O teto não é opcional. Sem ele, um agente que sempre pede mais uma rodada deixa
a run sem fim, e o motor não tem como julgar se a próxima volta vale a pena.

### Valores disponíveis no `prompt_template`

`{{chave}}`, e `{{#if chave}}…{{/if}}` para trecho opcional
([`pulse/prompts/render.py`](../pulse/prompts/render.py)). Chave sem valor é
**erro**, não buraco: instrução truncada sairia silenciosa.

| Chave | Conteúdo |
| --- | --- |
| `user_prompt` | o que o usuário pediu |
| `workspace` | diretório da run |
| `workflow_id` / `run_id` / `step_id` / `step_label` | identidade do passo |
| `previous_summary` | resumo do último step que **fechou** (`done`/`skipped`) |
| `previous_status` | como aquele step fechou: `done` ou `skipped` |
| `artifacts` | arquivos que a run já escreveu, um por linha |
| `item_id` / `item_label` | o item deste step, num step de fan-out |
| `item_index` / `item_total` | "2 de 7", para o prompt situar o agente |

Não há chave com nome de artefato ou de fase: o motor não tem nenhum para
oferecer. As `item_*` vêm **vazias** fora de um fan-out, e não ausentes: o mesmo
`prompt_template` roda nos dois modos, e chave ausente é erro.

## 3. O que o motor interpreta da resposta do agente

Só o desfecho do questionário de aprovação
([`pulse/prompts/approval.py`](../pulse/prompts/approval.py)), quando o step tem
`requires_approval`:

| Desfecho | O que o Pulse faz |
| --- | --- |
| `approve` | step vira `done`, segue para o próximo |
| `adjust` / `continue` | devolve a conversa ao agente com as respostas |
| `skip` | step vira `skipped` — não é falha |
| `cancel` | step não fechou; cai no menu de retry |

Step sem aprovação só precisa que o agente feche o turno (`stopReason`).

Falha ou não-aprovação abre o menu **Refazer / Outro — dizer o que fazer /
Parar**. "Outro" injeta a orientação do usuário no prompt da tentativa seguinte.

Queda de sessão (timeout, processo do agente morto) cai no mesmo menu: é falha
de tentativa, não fim de run. Antes de refazer, o processo ACP é reerguido.
O prazo de `session/prompt` conta **silêncio**, não duração: cada linha vinda do
agente o renova, e pergunta aberta na tela não gasta o relógio.

O conteúdo do que o agente produziu **nunca** é interpretado. O Pulse não lê
Markdown, não valida formato, não espera arquivo com nome conhecido.

## 4. Estado, retomada e artefatos

| Tabela | Para quê |
| --- | --- |
| `runs` | de onde retomar (`current_step`, `status`) |
| `run_steps` | status, resumo e sessão ACP de cada step |
| `run_events` | o stream que o cockpit reexibe |
| `run_artifacts` | caminhos que o agente escreveu |

Retomar = rodar o primeiro step que não está `done`/`skipped`. Não há refazer:
rodar tudo de novo é começar uma run nova, e a anterior fica no histórico.

Parar corta o turno em voo e devolve o step em curso para `pending`: ele não
terminou, então é refeito inteiro ao retomar. Step já fechado nunca é refeito.
Não há pausa — parar e retomar dão no mesmo, sem thread nem sessão ACP presas.

Artefato é descoberto pelos **tool-calls do ACP**: um `write`/`edit`/`create`
faz o Pulse gravar o caminho em `run_artifacts`
([`session_runner._record_artifacts`](../pulse/acp/session_runner.py)). Não há
convenção de pasta nem de extensão.

## 5. Config por workflow e por agente

`machine_workflows` e `project_workflows` guardam **override** de agent/model
por id de workflow — não definem pipeline nenhum, e nascem vazios.

```
agent_defs[step.agent_id]            runtime/model/policy declarados
  → agent_settings (por projeto)     o que o usuário ajustou na TUI
  → projeto.defaults
  → global.defaults
  → defaults do código
```

Campo vazio em `agent_defs` significa "use o padrão da máquina" — gravar um
runtime concreto na semente congelaria a escolha feita no `pulse init`.

## 6. A UI

[`HomeScreen`](../pulse/tui/screens/home.py) tem dois níveis: a raiz (**Nova
sessão** · Histórico · Configurações · Sair) e o submenu de loops, montado com
`list_workflows()`. Os loops ficam um nível abaixo porque a lista cresce com o
banco — na raiz, "Configurações" e "Sair" acabariam abaixo de N workflows. O
`default` ("Executar") fecha a lista: é o escape, não o que se procura ali. `Esc`
volta um passo de cada vez (fecha o campo de tarefa, depois sai do submenu).

No item vai só `label · description`, e a `description` de fábrica é curta de
propósito ("pipeline completo", "até 3 arquivos"). A cadeia de steps — o que é
longo — vai para a dica, montada a partir de `workflow_steps` e trocada conforme
o item destacado. A dica tem sempre duas linhas, mesmo sem descrição: alternar a
altura faria a lista pular a cada tecla.

[`CockpitState.configure_workflow`](../pulse/tui/state.py) monta a sidebar a
partir de `workflow_steps`, pelo mesmo caminho do motor. Não há mapa de fases na
UI. Workflow desconhecido resulta em sidebar vazia, que se preenche conforme os
steps começam.

A lista de fases não é fixa: `_sync_steps` manda a lista inteira a cada mudança,
e `CockpitState.sync_phases` reconcilia **por id**, preservando status, relógio e
contadores de quem já rodou. É o que permite o fan-out trocar uma fase por N no
meio da run sem apagar o que já aconteceu.

## Design

**O quê:** workflow como dado (linhas no banco) e um motor único que só sequencia
steps.

**Por quê:** o Pulse é um orquestrador. Saber o que o agente faz o prendia a um
processo específico — trocar o pipeline exigia mexer em `spec_types`, `runner`,
um flow, o mapa da sidebar e cinco arquivos de prompt.

**Trade-off:** workflow novo agora é `INSERT`, não release. Em compensação não há
tela para editar isso ainda: quem quiser outro pipeline escreve no banco pela
API ou por `pulse.store.workflow_defs`.

**O que a semente custou:** os steps de um loop são uma lista linear, então o
agente `classify` — que antes escolhia entre spec completa e quick e escrevia a
rota em disco — deixou de existir. Quem dimensiona o pedido é o usuário, no menu,
com o `quick-plan` como rede de segurança. E como cada step roda em sessão
isolada, o diretório da feature não é mais estado do motor: o step do PRD o
declara no resumo, e os seguintes o leem de `previous_summary`/`artifacts`.
Ramificação e estado por feature voltam a ser assunto do motor no dia em que um
loop realmente precisar deles.
