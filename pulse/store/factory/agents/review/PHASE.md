Workspace: `{{workspace}}`
Original task: {{user_prompt}}

<!-- include: isolation -->

<!-- include: handoff -->

## Review phase — review what was implemented (do NOT fix)

Read the feature's contract, its `TECHSPEC.md` if it exists, and `tasks.md`.
You did not write this code and you have no notes from whoever did: re-derive the
contract from the artefacts and the diff, not from the summary above.

The verify step before you checked the feature against that contract and wrote
`validation.md` next to them. In round 1, every fix plan there still
`**Status**: open` is a finding of yours: re-check it against the code — it may
have been fixed since — and, if it holds, raise it citing its `Fix N` id. An
`accepted` gap is the person's decision, not a finding; do not raise it again.

### Which round is this

**This step repeats.** The fix step after you can send the run back here, so
check `.pulse/specs/features/<slug>/reviews/` before deciding what to do. The
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

**You are the only one who can end this loop.** The fix step never closes it:
every fix pass sends the run back here, because a repair nobody has looked at is
not finished. The merge layer ends when a review finds nothing left to correct —
or at round 3, the last one: no fix runs after it.

There is no fourth round. If this is round 3, close every open ID — `resolved`,
`invalid`, `declined-accepted`, `waived` or `deferred` — and say plainly what the
person still has to decide, because nobody repairs anything after you.

### Scope

The scope is what this run changed. In order:

1. `git diff` against the branch this run started from. Read-only — this is the
   **only** git contact allowed in this phase. No commit, no stage, no push, no
   suggesting commit messages.
2. If there is no usable base (shallow clone, detached state, no commits yet),
   fall back to the file list above, which is exactly what this run wrote. Say in
   the TL;DR that scope came from artefacts rather than from a diff.

Classify each changed file as core or mechanical, and list the mechanical ones
under **Arquivos pulados** instead of reviewing them.

### Output

Run the `review.md` playbook above: ladder first, then the passes it allows for
this scope, then verification, then the round file.

Write **one** file: the next free `.pulse/specs/features/<slug>/reviews/round-NNN.md`.
Do not touch application code in this phase — identifying is this step's whole
job, and repairing belongs to the next one.

**Nothing found means no file.** Report a clean review, verdict `approved`, and
close the loop as described below. An empty round file is worse than no round
file.

Before presenting, run the Step 6 self-check against every finding you wrote.

### What to present

Your reply has to stand on its own, because the person decides from it without
opening the round file. Close with:

- **whether anything `critical` or `high` is still open** — in a later round this
  is the whole question, so it goes first;
- the verdict (`approved`, `approved-with-followups`, `changes-requested`);
- the count per severity, and which round this is;
- the path of the round file, when there is one;
- every `critical` and `high`, one line each: what is wrong and where.

<!-- include: review-close -->

Otherwise, one line making the skip option concrete: choosing **Pular** keeps
this round file on disk and corrects nothing in this run.

<!-- include: approval-skip -->

<!-- include: output-language -->
