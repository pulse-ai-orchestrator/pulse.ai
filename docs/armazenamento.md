# Armazenamento do Pulse

Tudo do Pulse vive em SQLite. O **único** conteúdo em arquivo é o que o agente
escreve no workspace — e desse o Pulse guarda só o caminho.

```
~/.pulse/pulse.db                 config, definições de workflow e estado das runs
<workspace>/…                     arquivos que o agente escreveu (onde ele quiser)
~/.cursor/                        SQLite do Cursor (Pulse só lê, ao vivo)
```

O layout de `~/.pulse` (banco, socket e meta do daemon, log, worktrees) é
definido num lugar só: [`pulse/store/paths.py`](../pulse/store/paths.py).

Resolução de config: `defaults do código` → tabela `machine` → tabelas
`project_*` no mesmo `pulse.db`, identificadas por `project_id` / `root_path`.

## Versão do schema

`PRAGMA user_version` guarda a versão do schema; `MIGRATIONS` em
[`pulse/store/db.py`](../pulse/store/db.py) lista as mudanças em ordem. Ao
abrir o banco, `migrate` aplica só as pendentes, cada uma numa transação junto
com o novo número — uma falha no meio deixa gravada a última versão boa. A
transação é `BEGIN IMMEDIATE` e relê a versão: duas conexões abertas juntas
num banco antigo (o primeiro start do daemon depois de um upgrade) migram uma
vez só, a segunda espera e pula.

- Banco novo nasce na última versão: `SCHEMA` já tem todas as mudanças.
- Versão 0 é todo banco anterior ao versionamento; a migração 1 adiciona as
  colunas que faltarem nele.
- A migração 3 adiciona `run_steps.context_tokens`. A coluna entrou no `SCHEMA`
  depois da versão 2, então um banco que já passou da migração 1 não a recebe
  de novo por ali.
- A migração 4 adiciona `workflow_defs.pull_request_template`, e
  `backfill_pull_request_templates` preenche o modelo da fábrica onde ficou vazio.
- A migração 7 adiciona `workflow_steps.opens_request` e `runs.request_opened`.
  `backfill_opens_request` liga a coluna no step de fábrica que abre o pedido,
  só nessa migração.
- Banco com versão maior que a do código (gravado por um Pulse mais novo) é
  recusado com `SchemaTooNewError`, em vez de ser escrito por um schema que
  este código não conhece.
- Mudança nova: acrescente uma `Migration` ao fim e a mesma mudança em
  `SCHEMA`. `SCHEMA` roda antes das migrações num banco existente, então um
  índice sobre coluna que a migração cria fica na migração, não no `SCHEMA`. Os reconciliadores da fábrica (`backfill_default_prompts`,
  `drop_approval_from_unattended_steps`, …) são de dados, idempotentes, e
  continuam rodando a cada abertura.

## Quem escreve o quê

| Dado | Onde | Formato | Quem escreve | Quem lê |
| --- | --- | --- | --- | --- |
| Config global | `pulse.db` (`machine*`) | SQLite | Pulse (`pulse init`, settings) | Pulse |
| Config do projeto | `pulse.db` (`projects`, `project_*`) | SQLite | Pulse (`pulse init`, `pulse config`) | Pulse |
| Definição de workflow | `pulse.db` (`workflow_defs`, `workflow_steps`) | SQLite | semente do banco / API | motor e TUI |
| Definição de agente | `pulse.db` (`agent_defs`) | SQLite | semente do banco / API | motor e TUI |
| Estado da run | `pulse.db` (`runs`, `run_steps`) | SQLite | Pulse (dono único) | retomada e histórico |
| Log da run | `pulse.db` (`run_events`) | SQLite | Pulse | cockpit e histórico |
| Artefatos | caminho em `run_artifacts`; conteúdo no workspace | — / livre | Pulse grava o caminho; o **agente** grava o arquivo | painel de artefatos |
| Ponteiro de sessão | `pulse.db` (`agent_sessions`) | SQLite | Pulse | diagnóstico |
| Log da sessão ACP | `~/.cursor/**/store.db` | SQLite | Cursor | Pulse (só leitura) |

## 1. Config da máquina — `~/.pulse/pulse.db`

Tabelas `machine`, `machine_agents`, `machine_workflows`.

Conteúdo: versão, binário ACP, auth, defaults (agent, model, workspace,
permission_policy), onboarding, lista de runtimes e overrides por workflow.
Um runtime registrado depois do onboarding é inserido em `machine_agents`
na leitura (`INSERT OR IGNORE`); a linha já gravada não é substituída.

Escrita em `pulse init` (`mark_onboarding_complete`) e no menu de configurações
(`update_global_defaults`, `update_global_agent`, `update_global_workflow`).

Não há `config.toml`. Override de testes: variável `PULSE_DB`.

## 2. Config do projeto — mesmo SQLite, `project_id`

Descoberta: sobe a partir do CWD até achar um `root_path` cadastrado em
`projects`.

Campos em `project_settings` / `project_agents` / `agent_settings`: agent, model,
permission_policy, workspace.

`machine_workflows` e `project_workflows` são **override de agent/model por id de
workflow**, e nascem vazios — eles não definem pipeline.

## 3. Definições — `workflow_defs`, `workflow_steps`, `agent_defs`

A configuração de fábrica é semeada no `SCHEMA` do banco
([`pulse/store/db.py`](../pulse/store/db.py)), com `INSERT OR IGNORE`: um
workflow `default` de um step e um agente `default` sem runtime fixo. É de
propósito que isso não seja arquivo — o pacote não carrega nenhum `.md`/`.yaml`
de domínio.

Detalhe do modelo: [workflows.md](workflows.md).

## 4. Estado das runs — `runs`, `run_steps`, `run_events`, `run_artifacts`

Chaveado por `run_id` e por `workspace_root`, **não** por `project_id`:
registrar o projeto só para satisfazer uma FK marcaria o workspace como
inicializado e faria o onboarding parar de rodar.

`run_steps` copia `label` e `position` da definição no início da run: editar o
workflow depois não reescreve o que já aconteceu.

`run_steps.context_tokens` guarda a última leitura de tokens no contexto do step
(`usage_update` do agente). Quem escreve é o log da sessão, não o `save` do
motor, que deixa a coluna de fora para não sobrescrever uma leitura mais nova.
A exceção: um step que volta a `pending` (parado ou reaberto num loop) roda de
novo em outra sessão, e o `save` zera a leitura dele.

`run_events` existe porque ler o log do runtime não serve — só o Cursor tem um, e
o Pulse é agnóstico ao agente.

## 5. Artefatos

O Pulse **não gera** arquivo nenhum. O agente escreve onde o prompt do step
mandar, e o Pulse descobre pelos tool-calls do ACP (`write`/`edit`/`create`),
gravando o caminho em `run_artifacts`. Não há convenção de pasta nem de nome, e
toda escrita é gravada; só o painel filtra, mostrando os `.md` dentro do
worktree.

A chave é `(run_id, path, step_id)` (migração 6): o mesmo arquivo escrito por dois
steps aparece nos dois, e reescrevê-lo atualiza `created_at`, de modo que a
última rodada de um loop é a versão mais recente.

## 6. Store do Cursor (externo)

O Pulse **não escreve** em `~/.cursor/`. `CursorStoreIndex` abre em modo leitura
`~/.cursor/acp-sessions/<sessionId>/store.db` (ou `~/.cursor/chats/…`) e usa a
tabela `blobs` para recuperar `args` de `tool-call` no cockpit ao vivo. É um
enriquecimento do stream vivo, não fonte de histórico.

## 7. Só memória (não persiste)

- `CockpitState` (steps, entries, artefatos selecionados)
- sessão ACP (`sessionId`, processo do agent)
- `ResolvedConfig` (merge em runtime)
- questionários e permissões

Se o cockpit fechar no meio, o stream se perde. `runs` / `run_steps` são o que
permitem retomar.
