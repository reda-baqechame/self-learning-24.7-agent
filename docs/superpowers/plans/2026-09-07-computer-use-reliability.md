# Computer Use Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build one task-owned, persistent, governed browser interaction loop after repairing the transport, configuration, evidence-storage and click-semantics primitives it depends on.

**Architecture:** `mcp.Server` owns one bounded reader/dispatcher for its process. A focused `computersession.py` module owns task/session lifecycle, typed operations and durable action records while `loop.Agent` exposes only narrow model tools. Existing `computeruse.py` authority and artifact verification remain the policy/receipt layer.

**Tech Stack:** Python 3.11+ standard library, MCP legacy stdio protocol `2025-06-18`, repository acceptance harness, Playwright MCP for real-browser qualification.

**Spec:** `docs/DESIGN-task-owned-computer-session.md`

## Global Constraints

- Preserve `main`, the Claude remediation worktree, the Twin worktrees and the two pasted source documents.
- Pin integration base `fc08b7f4a65f07bc77b269e7ef2b03cbfb548be2`; build on branch checkpoint `3e9dce7edf2fafec293d1c097a1242ec245e9fdf`.
- Standard-library production dependencies only.
- No network-accessible broker daemon and no unrestricted model-authored evaluator.
- One session lease per task; one reader/dispatcher per MCP process; serialized browser mutations.
- A lost response after dispatch is `UNKNOWN`; do not automatically repeat it.
- Keep development, acceptance and release flags separate and false until their own evidence gates pass.
- Do not call paid providers or perform unapproved production actions.
- Use test-first RED/GREEN cycles and commit each independently reviewed task.

---

### Task 1: Single-reader MCP transport

**Files:**
- Modify: `mcp.py`
- Modify: `tests/test_mcp_hardening.py`

**Interfaces:**
- Consumes: existing `Server._rpc(method, params)` and newline JSON-RPC transport.
- Produces: one reader thread per `Server`, ID-routed pending responses, bounded requests/frames, deterministic EOF/close errors, and thread-safe sends.

- [ ] **Step 1: Write failing transport tests**

Add real subprocess fixtures that delay request A past its timeout, then answer B; emit notifications and late A before B; close stdout with B pending; emit an oversized frame; and issue two concurrent calls. Assert B receives B, EOF wakes waiters, oversize taints the connection, pending capacity refuses before dispatch, and exactly one reader owns stdout.

- [ ] **Step 2: Verify RED**

Run: `python tests/test_mcp_hardening.py`

Expected: the delayed-response test times out B or demonstrates more than one stdout reader; the new bounded-state assertions fail on the current implementation.

- [ ] **Step 3: Implement the minimal dispatcher**

In `Server.__init__`, create one send lock, ID lock, pending map lock, pending map, terminal-error field and daemon reader thread. `_rpc` registers a bounded pending slot before sending and waits on that slot. The reader alone calls `stdout.readline()`, parses one bounded frame, routes matching IDs, ignores/logs notifications and late IDs, and wakes every pending waiter on EOF/malformed-overflow failure. Timeout removes only its own slot. `close()` marks terminal state, wakes waiters, closes/kills deterministically and joins the reader within the declared timeout.

- [ ] **Step 4: Verify GREEN and regressions**

Run: `python tests/test_mcp_hardening.py`

Run: `python tests/test_mcp.py`

- [ ] **Step 5: Add transport mutations and commit**

Add mutations for a second reader, wrong-ID delivery, timeout slot retention and EOF not waking waiters. Run `python mutate_check.py "mcp transport:"`, update the registered mutation badge, then commit only Task 1 files.

---

### Task 2: Transactional provider updates

**Files:**
- Modify: `providers.py`
- Modify: `tests/test_providers.py`
- Modify: `mutate_check.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `locks.holding(path)` and the lossless recursive TOML serializer.
- Produces: `_update(root, mutate)` holding one cross-process lock across load, mutation and unique-temp atomic save; `add` and `set_role` use it.

- [ ] **Step 1: Write failing concurrency and interruption tests**

Run two threads/processes whose mutations update different root sections while deliberately interleaved. Assert both changes and every original nested value survive. Force replacement failure after a fully flushed unique temporary file and assert the original settings still parse and no shared `.tmp` collision occurs.

- [ ] **Step 2: Verify RED**

Run: `python tests/test_providers.py`

Expected: one writer raises or one independent update is lost against the current shared `settings.toml.tmp` lifecycle.

- [ ] **Step 3: Implement one locked read-modify-write transaction**

Add `_update(root, mutate)` using `locks.holding(settings_path + ".update", timeout=20, stale=60)`. Within the lock, load current bytes, apply the callable to the current parsed mapping, serialize, validate, write through `tempfile.mkstemp` in the same directory, flush/fsync, `os.replace`, and clean only that unique temp on failure. Keep public `save` atomic and unique-temp; route `add` and `set_role` through `_update` so locking covers the read.

- [ ] **Step 4: Verify GREEN and semantic round-trip**

Run: `python tests/test_providers.py`

Run a temporary full-`settings.toml` `load -> save -> load` equality check.

- [ ] **Step 5: Add mutations and commit**

Mutate away the transaction lock, unique temp and fresh in-lock load; prove the concurrent test catches each. Run `python mutate_check.py "providers:"`, update the mutation badge, and commit only Task 2 files.

---

### Task 3: Immutable MCP image evidence

**Files:**
- Modify: `mcp.py`
- Modify: `tests/test_mcp.py`
- Modify: `mutate_check.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: MCP image/audio/blob content blocks and the expert-local `tmp/` zone.
- Produces: content-addressed immutable artifact metadata `{path, sha256, bytes, mime, width, height}` returned by `render_result` and usable by observation receipts.

- [ ] **Step 1: Write failing immutable-storage tests**

Freeze time and render two different same-index PNG blocks in one second. Assert distinct paths and preserved original bytes. Render identical bytes twice and assert the same immutable content-addressed path without rewriting. Include malformed and oversized payload refusal. Use literal PNG fixtures with independently known SHA-256 and dimensions.

- [ ] **Step 2: Verify RED**

Run: `python tests/test_mcp.py`

Expected: the second current image overwrites the first timestamp/index path.

- [ ] **Step 3: Implement content-addressed writes**

Hash decoded bytes, derive `tmp/mcp-artifacts/<sha256><validated-extension>`, create the directory, write with exclusive unique-temp plus atomic replace, and never replace an existing digest path. Parse PNG/JPEG/WebP dimensions with bounded standard-library byte inspection; use `null` dimensions when unsupported rather than guessing. Render the literal metadata needed to bind a receipt.

- [ ] **Step 4: Verify GREEN**

Run: `python tests/test_mcp.py`

Run: `python tests/test_computeruse.py`

- [ ] **Step 5: Add image mutations and commit**

Add mutations for dropping the digest from the name and accepting a same-path overwrite. Run `python mutate_check.py "mcp image:"`, update the badge, then commit only Task 3 files.

---

### Task 4: User-like bounded click semantics

**Files:**
- Modify: `computeruse.py`
- Modify: `tests/test_computeruse.py`
- Modify: `mutate_check.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `BrowserAuthority` observation receipts and owner-approved Playwright MCP server identity.
- Produces: host-generated locator-based click request with visibility, stability, enabled, hit-test, unique target, tab/frame and origin predicates; result distinguishes dispatched action from verified workflow.

- [ ] **Step 1: Write failing actionability tests**

Extend controlled browser fixtures for hidden, covered, `disabled`/`aria-disabled`, detached, duplicate, moved, cross-frame and tab-swapped targets. Assert every invalid target refuses before activation and produces no effect. Assert a visible stable unique target dispatches once and still does not imply business success.

- [ ] **Step 2: Verify RED**

Run: `python tests/test_computeruse.py`

Expected: current `a.click()` activates hidden, covered or disabled fixtures.

- [ ] **Step 3: Replace DOM activation**

Make the host adapter call a reviewed Playwright locator action rather than `HTMLElement.click()`. Use a host-generated exact selector derived from sealed target identity, request Playwright actionability, and keep a preflight observation immediately before dispatch. Label the receipt `ACTION_DISPATCHED`; return a fresh post-action observation separately. Never call the raw evaluator from model arguments.

- [ ] **Step 4: Verify GREEN in mock and real local Chromium**

Run: `python tests/test_computeruse.py`

Run the repository-controlled real-browser actionability fixture with no external network or provider calls; record browser/version and each positive/refusal outcome.

- [ ] **Step 5: Add actionability mutations and commit**

Mutate away visibility, enabled, hit-test, tab/frame and post-observation requirements. Run `python mutate_check.py "computer:"`, update the badge, then commit only Task 4 files.

---

### Task 5: Task-owned session and durable action state

**Files:**
- Create: `computersession.py`
- Modify: `loop.py`
- Modify: `computeruse.py`
- Create or modify: `tests/test_computer_session.py`
- Modify: `tests/run_all.py`
- Modify: `mutate_check.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: repaired `mcp.Server`, `BrowserAuthority`, immutable artifact metadata, task ID/lineage and configured MCP server/policy.
- Produces: `ComputerSession(root, task, server_name, policy_revision)` with `open(url)`, `observe()`, `click(receipt, target_id)`, `close(reason)` and durable action ledger states.

- [ ] **Step 1: Write failing lifecycle tests**

Use a real local MCP fixture process. Across multiple simulated model turns, assert one process/session/tab is reused; a second task cannot claim the lease; pause retains exclusive ownership; completion/cancel/browser death close or taint deterministically; restart changes epoch and refuses old receipts; model failover preserves the same runtime session; and close leaves no child process.

- [ ] **Step 2: Write failing action-ledger tests**

Assert intent/idempotency is durably `PREPARED` before dispatch, becomes `DISPATCHED` before waiting for response, and ends in exactly one terminal state. Kill before dispatch and after dispatch to prove `FAILED_WITH_KNOWN_NO_EFFECT` and `UNKNOWN` differ. Assert an unknown consequential action cannot repeat until independent reconciliation or owner intervention is recorded.

- [ ] **Step 3: Verify RED**

Run: `python tests/test_computer_session.py`

Expected: module/tools are absent and current CLI lifecycle cannot preserve one session across turns.

- [ ] **Step 4: Implement the session manager and typed tools**

Keep connection/session/action state in `computersession.py`. Add `computer_open`, `computer_observe`, `computer_click` definitions and `loop.Agent.exec_tool` branches. The Agent owns managers by task ID, never exposes raw JavaScript, serializes mutation calls, preserves blocked-task leases, and closes sessions in task completion, cancellation, unrecoverable failure and process-finally paths. `open` validates the owner-named server and origin before dispatch. `click` consumes a sealed receipt and records the state machine before and after the transport call.

- [ ] **Step 5: Verify GREEN and failure recovery**

Run: `python tests/test_computer_session.py`

Run: `python tests/test_computeruse.py`

Run: `python tests/test_mcp_hardening.py`

- [ ] **Step 6: Add lifecycle/action mutations and commit**

Mutate session reuse, task ownership, epoch invalidation, PREPARED-before-dispatch, UNKNOWN no-retry, cleanup and raw-evaluator exclusion. Run the new mutation filter, update the badge/test registry, and commit only Task 5 files.

---

### Task 6: Qualification and honest release reporting

**Files:**
- Create: `computerbench.py`
- Create: `tests/test_computerbench.py`
- Modify: `tests/run_all.py`
- Modify: `docs/DESIGN-bounded-computer-use.md`
- Modify: `REFERENCE.md`
- Modify: `MANUAL.md`
- Modify: `EVIDENCE.md` only through the repository evidence generator

**Interfaces:**
- Consumes: completed persistent loop and all primitive gates.
- Produces: development report, independently labeled acceptance report, capability matrix schema and unchanged false release flag until every gate passes.

- [ ] **Step 1: Re-run development fixtures**

Run the 36 portal variants with pinned source/browser/tool hashes. Report verified completions, safe refusals, rejected artifacts, unknowns, duplicates and cleanup; do not translate expected refusals into task success.

- [ ] **Step 2: Add the external acceptance-pack contract**

Implement a runner that accepts a separately supplied, content-sealed pack with provenance and variants across layout, wording, timing, authentication and multistep dependency. Freeze model/tool/policy/budget/retry/human-help settings and label browser-only, desktop and API-assisted tracks separately. `tests/test_computerbench.py` proves malformed, repository-authored, changed or unsealed packs cannot set acceptance true; it uses synthetic contract fixtures and must not label them independent acceptance evidence. If no externally maintained pack is supplied, record `acceptance_complete=false` and the missing evidence rather than creating one inside this implementation task.

- [ ] **Step 3: Run repository gates**

Run `python tests/run_all.py`, `python mutate_check.py`, `python execution.py --audit`, package/invariant checks, and all configured CI OS/Python jobs. Preserve every skip with its reason. Paid/live-provider checks remain not-run without explicit cost authorization.

- [ ] **Step 4: Update documentation from evidence**

Document that API compatibility is not model competence, DOM/action dispatch is not business success, and development is not acceptance/release. Correct any MCP protocol-era statement to the implemented `2025-06-18` legacy stdio scope. Keep `acceptance_complete=false` and `release_ready=false` unless every independent gate supplies evidence.

- [ ] **Step 5: Commit qualification artifacts**

Commit generated evidence and documentation without merging. Request final whole-branch review before presenting merge options.
