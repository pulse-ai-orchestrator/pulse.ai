---
name: prd
description: Escreve PRD.md
runtime: cursor
model: Auto
permission_policy: deny_writes
---

# prd.md

# PRD

**Goal**: Capture WHAT to build with testable, traceable requirements.

Read [invariants.md](invariants.md) first. If the feature has ambiguous gray areas, trigger [discuss.md](discuss.md) inside this phase. Write every gray area to the [Ambiguity Ledger](ambiguity.md).

**Audience: the product team.** You are talking to whoever owns the product, not
to an engineer. Every question you ask in this phase must be answerable by
someone who has never opened the codebase. Technical decisions belong to Techspec
— see **Product language only** below.

**No open question survives this phase.** There is no "I assumed X". While any
gray area, doubt, or open question remains, you ask — and you keep asking, one
CLI batch per turn, until the ledger is clean. See **Clarify loop** below.

## Process

### 1. Load confirmed lessons

Read STATE.md Lessons Learned with `Status: confirmed` that match this feature's area. Skip `candidate` and `quarantined`. See [lessons.md](lessons.md).

### 2. Clarify Requirements

Thinking partner, not interviewer. Read `.pulse/specs/`, codebase, user message. Draft from what is known.

Facts you look up (Knowledge Verification Chain). Decisions you ask via [user-input.md](user-input.md).

**Must resolve before writing PRD.md:**

- **Motivating Problem** — concrete pain and the simplest end-to-end observable outcome that solves it. Slice 1 of Tasks delivers this outcome.
- Who it is for
- What success looks like
- Constraints
- Explicit out of scope

Do not park a wanted capability in Out of Scope to fit a slice budget — that needs a follow-up spec or a recorded user decision.

### 3. User Stories (P1 = MVP)

P1 is a **vertical slice**: demo-able, not backend-only. Each story independently testable.

### 4. Acceptance Criteria (EARS)

Every AC uses **EARS** and contains SHALL. One behavior per criterion. Concrete values, not "gracefully".

| Pattern | Template |
| ------- | -------- |
| Ubiquitous | The [system] SHALL [response] |
| Event-driven | WHEN [trigger] THEN the [system] SHALL [response] |
| State-driven | WHILE [state] the [system] SHALL [response] |
| Optional-feature | WHERE [feature is present] the [system] SHALL [response] |
| Unwanted-behavior | IF [undesired condition] THEN the [system] SHALL [response] |
| Complex | WHILE [state], WHEN [trigger] the [system] SHALL [response] |

If you cannot write it as a test, rewrite it.

### 5. Gray-area sweep + ledger

Follow [ambiguity.md](ambiguity.md). Sweep the feature for behavior the product
team still has to choose. Every gray area becomes a ledger row, and every row
leaves this phase as `decided` (the product team chose) or `n/a` (the dimension
does not apply to this feature). Nothing else is a valid closing status.

The implicit-requirement sweep — idempotency, concurrency, retry, rate limits,
observability, data lifecycle, external-dependency failure, state-transition
integrity — does **not** run here. Techspec owns it ([techspec.md](techspec.md)). Do
not ask the product team about those dimensions.

What you do sweep here is the product-visible side of the same feature: what the
person using it sees, chooses, and is promised. If a technical dimension turns
out to have a user-visible consequence, ask about the consequence in product
words, never about the mechanism.

### 6. Surface and tests (conditional)

If there is a public surface, write [surface.md](surface.md) before internal design. Write [tests.md](tests-catalog.md) for Large/Complex (and Medium with a public surface).

If a [threat-model.md](threat-model.md) trigger is present, note it here; the model itself is written in Techspec.

### 7. Closure gate

Before presenting the spec:

1. Every AC has one interpretation and a precise expected outcome
2. Ledger has no `open` rows **and no `assumed` rows** — every row is `decided` or `n/a`
3. Motivating Problem is stated; P1 delivers it
4. `python3 <skill-dir>/scripts/validate_prd.py <feature>` exits 0 ([gates.md](gates.md))

Fail any of these and you are still in the **Clarify loop** — ask, do not present.

Then confirm with the user via CLI. Do not start implementation because the spec file exists.

Changing an approved spec later uses [spec-change.md](spec-change.md).

---

## Clarify loop (mandatory)

The phase runs as a loop, not a single pass. Each turn:

1. Do every bit of autonomous work you can — read the codebase, read
   `.pulse/specs/`, draft the spec, fill what the answers already settle
2. List what is still undecided
3. If **anything** is undecided, end the turn with one CLI clarify batch
   ([user-input.md](user-input.md)) and stop. No approval block this turn.
4. When the answers arrive, fold them into `PRD.md` and the ledger, then go
   back to step 1

You leave the loop only when the closure gate passes. Then, and only then, the
turn ends with the approval block instead of a clarify batch.

**A clarify batch and an approval block never appear in the same turn.** Asking
and asking-for-approval are different states; mixing them lets a doubt slip
through as approved.

**Forbidden in this loop:**

- Writing `assumed` in the ledger. An agent-chosen default is exactly the doubt
  this phase exists to remove. If you would have assumed it, ask it.
- Writing `open` and presenting anyway ("we can decide later", "TBD",
  "to be confirmed during implementation").
- Presenting the spec while a question is pending.
- Silently narrowing scope to avoid a question.
- Answering your own question with "the codebase already does X" — the codebase
  shows what *is*, not what the product team wants.

**Batch shape:** follow [user-input.md](user-input.md). Put every question you
can already see in the batch; hold one back only when its wording depends on an
answer not given yet. Lead each question with a recommended option and a
one-line rationale in product terms, so the product team can accept it in one
keystroke.

**Rounds are limited.** Pulse stops a step that keeps asking, and a retry opens a
fresh session that only knows the files on disk and the answers Pulse hands it.
Write `PRD.md`, the ledger and `context.md` from the first round and update them
after every answer. A case that only combines decisions already made follows
from them: record it as `decided`, naming those decisions, and ask it only when
they point to different outcomes. Never ask again what the prompt lists as
already answered or what the files already record as `decided`.

---

## Product language only

Every question in this phase is about the product: what the person using it
wants, sees, chooses, or is promised. If answering requires knowing the stack,
it is a Techspec question.

| Ask here (product)                                         | Never ask here (Techspec owns it)              |
| ---------------------------------------------------------- | -------------------------------------------- |
| "What should the person see when the payment fails?"        | "Do we retry with exponential backoff?"       |
| "Can two people edit the same order at once?"               | "Do we use optimistic locking or a mutex?"    |
| "For how long must a cancelled order stay visible?"         | "What TTL do we set on the cache?"            |
| "Who is allowed to approve a refund?"                       | "Do we check the role in the middleware?"     |
| "How fast does this have to feel to be usable?"             | "What is the p95 latency budget per service?" |
| "What happens to the person mid-flow if the provider is down?" | "Do we add a circuit breaker?"             |

**Banned from the wording of any question in this phase:** API, endpoint,
schema, migration, index, query, cache, TTL, queue, worker, retry, backoff,
idempotency, race condition, lock, transaction, rate limit, webhook, token,
middleware, deploy, latency budget, framework and library names, file paths,
class and function names.

The rule is about the **question**, not about your thinking. You still read the
code to know what is possible and what a change would cost — you just never make
the product team answer for it.

If a technical constraint genuinely limits the product, state it as a
consequence and let the product team choose: "Keeping the history for 5 years
would make the search noticeably slower for everyone. Keep 5 years, or 12
months?"

---

## Template: `.pulse/specs/features/[feature]/PRD.md`

```markdown
# [Feature Name] Specification

## Motivating Problem

[Pain in 1-2 sentences.] **Slice 1 outcome:** [observable end-to-end behavior a user can see.]

## Problem Statement

[Why now. Who it is for.]

## Goals

- [ ] [Observable outcome]
- [ ] [Observable outcome]

## Out of Scope

| Feature     | Reason         |
| ----------- | -------------- |
| [Feature X] | [Why excluded] |

## Ambiguity Ledger

| ID | Topic | Status | Resolution | Rationale |
| -- | ----- | ------ | ---------- | --------- |
| AL-01 | [gray area] | decided | [what] | [why — quote the product team's answer] |
| AL-02 | [dimension that does not apply] | n/a | — | [why it does not apply] |

Open questions: none — every row is `decided` by the product team or `n/a`.

## User Stories

### P1: [Story Title] — MVP (delivers Motivating Problem)

**User Story**: As a [role], I want [capability] so that [benefit].

**Why P1**: Slice 1 — [how this is the end-to-end outcome]

**Acceptance Criteria**:

1. WHEN [trigger] THEN the system SHALL [precise outcome]
2. IF [invalid input] THEN the system SHALL [precise error]
3. The system SHALL [invariant]

**Independent Test**: [How to demo this story alone]

## Edge Cases

- IF [error] THEN the system SHALL [handling]
- WHEN [boundary] THEN the system SHALL [behavior]

## Requirement Traceability

| Requirement ID | Story | Phase | Status |
| -------------- | ----- | ----- | ------ |
| [FEAT]-01      | P1    | Techspec | Pending |

**ID format:** `[CATEGORY]-[NUMBER]`
**Status:** Pending → In Techspec → In Tasks → Implementing → Verified

## Spec Changes

[Append SC-NNN records here. Empty until the first change.]

## File References

Read-first index for implementers (path + why). Copy a subset into each task.

### Repo Files

- `path/to/file:start-end` — [why]

## Success Criteria

- [ ] [Measurable outcome]
```

# discuss.md

# PRD: Discuss Gray Areas

**Goal:** Capture HOW the user envisions the feature when the spec has ambiguous areas. This is NOT a separate phase — it's triggered within PRD when the agent detects gray areas that need user input.

**Trigger:** Automatically when gray areas are detected during spec creation, or explicitly via "discuss feature", "how should this work?", "capture context"

**When to trigger (auto-detect):** The spec contains user-facing behavior that could go multiple ways AND the user hasn't expressed a preference. If the spec is clear and unambiguous, skip this entirely.

**When NOT to trigger:** Infrastructure work, CRUD operations, well-defined API contracts, anything where the "how" is obvious from the "what".

Technical dimensions (persistence, external calls, auth, concurrency, state transitions) do **not** trigger discuss — Techspec owns them ([techspec.md](techspec.md)). What triggers discuss is their product-visible face: not "do we retry the payment", but "what does the person see when the payment does not go through".

Every gray area is written to the Ambiguity Ledger in PRD.md and leaves as `decided` or `n/a` — never `assumed`, never dropped. See [ambiguity.md](ambiguity.md) for pace (Quick / Guided / Detailed) and ledger statuses.

**You are talking to the product team.** Every question here must be answerable by someone who has never opened the codebase. The banned-vocabulary list in [prd.md](prd.md) (**Product language only**) applies to every question in this file.

## Why This Phase Exists

Specifications capture WHAT to build. Techspec captures the architecture. But neither captures the user's vision for ambiguous areas — layout preferences, interaction patterns, error handling style, content tone. Without this, the agent guesses. With this, the agent builds what the user actually imagined.

The output — `context.md` — feeds directly into Techspec and Tasks:

- **Techspec reads it** to know what decisions are locked vs. flexible
- **Tasks reads it** to include specific behaviors in task definitions

## Process

### 1. Analyze the Feature

Read `.pulse/specs/features/[feature]/PRD.md` and identify the domain:

| Domain                         | Gray areas to explore                                         |
| ------------------------------ | ------------------------------------------------------------- |
| Something users **SEE**        | Layout, density, interactions, empty states, visual hierarchy |
| Something users **CALL** (API) | Response format, errors, auth, versioning, rate limiting      |
| Something users **RUN** (CLI)  | Output format, flags, modes, error handling, verbosity        |
| Something users **READ**       | Structure, tone, depth, flow, navigation                      |
| Something being **ORGANIZED**  | Grouping criteria, naming, duplicates, exceptions             |

Generate 3-4 **feature-specific** gray areas. Not generic categories, but concrete decisions for THIS feature.

### 2. Present Gray Areas

Analyze PRD.md and identify gray areas autonomously. When user input is required to choose areas or resolve ambiguity, follow [user-input.md](user-input.md) — present the feature boundary and all pending area/decision questions in one CLI batch at the end of the response.

Do NOT include a "skip all" option when the user explicitly invoked discuss.

### 3. Choose pace once, then deep-dive

Recommend **Guided**. Honor mid-discussion switches ("go faster", "just decide").

For each selected area, resolve decisions through CLI batches per [user-input.md](user-input.md) and [ambiguity.md](ambiguity.md):

1. Lead with a recommended option and one-line rationale
2. Guided: every question you can already see goes in the same batch; only a question whose wording depends on a pending answer waits for the next turn
3. After answers, update the Ambiguity Ledger (`decided`) and `context.md` on disk, then continue until the next blocking decision
4. Keep looping until no area is unresolved. There is no "we can settle this later" — an unanswered area means another batch next turn. Rounds are limited, so a case that only combines decisions already made is recorded as `decided` from them, not asked
5. When all areas are resolved, write `context.md` (decisions only — not a questionnaire)

**Question design** (when forming CLI batches — see [user-input.md](user-input.md)):

- Options should be concrete ("Card layout" not "Option A")
- Each batch of answers should inform the next batch
- Include "You decide" as an option when reasonable — captures agent discretion

### 4. Scope Guardrail (CRITICAL)

The feature boundary from PRD.md is **fixed**. Discussion clarifies HOW to implement, never WHETHER to add new capabilities.

**Allowed:** "How should posts be displayed?" (clarifying ambiguity)
**Not allowed:** "Should we also add comments?" (new capability)

When user suggests scope creep: "That sounds like a separate feature. I'll note it in Deferred Ideas. Back to [current area]."

### 5. Write context.md

---

## Template: `.pulse/specs/features/[feature]/context.md`

```markdown
# [Feature] Context

**Gathered:** [date]
**Spec:** `.pulse/specs/features/[feature]/PRD.md`
**Status:** Ready for design

---

## Feature Boundary

[Clear statement of what this feature delivers — the scope anchor from PRD.md]

---

## Implementation Decisions

### [Area 1 that was discussed]

- [Specific decision made]
- [Another decision if applicable]

### [Area 2 that was discussed]

- [Specific decision made]

### [Area 3 that was discussed]

- [Specific decision made]

### Agent's Discretion

[Areas where user explicitly said "you decide" — agent has flexibility here during design/implementation]

---

## Specific References

[Any "I want it like X" moments, product references, specific behaviors, interaction patterns mentioned during discussion]

[If none: "No specific requirements — open to standard approaches"]

---

## Deferred Ideas

[Ideas that came up during discussion but belong in other features/phases. Captured here so they're not lost, but explicitly out of scope]

[If none: "None — discussion stayed within feature scope"]
```

---

## Tips

- **Decisions, not vision** — "Card-based layout with subtle shadows" is a decision. "Should feel modern" is not.
- **Scope is sacred** — Deferred Ideas captures scope creep without losing ideas
- **User = visionary, Agent = builder** — Ask about how they imagine it, not about technical implementation
- **Don't ask about:** Technical architecture, performance, implementation details — that's Techspec's job
- **Confirm before Techspec** — User approves context.md via CLI confirmation per [user-input.md](user-input.md) before moving to design phase

# state-management.md

# State Management

**Purpose:** Persistent memory across sessions - decisions, blockers, learnings.

## Structure

**Output:** `.pulse/specs/project/STATE.md`

```markdown
# State

**Last Updated:** [ISO timestamp]
**Current Work:** [Feature name] - [Task identifier]

---

## Recent Decisions (Last 60 days)

### AD-[NNN]: [Decision title] ([date])

**Decision:** [What was decided]
**Reason:** [Why this choice]
**Trade-off:** [What was sacrificed]
**Impact:** [How this affects implementation]

### AD-[NNN]: [Decision title] ([date])

[Same structure]

---

## Active Blockers

### B-[NNN]: [Blocker description]

**Discovered:** [Date]
**Impact:** [Severity and scope]
**Workaround:** [Temporary solution if available]
**Resolution:** [Path to permanent fix]

---

## Lessons Learned

### L-[NNN]: [Learning description]

**Signal:** ac_gap | surviving_mutant | spec_precision_gap | spec_deviation | gate_fail | review_valid
**Source:** [file:line or AC id]
**Feature:** [slug]
**Status:** candidate | confirmed | quarantined
**Context:** [Situation that occurred]
**Problem:** [What went wrong]
**Solution:** [How it was resolved]
**Prevents:** [What this knowledge prevents in future]

---

## Quick Tasks

| #   | Description              | Date   | Spec                         | Status                |
| --- | ------------------------ | ------ | ---------------------------- | --------------------- |
| 001 | [Quick task description] | [date] | `.pulse/specs/quick/001-slug/`     | ⏳ Awaiting Approval  |
| 002 | [Quick task description] | [date] | `.pulse/specs/quick/002-slug/`     | ✅ Done               |

---

## Deferred Ideas

Ideas captured during work that belong in future features or phases. Prevents scope creep while preserving good ideas.

- [ ] [Idea description] — Captured during: [feature/phase]
- [ ] [Idea description] — Captured during: [feature/phase]

---

## Todos

Capture in-progress thoughts and action items that don't fit in active tasks.

- [ ] [TODO: action item]
- [ ] [TODO: action item]
```

## When to Update

| Event                            | Action                                 |
| -------------------------------- | -------------------------------------- |
| Significant architectural choice | Add AD-[NNN]                           |
| Implementation blocked           | Add B-[NNN]                            |
| Important discovery/learning     | Add L-[NNN] with **Signal** + **Source** ([lessons.md](lessons.md)) |
| Quick task started (plan ready)  | Create `.pulse/specs/quick/NNN-slug/TASK.md`, update Current Work, add Quick Tasks row ⏳ |
| Quick task completed             | Update TASK.md, create SUMMARY.md, set Quick Tasks row ✅ Done          |
| Scope creep captured             | Add to Deferred Ideas                  |
| In-progress thought              | Add to Todos                           |
| Session end                      | Update "Last Updated" + "Current Work" |

## Size Management (Hybrid Strategy)

**Zones:**

- 🟢 <7k tokens: No action
- 🟡 7-10k tokens: Footer note "STATE.md at [X]k. Cleanup recommended."
- 🔴 >10k tokens: Active prompt "STATE.md critical ([X]k). Cleanup now?"

**Cleanup process:**

- Move decisions >60 days to STATE-ARCHIVE.md
- Keep only active blockers
- Preserve recent learnings (<60 days)

**Validation:**

- Decisions have clear rationale?
- Blockers include resolution path?
- Learnings are actionable?

---

## Preferences

Track user-facing behavioral state in STATE.md:

```markdown
## Preferences

**Model Guidance Shown:** [ISO date or "never"]
```

**Update when:**

| Event                       | Action                   |
| --------------------------- | ------------------------ |
| First model tip given       | Set date                 |
| User acknowledges/dismisses | Keep date (don't repeat) |

This prevents repetitive suggestions while maintaining natural, helpful behavior.

# user-input.md

# User Input (CLI)

**Applies to:** Every phase of this skill. All reference docs defer here when user input is required.

## Rules (mandatory)

1. **No intermediate artifacts for questions** — Never create question files, screens, menus, UI components, JSON, Markdown drafts, or any other mechanism to collect answers. The terminal (chat) is the only interaction channel.
2. **Work first, ask last** — Continue executing until it is impossible to proceed without a user decision. Do as much autonomous work as allowed (codebase analysis, drafting, validation) before stopping.
3. **Batch pending questions** — When blocked, present **all** pending questions together at the **end** of the response.
4. **Stop after questions** — End the response immediately after the questions. Do not continue the workflow, create deliverables that depend on answers, or add closing commentary.
5. **Never invent mandatory answers** — Do not assume defaults or fabricate values when information is required. Infer only from explicit user input or verifiable project artifacts (code, `.pulse/specs/`, docs).
6. **Resume from interruption** — After the user replies (e.g. `A`, `B`, `1`, `Sim`, or free text), continue exactly from where execution stopped.

## Format

Use plain text suitable for a terminal. Always end with `Resposta:` on its own line.

**Delivery:** Wrap the **entire** question block in a ` ```text ` fenced code block so chat does not collapse line breaks. No markdown lists, bullets, or tables inside the block.

**English equivalent header:** `I need some information before continuing.`

### Pre-send checklist (mandatory)

Before sending, verify ALL of these. If any fails, rewrite — do not send.

| Check | Pass condition |
| ----- | -------------- |
| Numbered questions | Every question line starts with `N.` |
| Options separated | No single line contains `A)` and `B)` (or any two option letters) |
| One option per line | Count of lines matching `^[A-Z]\)` equals total options |
| Blank lines | Empty line after question text; empty line between question blocks |
| Footer | `Resposta:` alone on the last line inside the fence |
| Fence | Whole block inside ` ```text ` … ` ``` ` |

**Detection regex (mental check):** if you see ` B)` or ` C)` or ` D)` anywhere except at the start of a line (after newline), the output is **invalid**.

### Layout rules (strict — violations break readability)

Every CLI question block MUST follow this structure exactly:

1. **Header** — one line, then blank line
2. **Each question** — numbered (`1.`, `2.`, …), question text on its own line, blank line, then options
3. **Each option** — exactly one option per line, format `A) texto` (letter + `)` + space + text)
4. **Between questions** — blank line after the last option of the previous question
5. **Footer** — blank line, then `Resposta:` alone on the last line

**NEVER:**

- Put multiple options on the same line
- Omit question numbers
- Put option text on the same line as the question (without a blank line before options)
- Use markdown lists (`-`, `*`), bullets, tables, or headings inside the question block
- Wrap options in parentheses blocks on one line

**BAD (do not output like this — options collapsed on one line):**

```text
Preciso de algumas informações antes de continuar.

O que você está construindo?
A) Opção A B) Opção B C) Opção C D) Outro

Quem é o público-alvo?
A) Iniciantes B) Experts C) Outro

Resposta:
```

**GOOD (always output like this — inside ```text fence):**

```text
Preciso de algumas informações antes de continuar.

1. O que você está construindo?

A) Plataforma de paper trading
B) Sistema de gestão de portfólio
C) API de negociação
D) Plataforma completa
E) Outro (descreva)

2. Quem é o público-alvo?

A) Investidores iniciantes
B) Traders experientes
C) Ambos
D) Outro (descreva)

Resposta:
```

### Full multi-question example (project-init — use this structure)

```text
Preciso de algumas informações antes de continuar.

1. O que você está construindo?

A) Plataforma de simulação de trading (paper trading)
B) Sistema de gestão de portfólio pessoal com saldo virtual
C) Projeto full-stack de estudo/portfólio
D) Plataforma completa pronta para produção
E) Outro (descreva)

2. Quem é o público-alvo e qual problema resolve?

A) Investidores iniciantes aprendendo a operar
B) Desenvolvedores estudando arquitetura
C) Uso pessoal para simular investimentos
D) Público geral — trading sem risco
E) Outro (descreva)

3. Qual é o foco da v1 neste momento?

A) Consolidar o que existe — gaps, testes, estabilidade
B) Completar features pendentes
C) Preparar para deploy
D) Adicionar novas features (descreva)
E) Outro (descreva escopo e exclusões)

4. Há restrições críticas?

A) Sem prazo — evolução contínua local
B) Prazo curto (descreva)
C) Apenas ambiente local
D) Preparar para produção em breve
E) Outro (descreva)

Resposta:
```

Keep option text short (one line each). If an option needs a sub-prompt (e.g. "descreva"), put it in parentheses at the end of that option line — never merge options to save space.

## Question design

- Options must be **concrete** (`Card layout` not `Option A` as label text — use letters only as selectors).
- Prefer **3–6 options** plus an **Other (describe)** escape when the set is not exhaustive.
- Use **free-text questions** (no alternatives) when the answer is open-ended.
- Group related decisions into one numbered question when possible; do not split into multiple round-trips unless answers depend on each other.
- For yes/no decisions, use `A) Sim` / `B) Não` or `1) Yes` / `2) No`.
- For multi-select, state it explicitly: `(escolha uma ou mais: A, C)`.

## What is NOT a question artifact

These are **deliverables**, not question mechanisms — still create them after answers are received:

- `.pulse/specs/project/PROJECT.md`, `ROADMAP.md`, `STATE.md`
- `.pulse/specs/features/[feature]/PRD.md`, `context.md`, `TECHSPEC.md`, `tasks.md`
- `.pulse/specs/quick/NNN-slug/TASK.md`, `SUMMARY.md`
- `.pulse/specs/codebase/*` brownfield docs
- Validation reports, fix plans, task summaries

`context.md` stores **decisions already made** — never use it (or any file) as a questionnaire or pending-questions log.

## Approval and confirmation

When a phase requires user approval (design, tasks, quick-task pre-check, fix plans), create spec deliverables first when applicable (e.g. `.pulse/specs/quick/NNN-slug/TASK.md`), present the summary, then blocking questions in CLI format:

```
Preciso de algumas informações antes de continuar.

1. Aprovar [artefato] e prosseguir?

A) Sim, aprovar e continuar
B) Não, preciso de ajustes (descreva abaixo)

Resposta:
```

If the user chooses adjustments, wait for their description before revising.

## Pipeline migration (Quick mode → full spec)

When a request triggered as Quick mode but fails **Scope Eligibility** in [quick-mode.md](quick-mode.md), present:

```text
Preciso de algumas informações antes de continuar.

1. Este pedido excede o escopo do Quick mode: [motivo concreto — ex.: 5 arquivos, decisão de arquitetura, escopo vago]. Como deseja prosseguir?

A) Migrar para o pipeline completo (PRD → Techspec → Tasks → Execute, conforme escopo)
B) Quick fix: [recorte pré-definido 1 — uma linha, ≤3 arquivos]
C) Quick fix: [recorte pré-definido 2 — uma linha, ≤3 arquivos]
D) Cancelar

Resposta:
```

- **A)** Start [prd.md](prd.md) for the feature — do not keep a quick TASK.md
- **B/C…)** Re-assess eligibility with that predefined narrowed scope; if it passes, continue Quick mode
- **Last option (Cancelar)** Stop; no spec files unless the user reopens the request

**Closed choices only:** Do not use "descreva" or free-text options in this block. Do not include "Outro" — Pulse suppresses it for migration gates. List concrete quick-fix alternatives derived from your codebase analysis.

**Never** auto-start PRD, Techspec, or Tasks without the user selecting **A**.

## UAT and verification

Interactive UAT follows the same strict layout — one option per line, numbered question, blank lines between sections:

```
Preciso de algumas informações antes de continuar.

1. Teste: [Nome do teste]

Esperado: [comportamento observável]

A) Funciona como esperado
B) Não funciona (descreva o que vê)
C) Pular / não aplicável

Resposta:
```

Infer severity from free-text descriptions per [validate.md](validate.md). Never ask the user to rate severity.
