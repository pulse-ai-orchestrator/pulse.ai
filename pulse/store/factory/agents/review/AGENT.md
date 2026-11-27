---
name: review
description: Revisa o que foi implementado e escreve a rodada
runtime: cursor
model: Auto
permission_policy: ask
---

# review.md

# Review

**Goal**: Review code like a senior engineer with a high conviction bar, and stop.

Three findings that matter beat fifteen observations that waste the author's
time, and a review that never ends is worse than no review at all.

This is the **Merge layer** of the three-layer Definition of Done
(the implement step owns the task layer, the verify step the feature layer
and its `validation.md`). The Verifier proves tests against the spec; review
proves the code.

---

## Non-Negotiables

These override everything else. Read them before acting.

1. **The merge gate is the frozen round-1 set.** Merge unblocks when every
   `critical` and `high` from **round 1** is `resolved`, `invalid`, or waived by
   the user. A discovery in a later round never reopens it. "Can I merge?" never
   depends on "did the reviewer stop finding things?"
2. **Round 1 is the whole review.** Everything visible in round 1 is raised in
   round 1. Holding a finding back is forbidden. Code visible in round 1 and not
   flagged is forfeited permanently; the reviewer eats the miss.
3. **The set only shrinks.** Round 2 accepts at most 3 new findings, all
   `critical`, each naming the previous finding whose fix introduced it. Round 3
   accepts none. Round 4 does not exist.
4. **Evidence is verified, not declared.** Every internal citation carries the
   quoted line, and you re-open the file to match it. A citation that does not
   exist, or does not say what the finding claims, does not ship.
5. **Never flag what the repo's own tooling catches.** Run the project's linter,
   type checker, and focused tests first. Anything they report is out of review
   scope.
6. **Do not fix during review.** Review identifies; the next step repairs.
   Separate phases, separate sessions. This separation is the whole reason the
   review terminates.
7. **No git writes, no network writes.** Never commit, never push, never open or
   comment on a PR. `git diff` read-only for scope detection is the only git
   contact. The round file is the entire output.
8. **Spend tokens where judgment lives.** Read the diff, the files it touches,
   and their direct callers when tracing a finding. Never ingest the repo.

---

## Auto-Sizing

Depth follows scope, like every other phase. Review does not run at one fixed cost.

| Scope | Passes | Research | Round-1 budget |
| --- | --- | --- | --- |
| Quick mode | review does not run | - | - |
| **Medium** | A, B, C, D, G | only if the diff touches a dependency | 10 findings |
| **Large** | A, B, C, D, E, F, G | yes | 20 findings |
| **Complex** or security trigger | all, plus local reproduction of every `critical` | mandatory | 25 findings |

Over budget means prioritize by severity and fold the overflow into existing
findings as additional locations, not file a 40-item report.

---

## Process

### 0. Resolve scope and calibrate

Determine the feature and the round. List `.pulse/specs/features/<feature>/reviews/`;
the next round is the highest existing `NNN` plus 1.

**Calibrate from the history that exists.** Read every prior round in that
directory and count how many findings were triaged `invalid`. Above **30%**,
withhold passes E and F from this review until the rate drops. A reviewer that
cries wolf loses the subjective passes — that is where noise concentrates. With
no prior round, run everything the auto-sizing table allows.

Read, when they exist: `PRD.md`, `TECHSPEC.md`, `tasks.md`, `surface.md`,
`threat-model.md`, plus `.pulse/specs/codebase/TESTING.md`, `CONVENTIONS.md` and
`CONCERNS.md`. A finding inside a component already flagged in `CONCERNS.md`
moves up one severity.

Scope the diff. Classify each changed file as **core** or **mechanical**
(generated code, lockfiles, snapshots, vendored deps, build output); mechanical
files are skipped and listed. Detect moved code: 3+ consecutive lines deleted in
one place and added identically elsewhere is a move, not new code.

If the diff is large, partition it by the task boundaries that produced it and
review each partition against its task's contract. When it cannot be partitioned
and still exceeds what a complete read honestly covers, **say so in the TL;DR and
recommend splitting the delivery**. A review that silently degrades to sampling
certifies nothing.

If no round 1 exists, this is round 1: run the full process. If one exists, read
[convergence.md](convergence.md) and follow it instead.

### 1. Deterministic ladder

Run the project's own lint, type check, and tests focused on the changed files
(look at `package.json` scripts, `Makefile`, `pyproject.toml`, CI config, or
`.pulse/specs/codebase/TESTING.md`). Record the verbatim numbers. Findings these
tools produce are out of scope.

Then seed Pass G by scanning the diff for bypass markers:

```
eslint-disable   biome-ignore    @ts-ignore    @ts-expect-error
# noqa           # type: ignore  pylint: disable    rubocop:disable
@SuppressWarnings    nolint      pragma: no cover
.skip  .only  xit  fit  @pytest.mark.skip  t.Skip
--no-verify   InsecureSkipVerify   verify=False   rejectUnauthorized: false
```

Hits are **candidates** for Pass G, never findings: a suppression carrying a
justification and an issue link is acceptable; a naked one is not. Judge every
hit, and then look for what this list cannot see.

If the repo has no such tooling, or the sandbox will not run a command, note it
in **Checks rodados** and move on. Do not install anything, and do not claim a
check ran when it did not.

### 2. Research external surfaces

Follow the Knowledge Verification Chain: codebase first, then project docs, then
official documentation, then flag as uncertain. Never assert how a dependency
behaves from memory.

**Every URL consulted goes in the Log de pesquisa**, with the claim it supports
or refutes. A source that killed a candidate finding belongs there too; a
documented non-finding is evidence of diligence and saves a whole round.

If the diff touches no external surface, write that in the log.

### 3. Review passes

**Read [passes.md](passes.md) now.** Run only the passes Step 0 allows.

| | Pass | Looks for |
| --- | --- | --- |
| A | Contract | requirements, EARS acceptance criteria, traceability, mission fit, public surface |
| B | Test parity | every assigned test ID implemented and asserting the contracted behavior |
| C | Correctness | broken invariants, data-losing failure paths, concrete concurrency hazards |
| D | Security | high-confidence exploitability, newly introduced, threat model as input |
| E | Structure | code judo, file size, spaghetti growth, canonical layer, boundaries |
| F | AI slop | comments that restate code, defensive wrappers, speculative abstractions |
| G | Bypasses | suppressions, dodged tests, duplication, magic values, gambiarras |

Each pass produces candidates: claim, tentative severity, evidence pointer.
Generation optimizes for recall.

### 4. Verification

Verification optimizes for precision. For every candidate:

- Re-read the actual code at the cited location and confirm the claim holds.
  **Copy the line verbatim** into the evidence entry.
- Re-apply the exclusion lists in [severity.md](severity.md).
- Deduplicate by root cause across passes. One finding per distinct problem,
  listing the other affected locations in its body. Never N findings for N files
  with one cause.
- Reproduce when feasible. A `critical` that can be demonstrated inside the
  repo's own test harness gets `repro` evidence. **If reproduction was feasible
  and failed, the finding dies**, whatever your reading of the code said.
- Assign severity conservatively. A `critical` you are not certain of is a `high`
  phrased as a question.
- **Low risk is not false positive.** Kill for lack of evidence; downgrade for
  lack of impact. Never conflate the two.

### 5. Write the round file

**Read [round-file.md](round-file.md) and [comment-voice.md](comment-voice.md)
now.** Write exactly one file:

```
.pulse/specs/features/<feature>/reviews/round-001.md
```

In a quick task: `.pulse/specs/quick/NNN-slug/reviews/round-NNN.md`. Outside
both: `.pulse/reviews/NNN-slug/round-NNN.md`.

No findings means no file. Report a clean review and stop; do not create an empty
round.

### 6. Self-check (MANDATORY)

There is no script to run this for you, so run it yourself, by reading the file
you just wrote against [round-file.md](round-file.md). Every box below is a
rejection, not a suggestion:

1. Every `internal` citation: open the file, confirm the line exists, confirm the
   quoted text matches what is on disk. One mismatch and the finding comes out.
2. Every finding has `Local`, `Pass` and `Evidência`. Pass A has `Requisito`,
   Pass B has `Teste`, Pass E has `Âncora`.
3. `critical` carries a `repro` or two distinct `internal` references. `high`
   carries at least one evidence entry.
4. No Pass E finding is `critical` — the cap is `high`.
5. `Tipo: duplicação` carries two distinct internal locations.
6. Finding count is within the budget for the scope.
7. `counts` in the frontmatter matches the findings actually in the file, and
   `verdict` is **derived** from `counts` by the table in [severity.md](severity.md).
8. At most 5 detailed `low`; the overflow is a count in `## Excedente de low`.
9. Nothing from the banned list in [comment-voice.md](comment-voice.md) survived.

Fix every violation and re-check. A round file that fails its own check is not a
round file — rewrite it before presenting anything.

### 7. Report

Present to the user: the verdict, the counts by severity, the round file path,
and the blocking findings. Nothing is posted anywhere. The user decides what
happens next — including deciding that nothing gets fixed in this run.

---

## Severity and Verdict

| Severity | Definition | Effect |
| --- | --- | --- |
| `critical` | security, data loss, crash, race on a hot path, incorrect money | blocks Merge layer |
| `high` | wrong behavior vs spec, user-visible reliability or performance defect | blocks Merge layer |
| `medium` | maintainability, non-blocking coverage gap | follow-up |
| `low` | naming, docs, optional cleanup. At most 5 detailed; overflow is counted | none |
| `pre-existing` | defect the change did not introduce. Summary only, no line anchor | none |

`verdict` is derived, not chosen: any `critical` or `high` open (current or
carried over) means `changes-requested`; only `medium`/`low` means
`approved-with-followups`; nothing means `approved`.

Full definitions, security exclusions, and precedents: [severity.md](severity.md).

**Approval bar:** approve as soon as the change definitely improves overall code
health, even if imperfect. Unresolved `low` never blocks approval. Withholding
approval to extract polish beyond the severity table is scope creep by the
reviewer.

---

## Author != reviewer

Pulse already guarantees the isolation this phase needs: every step runs in its
own session, so the agent that wrote the code is not the agent reviewing it, and
you inherit no implementation notes from it. Use that. Re-derive the contract
from `PRD.md` and the diff rather than from any narrative about what was built.

Findings that are deterministic by nature go to **Promover a convenção**, and
from there into `STATE.md` as a confirmed lesson and `CONVENTIONS.md` as a rule.
Reviews get cheaper every cycle.

Git stays with the user. Approving a review authorizes nothing.

---

## Error Handling

- Feature directory missing: stop and report it.
- `PRD.md` missing: warn that contract passes cannot run, skip passes A and B,
  proceed with a code-only review and say so in the TL;DR.
- Lint or test ladder cannot run: note the failure in **Checks rodados** and
  proceed. Do not skip the review because tooling broke; acknowledge that the
  overlap filter could not be applied.
- `git diff` unavailable or useless (no base, detached state): fall back to the
  file list this run wrote, and say in the TL;DR that scope came from artifacts
  rather than from a diff.
- Round 4 requested: refuse. Report what is still open and ask the user to waive
  it or defer it to `STATE.md`.

# passes.md

# Review Passes

Load at Step 3. Run only the passes Step 0 allows for this project and the
auto-sizing table allows for this scope.

Global rule: generation optimizes for recall, verification (Step 4) optimizes for
precision. Flag freely here; kill freely there.

Order matters. A and B first: in a spec-driven flow, code that is perfect and
implements the wrong thing is the expensive failure, and no diff-only review
catches it.

---

## Pass A: Contract

Requires `PRD.md`; skip and say so when absent.

**Requirements.** Cross-check the implementation against every requirement and
EARS acceptance criterion. Flag anything missing, partially implemented, or
implemented differently than specified. Severity follows the gap: `critical` when
a core behavior is absent, `high` when behavior deviates, `medium` when a
specified edge case is unhandled.

**Mission fit.** When `PRD.md` states a motivating problem, verify the delivered
work actually solves it and name the slice that does. Checking the implementation
against the spec alone cannot catch a spec that drifted from its own mission. A
design decision that narrowed or deferred the motivating problem without the
user's recorded sign-off is itself a finding, at the severity of the gap it
created.

**Public surface.** When `surface.md` exists, a change to the public CLI, API,
SDK, or UI contract that is not reflected there is `high`. Users and agents type
against that file.

**Traceability.** Requirement IDs in the spec with no implementation and no
recorded deferral are findings.

Every finding here carries `Requisito:` with an ID that exists in `PRD.md`.

Do not flag: requirements the spec explicitly deferred, or behavior the Ambiguity
Ledger marks unresolved. Those belong to PRD, not review.

---

## Pass B: Test parity

Requires the task-level test assignments in `tasks.md`, or the coverage matrix in
`.pulse/specs/codebase/TESTING.md`; skip when neither exists.

Verify that every test ID assigned in completed tasks is implemented in the suite
**and asserts the behavior the catalog specifies**. A missing case is a finding.
A hollow one that exists and asserts nothing meaningful is the same finding: the
contract is unverified either way. Severity follows the impact of the behavior
left unproven.

Also flag: tests that assert mocks instead of behavior, and tests whose name
claims a case the body does not exercise.

A row in **Deferred test coverage** is a declared gap, not a missing test: the
implementation phase writes unit tests only. Flag it only when the deferral has
no reason and no named boundary.

Every finding carries `Teste:` with an ID that exists in `tasks.md` or `TESTING.md`.

Do not flag: missing coverage for behavior the catalog does not claim. That is a
spec gap, and it belongs in the ledger, not here.

---

## Pass C: Correctness and logic

Flag only what you can trace as a concrete failing path, **naming the input or
state that triggers it**.

Look for: broken invariants (a contract violated by a new caller or a changed
callee), unhandled failure paths that lose data or leave state partial,
off-by-one and boundary errors on real boundaries, async ordering bugs (missing
`await` where sequence matters, floating promises whose failure disappears),
concurrency hazards that are concrete (shared mutable state with an actual
interleaving, not a theoretical one), error swallowing that hides a failure the
caller must know about, and resource lifecycles that leak on the error path.

Do not flag: hypothetical inputs the system cannot produce, missing handling for
states upstream code makes impossible, or "what if someone later" speculation.
**If you cannot name the triggering input, it is not a finding.**

---

## Pass D: Security

Bar: above 80% confidence of real exploitability, and only for issues this change
introduced. Pre-existing security issues found along the way become
`pre-existing` summary entries.

When `threat-model.md` exists, it is the input: check the implementation against
the trust boundaries and mitigations it names. A mitigation the model requires
and the code omits is `critical`.

Categories: injection (SQL, command, template, NoSQL, XXE, path traversal),
authentication and authorization (bypass logic, privilege escalation, session
flaws, JWT misuse), crypto and secrets (hardcoded credentials, weak algorithms,
broken randomness, certificate validation bypass), data exposure (PII or
high-value secrets in logs, sensitive data in error messages or URLs), unsafe
deserialization, and SSRF where the attacker controls host or protocol.

The hard exclusion list and the precedents are in [severity.md](severity.md).
Apply them before writing anything.

---

## Pass E: Structure and maintainability

The ambitious pass, and the one most likely to generate noise. Two guardrails:
it **cannot produce `critical`**, and every finding needs an `Âncora:` field
naming either a documented convention from `CONVENTIONS.md` or a concrete metric.
"This could be simpler" without an anchor does not ship.

Within those guardrails, do not stop at "this could be a bit cleaner." Search for
the restructuring that preserves behavior while making the implementation
dramatically simpler. When there is a path to delete complexity instead of
rearranging it, push for that path.

**Code judo.** For every meaningful change, ask whether a reframing exists that
makes whole branches, helpers, modes, or layers disappear. A refactor that moves
complexity around without reducing the number of concepts a reader must hold is
not an improvement.

**File size.** A change pushing a file from under 1000 lines to over 1000 is a
finding on quality grounds. Prefer extracting helpers, subcomponents, or modules.
Waive for a compelling structural reason with the file still clearly organized.

**Spaghetti growth.** New ad-hoc conditionals, scattered special cases, and
one-off branches inserted into unrelated flows are design problems, not style
nits. Push the logic behind a dedicated abstraction, state machine, or module
instead of tangling an existing path.

**Boring over magic.** Generic mechanisms hiding simple data-shape assumptions,
thin wrappers, identity abstractions, pass-through helpers that add indirection
without buying clarity.

**Types and boundaries.** Unnecessary optionality, `any`, and cast-heavy code
where a clearer type boundary could exist. A silent fallback papering over an
unclear invariant signals the boundary should be explicit.

**Canonical layer and reuse.** Feature logic leaking into shared paths,
implementation details leaking through APIs, bespoke helpers duplicating an
existing canonical utility. Push code to the module that already owns the concept.

Remedies, in rough order of ambition: delete a layer of indirection rather than
polishing it; reframe the state model so conditionals disappear instead of
getting centralized; move the ownership boundary so the feature becomes a natural
extension of an existing abstraction; turn special cases into a simpler default
flow; replace condition chains with a typed model; split a large file into
focused modules; separate orchestration from business logic; collapse duplicate
branches; reuse the canonical helper.

Output priority: structural regressions, then missed simplifications, then
branching growth, then boundary and type problems, then file size, then
legibility. **Suppress low-value nits entirely when anything higher exists.**

Never settle for "maybe rename this" when the real issue is structural.

---

## Pass F: AI slop and useless comments

Agents dirty code, and slop compounds: every useless comment trains the next
reader, human or agent, to add more.

**Comments.** The golden rule is that a comment must explain WHY (a constraint, a
trade-off, a non-obvious reason) or a genuinely non-obvious HOW. A comment
narrating WHAT the next line does is a deletion, not a style preference.

Flag: comments restating the code (`// increment counter`), changelog narration
(`// changed from X to Y`, `// new function added`), docstring bloat on trivial
private helpers, commented-out code (delete it, git remembers), TODO comments
with no owner or issue reference, section banners in short files, and comment
style inconsistent with the surrounding file.

**Code slop.** Defensive try/catch on trusted internal paths where failure should
propagate, casts used only to silence the type checker, deep nesting fixable with
early returns, over-defensive null checks against states upstream code makes
impossible, dead branches and parameters added "for later", speculative
abstractions with a single implementation, configuration for values that never
change.

Guardrail: suggested cleanups keep behavior unchanged unless fixing a clear bug,
and prefer minimal focused edits over broad rewrites.

---

## Pass G: Bypasses, duplication, and gambiarras

Catches the workaround economy: code that dodges a check instead of satisfying
it, re-implements what exists instead of reusing it, or ships a hack disguised as
a solution. The marker scan from Step 1 seeds this pass; judge every hit, and
look for what a marker list cannot see.

**Bypasses.** Suppression directives without an adjacent justification and issue
link (`eslint-disable`, `@ts-ignore`, `# noqa`, `# type: ignore`,
`pylint: disable`, `rubocop:disable`, `@SuppressWarnings`, `nolint`,
`biome-ignore`), tests dodged to make CI pass (`.skip`, a stray `.only`, `xit`,
`@pytest.mark.skip` without reason), assertions deleted or loosened so a failing
test goes green, broad exception swallowing, TLS verification disabled,
type-checker escapes papering over a real nullable, hooks bypassed with
`--no-verify`, and environment-based dodges that make code behave differently
just to pass a check.

The rule: a suppression is acceptable only when it carries WHY plus an issue
reference next to it. A naked suppression is `low` or `medium`. A bypass hiding a
real defect inherits the severity of the defect it hides, up to `critical` on
money, auth, or data paths.

**Duplication.** Copy-pasted blocks, a near-duplicate of an existing canonical
helper, the same validation or regex or constant re-implemented elsewhere,
parallel type definitions that will drift. Tag the finding `Tipo: duplicação`,
which requires **two distinct internal locations**. One location is a suspicion,
not evidence. The fix suggestion always names the canonical home.

**Gambiarras.** Magic numbers or strings encoding a business rule without a name,
sleep or timeout used as synchronization (a delay is not a lock), retries
wrapping a deterministic bug, reflection to reach private internals,
string-typed logic where a type or enum exists, hand-edits to generated files,
hardcoded URLs or environment assumptions, and "temporary" workarounds with no
owner, no issue, and no ceiling.

A deliberate, labeled simplification is not a gambiarra: "skip X, add it when Y"
with an owner and an issue is an engineering decision. The difference is the
label. Unlabeled, the same code is a finding, because the next reader cannot tell
a chosen ceiling from a missed one.

# severity.md

# Severity, Verdict, and Exclusions

## Levels

### `critical`

Security flaws, data loss, crashes, undefined behavior, races on a hot path,
incorrect money. Issues that cause production incidents or compromise user data.

Examples: authentication bypass, injection, nil dereference on a hot path,
unbounded goroutine leak, writing secrets to logs, a required threat-model
mitigation absent.

**Blocks the Merge layer.** Requires either a `repro` or two distinct `internal`
evidence references, because this is the severity whose false positives are
expensive.

### `high`

Wrong behavior versus the spec, or a user-visible reliability or performance
defect. Needs fixing before merge.

Examples: a requirement implemented differently than specified, logic error
returning wrong results, missing transaction rollback, an error silently
swallowed on a critical path, a public surface change not reflected in
`surface.md`.

**Blocks the Merge layer.** Requires at least one evidence entry.

### `medium`

Maintainability concerns, code smells, non-blocking coverage gaps, non-idiomatic
patterns that degrade long-term health.

Examples: duplicated logic across modules, a function with deep nesting well past
the project's norm, a missing test for an error branch, an interface with a
single implementation.

### `low`

Minor improvements, documentation gaps, naming. At most **5 detailed per round**;
the overflow becomes a count in `## Excedente de low`.

### `pre-existing`

A defect this change did not introduce. Summary only, never anchored to a line,
never blocking. Recording it is how it reaches the backlog without hijacking this
review.

## Severity modifiers

- A finding inside a component already flagged in
  `.pulse/specs/codebase/CONCERNS.md` moves **up one level**. Known-fragile code
  earns less benefit of the doubt.
- A Pass E (structure) finding is capped at `high`. Architectural taste does not
  block a merge on its own.
- A bypass that hides a real defect inherits the severity of the defect it hides.

## Verdict

Derived, never chosen. Recompute it from `counts` before writing the frontmatter.

| Condition | Verdict |
| --- | --- |
| any `critical` or `high` open, current round or carried over | `changes-requested` |
| only `medium` or `low` | `approved-with-followups` |
| nothing | `approved` |

**Approval bar.** Approve as soon as the change definitely improves overall code
health, even when imperfect. Perfect code does not exist, only better code.
Unresolved `low` never blocks approval. Withholding approval to extract polish
beyond this table is scope creep by the reviewer.

## Security: hard exclusions

Never report these. They are the categories that generate volume without changing
a merge decision.

1. Denial of service or resource exhaustion of any kind (memory, CPU, file
   descriptors, rate limiting).
2. Secrets stored on disk when otherwise secured. That is a process concern.
3. Missing input validation on fields with no demonstrated security impact.
4. Missing hardening. Absent best practices are not vulnerabilities; only
   concrete exploitable flaws are.
5. Theoretical races and timing attacks. Only a concretely problematic race.
6. Outdated dependencies in general. One exception: Step 2 research surfaced a
   real advisory affecting the exact version this change pins, in which case
   report it with the advisory URL as `external` evidence.
7. Memory-safety issues in memory-safe languages. Do not report buffer overflows
   where the language makes them impossible.
8. Test-only files and fixtures.
9. Log spoofing via unsanitized input in log lines.
10. SSRF where the attacker controls only the path, not host or protocol.
11. User-controlled content flowing into AI prompts.
12. Regex injection and regex-based denial of service.
13. Findings in documentation files.
14. Missing audit logs.

## Security: precedents

Assume these. An argument that contradicts one of them needs external evidence to
stand.

1. Environment variables and CLI flags are trusted; an attack requiring control
   of them is invalid.
2. UUIDs are unguessable and need no validation.
3. Logging URLs is safe. Logging high-value secrets in plaintext is a finding.
4. React and Angular escape output by default. Only flag XSS through
   `dangerouslySetInnerHTML`, `bypassSecurityTrustHtml`, or an equivalent unsafe
   escape.
5. Low-signal web issues (tabnabbing, XS-Leaks, prototype pollution, open
   redirects) only at extreme confidence with a traced exploit path.

## Calibration

Compute the share of findings this project has triaged `invalid` across the
rounds already in `reviews/`. Above **30%**, passes E and F are withheld from the
next review until the rate drops.

This is deliberate. A filter that produces noise loses reach automatically,
without anyone having to notice and intervene. The two passes withheld are the
taste-based ones, which is where noise concentrates.

# round-file.md

# Round File Format

One markdown file per round. This is the only artifact the review produces.

```
.pulse/specs/features/<feature>/reviews/round-001.md
                                        round-002.md
                                        round-003.md
```

Next round = highest existing NNN + 1. **No findings means no file.** Never
create an empty round.

In a quick task: `.pulse/specs/quick/NNN-slug/reviews/round-NNN.md`.

Outside both (reviewing an arbitrary diff):
`.pulse/reviews/NNN-slug/round-NNN.md`.

## Why one file

Remediation is sequential by severity anyway, and one file per round deletes
three whole classes of check (cross-file frontmatter agreement, matching round
numbers, matching timestamps) because they collapse into single fields.

## Three format rules that matter

1. **The heading carries ID, severity, and status.** `### F1 · critical · pending`.
   Trivially parsed, and remediation edits one token to change state.
2. **Status has a single source.** It lives in the heading only, never in the
   index table. A status column would mean two edits per triage and a
   reconciliation check.
3. **IDs are stable forever.** F1 is F1 across every round. This is what makes
   the Resolução table work without an external ledger. A new finding takes a new
   number, never a recycled one.

## Template

````markdown
---
feature: checkout-v2
round: 1
created_at: 2026-10-02T14:30:00Z
scope: large
base: 4f2a1c9
head: a0f271a
verdict: changes-requested
counts: { critical: 1, high: 1, medium: 0, low: 0, pre-existing: 0 }
---

# Review Round 001 — checkout-v2

## TL;DR

One to three sentences: what the change does and the verdict with its reason.
Must contain the verdict token verbatim.

## Índice

| ID | Sev | Local | Resumo |
|---|---|---|---|
| F1 | critical | `src/billing/invoice.ts:142` | Divisão sem guarda de lista vazia |
| F2 | high | `src/checkout/session.ts:88` | RF-04 não implementado |

### F1 · critical · pending

- **Local:** `src/billing/invoice.ts:142`
- **Pass:** C
- **Evidência:**
  - `internal` `src/billing/invoice.ts:142` → `const avg = total / items.length`
  - `repro` `pnpm test invoice -t "empty cart"` → `AssertionError: expected NaN`
- **Triagem:**

`applyDiscount` divide por `items.length` sem guarda de lista vazia. Carrinho
esvaziado no meio do checkout produz `NaN` no total. Fix: guard clause retornando
`0` antes da divisão, 2 linhas. Chamadores em `src/checkout/session.ts:88` e
`src/api/cart.ts:31` passam listas potencialmente vazias.

### F2 · high · pending

- **Local:** `src/checkout/session.ts:88`
- **Pass:** A
- **Requisito:** RF-04
- **Evidência:**
  - `internal` `src/checkout/session.ts:88` → `return { id: cart.id }`
- **Triagem:**

RF-04 exige total zerado quando o carrinho esvazia. `startSession` não propaga o
estado de carrinho vazio, então o requisito não tem implementação.

## Resolução

_(round 2+ only; every previous ID appears here)_

| ID | Status | Nota |
|---|---|---|
| F1 | resolved | guard clause em `src/billing/invoice.ts:140` |
| F2 | open | sem mudança no caminho de RF-04 |

## Promover a convenção

Deterministic findings from this round, each with a one-line sketch of how to
lint it or which `CONVENTIONS.md` rule it becomes. Write `nenhum` if empty.

## Log de pesquisa

URLs consulted, one per line, with the claim each supports or refutes. Sources
that killed a candidate finding belong here too. Write `nenhuma superfície
externa tocada` if that is the case.

## Checks rodados

Deterministic ladder results, verbatim numbers, no interpretation: test counts,
linter and type checker outcome, bypass scan candidate count. A check that could
not run is recorded as "não rodou" with the reason, never omitted.

## Arquivos pulados

Mechanical and generated files excluded from review.

## Excedente de low

`N findings low adicionais não detalhados` when the cap was hit. Omit otherwise.
````

## Field reference

### Frontmatter

| Key | Rule |
| --- | --- |
| `feature` | feature slug |
| `round` | integer, must match the filename |
| `created_at` | RFC3339 UTC |
| `scope` | `medium`, `large`, or `complex`; drives the finding budget |
| `base`, `head` | revisions the diff spans |
| `verdict` | `approved`, `approved-with-followups`, `changes-requested`. Derived, not chosen |
| `counts` | per-severity totals; must match the actual findings |

### Heading

`### F<n> · <severity> · <status>`

- severity: `critical`, `high`, `medium`, `low`, `pre-existing`
- status: `pending`, `valid`, `invalid`, `unresolved`, `blocked`, `resolved`,
  `declined`, `declined-accepted`
- The separator is a middle dot (`·`, U+00B7)

### Fields

| Field | When | Rule |
| --- | --- | --- |
| `Local` | always | `` `path:line` ``. `pre-existing` uses `` `path` `` with no line |
| `Pass` | always | one of A-G |
| `Requisito` | Pass A | requirement ID that exists in `PRD.md` |
| `Teste` | Pass B | test ID that exists in `tasks.md` or `TESTING.md` |
| `Âncora` | Pass E | the documented convention or concrete metric backing the claim |
| `Tipo` | optional | `duplicação` forces two distinct internal locations |
| `Introduzido por` | round 2+ | the previous finding ID whose fix created this one |
| `Evidência` | see below | nested list |
| `Triagem` | always | empty while `pending`; required reasoning once the status changes |
| `Fix` | written by remediation | `` `path:line` `` or test id proving the repair |

### Evidence

```
  - `internal` `path:line` → `the exact line as it appears on disk`
  - `external` `https://official.example/docs#anchor` → `the claim it supports`
  - `repro` `the command that demonstrates it` → `the observed result`
```

- `internal`: re-open the file, check the line exists, and match the quote
  against it. A mismatch kills the finding. **This is the anti-hallucination
  check** and the quote is not optional.
- `external`: must be an https URL and must also appear in Log de pesquisa.
- `repro`: both the command and the observed result are required.

Bars: `critical` and `high` need at least one entry. `critical` additionally
needs either a `repro` or two distinct `internal` references.

### Body

The prose after the fields. Caps: 900 characters for everything except `low`,
which gets 400. If the explanation outgrows the cap, the comment is trying to do
the fix's job. See [comment-voice.md](comment-voice.md).

## Section headings

Pick Portuguese or English and keep the file consistent:

| Portuguese | English |
| --- | --- |
| `## Resolução` | `## Resolution` |
| `## Promover a convenção` | `## Promote to convention` |
| `## Log de pesquisa` | `## Research log` |
| `## Checks rodados` | `## Checks run` |

`## TL;DR` is required in both.

# comment-voice.md

# Comment Voice

Load at Step 5, before writing the TL;DR or any finding body.

The body is read by someone who wrote the code in good faith and is
context-switching to process your feedback. Every wasted word is a tax on them.

## Shape

1. **First line states the problem and where.** Not context, not a wind-up. The
   location closes the first line.
2. **The fix comes second, as the laziest fix that works.** Climb this ladder and
   stop at the first rung that holds: a helper or pattern that already exists in
   this repo, then the standard library, then a native platform feature, then an
   already-installed dependency, then one line, then minimal new code. Never
   suggest a new dependency for what three lines cover.
3. **Root cause, not symptom.** If the bug lives in a shared function, the fix is
   one guard there, not a patch in the caller the diff happens to touch. Say so,
   with the callers as evidence.
4. **Multi-step fixes get numbered steps**, each one bounded, five maximum.
   One-step fixes get one sentence.
5. **Deliberate simplification is labeled.** When suggesting something be cut,
   use "skip X, add it when Y" so the author knows the ceiling was considered,
   not missed.
6. **Questions end with the question.** When the finding is a question, the last
   line is the ask, concrete and answerable.
7. **Length.** Most bodies fit in four lines. Caps: 900 characters, or 400 for
   `low`. If the explanation outgrows the cap, the comment is trying to do the
   fix's job.

## Empathy without small talk

Empathy means respecting the author's time, competence, and intent. It never
means praise padding.

- **Genuine questions when the author may know something you do not.** "Can this
  move behind its own abstraction?" beats "this is wrong" whenever local context
  could justify the code. When the evidence is conclusive, state it plainly
  instead; fake uncertainty is its own disrespect.
- **Acknowledge a real trade-off in one clause, then make the ask.** "O retry
  mantém o caminho feliz simples; a terceira falha descarta o evento em silêncio.
  Dá para mandar para uma dead-letter?"
- **Never imply carelessness.** The code has a gap. Describe the gap.
- **Never lecture.** Do not explain concepts the author demonstrably knows; their
  own diff is proof of what they know.
- **No praise comments.** A positive observation earns at most one factual line
  in the TL;DR. Inline praise is noise wearing a smile.
- **Matter-of-fact on severity.** A `critical` is stated calmly with its
  evidence. No alarm words, no drama.

## Banned

- Em and en dashes.
- Exclamation marks. Code spans are exempt.
- Openers that announce instead of stating: "Let me", "I'll", "Looking at",
  "Sure", "Vou", "Deixa eu", "Primeiramente", "Olhando".
- Filler and closers: "hope this helps", "let me know", "feel free", "as you can
  see", "thanks for", "espero que ajude", "fique à vontade", "vale ressaltar",
  "vale a pena notar".
- Blame: "you forgot", "you missed", "você esqueceu", "obviously", "obviamente".
- Praise padding: "great job", "nice work", "kudos", "ótimo trabalho", "bom
  trabalho", "parabéns".
- Hedging stacks: "I think maybe", "perhaps consider", "you might want to", "it
  would be beneficial".
- AI-tell vocabulary: "delve", "seamless", "tapestry", "testament to".
- The "not just X but Y" construction, in English and Portuguese.

The list is deliberately short. Words with legitimate technical use (`simply`,
`leverage`, `landscape`, `note that`) are not banned, because a rule that fails
on correct prose costs more in rework than the noise it prevents.

## Language

Finding bodies and the TL;DR are written in Portuguese, like every artifact this
pipeline produces. Write it natively and correctly, with full diacritics;
plain-ASCII degraded Portuguese is a defect, not a style. Code identifiers,
quoted strings, error messages, and tool output stay verbatim. The ban list
applies in every language.

## Bad, then good

**Blocker.** Bad: "Great work on this refactor! I noticed that you might want to
consider adding a check here, because if the items array happens to be empty this
could potentially cause a division by zero, which would obviously be problematic
in production!"

Good: "`applyDiscount` divide por `items.length` sem guarda de lista vazia
(src/billing/invoice.ts:142). Carrinho esvaziado no meio do checkout produz `NaN`
no total. Fix: guard clause retornando `0` antes da divisão, 2 linhas. Chamadores
em src/checkout/session.ts:88 e src/api/cart.ts:31 passam listas potencialmente
vazias."

**Structural.** Bad: "This works but I feel like maybe the architecture could be
improved somehow? Perhaps consider refactoring this at some point."

Good: "Isso adiciona um terceiro booleano `mode` atravessando `Renderer`
(src/render/core.ts:210, :245, :301). As três flags codificam uma máquina de
estados com cinco estados válidos. Dá para trocar por um `RenderState` tipado? Os
branches em :245 e :301 colapsam no dispatcher e as combinações inválidas deixam
de existir."

**Useless comment.** Bad: "Consider whether this comment is needed."

Good: "O comentário em src/queue/worker.ts:57 repete a linha abaixo dele.
Deletar; o código já diz isso. Mesmo caso em :74 e :91."

**Claim question.** Bad: "Are you sure this fixes the race condition? It seems
hard to verify."

Good: "A descrição diz que isso corrige a corrida no worker pool, e nenhum teste
cobre o interleaving (nada em tests/ toca concorrência de `WorkerPool`). Qual
teste falha no main e passa aqui? Um teste falhando-depois-passando fixa a
correção; sem ele, um refactor futuro reintroduz a corrida em silêncio."

## Pre-write check

Per finding: the first line names problem and location; a fix or an answerable
question is present; nothing banned slipped in; reading only the first and last
lines tells the author what is wrong and what to do.

# convergence.md

# Convergence Contract

The failure mode this document exists to kill: the review that never ends. Fix,
find, fix, find, always something new, half of it nonsense. The cure is not
discipline, it is arithmetic.

## The loop ends on a review, never on a fix

review → fix → review → fix → review. A fix is never the last word: nobody has
looked at a repair yet when it lands, so every fix pass sends the run back here.
Only a review can say the merge layer is finished — by finding nothing left to
correct, or by being round 3, the last one, after which no fix runs.

A later review is the same role with a different job: it comes back to check
that the repair held and that nothing `critical` is still open.

Anything still open when round 3 closes is reported to the user, who waives it,
defers it to `STATE.md`, or starts a new run.

That is why Non-Negotiable 2 is not negotiable: **round 1 is the whole review.**
Round 2 cannot take new ground — it only accepts what a fix broke — so a finding
held back in round 1 is forfeited, not postponed.

## The one rule that ends the pain

**The merge gate is evaluated against the frozen round-1 set.**

The Merge layer unblocks when every `critical` and `high` from **round 001** is
`resolved`, `invalid`, or waived by the user. A discovery in round 2 or 3 does
not reopen it.

This decouples "can I merge?" from "did the reviewer stop finding things?" The
second question has no answer, which is exactly why it must never gate anything.

## Round 1: the freeze

Round 1 is exhaustive and it is the whole review. Everything visible is raised
now, in one file.

Holding a finding for a later round is forbidden. Code visible in round 1 and not
flagged then is **forfeited permanently**; the reviewer eats the miss. This is
not a concession, it is the mechanism: a reviewer who can always add later has no
reason to be thorough now.

One exception to volume, not to scope: do not stack `low` findings on code a
structural finding will rewrite. Note "nits withheld on lines the structural fix
rewrites" in the TL;DR.

Budget by scope: 10 findings for `medium`, 20 for `large`, 25 for `complex`. Over
budget means prioritize by severity and fold the overflow into existing findings
as additional locations. It does not mean file a 40-item report.

## Round 2: resolution, plus a narrow door

Exactly two jobs.

**1. Resolution check.** Every ID from every previous round appears in the
`## Resolução` table with a state:

| State | Meaning |
| --- | --- |
| `resolved` | fixed; the note cites the evidence |
| `open` | still present |
| `invalid` | triaged as not a real problem |
| `declined` | the author declined with a reason, and you are re-arguing |
| `declined-accepted` | the author's reason held; dropped permanently |
| `waived` | the user accepted the risk |
| `deferred` | moved to `STATE.md` deferred ideas |

A missing ID is a defect in the round file. This is a checklist verification, not
a fresh hunt.

**2. New findings through a narrow door.** At most **3**, all `critical`, and
each one must carry `Introduzido por:` naming the previous finding whose fix
created it.

That field is the whole design. It is not "new blockers anywhere", which is the
leak that lets the loop restart; it is "the fix broke something". A `critical`
that was always there and you missed in round 1 does not qualify. You missed it.
That is the deal.

## Round 3: the last word

Round 3 is the last review, and no fix runs after it — whatever it leaves open
reaches the user, not another repair. It takes no new findings at all, and its
Resolução table must bring **every** ID to a terminal state: `resolved`,
`invalid`, `declined-accepted`, `waived`, or `deferred`. An ID still `open` has
to be waived or deferred, and the reply says plainly which ones the person still
has to decide.

## Round 4: does not exist

Refuse it. By round 3 everything is fixed, waived, or in the backlog.

This is the escape valve, and it matters: **the loop terminates into `STATE.md`,
not into another round.** A finding that nobody wants to fix today is a deferred
idea with a home, not an open thread that keeps a branch alive for a week.

## Declined findings

When the author declines with a reason, first consider that they are closer to
the code and may be right. If the reasoning holds from a code-health perspective,
record `declined-accepted` and drop it permanently.

If it does not hold, re-argue **once**, with new evidence. Once. An ID that was
`declined` in a previous round cannot be `declined` again, so the second attempt
must end in `declined-accepted` or `resolved`.

Still disagreeing after that: say the disagreement is moving out of the review,
and stop. Review threads do not resolve philosophy.

## The shrinking sequence

| Round | New findings | Where | Allowed severity |
| --- | --- | --- | --- |
| 1 | up to budget | full scope | all |
| 2 | at most 3 | only what a previous fix introduced | `critical` only |
| 3 | 0 | - | - (manual only) |
| 4 | does not exist | | |

Monotonic. Checkable. Not a matter of judgment.

## What this does not guarantee

No check verifies that a finding is conceptually right. A `critical` with a real
citation, a matching quote, and a failing repro can still be a misreading of the
invariant.

What is guaranteed: the set only shrinks after round 1, the merge never waits on
new discoveries, every citation exists and says what the finding claims, and a
reviewer with a high `invalid` rate loses the subjective passes automatically.

The residue is wrong judgment backed by real evidence. A human kills that with
`invalid` at triage, which feeds the calibration, which narrows the next review.
Even the residue has a feedback loop.
