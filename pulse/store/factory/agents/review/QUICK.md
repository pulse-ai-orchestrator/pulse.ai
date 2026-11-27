Workspace: `{{workspace}}`
Original task: {{user_prompt}}

<!-- include: isolation -->

## Where this run is

Each step runs in its own session, so the only memory you have of the earlier
steps is what follows. This run is a **quick task**, not the feature pipeline:
there is no `PRD.md`, `TECHSPEC.md` or `tasks.md`, and nothing under
`.pulse/specs/features/` belongs to it. The task lives in
`.pulse/specs/quick/NNN-slug/`: take the directory from the `TASK.md` in the
file list below, or from the summary. If neither names one, list
`.pulse/specs/quick/` and use the most recently modified directory.

{{#if previous_summary}}### Previous step

{{previous_summary}}

{{/if}}{{#if artifacts}}### Files this run has written

{{artifacts}}

{{/if}}
## Review phase — review the quick task (do NOT fix)

Read the task's `TASK.md` and, if it exists, its `SUMMARY.md`. `TASK.md` is the
contract: what was asked, the files it allowed, and how to verify it. You did
not write this code and you have no notes from whoever did: re-derive the
contract from `TASK.md` and the diff, not from the summary above.

A quick task touches at most 3 files. A change outside the files `TASK.md`
lists, or a verification box ticked without the check passing, is a finding.

### Which round is this

**This step repeats.** The fix step after you can send the run back here, so
check `.pulse/specs/quick/NNN-slug/reviews/` before deciding what to do. The
next round is the highest existing `NNN` plus 1, and the rules change with it:

- **No round file yet → this is round 1.** Run the full process below. Round 1
  is the whole review: everything visible is raised now, because a finding held
  back is forfeited, not postponed.
- **A round file already exists → read [convergence.md](convergence.md) and
  follow it instead.** A later round has exactly two jobs: confirm every ID from
  the previous rounds reached a terminal state, and accept at most 3 new
  findings, all `critical`, each naming the fix that introduced it. Re-reviewing
  untouched code is re-running round 1, which is the loop this contract exists
  to terminate. Scope yourself to what the fixes changed.

<!-- include: review-loop-end -->

### Scope

The scope is what this run changed. In order:

1. `git diff` against the branch this run started from, plus uncommitted
   changes. Read-only — this is the **only** git contact allowed in this phase.
   No commit, no stage, no push, no suggesting commit messages.
2. If there is no usable base (shallow clone, detached state, no commits yet),
   fall back to the file list above, which is exactly what this run wrote. Say in
   the TL;DR that scope came from artefacts rather than from a diff.

Files under `.pulse/` are the task's own records, not code under review. Classify
each remaining changed file as core or mechanical, and list the mechanical ones
under **Arquivos pulados** instead of reviewing them.

### Output

Run the `review.md` playbook above: ladder first, then the passes it allows for
this scope, then verification, then the round file.

Write **one** file: the next free `.pulse/specs/quick/NNN-slug/reviews/round-NNN.md`.
Do not touch application code in this phase — identifying is this step's whole
job, and repairing belongs to the next one.

<!-- include: review-present -->

<!-- include: review-close -->

<!-- include: approval-skip -->

<!-- include: output-language -->
