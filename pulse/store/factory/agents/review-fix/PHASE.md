Workspace: `{{workspace}}`
Original task: {{user_prompt}}

<!-- include: isolation -->

<!-- include: handoff -->

## Review fix phase — remediate the round (do NOT review)

<!-- include: review-fix-skip -->

### When it runs

The round file is the entire scope: the highest `round-NNN.md` in
`.pulse/specs/features/<slug>/reviews/` — **if the review that just ran wrote
it**. Two cases mean the review found nothing, and you say so and close `done`
without going looking for work:

- there is no round file at all;
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
