Workspace: `{{workspace}}`
User task: {{user_prompt}}

<!-- include: isolation -->

## Triage first — does this task need a PRD at all?

A PRD settles what the **product team** decides. Before anything else, and
before asking any question, read the task (and the code it names, when that is
what tells you) and decide:

- **No product decision in it → skip this step.** The task is purely technical:
  refactor, rename, tech debt, dependency upgrade or CVE fix, build/CI/tooling,
  test coverage, performance or observability with no change the user sees,
  internal API or code reorganization, a bug whose correct behavior is not in
  question. Nobody on the product team would settle any of its open points
  differently from an engineer.
- **Any product decision in it → write the PRD.** Behavior a user sees, a
  business rule, copy or UX, scope the product team could cut or widen, a bug
  whose expected behavior is itself the question.
- **Unsure → write the PRD.** A skipped PRD hides product decisions inside the
  Techspec; a short PRD costs one approval.

Skipping is your call: do not ask the user whether to skip, and do not ask for
approval to skip. It is the one exit this phase takes without approval. When
you skip:

1. Pick a short kebab-case **feature slug**, create
   `.pulse/specs/features/<slug>/` and make sure `.pulse/specs/project/STATE.md`
   exists.
2. Write `.pulse/specs/features/<slug>/context.md` with a `## PRD` section that
   reads `PRD dispensado — <why, in one line>`. Do not write `PRD.md`.
3. Update `STATE.md` → Current Work with this feature.
4. Open your reply with the feature slug and its full path, say in one line why
   no product decision is involved, and close with the `pulse:outcome` block
   carrying `status: skipped` (format at the end of this prompt). No question
   block, no approval block.

The Techspec step that follows writes the requirements and acceptance criteria
itself, in a `## Requirements` section of `TECHSPEC.md`.

## PRD phase — capture WHAT to build (do NOT implement)

When the task does need a PRD, follow the `prd.md` playbook above (auto-sizing
by complexity).
ACP already loads the workspace rules/skills; do not re-read the whole set by habit.

1. Pick a short kebab-case **feature slug** from the task and create
   `.pulse/specs/features/<slug>/`.
2. Make sure `.pulse/specs/project/STATE.md` exists.
3. Write `.pulse/specs/features/<slug>/PRD.md` with traceable requirements.
4. Every gray area becomes an Ambiguity Ledger row and leaves this phase as
   `decided` (the product team chose) or `n/a` (does not apply to this feature).
   Record the decisions in `context.md`, next to the PRD, per `discuss.md`.
5. Update `STATE.md` → Current Work with this feature.

Open your summary with the **feature slug and its full path**. The next steps run
in a fresh session and find the feature by that path — a summary without it costs
them a search.

Then present: the problem, the scope, the complexity, and whether a Techspec is
needed at all (say so explicitly if it is not).

<!-- include: clarify -->

<!-- include: approval -->

<!-- include: output-language -->
