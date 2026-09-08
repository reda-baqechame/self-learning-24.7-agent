# Task 5 recovery report

Status: DONE_WITH_CONCERNS, ready for controller review; base 97682c7,
branch codex/bounded-computer-use. Scoped implementation commit follows this
report update; no push or merge. Final whole-tree qualification remains Task 6.

Recovered partial changes: computersession.py, computeruse.py, mcp.py,
tests/computer_session_fixture.py and tests/test_computer_session.py.
The prior implementer recorded RED: five missing-module assertions in
tests/test_computer_session.py. Its first partial-code run hit Windows sandbox
Temp ACL denial; that is not product failure or GREEN evidence.

Binding scope: one task-owned isolated server lease, full owner config reload,
durable PREPARED before mutation and DISPATCHED before transport send, acknowledged
click pending independent verification, UNKNOWN immutable with appended owner
attestation. No paid providers, production actions, push, merge or workflow UI edits.
Protected tests/mock_effect_server.py and ui.html remain untouched.

Initial recovery checklist (now executed): run partial-code tests; complete Agent typed tools and lifecycle,
owner-only evidence-bound reconciliation, advisory-lock health and package privacy
regressions; mutation checks, registry/count update, one short-root full suite,
self-review and scoped commit. Qualification gaps: top-level origin is not network
containment; adapter covers invoice links; images are persisted but model image
transport remains unsupported by the existing budget boundary.

Commands/results and final concerns will be appended as execution proceeds.

## Recovery execution checkpoints

- `AGENT_TEST_TMP=C:/tmp/cs-recovery-0907 python tests/test_computer_session.py`:
  first recovered run, 5 tests, 3 passed, 1 failure and 1 error. Root cause:
  VERIFIED navigation was rejected as an unresolved duplicate, blocking restart.
- Added Agent/owner evidence/health/package regressions and ran the same command:
  10 tests, RED with 3 failures and 6 errors (including Windows logger handles
  retained by the test helper). Missing `close_computers` and `reconcile`, stale
  advisory-lock deletion advice, and private action ledger present in archive.
- After focused implementation: same command, 10 tests, PASS in 6.882 seconds.
  Tests cover real stdio reuse, crash PREPARED/DISPATCHED distinction, unknown
  retry refusal, explicit task attribution, owner policy revocation, Agent
  role/lifecycle/finally, owner evidence, lock diagnostics and archive privacy.
- Supervisor RED: `python tests/test_computer_session.py
  Sessions.test_owned_grandchild_stops_when_session_closes_or_owner_dies` failed
  because a real grandchild's marker grew 15 to 21 bytes after parent close.
  Bounded 5-second fixture lifetime also caused temporary-directory cleanup
  contention; this is retained failed evidence, not a test pass.
- Supervisor first run: 11 tests, 9 passed, 2 failures. The new real-grandchild
  test passed for normal close and killed owner. Old crash fixture expected its
  Python finally block to write an exit marker; OS job termination intentionally
  cannot run it. Replaced that marker assertion with supervisor closure readback;
  grandchild execution is independently tested by the new case.

## Approved cleanup scope expansion

Controller approved one focused `computerprocess.py` supervisor, MCP integration,
authority audit declaration and real child/grandchild tests. Windows supervisor
joins a non-inherited kill-on-close Job before spawning children; named unique
job cleanup checks active process count. POSIX supervisor owns a separate child
process group and accepts a CONTROL stop request, avoiding stale PID signaling
on recovery. Docker requires runtime-generated name/cidfile and exact container
cleanup/readback. Startup/cleanup without proof remains tainted and cannot reuse
the lease. Cross-OS behavior remains unqualified until CI; POSIX children that
deliberately detach are unsupported. Microsoft primary design reference:
https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects.

## Additional RED/GREEN and focused verification

- Durability RED: `python tests/test_computer_session.py
  Sessions.test_prepared_and_dispatched_are_fsynced_before_input`: 1 failure,
  PREPARED had no fsync. Added opt-in `durable=True` to File Authority text/JSON
  write; session ledger uses it before atomic replacement.
- Real Chromium first session run: open, reuse and click succeeded; cleanup
  refused because File Authority classified raw Docker CID as secret content.
  No container was left in subsequent Docker readback. Added narrow owned CID
  reader described above; no general credential/content bypass.
- `AGENT_COMPUTER_LIVE=1 python tests/test_computer_session.py`: 13 tests PASS,
  20.363s, including exact owned container absence readback.
- Focused four-test self-review: 2 RED (post-click image metadata dropped,
  replacement task dictionary inherited old lineage), 2 PASS (unproven cleanup
  retains taint/lease; owner death with wedged child stdin stops grandchild).
  Preserved post-click metadata and rebound current task identity at public entry.
- `python tests/test_computer_session.py`: 16 tests PASS, 19.061s, Chromium
  explicitly NOT_RUN for this invocation; `python tests/test_computeruse.py`:
  16 PASS; `python tests/test_mcp_hardening.py`: 15 PASS.
- Final self-review RED: off-origin navigation after dispatch was mislabeled
  REFUSED; explicit empty role tools list allowed direct computer entry. Both
  tests failed before fixes. Post-dispatch navigation is now UNKNOWN; explicit
  empty computer tool allowlists deny.
- Latest focused checkpoint: `AGENT_COMPUTER_LIVE=1 python
  tests/test_computer_session.py`: 18 PASS in 22.405s; `python
  tests/test_harness.py`: PASS, 19 tools; `python tests/test_ledger_defects.py`:
  PASS, 158 registered tests / 104 mutations; `python execution.py --audit`:
  0 violations across 121 modules, 19 declared platform internals.

New acceptance file registered in both tests/run_all.py and evidence.py.
Mutations and the single full-suite invocation are next; no complete/release
claim is made at this checkpoint.

Mutation verification: `AGENT_TEST_TMP=C:/tmp/cs-mut-0907 python mutate_check.py
'computer session:'` completed with **13 caught, 0 missed, 0 skipped**. Captured
output: `task-5-mutations.log`. The harness restored each source byte-for-byte;
no simultaneous edits/tests ran. All 13 targeted lifecycle/authority/durability
protections made their acceptance test fail when removed. Raw-evaluator exclusion
uses the existing browser-authority test. Full suite begins next with both
registries and README badges already checked at 158 tests / 104 mutations.

## Single full-suite result (pre-correction tree)

`AGENT_TEST_TMP=C:/tmp/c5f-1949 AGENT_COMPUTER_LIVE=1 PYTHONUTF8=1
python tests/run_all.py`, captured through PowerShell Tee-Object in
`task-5-full-suite.log`: **158 executed, 154 passed, 2 skipped, 2 failed**.
Windows Python 3.14, September 7 2026, approximately 19:50-20:18 local.
Failures: test_invariants.py found ARCHITECTURE.md's stale 119-module count
(actual 121); test_providers.py compared a mixed-separator fixture root against
a normalized sibling temporary path. Skips: test_acquire.py, test_shutdown.py.
Existing browser 16, pinned Chromium 17 cases and task session 18 tests passed
(session 22.924s). This is NOT a green full suite. Captured log remains unchanged.
Controller approved focused post-suite viewport/provenance and best-effort-all
cleanup corrections plus coupled documentation counts; Task 6 must run the final
whole-tree suite. A native-backslash focused provider run will check the path
diagnosis without modifying prior Task 2 code.

## Post-suite corrective pass

- Three-test RED, `AGENT_TEST_TMP=C:\tmp\c5-correct python
  tests/test_computer_session.py Sessions.test_view_context_is_sealed_and_changed_viewport_refuses
  Sessions.test_unavailable_view_context_is_explicit
  Sessions.test_agent_cleanup_attempts_all_owned_sessions_after_failure`:
  2 errors (missing view_context), 1 failure (second session remained active).
  Captured `task-5-correction-red.log`.
- First full focused session attempt: 21 tests, 2 failures / 15 errors in
  30.853s (`task-5-correction-green.log`). Root cause: legacy BrowserAuthority
  strictly rejects added state fields. Kept metadata in the signed task envelope
  and removed it before legacy state validation, preserving that contract.
- Corrected run: `AGENT_TEST_TMP=C:\tmp\c5-correct AGENT_COMPUTER_LIVE=1 python
  tests/test_computer_session.py`: **21 PASS, 28.910s**, captured
  `task-5-correction-green-2.log`. Real pinned Chromium measured host viewport,
  changed it through host Playwright, refused the old receipt before click, then
  used a fresh receipt. Scale is explicitly page-untrusted; absent data is null.
  No screenshot-coordinate authority is exposed. Two real sessions prove later
  cleanup proceeds while first failure keeps taint, lease and aggregate error.
- ARCHITECTURE.md and REFERENCE.md current counts corrected to 121 modules /
  158 acceptance files. Two new mutation entries bring registration to 106.
- Parsing the pre-correction captured log with `evidence.py --from ... --out
  task-5-evidence-pre-correction.md` exited 1 (FAILING). Its summary says 155/158,
  inconsistent with the authoritative full-run footer; no green conclusion is
  taken from that generated summary. Controller notified for Task 6 qualification.
- `AGENT_TEST_TMP=C:\tmp\c5-correct AGENT_COMPUTER_LIVE=1 PYTHONUTF8=1
  python mutate_check.py 'computer session correction:'`: **2 caught, 0 missed,
  0 skipped**, viewport 23s, cleanup-all 25s, `task-5-correction-mutations.log`.
  All sources restored. The viewport mutant now declares its required live
  environment explicitly so an unrequested browser run cannot be mistaken for a
  miss/catch in ordinary CI. Together with the prior 13 this is 15 new caught
  mutations, not a claim that all 106 registered mutations ran in this task.

## Final restored-tree focused verification

PowerShell set `AGENT_TEST_TMP=C:\tmp\c5-final`, `AGENT_COMPUTER_LIVE=1`,
`PYTHONUTF8=1`, then sequentially ran the following commands, capturing all output
with `Tee-Object -Append task-5-final-focused.log` and counting nonzero exits.
The aggregate command exited **0**; no source edits or mutations ran concurrently.

- `python tests/test_computer_session.py`: 21 PASS, 28.116s.
- `python tests/test_computeruse.py`: 16 PASS, 0.590s.
- `python tests/test_mcp_hardening.py`: 15 PASS, 1.426s.
- `python tests/test_providers.py`: PASS with native-backslash root, including
  concurrent transactions/interruption. No provider source or test edits.
- `python tests/test_invariants.py`: PASS; 121 modules, 158 acceptance files,
  zero execution audit violations, 19 declared internals, current prose matches.
- `python tests/test_ledger_defects.py`: PASS, badges 158 tests / 106 mutations.
- `python tests/test_computeruse_live.py`: PASS, all 17 cases on pinned
  Chromium 152.0.7977.8, local synthetic network-none fixture only.
- `AGENT_COMPUTER_LIVE=0 python mutate_check.py 'computer session correction: viewport'`:
  exactly one explicit prerequisite SKIP, no browser launched. Source anchor
  check found exactly one anchor for each of all 15 Task 5 mutations.
- `git diff --check`: PASS. Protected dirty file SHA256 unchanged:
  `tests/mock_effect_server.py` =
  `7CA5E3E55BAE18A1E7FE04E06ECBDAB8CC2174F01C812538F8FBF5D6BDDFB2BF`;
  `ui.html` = `E7E050E58A9E5D39FC8919FD6D10DC65F7DA1190C5680DEC6502CDCBB6086BBF`.

## Scoped files and self-review

New runtime: computersession.py (lease, envelope, ledger, owner intervention),
computerprocess.py (owned process/job/container closure). New tests:
tests/computer_session_fixture.py and tests/test_computer_session.py.
Integration: loop.py, computeruse.py, mcp.py, fileauth.py (opt-in fsync),
harness.py (persistent-lock diagnosis), package.py (private state exclusion),
execution.py/doctor.py (authority/import declarations). Registries and counts:
tests/run_all.py, evidence.py, mutate_check.py, tests/test_harness.py, README.md,
ARCHITECTURE.md, REFERENCE.md. Design: docs/DESIGN-task-owned-computer-session.md.
This report is included; raw local logs remain available beside it but are not
packaged or broadly staged. No ui.py, goal.py, contract.py, protected dirty files
or other worktrees were edited.

Self-review inspected the full session/supervisor source and integration diff,
direct role boundaries, current task lineage, fsync ordering, pending intent
semantics, immutable UNKNOWN history, owner evidence authority, physical artifact
readback, fail-closed cleanup, package exclusions and mutation restoration.
The review found and corrected post-click image loss, stale task-dict ownership,
off-origin post-navigation misclassification, empty allowlist bypass, missing
viewport/provenance and early-abort cleanup. TDD, systematic debugging and
verification-before-completion skills drove failing regressions before each fix
and preserve failed results instead of replacing them with later passes.

Remaining concerns / qualification limits:

- The single full run FAILED before the final corrections. Final Task 6 suite,
  controller spec/quality review, full mutation matrix and OS/Python CI remain
  required. Windows Job behavior is locally tested; POSIX group behavior is not
  qualified here, and deliberately detached POSIX children are unsupported.
- Top-level origin validation is not network containment. Only the tested
  network-none Docker fixture proves that deployment's network scope. Reviewed
  executable/shell-script internals remain trusted owner code; external/shared
  attachment flags are refused, not generally inferred through arbitrary scripts.
- File fsync and atomic replacement prove process-crash boundaries tested here,
  not a whole-system power-loss/directory-fsync guarantee.
- CSS invoice-link actions are supported; screenshot-coordinate actions are not.
  Page scale is untrusted observation, not authority. No model image transport,
  invoice business verifier, live provider, production or release proof is claimed.
- Cleanup failure is surfaced and retains taint/exclusion; it does not claim
  the external environment is closed. Runtime finalization attempts all sessions.
- Existing README historical CI-green/112-test prose is not evidence for this
  tree. The pre-correction generated evidence summary discrepancy and native-path
  provider fixture portability are explicitly handed to Task 6, not silently fixed.
