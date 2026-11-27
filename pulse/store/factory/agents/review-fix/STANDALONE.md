Workspace: `{{workspace}}`
Original task: {{user_prompt}}

<!-- include: isolation -->

## Where this run is

Each step runs in its own session, so the only memory you have of the earlier
steps is what follows. This run is **not** part of the feature pipeline: there
is no `PRD.md`, `TECHSPEC.md` or `tasks.md`. The review that ran before you
reviewed the current branch and keeps its round files under
`.pulse/reviews/NNN-slug/`.

{{#if previous_summary}}### Previous step

{{previous_summary}}

{{/if}}{{#if artifacts}}### Files this run has written

{{artifacts}}

{{/if}}

## Review fix phase — remediate the round (do NOT review)

<!-- include: review-fix-skip -->

### When it runs

The round file is the entire scope: the highest `round-NNN.md` in the
`.pulse/reviews/<NNN>-<slug>/` directory named in the file list above — **if the
review that just ran wrote it**. Never pick a directory from `.pulse/reviews/`
that this run did not write: an older one is another review's history. Two cases
mean the review found nothing, and you say so and close `done` without going
looking for work:

- the file list names no round file at all;
- the highest round file was already closed by an earlier pass of this step
  (every finding in a terminal state, `Fix:` lines already there). A clean review
  writes no file, so the newest one on disk is the previous round's.

<!-- include: review-fix-newest-round -->

Follow the `review-fix.md` playbook above, in order:

1. Read the whole round file plus the artefacts the findings cite.
2. Triage **every** finding before editing any line.
3. Fix the `valid` ones in severity order, inside the files the findings name.
4. Verify with the project's own checks.
5. Close the round file in place: terminal status on every finding, `Fix:` on
   every `resolved`, `counts` and `verdict` recomputed.
6. Run the Step 5 self-check, then promote what deserves to become a rule.

<!-- include: review-fix-close -->

<!-- include: output-language -->
