Workspace: `{{workspace}}`
Original task: {{user_prompt}}

<!-- include: isolation -->

<!-- include: handoff -->

## Execute phase — implement

Read the feature's contract, its `TECHSPEC.md` if it exists, and `tasks.md`.

{{#if item_id}}### Your task: {{item_id}} — {{item_label}} ({{item_index}} de {{item_total}})

Implement **only** `{{item_id}}`, and nothing else. The other tasks belong to
other runs of this step, each in its own session — a change outside this task's
scope collides with them. If `{{item_id}}` cannot be done without touching
something else, say so and stop instead of widening it.

{{/if}}Work through every task in scope for this step, one at a time and in the
order `tasks.md` lists them: plan → implement → verify its *Done when* → tick it
off. A task whose verification fails is not ticked.

**Unit tests only in this phase.** Do not write integration or end-to-end tests:
those belong to a later step. If the task cannot be proven by unit tests alone,
implement it anyway and record the gap in the **Deferred test coverage** section
of `tasks.md`, with the reason (which boundary is crossed: process, network,
browser, database, external service).

Follow the `implement.md` playbook above.
Do not run git operations (no commit, no suggesting commit messages).

Stop and say so instead of forcing it through when the task turns out to
contradict the Techspec or to need a decision nobody made.

Close with what you implemented, what you verified and what is still open.

<!-- include: output-language -->
