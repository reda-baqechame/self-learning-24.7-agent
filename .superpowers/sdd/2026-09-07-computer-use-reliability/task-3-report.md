# Task 3: Immutable MCP image evidence

Base: `7108101f77748c7a6bb3fa08796ffc81f7e0e147`. Scope: MCP result-image persistence and evidence only. The test-driven-development skill, its writing-good-tests reference, and the verification-before-completion skill were read before implementation and final verification. No dependency, transport, provider, or browser-action changes were introduced, and no subagents were dispatched.

## Change and contract

Binary MCP result blocks are decoded only from strict base64 and refused when empty or larger than 25,000,000 bytes. Their decoded bytes are hashed with SHA-256 and stored inside the expert root at `tmp/mcp-artifacts/<sha256><validated-extension>`. The extension comes only from the fixed MIME mapping for PNG, JPEG/JPG, WebP, and GIF; other MIME types use `.bin`.

Creation uses a unique `tempfile.mkstemp` in the artifact directory, writes and flushes the bytes, calls `os.fsync`, then atomically publishes with a hard link. Unlike a replacement operation, hard-link publication cannot overwrite a digest path that a concurrent writer created after the existence check. The unique temporary link is removed in `finally`. An already-present target is read and accepted only when its complete bytes equal the decoded bytes; it is never rewritten. An existing digest path with unequal bytes is refused rather than replaced. This permits identical-byte deduplication while preserving immutable evidence.

`render_result` reports a compact literal JSON object with exactly `path`, `sha256`, `bytes`, `mime`, `width`, and `height`, while preserving the existing `ingest.py vision` instruction. PNG, JPEG (including `image/jpg`), and WebP dimensions are parsed from bounded headers using the standard library. WebP VP8X, VP8, and VP8L headers are supported. GIF, unsupported MIME types, and malformed or unrecognized headers deliberately report `width: null` and `height: null`; no dimensions are guessed. Dimension inspection is bounded to fixed fields for PNG and to the first 65,536 bytes for JPEG/WebP.

## TDD evidence

All commands ran from `C:\Users\redab\OneDrive\Bureau\self learning 24.7 agent\computer-use-worktree` on Windows.

### RED

Before any production change, the test froze `mcp.time.time()` at `1234567890` and rendered two different PNG blocks at content index zero. Both resolved to `tmp/mcp-1234567890-0.png`, and the second write replaced the first.

```powershell
python tests/test_mcp.py
```

Exit 1; exact failing portion:

```text
Traceback (most recent call last):
  File "C:\Users\redab\OneDrive\Bureau\self learning 24.7 agent\computer-use-worktree\tests\test_mcp.py", line 214, in main
    assert red_saved != green_saved, (
AssertionError: different same-index image bytes rendered in one second reused one path; the second image overwrote the first
```

The regression uses literal fixtures and independently fixed expectations rather than implementation helpers. The first PNG is 70 bytes, 1x1, SHA-256 `4ff6ab670a58c14270e034e2090d9a432caa263a14e0a25785386b0c12f880b5`; the second is 71 bytes, 2x3, SHA-256 `903dd2970e2f252c87178783090ab936f2727bc63d7690035444bf9f1a90b729`. It opens both resulting files and compares their complete stored bytes with the literal byte strings.

### GREEN

```powershell
python tests/test_mcp.py
```

Exit 0; final output:

```text
[mcp-image] different same-index images retain literal bytes at distinct SHA-256 paths; duplicates do not rewrite; PNG/JPEG/WebP dimensions are parsed, GIF stays null, and malformed/oversized payloads are refused
PASS test_mcp
```

The test also fixes and checks these independent fixtures: JPEG 41 bytes, 2x3, SHA-256 `f72fcc9b3aabce2fe66ba030abdb774264fcc41afffaac5c9521b7fbcbb7ef95`; WebP 30 bytes, 7x5, SHA-256 `d747fbe6df40aa39845f7f9f406c0e45a4fdcfa821643f6d5c9c584ec9dec47c`; GIF 10 bytes, SHA-256 `e08e8eef7834c49f2c83f1aad3c102a41e01f4d5459b2c967f23de681f678e3e`, with dimensions explicitly null. Every stored fixture is reopened and checked byte-for-byte. Re-rendering identical PNG bytes must retain the inode and a deliberately old nanosecond mtime, proving the target was not rewritten. Invalid base64 and an encoded payload over the 25 MB decoded limit are refused without adding artifacts or leaked temporary names.

```powershell
python tests/test_computeruse.py
```

Exit 0:

```text
Ran 13 tests in 0.536s

OK
PASS test_computeruse
```

## Mutation evidence and badge

```powershell
python mutate_check.py "mcp image:"
```

Exit 0:

```text
CAUGHT mcp image: digest dropped from artifact name
       test_mcp.py failed in 6s - different literal image bytes must retain distinct SHA-256 paths
CAUGHT mcp image: same-path overwrite accepted
       test_mcp.py failed in 6s - identical bytes must deduplicate without rewriting the artifact

2 mutations: 2 caught, 0 missed, 0 skipped
```

The first mutant removes the digest from the filename; the two literal images and exact expected paths catch the resulting collision. The second mutant overwrites an existing digest path; the inode/mtime non-rewrite assertion catches it. The mutation harness restored `mcp.py` after each run.

Independent registry readback:

```powershell
python -c "import mutate_check; print('registered mutations:', len(mutate_check.MUTATIONS))"
```

```text
registered mutations: 76
```

The README badge was updated from 74 to the actual registry count of 76. This count is registration evidence, not a claim that every mutation was run in this task.

## Complete suite

Exactly one complete suite invocation used a new short test root:

```powershell
$env:AGENT_TEST_TMP = 'C:\tmp\m3-' + [guid]::NewGuid().ToString('N').Substring(0,8)
New-Item -ItemType Directory -Path $env:AGENT_TEST_TMP | Out-Null
Write-Output "AGENT_TEST_TMP=$env:AGENT_TEST_TMP"
python tests/run_all.py 2>&1 | Tee-Object -FilePath '.superpowers/sdd/2026-09-07-computer-use-reliability/task-3-full-suite.log'
exit $LASTEXITCODE
```

Resolved root: `C:\tmp\m3-41c4980c`. Exit 0. Exact footer (the terminal rendered the harness dash as a replacement glyph):

```text
156 executed: 154 passed, 2 skipped, 0 failed  [skipped: test_acquire.py, test_shutdown.py]
ALL EXECUTED TESTS PASSED � the skipped ones proved nothing here; their reasons are printed above and counted in EVIDENCE.md
```

The two whole-file skips are acquisition without a configured isolated sandbox and the Windows-inapplicable SIGTERM shutdown test. Additionally, `test_research_discovery.py` reports `OK (skipped=1)` for its symlink case (`symlink privilege unavailable`); the runner counts that file among the passes. The raw suite output remains in `.superpowers/sdd/2026-09-07-computer-use-reliability/task-3-full-suite.log` as local evidence outside the scoped commit. There was one invocation, no failed full-suite run, no rerun, and no production edit during or after it.

## Files and self-review

- `mcp.py`: content-addressed artifact storage, non-overwriting atomic publication, bounded dimension parsing, and literal metadata rendering.
- `tests/test_mcp.py`: same-time/same-index collision regression; literal byte, hash, size, dimensions, deduplication, malformed, and oversize assertions.
- `mutate_check.py`: two targeted image-evidence mutants.
- `README.md`: mutation registration badge, 74 to 76.
- `.superpowers/sdd/2026-09-07-computer-use-reliability/task-3-report.md`: this evidence report.

Self-review: paths remain relative to and physically under the supplied expert root. User-controlled MIME cannot become a path fragment. Publication cannot replace an existing target. The duplicate branch reads one byte beyond the expected length, so a prefix match cannot pass. Unique temporary files are fsynced before publication and removed on success, contention, or failure. The response's metadata is generated from the same decoded bytes and path that are persisted. Transport framing, server lifecycle, provider code, browser authority/actions, and dependency manifests were not changed. Task-owned diffs pass the scoped whitespace check. The protected preexisting line-ending-only changes in `tests/mock_effect_server.py` and `ui.html` remain untouched and unstaged.

Concerns and evidence limits: atomic publication requires same-filesystem hard-link support in the expert-local artifact directory. If that filesystem refuses hard links, the block is reported as omitted rather than weakening immutability with an overwrite-capable fallback. The MIME mapping selects a safe extension and determines which bounded header parser runs; this is not full image decoding, CRC validation, or proof that all bytes form a displayable image. A recognized MIME with a malformed header is retained with null dimensions. SHA-256 collision or preexisting-path mismatch is handled by byte comparison and refusal, not overwrite. These tests prove local persistence behavior and suite compatibility; they are not production deployment, live-browser, power-loss, or release-readiness evidence. No paid or external provider was called.

Final status: implemented, committed, and self-reviewed; focused MCP and computer-use tests pass, both targeted mutations are caught, and the sole complete suite exits 0 with 154 passed files, two skipped files, and zero failures. Ready for independent review.
