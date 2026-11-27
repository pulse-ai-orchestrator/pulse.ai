Workspace: `{{workspace}}`
Original task: {{user_prompt}}

<!-- include: isolation -->

<!-- include: handoff -->

## Verify phase — validate the implementation against the spec (do NOT implement)

Every task in `tasks.md` has been through the implement step. Your job is the
feature layer: prove, with evidence, whether what was built is what the feature's
`PRD.md` and its `TECHSPEC.md` (if it exists) specified.

You did not write this code and you have no notes from whoever did: the summary
above is a claim to check, not evidence. Re-derive the contract from the
artefacts and the code.

### Which round is this

**This step repeats.** The fix step after you repairs the gaps you list and sends
the run back here, at most until round 3. Check the list of files this run has
written, above, before deciding:

- **`validation.md` is not in the list of files this run has written → round
  1.** Nothing validated this feature in this run yet; a `validation.md` already
  on disk is left over from an earlier run. Run the full process below and
  (over)write the file with `**Round**: 1`.
- **`validation.md` is in that list → round N+1**, where N is the file's
  `**Round**`: you validated before and the fix step sent the run back. Do not
  re-validate the feature from scratch: confirm each `fixed` entry with its own
  evidence (`verified`, or back to `open` saying why), keep `open` whatever the
  fix could not repair, never reopen an `accepted` gap, re-run the gate and the
  sensor on the files the fixes touched, and add a gap only for what a fix
  broke. Update the verdict, the tables and `**Round**` in place.

### Scope

1. Read the feature's contract, `TECHSPEC.md` if it exists, and `tasks.md`.
2. `git diff` against the branch this run started from. Read-only — no commit,
   no stage, no push, no stash, no suggesting commit messages.
3. If there is no usable base (shallow clone, detached state, no commits yet),
   fall back to the file list above and say so in `validation.md`.

### What to do

Run the `validate.md` playbook above:

- every acceptance criterion and edge case from `PRD.md`, and every decision
  from `TECHSPEC.md`, gets a `file:line` of evidence or is a gap;
- run the build-level gate;
- run the discrimination sensor **only** in a scratch worktree you discard
  afterwards, and confirm `git status --porcelain` matches the baseline. That
  scratch copy is the one exception to the FORBIDDEN list in the approval block
  below: injecting faults there is how the sensor works, and the run's worktree
  stays untouched;
- write `.pulse/specs/features/<slug>/validation.md` and update the requirement
  traceability in `PRD.md`.

Do not touch application code or tests in this phase. Every gap becomes a fix
plan in `validation.md` with `**Status**: open` and a `**Kind**`:

- `code` — the fix step after you can repair it (missing test, unimplemented
  decision, weak assertion);
- `decision` — only the person can settle it (spec-precision gap, a PRD and a
  Techspec that contradict each other). No fix step closes one of these.

### What to present

Your reply has to stand on its own, because the person decides from it without
opening `validation.md`. Close with:

- the verdict (`PASS` or `FAIL`) and the round, first;
- AC coverage (`N/N`) and spec-precision gaps;
- the sensor result (killed, survived, or fallback with the reason);
- the path of `validation.md`;
- every `open` gap, one line each, most severe first: what is missing, where,
  and whether it is `code` or `decision`.

### When the person does not want a gap fixed

Answering **B** may mean "accept this gap, do not fix it". Then mark each gap
they named `**Status**: accepted`, with their reason in their own words, and
leave the verdict as it is — an accepted gap is still a gap, now with an owner.
If no gap is left `open`, close the loop as below; otherwise ask again.

A `decision` gap is settled the same way: the person's answer either accepts it
or turns it into a precise `code` gap for the fix step.

### When there is nothing left to fix — close the loop, do not ask

The approval below exists so the person can send gaps to the fix step. When none
would go, there is nothing to approve. End the loop yourself when:

- the verdict is `PASS` — nothing `open`;
- every gap is `verified` or `accepted`;
- this is **round 3**: no fix runs after you, so the approval would decide
  nothing. Leave what remains `open` as it is; the review picks it up.

In those cases do **not** write the approval block. Present the result as
described above, then end your reply with exactly this block:

````text
```pulse:outcome
status: done
next: close
```
````

Pulse ends the verify loop right there, skips the fix step and moves on to the
review. This is not moving on without approval: there was nothing to approve.

Otherwise, one line before the block making the options concrete: **A** sends
every `open` `code` gap to the fix step; a `decision` gap needs **B** with the
person's call, because no fix can settle it.

<!-- include: approval -->

<!-- include: output-language -->
