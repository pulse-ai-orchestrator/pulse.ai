---
name: execute-spec
description: Implements one Pulse roadmap spec phase end-to-end from product and technical documents, validates with pytest, commits changes, and opens a PR via create-pr skill. Use when a prompt includes spec paths, branch name, and PR base branch. Do not use for PRD/TechSpec generation or generic coding without a spec phase.
---

# Execute Roadmap Spec Phase

Implement one roadmap spec phase from exploration through PR creation.

## Required Inputs

- Product spec path (`product.md`).
- Technical spec path (`technical.md`).
- Shared docs paths (architecture, acceptance criteria, schema when applicable).
- Applicable Cursor skills list.
- Target branch name (already checked out by the runner).
- Parent branch name (branch da fase anterior na cadeia sequencial).
- PR base branch (igual à parent branch — a fase anterior).
- Status file path for completion tracking.
- Git repository root.

## Workflow

1. Ground in repository and spec context.
   - Read `product.md` and `technical.md` for this phase.
   - Read shared docs provided by the caller.
   - Read applicable skills listed by the caller before writing code.
   - Read `backend/docs/ROADMAP.md` for architectural context.
   - Reconcile the current workspace state before new edits.
   - If requirements conflict between product and technical specs, stop and report instead of guessing.

2. Build the execution checklist.
   - Extract deliverables, acceptance criteria, affected files, and tests from both spec files.
   - Merge with global acceptance criteria from `shared/acceptance-criteria.md`.
   - Print the full checklist before implementation.
   - Mark each item done as evidence is produced.

3. Implement the phase.
   - Keep scope tight to the spec documents; do not expand beyond "Fora de escopo".
   - Follow repository patterns and applicable skills (`python-expert`, `clean-code`, `python-design-patterns`, `python-testing-patterns`, `python-project-structure`, `terminal-ui` when TUI applies).
   - Respect diff size guidance in the technical spec.
   - Do not add code comments unless the repository already uses them in the same area.

4. Validate and self-review.
   - Run `pytest` from `backend/` for the affected scope.
   - Fix failures before proceeding.
   - Perform a self-review and resolve blocking issues.

5. Update completion tracking.
   - Write `status: completed` to the status file path provided by the caller.
   - Include phase slug, branch name, and pytest result summary in the status file.

6. Commit changes.
   - Stage only files relevant to this phase.
   - Create one commit with a Conventional Commits message aligned to the PR title in the product spec.
   - Do not push and do not open a PR — the `pulse_specs` runner handles push and PR creation automatically.

7. Finalize.
   - Confirm `status: completed` in the status file.
   - Report what was implemented and pytest results.
   - Do not attempt GitHub MCP, `gh` CLI or manual PR creation.

## Error Handling

- If validation fails, do not mark the status file as completed.
- If git operations fail, report the error and stop.
- If git commit fails, report the error and keep status incomplete.
- Never force-push.

## Completion Gate

The phase is complete only when all are true:

- Implementation matches spec acceptance criteria
- `pytest` passes for affected tests
- Status file contains `status: completed`
- Local commit exists with phase changes
