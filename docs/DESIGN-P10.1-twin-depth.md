# Phase 10.1 — Twin depth: capture, cold start, augmentation, the rest of the benchmark (design, committed before code)

**Reconciliation status (2026-09-05): UNACCEPTED CANDIDATE.** The historical
design and implementation claims below are preserved, not certified. Required
corrections and evidence are in DESIGN-twin-depth-reconciliation.md. In particular,
predict(at) does not reconstruct historical trained state; capture safety,
prospective human fidelity and release readiness have not been established.

**Historical status: DESIGN → BUILT** (committed first; the build commit cites this
file; the preregistered benchmark below must be green before the phase is
permanent). **Branch:** `phase10.1/twin-depth`, on main after PR #19.
**Parent:** docs/DESIGN-P10-twin.md.

## Why a 10.1

The owner re-read the brief after Phase 10 merged and asked for
certainty that the system is *the person*, not a chatbot with memory. An
honest audit of Phase 10 against the brief's sixteen sections:

| Brief section | Phase 10 | Gap closed here |
|---|---|---|
| Layer 1 total experience capture (commands, edits, actions, time between them) | declared episodes only | **`twincapture.py`**: a consented work stream — the owner's panel actions, shell commands, and edit revisions — into `twin/events.jsonl`; routines mined from it; workflow fidelity measured |
| "ask why at high-information points" | built | unchanged |
| Self Model: identity, **objectives**, preferences, **belief state**, attention, heuristics, social | objectives and beliefs designed, not read | `objectives()` reads missions, goals and armed intentions into the kernel and the OWNER block; `predict(at=)` reconstructs what was knowable before a moment and cites only earlier episodes |
| four memories incl. autobiographical *versions* | versions, drift | `history()`: the autobiography — versions, confirmed and dismissed drifts with their shifts, interview, consent events |
| "predict alternatives you would consider" | options must be supplied | `consider()`: the options the owner weighed in the nearest past situations |
| Super-Self as an **augmentation engine** (analysts, simulations, evidence) | one model call | lenses (K parallel analyst calls, aggregated by vote, disputed assumptions and evidence collected) + a mechanical **sensitivity simulation** of the Clone over perturbed situations (stability, flip points) |
| the brutal benchmark: attention, preference, workflow, temporal, outcome fidelity | choice, calibration, novel, ranking, self-consistency, writing | all five added, each reported as a number or as *not measured*, never invented |
| cold start (Park et al.: first-person narrative and stated reasoning beat tags; the person's own retest is the ceiling) | none | a structured **interview** bank and **vignettes** — schema-driven decision situations the owner answers; a re-answer is a retest |
| cryptographic authorization, "every action signed" | sealed consent chain | HMAC-SHA256 **signatures** on every twin output when the owner sets `TWIN_SIGNING_KEY`; `verify()`; unsigned outputs say so |
| outcome fidelity | — | `outcome` amendments on episodes; the good-rate where the Clone agreed vs disagreed |

Nothing from Phase 10 is removed or renamed; every addition is a new
function, ledger or line.

## The work stream (Layer 1, as far as consent and a stdlib allow)

`twin/events.jsonl` — one row per observed act of the owner, hashed and
idempotent, CONTROL like the rest of `twin/`:

| kind | source | what is stored | consent |
|---|---|---|---|
| `panel` | `org/audit.jsonl` (every mutating panel route already writes one row per actor) | actor, action, object kind, object | the `predict` scope (it is the platform's own log of the owner) |
| `command` | a shell history file the owner NAMES in `[agent.twin] capture_history` | the command line after `credentials.redact`; a command containing a key-shaped token is stored as `[redacted command]` | naming the file |
| `edit` | directories the owner NAMES in `[agent.twin] capture_dirs` (bounded by `capture_max_files`, 5000) | path, added/removed line counts, byte delta, seconds since that path's last edit — **never content** | naming the directory |

From the stream, `twincapture.routines()` mines the owner's *workflow
programs*: a bigram next-act table and frequent trigrams with support ≥ 3
("after `git commit` they run `git push`, 12/14"). **Workflow fidelity**
is next-act accuracy on the held-out tail of the sequence (last 20 %)
against the majority-act baseline, reported with its lift.

The stream is read on the idle tick beside the episode harvest; a source
that is not named captures nothing, and the test proves the negative.

## Cold start: the interview and the vignettes

`twin.py interview` presents a fixed bank of fourteen first-person
questions (values, what they optimize, risk, speed vs accuracy, money vs
time, what persuades them, when they investigate more, what they delegate,
what they refuse, how they behave with different people, what they check
first, how they write, how they have changed). Answers are stored in the
kernel's identity (`identity.interview`), feed the style corpus, and the
OWNER block quotes them.

`twin.py vignettes` generates decision situations from a feature schema
(`[agent.twin] features`, default: risk, margin, cost_usd, reversibility,
trust, time_pressure; options grant/deny) by deterministic stratified
sampling; the owner answers with `--answer`, each answer becomes an
episode of kind `vignette`, and a later re-answer of the same vignette is
a **retest** that feeds the self-consistency ceiling. Twenty-four
vignettes give the kernel a first fit on day one.

## The augmentation engine

`superself()` now runs:

1. **Lenses.** `[agent.twin] lenses` (default 3: finance, risk,
   relationships; the owner may name more) — one metered model call per
   lens, each asked to decide *as the owner's analyst for that lens* and to
   return `{choice, reason, disputed_assumption, evidence}`; the choice is
   the vote, ties go to the Clone's argmax, reasons and evidence are
   collected, disputed assumptions listed.
2. **Simulation.** Mechanical, no model: the Clone re-predicts over 400
   perturbed copies of the situation (Gaussian noise at half a standard
   deviation per numeric feature, from the kernel's own stats) → **decision
   stability** (share agreeing with the unperturbed argmax) and **flip
   points** (per feature, the nearest value at which the Clone's choice
   changes, swept ±2σ in 8 steps each way).
3. **Divergence**, unchanged: if the vote ≠ the Clone's argmax, a
   policy-update question; the kernel never moves.

## The rest of the benchmark

| Dimension | Measurement |
|---|---|
| attention fidelity | of the answered "why" questions that named a candidate feature, the share naming one of the kernel's top-3 attention features |
| preference fidelity | refit on held-out rows alone (≥ 10) and compare the sign of the top-5 fit weights: agreement share |
| workflow fidelity | next-act accuracy on the held-out tail vs the majority baseline |
| temporal fidelity | with ≥ 2 versions, the current era's held-out rows scored by every version: the era's own version must score best |
| outcome fidelity | episodes carrying an `outcome` (good/bad, recorded by the owner): good-rate where the Clone agreed vs disagreed, ≥ 10 outcomes |

Each is a number or `not measured` with the reason.

## Signatures

`TWIN_SIGNING_KEY` (environment or `agent.env`, read the way provider keys
are read, never printed) → every output of `predict`, `superself`, `draft`,
`act` carries `signature = HMAC-SHA256(key, canonical body)` and `signed:
true`; `twin.py verify <file>` recomputes it. Without a key: `signed:
false`, and the label still travels.

## Benchmark that must pass (`tests/test_twin_depth.py`)

1. **Capture.** Panel audit rows, a named history file and a named
   directory produce events exactly once; a command carrying a key-shaped
   token is stored redacted; an edit stores counts, never content; with
   nothing named, commands and edits capture nothing.
2. **Routines.** A synthetic command sequence with a habit yields the
   habit as a routine and a held-out next-act accuracy above the majority
   baseline; the workflow line appears in the OWNER block.
3. **Cold start.** Interview answers land in the kernel and the block;
   24 vignettes answered by a known policy fit a kernel; re-answering
   three of them measures self-consistency.
4. **Objectives and beliefs.** A mission and a goal appear in
   `objectives()` and the block; `predict(at=)` cites only earlier
   episodes and reports what was knowable.
5. **Augmentation.** Three scripted lenses are aggregated by vote with
   evidence and a disputed assumption; three calls are metered; the
   simulation reports stability and a flip point on the feature that
   decides; divergence still queues a question.
6. **Benchmark.** attention, preference, temporal (era version wins after
   a confirmed drift), outcome and workflow fidelity are reported; with
   no data each says not measured.
7. **Signatures.** With a key every output verifies; a tampered body
   fails; without a key outputs say unsigned.
8. **Alternatives and autobiography.** `consider()` returns the options
   weighed in similar situations; `history()` lists versions, drifts and
   the interview.
9. **Registration.** run_all, evidence, proof, doctor, leakage
   enumeration, REFERENCE, MANUAL, settings.

## What this phase does NOT claim

No screen or keystroke capture — the work stream is what a consented
stdlib process can read: the platform's own audit, a named history file,
named directories. No claim that a simulation over perturbed situations
predicts real-world outcomes; it measures the Clone's own stability.
Lenses are model calls under the same mock discipline as every other
model path.
