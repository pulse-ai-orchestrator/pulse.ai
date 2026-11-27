{{#if previous_status}}Previous step outcome: `{{previous_status}}`.

{{/if}}### Read this before anything else

`skipped` above means the person saw the review and chose **not** to have it
corrected in this run. That decision is yours to honour, not to revisit: do not
open the round file, do not read the diff, do not change a single line. Close
immediately with `status: done`, saying that the round stays on disk as written
and nobody asked for a repair. Anything else undoes an explicit instruction from
the user.

Anything other than `skipped` means the review was approved and this step runs.
