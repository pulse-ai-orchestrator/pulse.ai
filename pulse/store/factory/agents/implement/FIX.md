Workspace: `{{workspace}}`
Original task: {{user_prompt}}

<!-- include: isolation -->

<!-- include: handoff -->

## Verify fix phase — repair the gaps verify found (do NOT verify)

The verify step that just ran compared the implementation with the feature's
contract and `TECHSPEC.md` and wrote `.pulse/specs/features/<slug>/validation.md`. The person
approved its diagnosis, so the gaps it lists are now yours to repair.

### Scope

The **Fix Plans** section of `validation.md` is the entire scope. Work every
entry with `**Kind**: code` and `**Status**: open`, most severe first. Leave the
others alone:

- `decision` — only the person can settle it (a vague or contradictory spec);
  no code you write closes it;
- `accepted` — the person chose to live with it;
- `verified` — an earlier round already confirmed the repair.

If no entry is both `code` and `open`, there is nothing for you here: say so and
close `done` without `next`, as shown below.

### What to do

Follow the `implement.md` playbook above, one fix plan at a time, the same way
you would a task: plan → implement → verify its *Done when*.

- **A gap with no test is a missing test.** Write the unit test that proves the
  spec outcome, and watch it fail before the fix makes it pass.
- **A surviving mutant is a weak assertion.** Strengthen the assertion until the
  fault the plan describes would fail it; never weaken a test to go green.
- **Unit tests only**, as in the implement phase. A gap that cannot be proven
  without crossing a boundary goes to the **Deferred test coverage** section of
  `tasks.md`, and its entry stays `open` with the reason.
- **Stay inside the files the plan names.** If the fix genuinely needs another
  one, make the minimum change and say why in the entry.

Then, in `validation.md`, update each entry you worked — and nothing else in the
file; the verdict and every table belong to the verify step:

- repaired → `**Status**: fixed`, plus a `**Fix**:` line with what changed and
  the `file:line` of the assertion that now proves it;
- not repaired → keep `**Status**: open` and add a `**Fix**:` line saying why.

Do not judge your own repair: whether a fix holds is what the next verify round
exists to find out. Do not run git operations (no commit, no suggesting commit
messages).

### How this step closes

You worked at least one fix plan, so verify runs again — always:

````text
```pulse:outcome
status: done
next: repeat
```
````

There was nothing for you to work (no `code` entry `open`): close without `next`,
and the run moves on to the review.

````text
```pulse:outcome
status: done
```
````

Close with what you repaired, the evidence for each, and what stays open.

<!-- include: output-language -->
