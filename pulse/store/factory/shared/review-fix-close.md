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
