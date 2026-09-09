# Task 1 report: single-reader MCP transport

Base: `2e3d3331d4d9d0cc4c65667eedbded6a22cc6d29` on `codex/bounded-computer-use`.
Workspace: `C:/Users/redab/OneDrive/Bureau/self learning 24.7 agent/computer-use-worktree`.

## Implementation

`mcp.Server` now starts exactly one daemon reader thread for its subprocess. It owns every stdout read, dispatches responses by integer request ID, and ignores notifications, server requests, and late/foreign IDs without retaining their contents. Each RPC registers an event-backed slot before dispatch. Separate send, ID, and pending locks protect writes, identifier allocation, and response/terminal-state ownership. A request timeout releases only that request's slot.

The controller supplied these exact values after the initial brief omitted numeric limits:

- `MAX_PENDING_REQUESTS = 64`.
- `MAX_FRAME_CHARS = 4_194_304`.
- The sole reader calls `readline(MAX_FRAME_CHARS + 1)`.
- `READER_JOIN_TIMEOUT_SECONDS = 2.0`.
- The existing caller-selected `Server.timeout` remains the response wait bound.

Oversized or unterminated frames, invalid JSON/non-object frames, pipe read failures, EOF, send failures, and explicit close establish a stable terminal error, clear pending ownership, and wake registered waiters. Subsequent dispatch is refused. Close publishes failure before killing a live child, waits/reaps the child and joins the reader against a shared two-second deadline, then closes the pipes. Killing first releases an in-progress pipe write from a child that stopped reading. Shutdown failure is explicit if the reader does not stop within the bound. Repeated close is supported.

The legacy `2025-06-18` protocol and newline framing remain the only implemented transport. This task adds neither a service daemon nor modern protocol/HTTP support.

## Tests and commands

All commands below ran from the workspace above. Strict TDD was used, following the test-driven-development skill and its writing-good-tests reference; verification-before-completion governed final reporting.

1. Wrote real Python subprocess fixtures before editing production code. The environment-grant test now requests its result through `_rpc`, because the removed private `_read_response` method was itself an extra stdout owner.
2. First RED command: `python tests/test_mcp_hardening.py`. It reported 14 tests, 3 failures and 7 errors in 40.058 seconds. One existing environment fixture had a missing flush after conversion to request/reply; that test-only mistake was fixed before accepting RED evidence.
3. Accepted RED command: `python tests/test_mcp_hardening.py`. Exit 1: **15 tests, 3 failures and 7 errors in 19.461 seconds**. The real concurrent test returned a timeout for A instead of A's response. The observed real stdout pipe was read by **3 distinct threads**, violating the single-reader requirement. EOF produced `TimeoutError` rather than a terminal transport failure. Capacity/cleanup assertions found no pending map, and overflow/malformed/unterminated frames did not establish the required terminal failure. Production `mcp.py` was still unchanged at this point.
4. Implemented the dispatcher. `python tests/test_mcp_hardening.py`: exit 0, **15 tests in 1.419 seconds, OK**.
5. `python tests/test_mcp.py`: exit 0, **PASS test_mcp**. It covered legacy negotiation, tool discovery/calls, fenced results, error reporting, caller-selected timeout, toolbox discovery, A2A card behavior, URL-argument guards, and image-result rendering. Some pre-existing console glyphs rendered as replacement characters in the tool output; tests passed.
6. `python mutate_check.py "mcp transport:"`: exit 0, **4 mutations caught, 0 missed, 0 skipped**. Caught mutations were a second stdout reader (6 seconds), wrong-ID delivery (2 seconds), retained timeout slot (3 seconds), and EOF leaving waiters asleep (7 seconds). The harness restored production source afterward.
7. Strengthened overflow/malformed fixtures to keep the subprocess alive after emitting bad data, proving overflow is detected without waiting for EOF. `python tests/test_mcp_hardening.py`: exit 0, **15 tests in 1.403 seconds, OK**.
8. `python -c "import mutate_check; print('Registered mutations:', len(mutate_check.MUTATIONS))"`: exit 0, **Registered mutations: 70**. Updated the README registration badge from 66 to 70.
9. `python tests/run_all.py *> .superpowers/sdd/2026-09-07-computer-use-reliability/task-1-full-suite.log; exit $LASTEXITCODE`: exit 1, **156 executed: 153 passed, 2 skipped, 1 failed**. Skips: `test_acquire.py`, `test_shutdown.py`. Failed: `test_git_operators.py`, before any test behavior ran. The traceback was `tests/test_git_operators.py:662 -> tests/common.py:95 -> os.makedirs(sb) -> FileExistsError: [WinError 183]` for `C:/Users/redab/AppData/Local/Temp/agent-suite/git-operators`. The existing harness had exhausted its ten `shutil.rmtree(ignore_errors=True)` / recreate retries against that stale sandbox. No Task 1 function appears on that stack. The failed log and old directory are preserved.
10. `git diff --check`: exit 0, no whitespace errors. Git printed existing CRLF normalization warnings for the two protected user files; they have no content diff and were not edited or staged.
11. Per controller instruction, a focused rerun was not substituted for the full-suite gate. Repeated the entire suite with a unique root, using PowerShell:

    ```powershell
    $task1TestRoot = Join-Path $env:TEMP ('agent-suite-mcp-transport-full-20260907-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $task1TestRoot | Select-Object -ExpandProperty FullName
    $env:AGENT_TEST_TMP = $task1TestRoot
    python tests/run_all.py *> .superpowers/sdd/2026-09-07-computer-use-reliability/task-1-full-suite-isolated.log
    exit $LASTEXITCODE
    ```

    Resolved root: `C:/Users/redab/AppData/Local/Temp/agent-suite-mcp-transport-full-20260907-67ab07adc8da468fa2b1a135976a527c`.
    Exit 1: **156 executed: 153 passed, 2 skipped, 1 failed**. Skips again were `test_acquire.py` and `test_shutdown.py`. `test_git_operators.py` passed. `test_twin.py` failed at `twin._write_json` opening an evaluation temporary file: the long unique root made that path **262 characters**. Its parent directory was verified to exist. The failure was `FileNotFoundError` on the `.json.<pid>.<uuid>.tmp` path; no Task 1 code appeared on the stack. This is consistent with the Windows legacy path-length limit.
12. Diagnostic probe only: created fresh `C:/Users/redab/AppData/Local/Temp/mcp-p-c014ac83`, set `AGENT_TEST_TMP` to it, and ran `python tests/test_twin.py *> .superpowers/sdd/2026-09-07-computer-use-reliability/task-1-twin-short-root.log; exit $LASTEXITCODE`. Exit 0: **PASS test_twin**. This was not substituted for a full-suite run.
13. Per controller instruction, started the **entire suite** again under a separate, short unique root. No production or test code was changed to suppress the path-length failure. Exact PowerShell command:

    ```powershell
    $task1ShortRoot = Join-Path $env:TEMP ('mcp-' + [guid]::NewGuid().ToString('N').Substring(0,8))
    $task1SamplePath = Join-Path $task1ShortRoot 'twin\experts\random-owner\twin\evaluations\fb5c3e0a0e2204580594d751454230d6ec481d21a85ada69df725fd0ceb5c49c.json.999999.1a80808929204c64907cfe76f62e0e50.tmp'
    if ($task1SamplePath.Length -ge 240) { throw 'Twin sample path too long' }
    Write-Output ('Twin sample path characters: ' + $task1SamplePath.Length)
    New-Item -ItemType Directory -Path $task1ShortRoot | Select-Object -ExpandProperty FullName
    $env:AGENT_TEST_TMP = $task1ShortRoot
    python tests/run_all.py *> .superpowers/sdd/2026-09-07-computer-use-reliability/task-1-full-suite-short-root.log
    exit $LASTEXITCODE
    ```

    Resolved root: `C:/Users/redab/AppData/Local/Temp/mcp-61b9e3f3`. Representative Twin evaluation temporary path: **203 characters** (including a six-digit PID), checked before launch. Both prior failed full-suite logs and their directories remain preserved.
    Exit 0: **156 executed: 154 passed, 2 skipped, 0 failed**. Skips: `test_acquire.py` and `test_shutdown.py`. Both `test_git_operators.py` and `test_twin.py` passed in this complete run, as did the MCP transport hardening file and existing MCP integration. This completed full-run ledger is the commit gate; neither a focused rerun nor a combination of earlier partial passes substitutes for it.

Focused coverage includes delayed A followed by notifications, foreign ID, late A, then B; one actual stdout owner across timeout and subsequent calls; reversed concurrent responses; two pending requests waking on EOF; overflow without EOF; unterminated/malformed frames; capacity refusal before dispatch; timeout capacity recovery; all 64 default slots and rejection of a 65th request; and deterministic process/reader shutdown with a pending call.

## Files changed

- `mcp.py`: bounded single-reader dispatcher and lifecycle.
- `tests/test_mcp_hardening.py`: subprocess behavior tests and environment fixture conversion.
- `mutate_check.py`: four registered transport mutations.
- `README.md`: mutation registration badge only.
- `.superpowers/sdd/2026-09-07-computer-use-reliability/task-1-report.md`: this report.

The raw full-suite logs are local evidence and are not part of the commit. Protected existing line-ending-only changes in `tests/mock_effect_server.py` and `ui.html` remain untouched and unstaged.

## Self-review and concerns

- No per-request thread reads stdout; the observer wraps the real child pipe and checks the actual calling thread objects and bounded readline argument.
- Pending registration precedes sending, so a fast response cannot race ahead of its slot. The slot result is retained locally after removal from the pending map, so EOF after a valid response does not replace the response with a failure.
- Timeout cleanup removes only its own ID. Response delivery and terminal failure publish under the pending lock. No pending lock is held during a blocking send or close/join.
- Terminal error is first-writer-wins. Close/EOF/overflow cannot reopen a connection; notifications and late replies consume no retained-state capacity.
- The approved frame limit counts decoded characters, including the line terminator, rather than bytes. This follows the controller's explicit ruling.
- These are offline subprocess and repository regression results, not live browser or release-readiness evidence. The task-owned session and action-state work remains in later tasks.
- The two full-suite environment failures remain documented rather than hidden. The clean full run uses a short unique test root; it does not claim to fix the existing shared-temp cleanup behavior or general Windows long-path support. Future suite runs on this host should start with a short unique `AGENT_TEST_TMP`.
- Response timeout does not remotely cancel a tool action. As in the existing transport, a caller blocked inside an OS pipe write is released by close; this task does not introduce an independent outbound-write deadline or process-tree containment.

Final status: Task 1 implemented and self-reviewed; focused tests pass, all four targeted mutations are caught, and the complete short-root suite passed with 154 passes, two explicit skips, and zero failures. Ready for the scoped Task 1 commit and independent review.
