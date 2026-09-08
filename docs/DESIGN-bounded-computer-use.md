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

## Task 6 development result and acceptance boundary

The corrected deterministic run retained 36 trial receipts and produced the
preregistered class totals: 12 `verified_completion` (normal, delayed, moved and
injection, three each), 15 `safe_refusal` (ambiguous, dialog, expired, restart
and cross-origin, three each) and 9 `rejected_artifacts` (interrupted, corrupt
and duplicate/missing, three each). Cleanup was independently read back for all
36 owned containers and no provider was called. An earlier 35/36 run is also
retained: one moved-layout receipt arrived after movement, and the runner wrongly
treated a legitimate fresh dispatch as a stale-receipt failure. That failed run
was not relabelled; the runner gained a sealed-state comparison and a new full
run used a fresh root.

These are known synthetic development fixtures. `computerbench.py` separately
defines an external acceptance-pack contract with layout, wording, timing,
authentication and multistep variants. The pack and results must be supplied
separately, content-sealed and authenticated by independently supplied owner
trust outside repository/worker-authored content. The contract freezes model,
tool, policy, budget, retries and human help; sealed results report steps,
elapsed time and cost and are rejected when their aggregate exceeds those
frozen ceilings. It reports browser-only,
native-desktop and API-assisted tracks separately. No author string or
self-generated digest establishes independence. No real external pack/results
were supplied in this task, therefore `acceptance_complete=false` and
`release_ready=false`.

MCP/API compatibility is not model competence. DOM observation or acknowledged
input dispatch is not verified business success. The implemented MCP scope is
the legacy stdio `2025-06-18` protocol only. The observer/action vocabulary is
the invoice-link family only. Top-level origin validation is not browser-network
containment; immutable image storage is not model-vision transport; the context
budget still rejects non-text multimodal input. Native desktop, real-account,
live-model, soak and rollback evidence remains unproven.
