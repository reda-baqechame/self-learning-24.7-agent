# Task-owned computer session reliability

Status: owner-approved implementation specification, 2026-09-07. This is not
release evidence and does not authorize production actions.

## Boundary

One agent task owns one runtime-managed MCP browser process and browser session.
This increment does not add a network-accessible broker daemon. The runtime,
not the model, owns connection state, the session lease, policy, deadlines,
cancellation, action ordering, evidence storage and cleanup.

The initial public action vocabulary is `open`, `observe` and `click`. It does
not expose model-authored JavaScript or the raw evaluator. Navigation is an
authorized action. Fill, select, scroll, keyboard, upload and download controls
require separate later specifications and tests.

## Required invariants

- One stdout reader/dispatcher serves one MCP process. It routes responses by
  request ID, handles notifications, late replies and EOF, bounds pending
  requests and frames, and does not leave a timed-out reader consuming stdout.
- Browser mutations are serialized. A transport failure after dispatch yields
  `UNKNOWN`, taints the session and cannot be retried automatically.
- A task owns a session lease with `created`, `active`, `closing`, `closed` and
  `tainted` states. A restart changes the epoch and invalidates old observation
  authority without deleting unresolved action history.
- Observations bind task, session, epoch, sequence, tab, frame, URL/origin,
  timestamp, policy revision, viewport, scale, structured target state and any
  immutable screenshot artifact/hash. A screenshot hash does not prove the
  whole application is unchanged.
- Receipts are refused when stale, foreign, tampered, expired or consumed.
  Target-specific predicates avoid invalidating actions for unrelated animation.
- Click means user-like input. The target must be uniquely identified, visible,
  stable, enabled, hit-testable and bound to the observed tab/frame. Host-owned
  adapter code rechecks before dispatch and returns a fresh post-action
  observation. Programmatic DOM activation is not the default click.
- Action records progress through `PREPARED`, `DISPATCHED`, then `VERIFIED`,
  `REFUSED`, `FAILED_WITH_KNOWN_NO_EFFECT` or `UNKNOWN`. Dispatch acknowledgment,
  UI change, business effect and task completion remain distinct.
- Remote exactly-once effects are not claimed. Unknown outcomes require an
  independent reconciliation result or owner intervention.
- Provider read/modify/write is one locked transaction. Unique temporary files
  and atomic replacement preserve arbitrary nested/unrelated TOML and avoid
  collisions; interrupted writes leave the prior valid file.
- Binary MCP artifacts are immutable and content-addressed. Observation
  receipts bind original bytes, digest, dimensions and provenance.
- Browser origins, redirects, popups, network, downloads, uploads, filesystem,
  profiles and credentials remain owner-configured and fail closed.
- Page text, screenshots, downloads and retained lessons are untrusted data and
  cannot grant authority or redefine the task.

## Evidence boundary

Development fixtures, including the 36 portal trials, stay development-only.
Acceptance uses an independently maintained unseen set. Release requires the
declared OS/Python matrix, mutations, real local-browser tests and separately
authorized live-provider tests. Report verified completion, false success,
unauthorized effects, abstention, recovery, duplicates, intervention, cost and
latency. No aggregate score or compatible API establishes industry leadership.
