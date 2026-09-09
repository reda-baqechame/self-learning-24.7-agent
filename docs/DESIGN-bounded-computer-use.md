# Bounded computer-use evidence phase

Status: preregistered development benchmark, not release acceptance.
Base: reviewed main fc08b7f. Claude's original files and candidate are separate.

## Contract

First establish an independent invoice artifact verifier, then run the twelve
fixtures in the preserved COMPUTER_RELIABILITY_PROTOCOL three times each.
Required artifacts: exactly three unique invoice IDs for a synthetic month,
matching externally supplied SHA-256 digests and confined regular-file paths.
Missing, duplicate, extra, corrupt, partial, linked or oversized files refuse.
The browser/controller cannot supply or amend the expected manifest.

The artifact verifier is necessary, not sufficient: it cannot certify the
browser's action authority, observation freshness or session identity. Those
are separate adapter gates. A DOM self-report is not an authenticated browser
observation. Independent destination and effect verification remain mandatory.

The next adapter checkpoint seals normalized page/target observations with an
authority-private HMAC and a per-process session identity. Only the latest
bounded-age receipt may authorize an action. Each authorization is consumed
before the trusted atomic adapter runs, so an unknown outcome cannot retry.
Target identity, text, URL and geometry, page URL, allowed origin and deadline
are supplied as adapter preconditions. Adapter precondition refusal means no
action; an exception or malformed readback is unresolved. This contract does
not make a generic MCP evaluator safe and does not prove an adapter enforced
the preconditions until an integrated runtime test exercises it.

## Trial boundary

Use the platform mcp.guarded_call path and pinned isolated Chromium image, no
personal profiles, accounts or provider calls. A disposable loopback supplier
fixture may run inside the network-disabled container. Any mounted inputs must
be synthetic read-only fixtures; output mounts must be empty disposable paths.
No unsafe-host product fallback. Keep all failed attempts and classify each
trial as verified completion, expected safe refusal, unresolved, or incorrect
completion. A safe refusal is not successful invoice retrieval.

The 36 known deterministic fixtures are development coverage. They are NOT
hidden held-out variants, evidence of population reliability, comparison with
other agents, or a basis for claiming best-in-world computer use.

## Acceptance sequence

1. Independent verifier acceptance tests, including malformed manifests,
   filesystem containment and adversarial artifacts; load-bearing mutations.
2. Adapter authority, authentic session/state observation, deadline and target
   checks. Explicitly test non-atomic observe/action races before acceptance.
3. Twelve fixtures x three reset runs with retained per-trial receipts, artifact
   manifests, timing and zero-provider-cost disclosure. Do not relabel an
   unexecuted or prerequisite-blocked trial as a successful safe refusal.
4. Full suite, generated evidence, zero execution audit violations, independent
   review and six supported CI configurations before phase merge.

Native desktop, real-account and live-model quality, uncertain business writes,
comparative trials and soak/rollback release proof remain separate gates.

## Task 6 historical result and corrected acceptance boundary

The retained 36-trial run reported 12 `verified_completion`, 15 `safe_refusal`
and 9 `rejected_artifacts`, with 36 cleanup readbacks and no provider call. That
receipt is historical evidence for the pre-review classifier, not corrected-tree
clearance: case names could turn unreconciled controller/action `UNKNOWN` into a
refusal or artifact rejection. Corrected classification makes every unreconciled
`UNKNOWN` an `unresolved` trial even when artifacts reject, keeps artifact outcome
separate, and does not force preregistered totals. A fresh complete batch is
required; any unresolved or expected-class mismatch keeps `development_complete`
false. The earlier 35/36 moved-layout failure also remains historical.

These are known synthetic development fixtures. Candidate `computerbench.py`
cannot issue a challenge or verify acceptance; its acceptance command always
exits nonzero. `computerbench_verifier.py` is only an out-of-band installation
template for the external acceptance-pack contract. Production refuses unless
the root-owned `computerbench-verifier` launcher starts that module from its
exact fixed `/opt` location using fixed `/usr/bin/python3 -I -S` and an
allowlist-only environment. The verifier source is non-executable and validates
the exact interpreter arguments, isolated/no-site/ignore-environment flags and
environment again; direct entry refuses. Every installation directory, launcher
and module is root-owned/non-writable, and the process is the
configured dedicated nonroot verifier UID distinct from the worker. It imports
only stdlib after launcher isolation and never imports or executes a candidate
module. Worker `PATH`, `PYTHONPATH`, user-site and `sitecustomize` code cannot
precede validation. A fixed root-owned public store supplies separate issuer and
evaluator RSA keys; no CLI provisions or signs. Windows and absent, aliased,
misowned or mispermissioned authority fail closed. The candidate is the exact
`package.py` ZIP treated solely as data. The verifier rejects traversal,
duplicates, links and special members, and binds archive bytes, the complete
member manifest including synthesized `.gitkeep` members, runtime/config
digests, launcher+verifier build, trust metadata, frozen settings, issue/expiry times and
a one-run challenge.
Consumption locks the transition, durably creates an exclusive tombstone before
removing issued state, and a tombstone forever dominates restored issued bytes.
The contract freezes model,
tool, policy, budget, retries and human help; sealed results report steps,
elapsed time and cost and are rejected when their aggregate exceeds those
frozen ceilings. It reports browser-only,
native-desktop and API-assisted tracks separately. No author string or
self-generated digest establishes independence. An explicitly internal temp
backend supports public-key verification mechanics but cannot set acceptance
true. This Windows host lacks the required POSIX verifier authority and no real external pack/
results were supplied, therefore `acceptance_complete=false` and
`release_ready=false`.

MCP/API compatibility is not model competence. DOM observation or acknowledged
input dispatch is not verified business success. The implemented MCP scope is
the legacy stdio `2025-06-18` protocol only. The observer/action vocabulary is
the invoice-link family only. Top-level origin validation is not browser-network
containment; immutable image storage is not model-vision transport; the context
budget still rejects non-text multimodal input. Native desktop, real-account,
live-model, soak and rollback evidence remains unproven.
