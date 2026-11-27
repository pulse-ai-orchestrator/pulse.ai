Workspace: `{{workspace}}`
Original task: {{user_prompt}}

<!-- include: isolation -->

<!-- include: handoff -->

## Tasks phase — break into atomic tasks (do NOT implement)

Read the feature's contract and its `TECHSPEC.md` if it exists.
Write `tasks.md` next to them, one heading per task (`### T1: …`, `### T2: …`),
in execution order.
Do not end this phase without that file. A clarifying question does not approve
the phase.
ACP already loads the workspace rules/skills; do not re-read the whole set by habit.

No task carries `Tests: integration` or `Tests: e2e` — the implementation writes
unit tests only. A layer that would need integration/e2e becomes a row in the
**Deferred test coverage** section of `tasks.md`, with ID, type, what it covers
and which boundary is crossed. The gap stays visible and traceable, not silent.

Run the 3 mandatory checks from the `tasks.md` playbook before presenting.
Present a summary: the feature path, the task count, the execution phases, the
critical dependencies, and what ended up in Deferred test coverage.

### Task list for Pulse (mandatory)

Pulse runs **one isolated agent per task**, and it only knows the tasks you
declare here. End your summary — before the approval block — with a fenced
`pulse:items` block, one line per task, in execution order:

````text
```pulse:items
T1 — Criar o endpoint de exportação
T2 — Montar o CSV a partir do relatório
T3 — Cobrir o endpoint com testes unitários
```
````

The id (`T1`) must match the heading in `tasks.md`; the text after the dash is
what shows up in the Pulse panel, so write it in Portuguese and keep it short.
Emit the block exactly once, listing every task — a task missing from it is a
task nobody implements.

<!-- include: approval -->

<!-- include: output-language -->
