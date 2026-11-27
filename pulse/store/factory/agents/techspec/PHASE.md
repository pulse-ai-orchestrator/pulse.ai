Workspace: `{{workspace}}`
Original task: {{user_prompt}}

<!-- include: isolation -->

<!-- include: handoff -->

## Techspec phase — define HOW to build it (do NOT implement)

Read the feature's `context.md` and its `PRD.md`.
Write `TECHSPEC.md` next to them, per the `techspec.md` playbook above.

{{#if previous_status}}The PRD step closed as `{{previous_status}}`; `skipped` means there is no PRD.
{{/if}}**No PRD** (the PRD step closed as `skipped`, or `context.md` says
`PRD dispensado`): this Techspec is also the
contract. Before the architecture, write a `## Requirements` section with what
the task must deliver — requirement IDs, EARS acceptance criteria (one testable
behavior each, concrete values), edge cases — and a `## Requirement Traceability`
table, the same shape the PRD template uses. Every gray area becomes an Ambiguity
Ledger row here. If you find a decision that does belong to the product team, ask
it in product language instead of deciding it.
Read rules/conventions from disk only when they bear on an architecture decision.

The **implicit-requirement sweep** belongs to this phase (PRD only covers
product): input validation, partial failure, idempotency/retry, auth boundaries
and rate limits, concurrency/ordering, data lifecycle, observability,
external-dependency failure and state-transition integrity.
Each dimension becomes a `decided` or `n/a` Ambiguity Ledger row — `assumed` does
not exist. When the choice is a real trade-off with no obvious answer in the code,
ask the technical owner instead of deciding alone. Technical vocabulary is welcome
here.

Present a summary: the feature path, the architecture, the components, and what
existing code gets reused.

<!-- include: approval -->

<!-- include: output-language -->
