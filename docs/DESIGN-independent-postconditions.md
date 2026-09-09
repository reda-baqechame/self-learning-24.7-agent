# CU-1: independent post-action terminalization

Status: frozen implementation design for the first synthetic invoice predicate. This does not qualify general browser, desktop, live-model, or release readiness.

## Existing call map

1. `loop.Agent.exec_tool` owns one `ComputerSession` per task and exposes `open`, `observe`, and `click`.
2. `ComputerSession.click` validates a sealed observation, appends a durable `PREPARED` action, moves it to `DISPATCHED` immediately before the MCP send, and returns only `ACTION_DISPATCHED` plus a fresh observation. It deliberately cannot report workflow success.
3. Session death/closure maps `PREPARED` to `FAILED_WITH_KNOWN_NO_EFFECT` and `DISPATCHED` to `UNKNOWN`.
4. Owner reconciliation records an attestation but cannot turn executor evidence into `VERIFIED`.
5. `computerbench.run_development_trial` currently clicks all invoice links, closes the browser, and independently calls `computeruse.verify_invoices`. That artifact verdict is not bound to an action and does not terminalize the durable ledger.
6. `loop.Agent.check_done` runs a named verifier and/or contained shell gate, but does not inspect required computer actions or their receipts.

## Frozen contract

The trusted controller, never page content, executor output, click results or the model, constructs one versioned `invoice-set.v1` workflow contract before any dispatch. Its canonical body contains:

- predicate and schema version;
- task, lineage, session epoch, policy revision, server and allowed origin;
- the complete ordered intent set: target invoice IDs and destination URLs;
- the complete expected manifest and its canonical digest;
- an `expectation_source` identity, version and content digest for the independently supplied manifest;
- an independently supplied account/tenant identity which every invoice must match;
- confined CONTROL/RUNTIME output directory that ordinary agent file authority cannot write;
- a stable pre-dispatch empty baseline plus the output directory's filesystem identity;
- verifier identity/version and bounded read limits;
- an output-authority lease derived from the physical directory device/inode identity, so case and 8.3 aliases contend on the same authority, plus a bounded verification deadline;
- `required_for_task=true`.

Before any `ComputerSession` can dispatch even navigation, it acquires a deterministic per-lineage index lease and registers its action-ledger path in `effects/computer/task-<lineage-digest>.json`. Registration writes the index as `PREPARED`, ensures the named ledger exists with the exact task/lineage/server binding, then replaces the index with `COMMITTED`. Workflow creation later uses the same ordered transaction: acquire and retain the output-authority lease before capturing the baseline, bind that physical output identity to exactly one workflow, persist a root-wide `PREPARED` claim keyed by device/inode while holding that lease, write the lineage-index `PREPARED` revision and immutable ledger workflow, commit the lineage index, then move the exact root claim to `COMMITTED`. Recovery commits a prepared claim only when the exact workflow/contract/ledger and committed lineage index exist; otherwise it records `ABORTED`, and a later prepared claim chains the aborted digest and revision. Different ledgers and close/reopen therefore cannot forget ownership, while a crash before workflow persistence does not brick an unused directory. A committed first-predicate claim is permanent and the evidence directory is never recycled. These are ordered durable single-file commits, not cross-file atomicity. A `COMMITTED` index whose registered ledger is missing or mismatched fails closed. Because the index name is derived from task lineage, `check_done` does not depend on a fallible second update to `state.json`.

The contract digest is computed by a pure validator. Every later `PREPARED` action may only select the next ordered intent and stores that existing digest before `_dispatch`; it cannot supply or modify expectations. Existing, orphaned and malformed records have no authority for this transition.

The first invoice predicate requires an independently observed empty output baseline. Any old expected, partial, or unrelated output makes contract creation unqualified; hash equality alone cannot attribute the current action. Later predicates may define richer baseline policies, but this one does not silently inherit files.

## Independent evidence and receipt

The browser/MCP result remains executor evidence only. After each required invoice action is dispatched, the trusted harness enters `QUIESCING` without calling ordinary `close`: it durably binds the action to the current environment incarnation, closes the server, independently confirms that exact process/container incarnation absent through `computerprocess.cleanup`, records a cleanup receipt/digest, clears the owner environment, and enters `QUIESCENT` while retaining the session, lineage-index and output-authority leases. Failure at any boundary taints the session and preserves or produces raw UNKNOWN.

Only after that cleanup receipt exists may the verifier observe the exact ordered prefix of expected files: all previously verified files plus the current target, no missing file, no future file and no extra file. It reopens the directory and files through secure anchored reads, validates exact byte counts/digests, parses every observed invoice, and checks ID, month, account and `total_cents` against the independently sourced manifest. The cleanup incarnation and receipt are bound into the postcondition receipt.

After the current action terminalizes, the same live session epoch may reconnect for the next action. Every `_connect` first durably allocates a strictly increasing environment incarnation and uses a fresh `effects/computer/process-<epoch>-<incarnation>.json` identity; it never reuses a prior process record. Ordinary `close` remains terminal and unchanged in meaning. Recovery of a crashed `QUIESCING`/active incarnation cleans that exact record, maps its dispatched action to raw UNKNOWN, and never reconnects until cleanup is independently confirmed.

Before filesystem I/O, the verifier durably appends a `STARTED` attempt containing a monotonic per-workflow sequence, action/contract/verifier bindings, fixed deadline and bounds. It later appends `VERIFIED`, `REFUSED`, `UNAVAILABLE` or `INTERRUPTED`, retaining every attempt. Recovery first marks an incomplete prior attempt `INTERRUPTED`; it never guesses success. Eventual-consistency polling is bounded by the frozen deadline and deterministic injected clocks/barriers in tests, never unbounded sleeps.

A successful exact-prefix transition produces one immutable `computer.postcondition-receipt.v1` for that action. Each receipt binds a stable receipt ID/digest, action ID, intent key, workflow and contract digest, task, lineage, original epoch, policy revision, verifier and expectation-source identities/versions, account, verification sequence/time, prior verified prefix and complete current readback. Its cleanup record must exactly equal the action's durable cleanup history and its metadata digest must still bind the durable closed environment record. Executor-returned fields and caller-supplied `decision='VERIFIED'` are never accepted as receipts. A click no-op is missing its next target; a click that creates later targets is an extra-set failure. Neither can receive a successful receipt.

When the owned environment is conclusively absent and the independent readback conclusively contradicts the frozen predicate, the action becomes terminal `FAILED_POSTCONDITION`. This does not claim no effect: it records that the requested domain result was not achieved. Transport, cleanup, verifier, or readback ambiguity never uses that state and remains DISPATCHED until ordinary close/recovery preserves UNKNOWN.

## Atomic transition and recovery

`ComputerSession` already serializes ledger writes under an exclusive task/server lease. Receipt append and terminalization additionally retain the frozen output-authority lease. The transition re-reads the ledger and compares stored state, ordered action/intent, workflow/contract digest, task, lineage, original epoch and policy. A matching `DISPATCHED` action may become `VERIFIED`. Repeating the same receipt ID/digest returns the stored receipt; a different receipt or changed binding is refused. No history is overwritten.

If a crash occurs after the external effect but before the receipt, recovery preserves the raw action state as `UNKNOWN`. A later explicit trusted verification may append a bound authoritative resolution and receipt to that same action, but may not rewrite its `UNKNOWN` scalar or erase owner reconciliation. A pure effective-status function can report `VERIFIED_BY_POSTCONDITION` only when that appended receipt validates against the frozen contract and exact history; otherwise UNKNOWN remains unresolved. Ordinary model dispatch and retry stay blocked. Failed or unavailable verification leaves `DISPATCHED` or `UNKNOWN` unresolved.

## Task completion

Before its current early success for tasks with no ordinary gate, `check_done` derives the deterministic index and performs a bounded, secure census of the runtime-controlled `effects/computer` directory. It identifies every structurally valid action ledger whose stored lineage matches the task and compares that complete set with the committed index. Missing/deleted index plus matching history, extra or missing registered ledgers, census overflow, linked entries, malformed candidate ledgers, `PREPARED`/`ABORTED` index, or unreadable/mismatched records all fail closed. No index may pass only when the authenticated directory census contains no computer history for that lineage.

Every `required_for_task` workflow in a valid `COMMITTED` index must have exactly its frozen ordered intent set, each action must have a valid independent receipt or bound `VERIFIED_BY_POSTCONDITION` resolution, the verified IDs must equal the complete expected manifest, and no other critical `DISPATCHED`/unresolved `UNKNOWN` action may remain. A navigation-scoped `VERIFIED` action never satisfies an invoice task. Any legacy click in the lineage is unqualified and unresolved, with or without a workflow contract; it is never silently accepted as proof.

## First integration and exclusions

`computerbench` will independently supply the manifest, expectation-source and synthetic account identity, freeze all three intents/baseline, and run dispatch → quiesce → exact-prefix verification for each invoice. It will consume only validated receipts in `_development_status`; the raw UNKNOWN rule is not relaxed. Its acceptance and release fields remain false. The 36 development trials may run only when the pinned local Docker fixture is available; mocks cannot replace them.

This phase does not add general predicates, native desktop actions, new browser operations, live providers, OSWorld, Twin changes, or production deployment. UNKNOWN, `_development_status`, and `ACTION_DISPATCHED` retain their fail-closed meanings.
