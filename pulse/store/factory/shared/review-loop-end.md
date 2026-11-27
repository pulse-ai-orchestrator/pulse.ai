**You are the only one who can end this loop.** The fix step never closes it:
every fix pass sends the run back here, because a repair nobody has looked at is
not finished. The merge layer ends when a review finds nothing left to correct —
or at round 3, the last one: no fix runs after it.

There is no fourth round. If this is round 3, close every open ID — `resolved`,
`invalid`, `declined-accepted`, `waived` or `deferred` — and say plainly what the
person still has to decide, because nobody repairs anything after you.
