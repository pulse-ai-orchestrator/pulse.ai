### When there is nothing left to correct — close the loop, do not ask

The approval below exists so the person can decide what becomes a fix. When
nothing would, there is nothing to approve, and asking anyway only sends a fix
step to run for no reason. You end the loop yourself in three cases:

- this review wrote **no round file** — clean review, verdict `approved`;
- this is a later round and **every ID is already in a terminal state** with no
  new finding accepted — the fixes worked;
- this is **round 3**: nothing runs after you, so the approval would decide
  nothing.

In those cases do **not** write the approval block. Present the review as
described below, then end your reply with exactly this block:

````text
```pulse:outcome
status: done
next: close
```
````

Pulse ends the review loop right there and skips the fix step. Anything still
`pending`, `valid` or `needs-info` after round 1 or 2 is something to correct:
then, and only then, close with the approval block.

Otherwise, one line making the skip option concrete: choosing **Pular** keeps
this round file on disk and corrects nothing in this run.
