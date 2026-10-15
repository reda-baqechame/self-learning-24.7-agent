# Claude Phase 10.1 continuation gates

## Local reconciliation checkpoint, 2026-09-05

Measurement PR 22 is merged as fc08b7f. This candidate combines that main
revision with the preserved Claude snapshot; it is not accepted or released.
The ten merge conflicts were resolved by retaining both registrations and
implementations, with training-only reasons and frozen measurement neighbors.
Counts are 120 root Python modules, 156 registered tests, 57 mutations.

New failing-before-fix regressions cover another human entering panel capture,
same-time actor collisions, receipt freshness after question/event changes and
an event write during evaluation. Capture now binds new panel entries to the
consented actor, preserves legacy bytes and avoids duplicating matching legacy
events. Receipts bind questions, events and both depth-module source hashes;
depth metrics explicitly state their exploratory/noncausal limits.

This is partial closure of gates 1, 3, 8 and 9, not closure of the phase.
Capture task authority, credential/link containment, bounded reads and compound
concurrency remain unresolved. Historical snapshots, prospective enrollment,
lens provenance/signing authority, full-suite evidence and independent CI/review
remain required. Existing EVIDENCE.md describes main's run, not this candidate.

Inspected 2026-09-05. The original 17 modified and three untracked source files
remain untouched in remediation-worktree. A local 20-file snapshot with hashes
is claude-phase10.1-source-20260905.zip. This document does not certify the phase.

## Required changes before integration

1. Preserve the measurement repair's group split, frozen neighbors, full fit
   hash, receipt binding and stale suppression. Never replace twin.py wholesale
   with the older Phase 10.1 copy. Reasons mined from episodes must use training
   rows only; final-answer perturbation must leave every fitted field unchanged.
2. Capture must enforce consent and caller authority at each public entry point,
   including its standalone CLI, not only the caller's idle tick. A temporary
   no-consent direct tick was executed and created capture-state.json. No real
   history, directories or panel data were supplied in that probe.
3. Attribute panel capture to the consented owner, not every non-agent actor in
   a shared fleet. Test two distinct human actors and same-time actions.
4. Named capture directories do not authorize following links outside those
   directories or reading credentials through ordinary file reads. Bound reads,
   protect partial/truncated histories and fail closed if redaction is unavailable.
5. Make capture's deduplication and state replacement recoverable under concurrent
   ticks. PID-only temporary names and append-only locking do not by themselves
   protect compound updates. Crash/retry tests must preserve original evidence.
6. Interview amendments and vignette retests need explicit record identity and
   preserved history. They are development data unless prospective enrollment
   was independently established before answers. Test malformed/duplicate schema
   names, non-finite bounds, invalid choices and repeated submissions.
7. predict(at=...) currently filters citations, not all trained state. Do not call
   that historical reconstruction. Require a fully identified eligible snapshot
   or refuse the historical claim. Temporal comparison must use each snapshot's
   own frozen neighbors, not today's training set for every version.
8. Preference sign agreement fitted on final rows is an exploratory secondary
   diagnostic, not promotion evidence. Do not let it select the candidate.
   Outcome agreement is observational, not a causal improvement estimate.
9. Additional metrics need receipt inputs and evaluator-source hashes. Live
   workflow/objective/interview changes cannot silently retain a current receipt.
10. Lenses remain model opinions; generated evidence strings are not verified
    sources. Preserve input provenance and bound calls through the model gateway.
    Simulation is policy sensitivity, not a forecast. Signing uses the credential
    authority and must not turn an unsigned result into an authorization grant.

## Acceptance and order

First merge the separately reviewed measurement repair only after required CI.
Then implement this reconciliation on its own branch with its own design,
benchmark, review and merge. Keep Claude's original snapshot and both pasted
documents local and unchanged. Each claimed correction requires a failing
regression, passing fix, applicable mutation, full suite and supported CI.
No personal capture is enabled during development; fixtures only.

The computer track follows its separately preserved matrix and bounded portal
contract. A configured browser tool, a screenshot or a successful click is not
independent proof of invoice coverage, contents or correct business completion.
