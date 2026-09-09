# Task 2: Transactional provider updates

Base: `9a221817cf75f45652cb818488f313f80bd7c99a`. Scope: provider settings transactions only. The TDD skill and its writing-good-tests reference were read before tests were written. No dependencies, MCP changes, browser changes, or subagent dispatch were introduced.

## Change and contract

`add` and `set_role` now use `_update(root, mutate)`. It acquires `locks.holding(settings_path + ".update", timeout=20, stale=60)` before loading settings and holds it through mutation, recursive serialization, TOML validation, and atomic replacement. Provider existence checking and preservation of existing role fields happen against the fresh mapping inside the lock. Public return values remain the provider/role mapping.

Public `save` remains a whole-configuration replacement operation. It creates a unique `tempfile.mkstemp` file in the destination directory, writes and flushes its text, calls `os.fsync`, closes it, and calls `os.replace`. Its `finally` removes only the unique file allocated by that save if replacement failed. It never claims or cleans the old shared `settings.toml.tmp` name.

## TDD evidence

All commands below ran from `C:\Users\redab\OneDrive\Bureau\self learning 24.7 agent\computer-use-worktree` on Windows.

1. RED, before any production changes:

   ```powershell
   python tests/test_providers.py
   ```

   Exit 1; exact output:

   ```text
   Traceback (most recent call last):
     File "C:\Users\redab\OneDrive\Bureau\self learning 24.7 agent\computer-use-worktree\tests\test_providers.py", line 387, in <module>
       main()
       ~~~~^^
     File "C:\Users\redab\OneDrive\Bureau\self learning 24.7 agent\computer-use-worktree\tests\test_providers.py", line 209, in main
       concurrent_updates(sb)
       ~~~~~~~~~~~~~~~~~~^^^^
     File "C:\Users\redab\OneDrive\Bureau\self learning 24.7 agent\computer-use-worktree\tests\test_providers.py", line 121, in concurrent_updates
       assert after["roles"].get("concurrent-role") == {
              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
           "provider": "m", "model": "concurrent-model"}, "independent role update lost"
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
   AssertionError: independent role update lost
   ```

   This exercises actual public `add` and `set_role` calls, with real loading, file locking (when present), serialization, filesystem writes, and replacement. Wrappers only pause the first save and observe the second writer's load/lock boundary. Separate literal assertions require the added provider AND the added role to survive; removing both new entries must leave the original parsed mapping equal in full, including its nested HTTP endpoint, memory router, and unrelated `acquire` section. The baseline lost the role edit silently; both writer threads returned successfully.

2. RED, independent interruption test, still before production changes:

   ```powershell
   python -c "import sys; sys.path.insert(0, 'tests'); import test_providers as t; sb=t.make_sandbox('providers_interrupt_red', providers={'m': {'script': 's.json'}}, roles={'tester': 'm'}, scripts={'s.json': []}); t.interrupted_saves(sb)"
   ```

   Exit 1; exact output:

   ```text
   Traceback (most recent call last):
     File "<string>", line 1, in <module>
       import sys; sys.path.insert(0, 'tests'); import test_providers as t; sb=t.make_sandbox('providers_interrupt_red', providers={'m': {'script': 's.json'}}, roles={'tester': 'm'}, scripts={'s.json': []}); t.interrupted_saves(sb)
                                                                                                                                                                                                                ~~~~~~~~~~~~~~~~~~~^^^^
     File "C:\Users\redab\OneDrive\Bureau\self learning 24.7 agent\computer-use-worktree\tests\test_providers.py", line 170, in interrupted_saves
       assert len(replaced) == 2 and len({row[0] for row in replaced}) == 2, \
              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
   AssertionError: concurrent saves collided on a shared temporary file
   ```

   Both real public saves reach an injected replacement failure together. The test verifies two distinct source paths, destination-directory placement, complete parseable bytes, real `fsync` before replacement (matching file identity and size), unchanged original bytes and parsed data, removal of each failed writer's own temporary file, and survival of a preexisting foreign `settings.toml.tmp` sentinel. The separate RED sandbox remains at `C:\Users\redab\AppData\Local\Temp\agent-suite\providers_interrupt_red`. The first concurrency RED traceback is preserved above; subsequent focused runs reused its ordinary `providers` sandbox.

3. GREEN, after implementation:

   ```powershell
   python tests/test_providers.py
   ```

   Exit 0; exact output:

   ```text
   [transaction] concurrent public add + set_role preserve both edits and all original settings
   [interruption] concurrent failed replacements preserve original and foreign temp; unique temps fsynced and cleaned
   [add] known rail + custom endpoint added; settings round-tripped losslessly; only key NAMES are written
   [roles] any role re-pointed at any provider/model incl. fallback + escalation; unknown providers refused
   [catalog] models listed from a live /models endpoint; free-only and text filters work
   [custom] your own tools appear as capabilities, honour ready_check, and reach agents with the exact command to run
   created expert 'any-expert' at C:\Users\redab\AppData\Local\Temp\agent-suite\providers_fleet\experts\any-expert
     teach it:  drop files in C:\Users\redab\AppData\Local\Temp\agent-suite\providers_fleet\experts\any-expert\inbox
                python ingest.py add-url <url> --root C:\Users\redab\AppData\Local\Temp\agent-suite\providers_fleet\experts\any-expert
     run it:    python loop.py run --root C:\Users\redab\AppData\Local\Temp\agent-suite\providers_fleet\experts\any-expert
   [fleet-tools] a tools.json at the fleet home reaches every expert in it
   2026-09-07 15:16:22,928 {"event": "provider_autowired", "provider": "xai", "key_env": "XAI_API_KEY", "note": "from the KNOWN catalog; make it durable with `python providers.py add`"}
   2026-09-07 15:16:22,928 {"event": "provider_autowired", "provider": "cloudflare", "key_env": "CLOUDFLARE_API_TOKEN", "note": "from the KNOWN catalog; make it durable with `python providers.py add`"}
   [plug] a key in the environment IS a provider: a role named a rail with no settings entry and it wired from the verified catalog at runtime; keyless rails refuse naming the exact env var; cloudflare's missing account id is a named error at wire time; an explicit settings entry always outranks the catalog
   PASS test_providers
   ```

4. Full repository settings semantic round-trip:

   ```powershell
   python -c "import tempfile, providers; before=providers.load('.'); tmp=tempfile.mkdtemp(prefix='providers-roundtrip-'); providers.save(tmp, before); after=providers.load(tmp); assert after == before; print('PASS full settings.toml load -> save -> load equality:', len(before), 'root entries; artifact:', tmp)"
   ```

   Exit 0:

   ```text
   PASS full settings.toml load -> save -> load equality: 3 root entries; artifact: C:\Users\redab\AppData\Local\Temp\providers-roundtrip-bl8guu4d
   ```

   The checked-in settings file was only read. The round-trip artifact remains in that temporary directory.

5. Mutation check:

   ```powershell
   python mutate_check.py "providers:"
   ```

   Exit 0; output (the terminal's replacement glyph for the harness dash is retained):

   ```text
   ==============================================================================
   MUTATION RESULTS � a MISSED row is a test that measures nothing
   ==============================================================================
     CAUGHT  providers: unrelated root settings dropped
             test_providers.py failed in 1s � provider edits must preserve unrelated root tables
     CAUGHT  providers: nested tables stringified
             test_providers.py failed in 1s � provider edits must preserve nested tables as tables
     CAUGHT  providers: transaction lock removed
             test_providers.py failed in 0s � concurrent public add and set_role must both survive
     CAUGHT  providers: shared temporary file
             test_providers.py failed in 1s � concurrent failed saves must isolate and clean only their own temps
     CAUGHT  providers: stale load before transaction lock
             test_providers.py failed in 1s � the waiting public update must read the preceding commit

   5 mutations: 5 caught, 0 missed, 0 skipped
   ```

   New mutants remove the transaction lock, replace `mkstemp` with the shared truncating path, and move the settings load before lock acquisition. The public-operation concurrency test protects the lock/fresh-read boundary; the concurrent failed-save test protects unique-temp isolation. The mutation harness restores the production file after each mutant. Registration count independently printed `registered mutations: 73`, matching the updated README badge. This is a registration count, not a claim that all 73 mutations were run.

## Complete suite

One complete suite invocation, with a new short root:

```powershell
$env:AGENT_TEST_TMP = 'C:\tmp\p2-' + [guid]::NewGuid().ToString('N').Substring(0,8)
New-Item -ItemType Directory -Path $env:AGENT_TEST_TMP | Out-Null
Write-Output "AGENT_TEST_TMP=$env:AGENT_TEST_TMP"
python tests/run_all.py 2>&1 | Tee-Object -FilePath '.superpowers/sdd/2026-09-07-computer-use-reliability/task-2-full-suite.log'
exit $LASTEXITCODE
```

Resolved root: `C:\tmp\p2-c8896869`. Full raw output is retained in `.superpowers/sdd/2026-09-07-computer-use-reliability/task-2-full-suite.log` as local evidence, outside the scoped commit.

Exit 0. Exact suite footer:

```text
156 executed: 154 passed, 2 skipped, 0 failed  [skipped: test_acquire.py, test_shutdown.py]
ALL EXECUTED TESTS PASSED � the skipped ones proved nothing here; their reasons are printed above and counted in EVIDENCE.md
```

The two whole-file skips are acquisition without a configured isolated sandbox and the Windows-inapplicable SIGTERM shutdown test. Additionally, `test_research_discovery.py` reports `OK (skipped=1)` for its symlink case (`symlink privilege unavailable`); the runner counts that file among the passes. Provider tests, MCP hardening, Git operators, Twin, Twin measurement, and computer-use all passed within this same complete run. There was one full-suite invocation, no full-suite failures or reruns, and no production edits during the run.

## Files and self-review

- `providers.py`: transactional update boundary and unique, flushed atomic save.
- `tests/test_providers.py`: public-operation interleaving and concurrent replacement-failure regressions.
- `mutate_check.py`: three transactional/temporary-file mutants.
- `README.md`: mutation registration badge, 70 to 73.
- `.superpowers/sdd/2026-09-07-computer-use-reliability/task-2-report.md`: this report.

Self-review: the lock encloses the read, validation dependent on current state, mutation, serialization, flush/fsync, and replacement. No public update reads stale settings before acquiring it. Save validates TOML before allocating its temporary file; replacement only sees a closed, fsynced file. Failed replacement leaves the original destination untouched and only attempts cleanup of the allocated unique name. Nested serialization was reused unchanged. Existing provider and role return shapes, fallback/escalation behavior, and tool lists are preserved. The read-only Git diff check found no whitespace errors in Task 2 changes; it reported only the known line-ending notices for the protected user files.

The protected preexisting line-ending-only changes in `tests/mock_effect_server.py` and `ui.html` remain untouched and unstaged.

Concerns and evidence limits: the lock primitive deliberately treats locks older than 60 seconds as stale. A process suspended past that threshold can lose exclusivity; this follows the brief's specified existing lock contract. Direct public `save` is an atomic whole-snapshot write and does not merge competing snapshots; narrow provider/role edits must use `add`/`set_role` or `_update`. These tests prove local filesystem transactions and injected replacement-error behavior, not power-loss recovery, arbitrary external writers, or live browser/release readiness. No paid AI provider was called.

Final status: implemented and self-reviewed; focused tests pass, all five provider mutations are caught, and the complete suite exits 0 with 154 passed files, two skipped files, and zero failed files. Ready for scoped commit and independent review.

## Independent review fix round 1: non-stealable OS exclusion

Review finding: the original task-plan lock choice was weaker than the transaction invariant. A paused live owner could age past 60 seconds, lose its lock to another writer, then resume and overwrite that writer's update. The controller explicitly overrode the plan's requirement to use `locks.holding` and authorized a separate standard-library advisory primitive in `locks.py`. This section supersedes the earlier report's acceptance of that stale-lock limitation. Direct `save` remains an approved atomic whole-snapshot operation.

The new `locks.advisory_holding(path, timeout=20)` uses `msvcrt.locking(... LK_NBLCK, 1)` on Windows and `fcntl.flock(... LOCK_EX | LOCK_NB)` on POSIX. It opens a persistent lock file without truncation, initializes byte zero only for an empty file, and never removes/replaces the file. Each acquisition holds its own descriptor until unlock/close. Contention retries use monotonic deadlines and bounded jitter. File age has no role; the OS releases exclusion when the owning process dies. The original `locks.holding` implementation is unchanged. Provider `_update` now uses the advisory primitive around the same complete transaction.

### RED before implementation

The first new regression launches a separate process running actual public `add`, pauses its `save` after loading and acquiring the production transaction lock, and sets the real lock file's mtime 120 seconds into the past. A second process calls public `set_role` with a 0.2-second lock timeout. The first process remains alive and blocked awaiting input. The regression requires the second process to time out without changing settings, then resumes the first process and independently checks that both public edits and every original setting survive. It also checks lock-file identity and size across subsequent acquisitions.

Command: `python tests/test_providers.py`. Exit 1 before any lock implementation change. Exact traceback:

```text
Traceback (most recent call last):
  File "C:\Users\redab\OneDrive\Bureau\self learning 24.7 agent\computer-use-worktree\tests\test_providers.py", line 487, in <module>
    main()
    ~~~~^^
  File "C:\Users\redab\OneDrive\Bureau\self learning 24.7 agent\computer-use-worktree\tests\test_providers.py", line 308, in main
    process_updates(sb)
    ~~~~~~~~~~~~~~~^^^^
  File "C:\Users\redab\OneDrive\Bureau\self learning 24.7 agent\computer-use-worktree\tests\test_providers.py", line 126, in process_updates
    assert out.strip() == "BLOCKED", "aged live provider owner was stolen"
           ^^^^^^^^^^^^^^^^^^^^^^^^
AssertionError: aged live provider owner was stolen
```

The second regression kills a separately paused provider process before its save, waits for process exit, then requires a new public `set_role` to commit within the same short lock timeout, without stale-time manipulation. It independently verifies that the killed writer committed nothing and that recovery changed only the new role.

```powershell
python -c "import sys; sys.path.insert(0, 'tests'); import test_providers as t; sb=t.make_sandbox('providers_dead_red', providers={'m': {'script': 's.json'}}, roles={'tester': 'm'}, scripts={'s.json': []}); t.dead_provider(sb)"
```

Exit 1 before implementation. Exact traceback:

```text
Traceback (most recent call last):
  File "<string>", line 1, in <module>
    import sys; sys.path.insert(0, 'tests'); import test_providers as t; sb=t.make_sandbox('providers_dead_red', providers={'m': {'script': 's.json'}}, roles={'tester': 'm'}, scripts={'s.json': []}); t.dead_provider(sb)
                                                                                                                                                                                                        ~~~~~~~~~~~~~~~^^^^
  File "C:\Users\redab\OneDrive\Bureau\self learning 24.7 agent\computer-use-worktree\tests\test_providers.py", line 154, in dead_provider
    assert out.strip() == "COMMITTED", "dead provider owner retained exclusion"
           ^^^^^^^^^^^^^^^^^^^^^^^^^^
AssertionError: dead provider owner retained exclusion
```

The separate dead-owner RED sandbox remains in `C:\Users\redab\AppData\Local\Temp\agent-suite\providers_dead_red`. The live-owner RED traceback is preserved above; subsequent tests reused its ordinary provider sandbox.

### GREEN and mutation evidence

Windows command: `python tests/test_providers.py`. Passed immediately after implementing the advisory primitive; then passed after strengthening stable-file assertions and adapting the existing concurrency observer to recognize both lock variants. Exact final assertion/result lines (routine fleet paths and timestamped auto-wiring messages omitted):

```text
[transaction] concurrent public add + set_role preserve both edits and all original settings
[interruption] concurrent failed replacements preserve original and foreign temp; unique temps fsynced and cleaned
[live-owner] old mtime cannot steal a paused provider transaction; resumed edits both survive
[dead-owner] terminating a provider process releases exclusion without stale-time takeover
[add] known rail + custom endpoint added; settings round-tripped losslessly; only key NAMES are written
[roles] any role re-pointed at any provider/model incl. fallback + escalation; unknown providers refused
[catalog] models listed from a live /models endpoint; free-only and text filters work
[custom] your own tools appear as capabilities, honour ready_check, and reach agents with the exact command to run
[fleet-tools] a tools.json at the fleet home reaches every expert in it
[plug] a key in the environment IS a provider: a role named a rail with no settings entry and it wired from the verified catalog at runtime; keyless rails refuse naming the exact env var; cloudflare's missing account id is a named error at wire time; an explicit settings entry always outranks the catalog
PASS test_providers
```

Windows command: `python tests/test_lock.py`. Exit 0. Exact result lines:

```text
[unit] live lock blocks; dead/unknown/stale owner locks are broken
[integration] two same-course tasks serialized, both done, lock released
[hammer] 12 threads x 40 acquisitions: every writer survived and all 480 rows landed � EACCES during lockfile creation is retried as the contention it is
PASS test_lock
```

Command: `python mutate_check.py "providers:"`. Exit 0. Exact output:

```text
==============================================================================
MUTATION RESULTS � a MISSED row is a test that measures nothing
==============================================================================
  CAUGHT  providers: unrelated root settings dropped
          test_providers.py failed in 1s � provider edits must preserve unrelated root tables
  CAUGHT  providers: nested tables stringified
          test_providers.py failed in 0s � provider edits must preserve nested tables as tables
  CAUGHT  providers: transaction lock removed
          test_providers.py failed in 0s � concurrent public add and set_role must both survive
  CAUGHT  providers: shared temporary file
          test_providers.py failed in 1s � concurrent failed saves must isolate and clean only their own temps
  CAUGHT  providers: stale load before transaction lock
          test_providers.py failed in 1s � the waiting public update must read the preceding commit
  CAUGHT  providers: stealable age-based lock restored
          test_providers.py failed in 1s � an aged live provider owner must retain exclusion

6 mutations: 6 caught, 0 missed, 0 skipped
```

Existing lock/fresh-load mutation anchors now target the advisory call. The new mutant restores the complete old age-based lock call, and the paused-live-owner process regression catches it. The README registration badge increases from 73 to 74; only the six provider mutations were run this round.

POSIX command, using the already installed Python image without a pull or network access:

```powershell
docker run --rm --pull never --network none --read-only --tmpfs /tmp:rw --mount "type=bind,source=C:\Users\redab\OneDrive\Bureau\self learning 24.7 agent\computer-use-worktree,target=/src,readonly" -w /src -e PYTHONDONTWRITEBYTECODE=1 python:3.11-slim python tests/test_providers.py
```

Exit 0. The same provider assertion/result lines printed as in the Windows GREEN block, ending `PASS test_providers`. This executed actual `fcntl.flock` thread/process exclusion, old-mtime refusal, dead-process release, unique-temp failure recovery, and provider operations on the container's Linux temporary filesystem. It is not a mocked POSIX backend. The source mount was read-only; the disposable container and its successful temporary fixtures were removed by `--rm` after completion.

### Fix-round self-review and scope

- `locks.py`: adds one advisory context manager and platform-standard imports; the existing age-based `holding` code is unchanged.
- `providers.py`: switches only the transaction lock call.
- `tests/test_providers.py`: subprocess regressions, stable lock-file checks, and existing observer adaptation. Concurrency/temporary-file tests run before the process regressions so their existing mutants fail for their original behavioral reasons.
- `mutate_check.py`: updated anchors plus the age-based restoration mutant.
- `README.md`: registration badge only.
- This report: preserved original evidence and appended the review finding and fix evidence.

No lock-file cleanup runs on unlock or process death; keeping the same file identity is part of exclusion. The file is not truncated by later open calls. Windows byte initialization races are treated as contention when the byte has already become locked. Non-contention OS errors propagate; contention times out rather than stealing. Both normal and exceptional exits close the descriptor. The provider tests use real subprocesses, real OS locks, real file ages, and real termination; only pauses and the short contender timeout are test-controlled. No new dependencies, browser/MCP changes, or delegated agents were used. Protected user files remain untouched.

Verification limit: the earlier 154-pass full-suite footer belongs to the pre-review commit `d37a56904d6c2d69aee8ab40e426306d7ac207e1`. This fix round ran focused provider tests on Windows and Linux, the existing Windows lock test, and targeted provider mutations; it did not rerun the full suite. Advisory exclusion coordinates callers using the same persistent file; direct snapshot saves and unrelated external tools remain outside narrow-update merging, as approved by the controller.

Final test strengthening: the dead-owner subprocess now attempts a distinct `killed-provider` addition, so equality with the original settings cannot pass merely because it attempted an identical existing value. After that test-only change, the exact Windows and Docker provider commands above were rerun and both exited 0 with the same assertion/result lines. The exact mutation command was rerun: all six rows were `CAUGHT`, each reported `failed in 1s`, and the footer remained `6 mutations: 6 caught, 0 missed, 0 skipped`. Registration readback printed `registered mutations: 74`. Task-owned diffs pass `git diff --check`.

Fix-round status: the reviewed age-takeover finding is addressed; Windows and POSIX focused tests pass, the existing lock regression passes, and all six provider mutations are caught. Ready for independent review of the scoped fix commit.
