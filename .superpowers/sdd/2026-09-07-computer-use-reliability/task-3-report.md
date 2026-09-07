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

## Independent review fix round 1: containment, structured evidence, and byte-derived type

This section supersedes the original implementation where the review findings conflict with it. The review found three material gaps: path operations could follow a redirected `tmp`/`mcp-artifacts` directory or accept an existing linked digest; artifact metadata existed only in display text that an earlier long text block could push past truncation; and MIME/extension selection trusted the declaration rather than the bytes. It also requested a pre-decode encoded-length bound.

### RED evidence

Each probe below exercised the committed Task 3 implementation `bd0410fe2dc98684cbd41226eacca1074a022d88` before the corresponding production fix. All commands ran from the repository root. The Windows host lacks symbolic-link privilege, so the tests use real NTFS junctions for directory redirects and real hard links for regular-file aliases; on a symlink-capable host the same helpers use symlinks.

```powershell
python -c "import sys; sys.path.insert(0, 'tests'); import test_mcp as t; t.image_directory_redirection()"
```

```text
AssertionError: redirected tmp directory was accepted
```

```powershell
python -c "import sys; sys.path.insert(0, 'tests'); import test_mcp as t; t.image_existing_target_link()"
```

```text
AssertionError: existing digest hard-link was accepted as immutable evidence
```

```powershell
python -c "import sys; sys.path.insert(0, 'tests'); import test_mcp as t; t.image_structured_artifacts()"
```

After converting the missing-keyword `TypeError` to the contract-level assertion required by the TDD rules, the exact final line was:

```text
AssertionError: render_result lacks a structured artifact evidence API
```

```powershell
python -c "import sys; sys.path.insert(0, 'tests'); import test_mcp as t; t.image_signature_type()"
```

```text
AssertionError: PNG type and extension were not derived from bytes
```

```powershell
python -c "import sys; sys.path.insert(0, 'tests'); import test_mcp as t; t.image_mime_conflict()"
```

```text
AssertionError: PNG bytes mislabeled JPEG claimed the wrong MIME/extension
```

```powershell
python -c "import sys; sys.path.insert(0, 'tests'); import test_mcp as t; t.image_encoded_limit_precheck()"
```

```text
AssertionError: oversized encoded input reached the allocating decoder
```

Two deterministic filesystem race probes were also run against the committed base by loading `git show HEAD:mcp.py` into an isolated module. Both failed on the real filesystem, not on source-text inspection:

```text
AssertionError: directory swapped before unique-temp creation was accepted
AssertionError: digest target swapped to an outside hard link was accepted
```

A still narrower probe swaps the directory exactly inside the publication call and supplies the source name an attacker would need. It exposed a residual issue after the first containment implementation:

```powershell
python -c "import sys; sys.path.insert(0,'tests'); import test_mcp as t; t.image_publication_swap_race()"
```

```text
AssertionError: a last-moment directory swap published outside the expert root
```

That RED led to descriptor-relative publication on POSIX and immediate identity revalidation plus same-inode alias cleanup on Windows.

### Final implementation

`_artifact_directory` now obtains `tmp/mcp-artifacts` through `fileauth.resolve` as harness-owned root-zone state, compares the resolved result with the exact physical path under `realpath(root)`, creates it, resolves it again, and rejects symlink/junction/non-directory components. Directory device/inode identity is retained and rechecked before temporary creation, before publication, and after publication. Static redirects are refused before any file is created. A redirect introduced at unique-temp creation is detected and its outside temporary file is removed before publication.

On POSIX, publication uses a descriptor opened with `O_DIRECTORY` and `O_NOFOLLOW`, and both names passed to `os.link` are relative to that validated descriptor. On Windows, where Python exposes no directory-relative link operation, the code revalidates around the atomic link; if a directory changed at the syscall boundary it removes the published name only when the target and current temporary name are the same regular inode with at least two links, then removes the temporary alias. The deterministic last-moment swap test requires that no digest remains outside the expert root.

Existing digest targets are inspected with `lstat`, must be regular and singly linked, and must retain the same device/inode across `lstat`/open/`fstat`/read/`lstat`. Symlinks, junctions, directories and hard-linked aliases refuse. The target-swap test replaces a regular digest with a real outside hard link between `lstat` and open; the identity and link-count checks refuse it.

`render_result(result, root=None, artifacts=None)` remains string-return compatible. A caller such as Task 5 may pass a list as `artifacts`; exact copies of each successfully stored `{path, sha256, bytes, mime, width, height}` mapping are appended before flattened display truncation. A regression puts 20,100 text characters before a PNG, proves its path is absent from the truncated string, then requires the literal structured mapping and reopens the stored bytes.

Supported type and safe extension now come from byte signatures: PNG -> `image/png`/`.png`; JPEG -> canonical `image/jpeg`/`.jpg` (declared `image/jpg` is the accepted alias); WebP -> `image/webp`/`.webp`; GIF87a/GIF89a -> `image/gif`/`.gif`. PNG/JPEG/WebP dimensions remain header-derived; GIF dimensions remain deliberately null. Unsupported signatures are refused. A missing declaration is accepted using the derived canonical type; a nonempty declaration that conflicts with the derived type is refused before creating `tmp`. The encoded length and terminal padding now establish a decoded-size upper bound before `base64.b64decode`; strict decode and the post-decode 25 MB check remain defense in depth.

### GREEN evidence

Final focused MCP command:

```powershell
python tests/test_mcp.py
```

Exit 0. Exact new/final result lines:

```text
[mcp-image] different same-index images retain literal bytes at distinct SHA-256 paths; duplicates do not rewrite; PNG/JPEG/WebP dimensions are parsed, GIF stays null, and malformed/oversized payloads are refused
[mcp-containment] redirected tmp/artifact directories refused through real junction/junction filesystem entries
[mcp-containment] existing digest hard-link/junction refused without changing its outside target
[mcp-race] junction swap before unique-temp creation fails closed and cleans the outside temporary file
[mcp-race] directory replacement at atomic publication is blocked or fails closed without an outside artifact
[mcp-race] existing regular target swapped to an outside hard link during read fails closed
[mcp-structured] long display text truncates, but exact structured path/hash/bytes/mime/dimensions remain available
[mcp-signature] unlabelled PNG derives .png/type/dimensions from bytes
[mcp-signature] PNG bytes declared as JPEG are refused before storage
[mcp-size] encoded-length precheck refuses a >25 MB decoded payload before base64 allocation
PASS test_mcp
```

Final computer-use regression command:

```powershell
python tests/test_computeruse.py
```

Exit 0:

```text
.............
----------------------------------------------------------------------
Ran 13 tests in 0.335s

OK
PASS test_computeruse
```

### Mutation evidence and badge

The first expanded run honestly found one missed mutation: `directory race recheck removed`; footer `6 mutations: 5 caught, 1 missed, 0 skipped`. Its replacement originally changed only the final equality while the preceding secure resolve still refused. The mutant was corrected to bypass the re-resolution itself, which the real directory-swap regression catches. After the later publication-race RED, a seventh mutant was added for removing raced-alias cleanup.

Final command:

```powershell
python mutate_check.py "mcp image:"
```

Exit 0; exact final output (the terminal rendered the harness dash as a replacement glyph):

```text
==============================================================================
MUTATION RESULTS � a MISSED row is a test that measures nothing
==============================================================================
  CAUGHT  mcp image: digest dropped from artifact name
          test_mcp.py failed in 8s � different literal image bytes must retain distinct SHA-256 paths
  CAUGHT  mcp image: existing digest validation bypassed
          test_mcp.py failed in 8s � linked or swapped existing digest targets must refuse
  CAUGHT  mcp image: directory race recheck removed
          test_mcp.py failed in 7s � a redirected artifact directory must fail closed after creation
  CAUGHT  mcp image: raced publication cleanup removed
          test_mcp.py failed in 7s � a last-moment directory swap must leave no outside digest
  CAUGHT  mcp image: structured artifact sink dropped
          test_mcp.py failed in 27s � artifact metadata must survive flattened display truncation
  CAUGHT  mcp image: declaration conflict accepted
          test_mcp.py failed in 21s � mislabeled image bytes must not claim the declared MIME
  CAUGHT  mcp image: encoded allocation bound removed
          test_mcp.py failed in 11s � oversized encoded input must refuse before base64 decoding

7 mutations: 7 caught, 0 missed, 0 skipped
```

Registry readback after the seven Task 3 image registrations/updates:

```text
registered mutations: 81
```

The README badge is updated from 76 to the actual count of 81. Only the seven filtered image mutations were run in this fix round.

### Fix-round files, self-review, and evidence limits

- `mcp.py`: File Authority containment, redirect/link/race refusal, descriptor-relative POSIX publication, canonical byte-signature typing, encoded precheck, and optional structured artifact sink.
- `tests/test_mcp.py`: static junction/symlink/hard-link checks, deterministic creation/publication/target swap races, long-text structured evidence, unlabelled/mislabeled literals, and pre-decode size observation.
- `mutate_check.py`: updated existing-target mutant and five new load-bearing mutants, bringing the image filter to seven rows.
- `README.md`: mutation registration badge, 76 to 81.
- This report: appended review finding, RED/GREEN, mutation, scope, and limitation evidence.

Self-review: all artifact paths remain rooted through the repository's File Authority boundary. The tests check real outside directories remain without a digest; linked targets retain their outside bytes; stored evidence is reopened; structured expectations remain hand-written literals. Declaration conflict refusal happens before directory creation. Existing string callers need no change, while Task 5 gets an explicit structured collection. No MCP transport line, provider module, browser action, or dependency manifest changed. The protected preexisting line-ending-only edits in `tests/mock_effect_server.py` and `ui.html` remain untouched and unstaged.

Evidence limit: the complete-suite footer earlier in this report belongs to the original Task 3 commit and is not evidence for this review fix. Per controller direction, this round did not run or claim a broad full suite. Focused MCP, computer-use, and all seven relevant mutations are the verification boundary. No paid or external provider was called.

Fix-round status: all review findings are implemented, the scoped verification is green, and the changes are committed. Ready for independent review.
