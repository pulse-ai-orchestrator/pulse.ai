Workspace: `{{workspace}}`
Original task: {{user_prompt}}

<!-- include: isolation -->

## Where this run is

Each step runs in its own session, so the only memory you have of the earlier
steps is what follows. This run is a **quick task**, not the feature pipeline:
there is no `PRD.md`, `TECHSPEC.md` or `tasks.md`. The task lives in
`.pulse/specs/quick/NNN-slug/` — take the directory from the `TASK.md` in the
file list below — and the review that ran before you keeps its round files in
its `reviews/` subdirectory.

{{#if previous_summary}}### Previous step

{{previous_summary}}

{{/if}}{{#if artifacts}}### Files this run has written

{{artifacts}}

{{/if}}

## Review fix phase — remediate the round (do NOT review)

{{#if previous_status}}Previous step outcome: `{{previous_status}}`.

{{/if}}### Read this before anything else

`skipped` above means the person saw the review and chose **not** to have it
corrected in this run. That decision is yours to honour, not to revisit: do not
open the round file, do not read the diff, do not change a single line. Close
immediately with `status: done`, saying that the round stays on disk as written
and nobody asked for a repair. Anything else undoes an explicit instruction from
the user.

Anything other than `skipped` means the review was approved and this step runs.

### When it runs

The round file is the entire scope: the highest `round-NNN.md` in
`.pulse/specs/quick/NNN-slug/reviews/` — **if the review that just ran wrote
it**. Never pick another quick task's directory: it is another run's history.
Two cases mean the review found nothing, and you say so and close `done` without
going looking for work:

- the file list names no round file at all;
- the highest round file was already closed by an earlier pass of this step
  (every finding in a terminal state, `Fix:` lines already there). A clean review
  writes no file, so the newest one on disk is the previous round's.

Only the newest round is yours. Earlier rounds were closed by earlier passes of
this same step, and reopening one would restart the loop this design exists to
terminate.

Follow the `review-fix.md` playbook above, in order:

1. Read the whole round file, the task's `TASK.md`, and the artefacts the
   findings cite.
2. Triage **every** finding before editing any line.
3. Fix the `valid` ones in severity order, inside the files the findings name.
   A quick task touches at most 3 files: a fix that needs a file `TASK.md` does
   not list is a decision for the person, not a repair — report it and leave it
   `unresolved`.
4. Verify with the project's own checks.
5. Close the round file in place: terminal status on every finding, `Fix:` on
   every `resolved`, `counts` and `verdict` recomputed.
6. Run the Step 5 self-check, then promote what deserves to become a rule.

Never add a finding and never open a new round — that freeze is what makes the
review terminate. Something new that is genuinely `critical` goes in your closing
report, for the user to decide.

Do not run git operations (no commit, no staging, no suggesting commit messages).

### How this step closes — and whether the review runs again

There is no approval here, so you are the one attesting the delivery. **You do
not decide whether the merge layer is finished — the review does.** A fix pass
can never be the last word: only the next review round can confirm there is
nothing left to correct.

The rule is one line: **you worked a round, the review runs again.**

````text
```pulse:outcome
status: done
next: repeat
```
````

Use `next: repeat` whenever this pass worked a round file — you edited files,
or you triaged every finding as `invalid`, or anything in between. Something you
repaired can break something else, and a triage nobody checked is still your
word against the reviewer's; that second look is the whole reason the loop
exists. The next review will not re-review the feature from scratch; it checks
your pass and accepts only what a fix broke.

Omit `next` only when there was no round for you to work: the review found
nothing (see *When it runs*), or the person skipped it. That is the review
closing the loop, not you.

````text
```pulse:outcome
status: done
```
````

Use `blocked` when a `critical` or `high` is still open and the person has
neither waived nor deferred it, naming what is missing:

````text
```pulse:outcome
status: blocked
needs: user
```
````

Closing `done` with a blocker open would tell the pipeline the merge layer is
finished when it is not — and asking for another round does not fix a blocker,
because the next review cannot decide what only the person can.

The loop has a ceiling of three review rounds, and the third is the last word:
no fix runs after it. So your request for another round is always honoured —
the run never ends on your pass.

<!-- include: output-language -->
