Workspace: `{{workspace}}`
Original task: {{user_prompt}}

<!-- include: isolation -->

## Where this run is

Each step runs in its own session, so the only memory you have of the earlier
steps is what follows. This run is **not** part of the feature pipeline: there
is no `PRD.md`, `TECHSPEC.md` or `tasks.md`, and nothing under
`.pulse/specs/features/` belongs to it. Its round files live under
`.pulse/reviews/NNN-slug/`.

{{#if previous_summary}}### Previous step

{{previous_summary}}

{{/if}}{{#if artifacts}}### Files this run has written

{{artifacts}}

{{/if}}
## Review phase — review the current branch (do NOT fix)

There are no spec artefacts to read. Re-derive the contract from what the branch
says about itself: the commit messages (`git log <base>..HEAD`), the diff, and
the project's own docs (`README`, `ARCHITECTURE.md`, `.pulse/` rules) where they
exist. You did not write this code and you have no notes from whoever did.

### Which round is this

**This step repeats.** The fix step after you can send the run back here, so
look at the file list above before deciding what to do:

- **It names no `.pulse/reviews/…/round-NNN.md` → this is round 1.** Create the
  review directory: `.pulse/reviews/<NNN>-<slug>/`, where `NNN` is the highest
  existing number under `.pulse/reviews/` plus 1 (`001` if there is none) and
  `slug` is the current branch name in kebab-case (`/` becomes `-`). Run the
  full process below. Round 1 is the whole review: everything visible is raised
  now, because a finding held back is forfeited, not postponed.
- **It names a round file → that directory is this run's.** The next round is
  the highest `NNN` in it plus 1. Read [convergence.md](convergence.md) and
  follow it instead: confirm every ID from the previous rounds reached a
  terminal state, and accept at most 3 new findings, all `critical`, each naming
  the fix that introduced it. Re-reviewing untouched code is re-running round 1,
  which is the loop this contract exists to terminate. Scope yourself to what
  the fixes changed.

Never reuse a `.pulse/reviews/` directory this run did not write: an older one
is another review's history.

<!-- include: review-loop-end -->

### Scope

The scope is everything the current branch changed, committed or not. Read-only
git only — no commit, no stage, no push, no suggesting commit messages:

1. Find the base: `git merge-base HEAD main`; if `main` does not exist, try
   `master`, then the branch `origin/HEAD` points to.
2. `git diff <base>` — this covers commits on the branch **and** uncommitted
   changes in the working tree.
3. Add untracked files from `git status --porcelain` (`??` lines), ignoring
   anything under `.pulse/`.
4. If there is no usable base (shallow clone, detached state, no commits yet, or
   HEAD is the main branch itself), review the uncommitted changes alone
   (`git diff HEAD` plus untracked). Say in the TL;DR where the scope came from.

If the scope is empty, say so, verdict `approved`, and close the loop as
described below.

Classify each changed file as core or mechanical, and list the mechanical ones
under **Arquivos pulados** instead of reviewing them.

### Output

Run the `review.md` playbook above: ladder first, then the passes it allows for
this scope, then verification, then the round file.

Write **one** file: the next free `round-NNN.md` in this run's
`.pulse/reviews/<NNN>-<slug>/` directory. Do not touch application code in this
phase — identifying is this step's whole job, and repairing belongs to the next
one.

<!-- include: review-present -->

<!-- include: review-close -->

<!-- include: approval-skip -->

<!-- include: output-language -->
