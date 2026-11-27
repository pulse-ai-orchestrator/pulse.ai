## Where this run is

Each step runs in its own session, so the only memory you have of the earlier
steps is what follows. The feature directory is `.pulse/specs/features/<slug>/`:
take the slug from the summary or the file list below. If neither names one, list
`.pulse/specs/features/` and use the most recently modified directory.

### The feature's contract

What this feature is built and checked against is its `PRD.md`. A purely
technical task has none: the PRD step skipped it, `context.md` records
`PRD dispensado`, and the contract is the `## Requirements` section of
`TECHSPEC.md` instead — same requirement IDs, same EARS acceptance criteria, same
`## Requirement Traceability` table. Wherever these instructions say `PRD.md`,
read that section; a missing `PRD.md` with that note is not a gap.

{{#if previous_summary}}### Previous step

{{previous_summary}}

{{/if}}{{#if artifacts}}### Files this run has written

{{artifacts}}

{{/if}}
