# Questions

O Pulse **não lê pergunta em arquivo**. O único canal é o terminal / TUI.

Há **dois jeitos** de o agente perguntar, mais um irmão (permissão). Os três caem no mesmo `PromptHandler`.

```
agente
  ├─ texto com ```text          → parse_text_questionnaire
  │                               (depois do turn)
  ├─ JSON-RPC cursor/ask_question → respond_to_ask_question
  │                               (no meio do turn)
  └─ MCP tools/call AskQuestion   → o mesmo handler
        │
        ▼
PromptHandler  (terminal / questionary)
  ou
TextualPromptHandler → PromptBridge → PromptDock (TUI)
        │
        ▼
resposta volta ao agente
  ou
Pulse classifica o outcome (aprovar / ajustar / cancelar / …)
```

## 1. Questionário de texto (o fluxo principal)

Um step com `requires_approval` espera que o agente **termine** a resposta com um
bloco assim. Quem pede isso é o `prompt_template` do step — o Pulse não instrui o
agente, só sabe ler o resultado:

````text
```text
Preciso de algumas informações antes de continuar.
1. Aprovar o plano (docs/PLANO.md) e avançar?
A) Sim, aprovar e continuar
B) Não, preciso de ajustes (descreva)
C) Cancelar workflow
```
````

Regras que o parser exige (`pulse/replies/text_questionnaire.py`):

- header `Preciso de algumas informações…` ou `I need some information…`
- pergunta `N. texto`
- opções `A) texto` (uma por linha)
- de preferência dentro de ` ```text `
- `Resposta:` no fim é ignorado (é para o chat, não para o Pulse)

Enquanto o texto chega, `CockpitSink` / `StreamRenderer` entram em **questionnaire mode**: param de imprimir o bloco e mostram só `Questionário interativo`.

Depois do `session/prompt` acabar, o runner chama `_run_text_questionnaire`:

| Parser | Significado |
| --- | --- |
| bloco inválido / ausente | retorna `""` — ninguém perguntou |
| usuário cancela (Esc) | retorna `None` — workflow cancela |
| usuário responde | texto `→ A) Sim, aprovar…` |

O handler mostra **uma pergunta por vez**. Sem opções → campo livre. “Outro” → texto livre (`__other__`).

O campo de texto abre depois do select por duas razões
([`approval.answer_needs_description`](../pulse/replies/approval.py)):

1. **O rótulo pede.** Não só `(descreva)`: vale parêntese, colchete ou cauda
   depois de travessão/dois-pontos, com qualquer verbo de escrever nos dois
   idiomas — `(describe)`, `[descreva]`, `— especifique`, `Descreva:`.
2. **É portão de aprovação e a escolha não aprova, pula nem cancela.** Esta não
   depende da redação: o desfecho é lido pelo mesmo `classify_outcome` que o
   motor usa, então um `B) Não` seco também abre o campo. Sem isso a escolha
   volta ao agente como “o usuário quer mudanças” sem dizer **o que** mudar, e
   ele refaz o step no escuro.

O vocabulário do portão (`aprovar/approve`, `cancelar/cancel`, `pular/skip`,
`ajuste/adjust/change`) é bilíngue: os playbooks de fábrica são em inglês e pedem
o bloco em português, e o agente nem sempre obedece.

O Pulse **injeta** `Outro (descreva)` sozinho, **exceto** em perguntas fechadas de aprovação / migração / “funciona como esperado”.

## 2. `cursor/ask_question` (durante o turn)

O agent pode mandar um request JSON-RPC no stdout. O `AcpSessionRunner` não trata isso como `session/update`: chama `_handle_agent_request`.

Payload típico:

```json
{
  "title": "Preciso de algumas informações antes de continuar.",
  "questionIndex": 1,
  "totalQuestions": 2,
  "questions": [
    {
      "id": "q1",
      "prompt": "Qual stack?",
      "options": [{"id": "a", "label": "Python"}, {"id": "b", "label": "Go"}],
      "allowMultiple": false
    }
  ]
}
```

Resposta que volta no JSON-RPC:

```json
{
  "outcome": {
    "outcome": "answered",
    "answers": [{"questionId": "q1", "selectedOptionIds": ["a"]}]
  }
}
```

Cancelar: `{"outcome": {"outcome": "cancelled"}}`.

Descrição extra (opção “descreva”) vai no id: `"B::o botão some no mobile"`.

Este canal **não** passa pelo classificador de fase. A resposta vai direto ao agente, que continua o mesmo turn.

## 3. MCP `AskQuestion`

No `start()` do runner sobe um HTTP local (`AskQuestionHttpServer`, `127.0.0.1` porta aleatória, path `/mcp`).

O servidor recusa (`403`) request com `Origin` ou com `Host` que não seja `127.0.0.1`/`localhost`: só o processo do agente fala com ele, nunca uma página no navegador ([ADR 0003](adr/0003-listeners-locais-recusam-navegador.md)).

`session/new` registra:

```json
{ "type": "http", "name": "pulse-ask", "url": "http://127.0.0.1:<porta>/mcp" }
```

O agente chama `tools/call` com a tool `AskQuestion` (schema em `pulse/mcp/ask_protocol.py`). O servidor usa o **mesmo** `respond_to_ask_question`. O resultado vira texto JSON no content da tool.

Existe também um bridge Unix socket (`AskQuestionBridgeServer`) para testes / stdio. O caminho de produção do runner é o HTTP.

## 4. Onde a UI aparece

| Superfície | Handler | Widget |
| --- | --- | --- |
| Menu terminal (Rich) | `PromptHandler` | `questionary.select` / `checkbox` / `text` |
| TUI cockpit | `TextualPromptHandler` | `PromptBridge` + `PromptDock` |

Na TUI o worker ACP **bloqueia** num `Future`. A thread da UI faz `poll()` a cada 100 ms, monta o dock no `LogStream` e devolve o resultado. Esc cancela.

Tipos do dock: `select`, `multi_select`, `text`, `confirm`.

## 5. O que o Pulse faz com a resposta

### Steps com aprovação

Até **12 turns** (`MAX_PHASE_APPROVAL_TURNS`). Esgotados os turns sem
aprovação, o step cai no menu de retry com esse motivo, e a nova tentativa
recebe as respostas já dadas. O texto de respostas que volta ao agente pede
que ele faça no mesmo bloco todas as perguntas que já enxerga, em vez de uma
por rodada. Depois de cada turn, o Pulse classifica as linhas `→ …`
(`pulse/replies/approval.py`):

| Outcome | Gatilho (texto) | Efeito |
| --- | --- | --- |
| `approve` | “aprov” numa opção escolhida | step vira `done`, segue |
| `cancel` | “cancelar” | step não fechou; cai no menu de retry |
| `skip` | “pular” | step vira `skipped` — não é falha |
| `adjust` | “ajuste” | prompt de continuação, sem avançar |
| `continue` | resto | prompt de continuação, tenta de novo |

Texto livre (“Outro — …”) **nunca** aprova: é orientação, não escolha. Sem bloco
de aprovação, o laço para sem aprovar e o step cai no menu de retry.

Esse é o **único** conteúdo da resposta do agente que o Pulse interpreta.

### Steps sem aprovação

`run_isolated_prompt` não espera questionário: basta o agente fechar o turno
(`stopReason`). Perguntas no meio do turn continuam funcionando via
`ask_question` / MCP.

## 6. Irmãos: permissão e plano

Não são questionário, mas usam o mesmo handler:

- `session/request_permission` / `cursor/request_permission` — política `ask` / `auto_approve` / `deny_writes`
- `cursor/create_plan` — confirm “Aprovar plano?”

`deny_writes` aprova sozinho só o que não mexe em nada (`read`, `search`,
`fetch`, `think`) e recusa `edit`/`delete`/`move` **sem exceção por caminho**: o
Pulse não sabe qual pasta é “dele”. `execute` (o Bash do Claude) e kind
desconhecido viram pergunta, porque só quem lê o comando sabe se ele escreve.
Step que precisa escrever é step com `ask` ou `auto_approve`. Shell sem
capability de terminal é recusado. Aprovar sozinho escolhe `allow_once`, nunca
`allow_always`: a escolha não vaza para os steps seguintes da sessão.

## 7. O que **não** é persistido

Pergunta não vira arquivo em lugar nenhum. Só o que sobra é o log do cockpit (`Question` / `Answer`) se a TUI estiver aberta — ver [logs.md](logs.md).

## Design da escolha

**O que:** terminal como único I/O; bloco ` ```text ` como contrato mínimo com o agente; MCP/`ask_question` como atalho no meio do turn.

**Por quê:** o agente ACP não tem TUI. O Pulse precisa **parar o processo** e perguntar no mesmo terminal em que o usuário rodou `pulse`. O bloco de texto é parseável sem tool. O MCP cobre o caso em que o modelo prefere chamar `AskQuestion`.

**Alternativas:** arquivos de pergunta no disco, UI web, sempre tool e nunca texto.

**Trade-off:** se o modelo quebrar o formato (`A) B) C)` na mesma linha), o parser ignora o bloco e o step **não aprova** — cai no menu de retry. Por isso o `prompt_template` de um step com aprovação precisa ser rígido no layout que pede.
