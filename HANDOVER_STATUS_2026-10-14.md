# Handover status — 14 October 2026

**What this is.** A verification pass over the whole project, two days after
the 12 October readiness audit, written to answer three questions for a
handover: *what is done, what is not done, and what is done incorrectly.*
Every status below is either (a) a result I produced today with the command
named beside it, or (b) a finding carried forward from the 12 October audit
**and re-verified in the current source**. Where I could not verify
something, it says so.

Companion document: **`PLATFORM_MAP.md`** — what every part of the platform
is and does.

---

## 1. The decision, in one paragraph

**Expert Fleet is close.** Its machinery is built and tested; what remains
is one short list of panel-honesty defects (now closed, §4), a set of
qualification runs that need an owner decision and a budget (§6), and some
narrower unfinished integrations (§5). **Screen Tutor is not.** Five of its
38 work packages are accepted, 13 are partial with acceptance withheld, 20
have not started, and none of it has ever been committed to `main` or run in
CI. Those are two different handovers, and the single most consequential
choice to make now is whether the thing being handed over is *Expert Fleet,
with the Tutor named as unfinished work in progress*, or *both products as
one release* — which is weeks of further build plus human-subject,
content-review and device qualification that no amount of engineering can
substitute for.

---

## 1b. Where it stands on GitHub

| What | State |
|---|---|
| Remote `main` (`reda-baqechame/self-learning-24.7-agent`) | **`85aac33` — PR #28 merged by `reda-baqechame` on 14 October 2026, 22:19 UTC.** Everything in this document's §4 is on `main` |
| [PR #28](https://github.com/reda-baqechame/self-learning-24.7-agent/pull/28) | **merged** (opened from `redabaquechame:fix/handover-defects-2026-10-14`; that account has read-only access to the main repository, so the owner account merged it) |
| Commits on the PR | `e391174` the twelve fixes and the two documents · `5f5fdec` the endurance-test flake (below) · `8c1bde6` `RESEARCH_FOUNDATIONS.md` and `EVIDENCE.md` regenerated from a full run of the pushed tree · `aa3125a` changelog entries v14 and v15, test counts. CI green on all 6 jobs at `aa3125a` |
| CI on the first push | **5 of 6 jobs green.** Windows/Python 3.13 failed `test_endurance` on a single slow last batch (1.17s against a 0.17s median) — a hosted-runner stall, not a slowdown: the same code was flat on Windows 3.11, spiked once mid-run on 3.12, and pristine `main` shows the same kind of spike on the same job. The latency check judged one sample; it now re-measures an outlier on fresh work, so a real trend still fails and a stall clears, and the judge itself is tested both ways. |
| CI on the second push (`5f5fdec`) | **all 6 jobs green** (Ubuntu + Windows × Python 3.11/3.12/3.13), plus the automated review check |
| Local full run on `5f5fdec` | **161 executed — 156 passed, 5 skipped, 0 failed**; `EVIDENCE.md` regenerated from that run (156/161, 919 observations) |
| Not pushed, by design | the Screen Tutor worktree (owned by another working session, PAUSED — see H04), and the other local worktrees (H05) |

## 1b-ii. What remains outside `main`, and why it was not merged

Checked on 14 October 2026 against every branch on this computer, on
`origin` and on the fork. **Nothing that was built is lost — every piece is
on GitHub.** Exactly two bodies of work are not on `main`, and both were
kept out deliberately:

| Work | Where it is preserved | Size | Merges onto `main` today? | Why it was not merged |
|---|---|---|---|---|
| Screen Tutor | fork, `wip/screen-tutor-snapshot-2026-10-14` (byte-identical to the working folder); an earlier SC-0A checkpoint on `screen-tutor/sc-0a-bootstrap` is superseded by it | 629 files | **no** — conflicts in `ui.html`, `README.md`, `ARCHITECTURE.md`, `REFERENCE.md`, `tests/test_effects.py`, `tests/test_frontend.py` | 5 of 38 work packages accepted; the build is PAUSED by owner instruction and owned by another working session; never through CI or review |
| Deeper Twin (Phase 10.1) | fork, `codex/twin-depth-reconciliation` (5 commits; it contains `phase10.1/twin-depth` and is byte-identical to the uncommitted state of `remediation-worktree`) | 23 files | **no** — conflicts in `doctor.py`, `mutate_check.py`, `tests/run_all.py`, `CHANGELOG.md`, `README.md`, `ARCHITECTURE.md`, `REFERENCE.md` | its own checkpoint withholds acceptance: capture authority, containment, recovery, snapshots, enrolment and signing gates are open (F15) |

The safe path to `main` for each is the one PR #28 took: reconcile onto the
current `main`, run the full suite and the mutation check, pass CI, close the
work's own acceptance gates, then review and merge. Pushing either one
straight to `main` would put unreviewed, conflicting work into the product
being handed over.

## 1c. Everything Codex built, and where each piece lives

Codex did most of the recent build work, in its own branches and folders.
Checked branch by branch against both GitHub remotes on 14 October:

| Codex branch | What it is | On `main`? | On GitHub? | Left in its local folder |
|---|---|---|---|---|
| `codex/verified-learning-hardening` | verified-learning hardening | **merged** | yes | — |
| `codex/twin-measurement-integrity` | Twin measurement repair (PR #22) | **merged** | yes | 7 evidence logs |
| `codex/user-workflow-completion` | truthful mission/goal starts, contract validation (PR #23) | **merged** | yes | — |
| `codex/bounded-computer-use` (+ `-integration`) | bounded browser authority, sealed observations | **merged** | yes | 16 evidence logs |
| `codex/cu1-independent-postconditions` | independent computer-action postconditions (PRs #26, #27) | **merged** | yes (fork) | 1 evidence folder |
| `codex/twin-depth-reconciliation` | the deeper Twin: capture, consent at the entry point, cold start, augmentation | **not merged — 5 commits ahead** | yes (fork), unreviewed | 3 evidence logs |
| `codex/screen-tutor-build` | Screen Tutor: native companion, learning contracts, teaching packs, 38-packet plan | **not merged — 1 commit ahead** | **no — not on either remote** | **20 modified + 77 untracked entries (626 files of source and evidence)** |

Read the right-hand column carefully. **Every finished Codex feature is on
`main`.** The "modified" files the merged folders still show (`ui.html`,
`tests/mock_effect_server.py`) have **zero real diff** — they are the
line-ending rewrite N04 fixes, nothing lost. What is left is *evidence
logs* (suite and mutation receipts), which matter for the verification
trail but are not code. The two pieces of real unmerged work are the Twin
depth candidate (safe on the fork, awaiting review — F15) and the Screen
Tutor (in no repository — H04).

Codex also produced work that was never meant for git, all inside the
OneDrive project folder: the build plans (`planning/` — the Screen Tutor
master plan, requirements, reconciliation and execution state), the two
audits (`audit-2026-09-07/`, `audit-handover-2026-10-12/` — the 37-finding
register this document builds on), market research (`research/`), and
packaged handoffs (`exports/`). They are the design and audit record; a
buyer should receive them alongside the repository.

## 2. Which bytes are the candidate

| Build | Identity | State as of today |
|---|---|---|
| Remote `main` | `53bbb279` | 6 CI jobs green (run 34697236092, 12 Sep 2026). Unchanged since. |
| The `agent/` folder you work in | was `fc08b7f4`, **now `53bbb279`** | It was 38 commits behind remote `main` — audit finding H01. I fast-forwarded it today; it is clean and identical to `main`. To undo: `git reset --hard fc08b7f4`. |
| **The release candidate** | branch `audit/handover-rc-2026-10-14` (pristine `main`) and **`fix/handover-defects-2026-10-14`** (`main` + today's ten fixes) | The second is the candidate to review and merge. |
| Screen Tutor | branch `codex/screen-tutor-build`, head `160fa4b` **plus uncommitted work** | 16 modified tracked paths, 41 untracked entries. `BUILD_STATE.json` revision 66 says **PAUSED** on owner instruction. Never in CI. |
| Twin depth | `1d7ff7c9` | A separate local candidate, not an ancestor of `main`. Unaccepted. |

**H01 is now half-closed:** there is one version in the working folder and
one reviewable candidate branch. What remains is the owner's half — tag a
release, record the payload digest, and identify every installer by the
exact tested commit (§6, F20).

---

## 3. What I ran today, and what each run proves

| Run | Result | What it establishes |
|---|---|---|
| `python3.12 tests/run_all.py` on pristine `main` (Windows 11, Python 3.12.13, `AGENT_TEST_TMP=C:/Users/.../Temp/rc`) | **160 executed: 154 passed, 5 skipped, 1 FAILED** (`test_providers.py`), exit 1 | `main` is **not green on this machine**. The failure is a test defect, not a product defect — but it is a real one, and it means the suite's green depends on how the temp root is spelled (§4, N02). |
| `python3.12 tests/run_all.py` on the candidate | **see §4 footer** | the same suite with all ten fixes |
| `python execution.py --audit` | **0 violations across 124 modules**, 19 declared platform-internal | no module bypasses the Execution Authority |
| `python harness.py --check` | **0 contract problems**, 1 health problem (docker daemon not running here) | the harness contracts hold |
| `python mutate_check.py handover` | **7 mutations: 7 caught, 0 missed, 0 skipped** | each new test fails when its fix is reverted |
| Targeted reruns: `test_frontend`, `test_ux`, `test_ledger_defects`, `test_invariants`, `test_subquery`, `test_harness`, `test_uicards`, `test_ui_auth_hardening`, `test_package`, `test_procedural_learning`, `test_correctness_patch`, `test_paths`, `test_hardening`, `test_transactional_contracts`, `test_providers` | all pass | the fixes break nothing adjacent |
| The panel opened in a real browser on a disposable fleet: an untrained expert's badges, the Home gate claim, the New-mission dialog's role/focus/Tab containment and focus restoration, the selected-agent shortcut, and a simulated failed procedure read | every one of the audit's five panel repros now behaves correctly, including the third badge site a grep had missed | these are the audit's own reproduction steps, re-run |
| Long-path probe through the File Authority, before and after | **before: `FileNotFoundError` on a 245-character destination; after: writes correctly** | a reproduced core defect and its fix (§4, N01) |
| `gh run view 34697236092 --log` | Ubuntu runs `test_docker_live` **for real** (2 skips); Windows skips it (5 skips) | the docker backend *is* exercised in CI on Linux — which is where F21's fix will be proven |
| Documentation command drift: every `python <module>.py <subcommand>` in README, QUICKSTART, MANUAL, REFERENCE, ARCHITECTURE and the new map, run with `--help` | **50 pairs checked, 0 mismatches** | a negative result worth having: the platform's own invariant test guards only the commands `MANUAL.md` names, so I checked the other five documents by execution. Nothing in them promises a command the CLI refuses. |
| `curl` on the three one-line installers; `gh repo view` | HTTP 200 for `install.ps1`, `install.sh`, `get-fleet.sh`; repository is **PUBLIC**, not private | the advertised install paths resolve — and the licence/exposure point in §6b |

**Not run, and therefore not claimed:** anything involving a live provider,
real money, physical devices, human participants, a buyer deployment target,
or a third-party MCP/A2A peer. Those are §6.

---

## 4. Closed today — twelve findings, each with a test that fails without it

All twelve are on `fix/handover-defects-2026-10-14`. They are pinned by a
new test, `tests/test_handover_defects.py`, and by **nine new entries in
`mutate_check.py` — 9 caught, 0 missed, 0 skipped** (registry now 225), so
every one of them fails the suite if it is reverted.

| ID | Was | Now |
|---|---|---|
| **F01** | Four palette shortcuts ("Steer a running pursuit", "See the knowledge graph", "Mastery", "What may no longer be true?") set the sub-view and then called `go('agents')`, whose first act is `S.sel=null` — so with an agent open they landed on the roster. | They route through `openAgentAction()`, which keeps the open agent, falls back to the only agent, and asks when there are several. |
| **F02** | The dialog was a styled `div`: no `role`, no name, no focus containment. Tab from the trigger moved onto a button *behind* the overlay; no dialog element existed in the DOM; labels were not associated with their fields. | `role="dialog"`, `aria-modal`, `aria-labelledby`, focus moved in on open and **restored to the opener** on close, Tab contained inside the modal, and every dialog label paired with its control by one helper (`dlgPairLabels`) rather than in 23 templates. |
| **F03** | One tag claimed both the creation lane and measured training: a brand-new expert with zero courses, zero tasks and no exam read **TRAINED**. | Two tags from two facts: the lane (`QUICK` / `FULL`) and the state read off disk (`UNTRAINED`, or the course count). Competence stays on Proof and Mastery, where the evidence is. |
| **F04** | Home claimed *every* task is gated and examined by a second model family. `check_done` trusts a task that declared no gate — by design, in its own docstring — so the claim was false for the first thing a visitor tries. | Home states the law **and its boundary**, and a completed task that declared no check is labelled **"done (unverified)"** in both places a task status is rendered. |
| **F05** | `loadProcedures` turned any response without a `runbooks` key — including the `{error}` object the API client returns on failure — into `[]`, so a failed read showed the same screen as an empty library. | Four states: loading, failed (with the error named and a retry), empty, populated. |
| **F18** | `subquery` called `f.readlines()` before slicing, so peak memory scaled with the whole file — the opposite of the claim the tool exists to make. | A new `loop.read_slice()` streams, stops at `end_line`, and enforces the budget *while reading*. Measured: **a two-line slice of a 20 MB corpus peaks at 25 KB against 25 MB** for the code it replaced. |
| **F21** | The docker timeout test diffed every container on the daemon, so an unrelated container started during the window was reported as this test's leak — a false alarm with a known mechanism, which is how it polluted the Tutor campaign. | It learns the name its own container was given, requires **that** one to be gone, and keeps a deliberate stranger container running throughout as a standing negative. |
| **N01** *(new today)* | **A real core defect.** `fileauth.write_text`/`write_bytes` appended `.<pid>.<uuid32>.tmp` (~45 characters) to the destination, so a *valid* Windows path of 245 characters produced a 288-character scratch name and the write failed with `FileNotFoundError` — through the File Authority, which is mandatory for the platform's own state. Reproduced on `main` today. A fix existed on the Tutor branch (`160fa4b`) and had never reached `main`. | Ported onto the candidate: short exclusive staging beside the destination, unchanged containment, encoding, durability, retry and cleanup semantics. Verified at 245 characters, and `test_correctness_patch.py` (which came with the fix) passes. |
| **N02** *(new today)* | `test_providers.interrupted_saves` compared paths as **strings**. `tempfile` normalises the directory it is handed, so a sandbox root spelled with forward slashes — which `AGENT_TEST_TMP` legitimately is on Windows — failed an assertion about a save that was correct. This is the one failure in the baseline run in §3. | Compared by filesystem identity (`samefile`, with a normalised fallback for a destination that does not exist yet, which is the case under test). |

| **F03b** *(found today, by looking)* | The first pass of the F03 fix patched the two sites that matched `e.quick` — and the agent's **own page** kept printing TRAINED from `row.quick` (`ui.html:2111`). A grep found two sites; opening the panel in a browser found the third. | All three render `laneTag()`, and the test now asserts the **shape** (`?"QUICK":"TRAINED"` appears nowhere, whatever the variable is called) instead of a count of the sites I happened to know about. Re-verified in the browser: the agent page reads **FULL · UNTRAINED**. |
| **N04** *(new today)* | `test_frontend` edits the shipped `ui.html` in place to prove the panel hot-reloads, and `test_effects` regenerates `tests/mock_effect_server.py` — both wrote in text mode, so on Windows every `
` came back as `
`. **After every suite run, `git status` showed two modified files with an empty diff**, and a hard kill between the two writes would leave the panel titled "Edited Live" in the tree. (`proof.code_hash` normalises line endings before hashing and says why, so no badge was ever affected — the platform had already thought of that one.) | `newline=""` on the borrow and the restore. Proven: `ui.html` is **byte-identical (sha256 unchanged)** after a `test_frontend` run, and the tree is clean. |

> **Review pass (Opus 5.5, 14 Oct 2026).** The fixes above were re-read
> with fresh eyes before handover. Two slips in the first pass were found
> and closed: the new `read_slice` labelled a slice with the *requested*
> `end_line`, so `end_line=5000` on a 2,000-line file was fenced as "lines
> 1-5000" (the code it replaced had capped it — now it names the last line
> actually read, pinned by a test and a ninth mutation); and a stray
> backslash sat in one tooltip string. One hardening was added: dialog
> label pairing never attaches a second label to a field that already has
> one. Key tests and all nine handover mutations re-run green after it.

> **Candidate suite result, Windows 11 / Python 3.12.13:**
> **161 executed — 156 passed, 5 skipped, 0 failed (exit 0).**
> Baseline `main` on the same machine, same command, same temp root:
> 160 executed — 154 passed, 5 skipped, **1 failed**.
> The five skips are the same ones CI skips on Windows and declare their own
> reason: `test_acquire`, `test_shutdown`, `test_docker_live`,
> `test_frontier_live`, `test_computeruse_live` (no docker daemon and no
> opt-in live fixtures on this machine; Ubuntu CI runs `test_docker_live`
> for real).
> Also run end to end on the baseline tree: **`python demo.py` — exit 0**,
> a full course ingested into cited notes, spec 1/1 PASS, 0 gaps, exam 95
> against a threshold of 90, course COMPLETE, memory integrity PASS. That is
> the whole machinery, keyless, in one command.

---

## 5. Still open — engineering, no external dependency

Ordered by what a buyer notices first. Estimates are my own and assume the
house standard (a test that fails without the fix, plus a mutation where the
behaviour is load-bearing).

| ID | What is wrong or missing | What "done" looks like | Size |
|---|---|---|---|
| **F06a** | The workflow dialog requires raw stages JSON (`ui.html:4142` — a textarea plus `JSON.parse`, failing with "stages must be valid JSON"), and owner-preference/Twin capture exposes feature JSON and internal scopes. | A staged-workflow form and a preference form with plain validation; the raw JSON kept as an advanced option. | 1–2 days |
| **F06b** | **Navigation names disagree with the screen, and it needs your decision, not a patch.** The agent tabs were renamed (`SUBTABS`, `ui.html:2084`): `board` is labelled **Work** and `mind` is labelled **Skills**. But the view headings and the Guide still use the old words — `renderBoard` prints "Board — all work" (3091) under a tab that says Work; `renderMind` (tab: Skills) prints "Mind — everything it knows" (3214) *and* contains Self-model, Twin, Knowledge, Context windows and Procedures; and 14 Guide/prose places tell the operator to click **Board** or **Mind** (1005, 1435, 1444, 1494–1497, 1544, 2402, 2512, 2673, 4311, 4313, 4486, 4529). Every one of those instructions names a tab that is not on screen. | Pick one: **(a)** make the prose and headings read the live label from `SUBTABS` (navigation becomes correct, the labels stay as they are), or **(b)** rename the tabs to match what the views actually hold (the "Skills" tab is really the mind/memory browser). Either way, a test that walks every `agent → X →` instruction and fails when `X` is not a current label — so a future rename cannot drift again. I did not choose for you: this is product naming, and the mechanical half is worthless if the names are wrong. | 0.5 day once chosen |
| **T07** | Stop sharing prevents a second sharing session in the same panel. | Sharing can be stopped and restarted in one session, with a test. | hours |
| **T08** | Closing the real companion is not the continuity its view model tests. | The tested continuity is the one the real companion exercises. | hours |
| **F15** | The deeper cognitive Twin (`twinaugment`, `twincapture`) is a separate unaccepted candidate at `1d7ff7c9`; its capture-authority, containment, recovery, snapshot, enrolment and signing gates are unverified. | Reconcile only reviewed owned changes onto the candidate, keep the merged measurement repair, verify the remaining boundaries with synthetic fixtures, then run the combined suite and CI. Personal capture stays a separate, later qualification. | 2–4 days |
| **F09** | MCP is the legacy stdio subset, and says so; no third-party server has been qualified. | A published server/transport/version compatibility list, plus a qualification of the exact connectors the buyer needs. Further transports only if they are in the agreed scope. | 1 day for the list; more per transport |
| **F10** | Federation is a custom protocol; `a2a_task_api` is false and the card says so. | Either describe the supported protocol accurately in the buyer-facing docs (cheap, honest), or implement and qualify A2A `SendMessage`/`GetTask`. | 0.5 day / 1 week |
| **F17** | No OpenAPI-to-candidate-operator importer exists (original request R09); named HTTP operators are narrower. The provider capability matrix (vision/audio/reasoning/continuation/logits per provider) is not published. | A bounded importer for the agreed contract subset with platform-generated probes, permission review and schema/effect validation; plus the published matrix. | 3–5 days |
| **F11** | The computer registry registers capabilities and explains a choice, but ordinary task execution still uses the expert's own sandbox configuration — it is not a distributed dispatcher, and kind-implied abilities are declared metadata rather than a device probe. | Dispatch bound to an authenticated worker with durable task/session identity, and capability, transfer, receipts, pause, disconnect, retry and cleanup verified on every advertised worker kind. | 1–2 weeks |
| **F12** | `sandbox.run` refuses hosted backends unless the workload is explicitly stateless, because no authorized workspace round-trip is implemented; the hosted tests use a local imitation. | Either scope hosted support to stateless operations in the docs and the guard (honest, ~0.5 day), or implement and qualify upload → execute → download → cleanup → unknown-outcome recovery against the real service (needs an account, §6). | 0.5 day / 1–2 weeks |
| **F18b** | The subquery sub-call still returns fenced text rather than the separately requested schema-validated structured result. (The memory half is fixed; this half was always a second claim.) | A validated structured return with provenance and error limits, or the claim narrowed. | 1 day |
| **F19** | `signatures.py` routes nothing and the lexical floor keeps authority pending SIG-001; the scheduler is shadow-only; the broader cognition/adaptation program is unestablished. | Keep every one of them labelled experimental/shadow in buyer-facing material (already true in the code), and complete each frozen comparison before it changes a live decision or appears as a benefit. | discipline, not days |
| **F16** | The requested narrated SaaS walkthrough (original R05 — explore, discover flows, record, narrate, compose, check the final video) has no delivered workflow or final-video acceptance receipt. | One scoped authorized walkthrough end to end, with control, recording, composition, quality checks, costs and failure recovery. | 1–2 weeks (and needs an authorized target app) |
| **N03** *(new today, cosmetic)* | `test_mcp.py` prints **nine Python tracebacks** (`UnicodeDecodeError` from `subprocess` reader threads) into the suite output while passing. It is a deliberate invalid-bytes case, and it is identical on pristine `main` — but a buyer reading the evidence log sees nine tracebacks in a green run and has to be told they are fine. | Read the child's stream as bytes, or decode with `errors="replace"`, so the deliberate case is *described* rather than *thrown*. | 1 hour |
| **T12 / Tutor** | 20 of 38 Tutor packages have not started; 13 are partial. | See §7. | weeks |

---

## 6. Still open — gated on the owner, not on code

**Nothing in this section can be closed by engineering alone.** Each needs a
decision, an account, a budget, a device or a person. They are the real
critical path to a handover a buyer can rely on.

| ID | What is blocked | What unblocks it |
|---|---|---|
| **F07** | No live provider has ever been qualified. Every model call in the suite is a scripted mock. | Freeze a provider, model and rates; authorize a spend budget; then run representative success, refusal, retry/fallback and cancellation tasks and keep the deliverables, checks and gateway receipts. **This is the single highest-value run available.** One day's work once a key and a budget exist. |
| **F08** | The learning and lift experiments (LEARN-001, LIFT-001A) are `NOT_RUN`, so "it learns and improves" is unmeasured. | The same key and budget, plus held-out work and a baseline; report quality, total cost, human intervention, failures and retention. |
| **F13** | Bounded browser hardening is not general computer-use acceptance; `computerbench` cannot self-certify. | An independently controlled held-out acceptance pack for the exact supported track. |
| **F14** | Unattended deployment and recovery are not demonstrated: no buyer-target install, no long real-provider soak, no restored backup on fresh hardware, no alerting, no support runbook. | A target host and an agreed soak window. Then install the exact release, drive it through outages and restarts, restore a backup, and verify data, budget limits and rollback. |
| **F20** | `main` is **unprotected**: no required review, no required status checks, no rulesets, no published releases. | GitHub admin: protect `main`, require the `tests` workflow, tag a version, attach the payload digest. 30 minutes, and it is what makes every other claim in the handover auditable. |
| **H02** | The Tutor is outside the committed, remotely tested release. A buyer cloning `main` or running its installer gets Fleet only. | The scope decision in §1, then commit, review and CI the Tutor candidate. |
| **T01–T06, T09–T14** | The Tutor's twelve P1 items are each blocked on at least one of: an authorized provider route and budget; an independent subject-matter reviewer bound to a frozen content digest; consented human participants (novice usability, comprehension, accessibility); physical microphone/headset/speaker tests; real accounts and private connectors; a signed supported release. | Owner decisions and resources, in that order. Engineering cannot substitute for any of them. |

---

## 6b. Two handover facts that are not defects — and that I would settle before signing

**H03 — the repository is public, under AGPL-3.0.**
`gh repo view` reports `"visibility":"PUBLIC"`, `"isPrivate":false`, and the
one-line installers in `README.md` resolve (HTTP 200 for `install.ps1`,
`install.sh`, `get-fleet.sh`). So the thing being offered for is *already*
publicly readable and forkable, and AGPL-3.0 obliges anyone who runs a
modified version over a network to publish their source. That may be exactly
what you intend. If the offer assumes exclusivity, a private copy, or a
permissive licence for the buyer's own closed product, settle it in writing
**before** handover — relicensing is yours to do as the sole copyright
holder, but only before other contributors' code is in the tree.
Note also that the public tree includes the full audit record
(`GAPS_RISKS_AND_UNFINISHED.md`, `REMEDIATION.md`), which is an asset in a
technical diligence conversation and a liability in a naive one. I would keep
it and lead with it.

**H05 — nine working folders, seven of them holding already-merged branches.**
`git worktree list` shows 14 worktrees of this repository. Seven carry
branches **fully merged into `main`** — `codex/bounded-computer-use` (40 MB),
`codex/bounded-computer-use-integration` (18 MB),
`codex/cu1-independent-postconditions` (16 MB),
`codex/twin-measurement-integrity` (17 MB),
`codex/user-workflow-completion` (13 MB) and two temporary ones. Three carry
real unmerged work: `codex/screen-tutor-build` (466 MB),
`codex/twin-depth-reconciliation` (12 MB, 5 commits ahead) and
`phase10.1/twin-depth` (42 MB, 1 commit ahead, currently owned by another
working session). This is H01's problem in its everyday form: a buyer — or
you, on a tired evening — opens a folder and cannot tell which one is the
product. After committing, retire the merged ones with
`git worktree remove <path>`, keep the three that still hold work, and put
one line at the top of each saying what it is for. I removed nothing.

**H04 — a month of Screen Tutor work is in no git repository.**
`origin` was last pushed **12 September 2026**. The Tutor worktree carries
**20 modified tracked files and 77 untracked entries** on top of commit
`160fa4b`, and none of it is pushed anywhere. The good news: `.gitignore`
already excludes `companion/windows/**/bin|obj` and `tests/native/**/bin|obj`,
so of the ~247 MB on disk (154 MB of it .NET build output)
`git add -A --dry-run` would carry **626 files** — 299 evidence logs, 131
JSON, 76 Markdown, 75 Python, 31 C#, 4 csproj, 3 XAML. That is source and
evidence, not artefacts. The project folder sits inside OneDrive, so the
files are most likely synced to the cloud — but OneDrive is a file copy, not
version control: it keeps no commit history, it cannot tell a deliberate
change from a sync conflict, and a stray `git clean` or a conflicted sync
replicates the loss. **Commit it to its branch and push it**, even
unreviewed and behind a `wip/` name — reviewing a pushed branch is easy,
reconstructing an unpushed one from synced files is not.
(The branch is currently PAUSED and owned by another working session; the
push is the owner's call, which is why I did not stage anything in it.)

---

## 7. Screen Tutor, by the numbers

From `planning/screen-tutor-execution/BUILD_STATE.json` (revision 66,
**PAUSED**, 14 Oct 2026):

| State | Count |
|---|---|
| Accepted | **5** — preservation; protocol/permissions/cancellation; the locked environment; one in-process learning-service contract; limited native summon/capture/bridge |
| Partial, acceptance withheld | **13** |
| Not started | **20** |

The visible journey a buyer would be shown — *pick a source → ask → get an
answer → see it highlighted on screen → practise safely* — is **not
connected end to end**. The pieces that exist are foundations and contracts,
tested against local fixtures and controlled native checks (including a real
322×272 capture and a verified .NET 10.0.401 toolchain). That is genuine
engineering; it is not a product demonstration, and the audit register
(T01–T14) says exactly which link of the chain is missing.

---

## 8. The route to a release a buyer can rely on

Sequenced so that each step makes the next one cheaper, and so the expensive
owner-gated items start as early as they can.

**Now (hours).**
1. Review and merge `fix/handover-defects-2026-10-14` (§4) — twelve fixes,
   one new test, nine new mutations, and the two documents this one belongs
   to. The branch is currently **uncommitted work in a worktree at
   `C:\Users\redab\ef-fix`** — commit it first, for the same reason as H04.
2. Protect `main` and require the `tests` workflow (**F20**). Tag the merge.
3. Decide §1: Fleet-only handover, or both products.

**This week (days), in parallel.**
4. Get a provider key and a spend ceiling in place and run **F07**. Until
   this exists, the platform's central claim is untested against a real
   model.
5. Close **F06** (ordinary-user forms and the navigation registry), **T07**,
   **T08**.
6. Pick the honest option for **F10** and **F12** — describing the real
   boundary is a legitimate, cheap close, and the current docs already do it
   in the code; the buyer-facing material is what must agree.
7. Publish the **F09** compatibility list and the **F17** provider matrix.

**Then (1–2 weeks).**
8. Run **F08** on the frozen protocols. This is what turns "it learns" from
   a design claim into a measurement.
9. **F14**: install the tagged release on a real target, soak it, restore a
   backup, write the support runbook.
10. **F15**: reconcile the Twin depth candidate under review.

**Only if the Tutor is in scope.**
11. Commit the Tutor candidate, get it through CI (**H02**), finish the
    visible lesson chain (T01–T06, T09), then start the human, content,
    device and accessibility qualifications (T10–T14) — these have lead
    times measured in weeks because they need other people.

---

## 9. The 30 original requirements — where each one stands

The 12 October audit preserved all **30 original request themes** (R01–R30)
from the build record and gave each a current disposition
(`audit-handover-2026-10-12/ORIGINAL_REQUIREMENTS_MATRIX.json`). Read as a
whole, the pattern is consistent and worth stating plainly:

> **Of the 30 things originally asked for, none is closed end to end to this
> project's own standard — and for most of them the reason is not missing
> code but missing *qualification*.** The usual shape of a row is
> "mechanisms built and tested against fixtures; the real-world outcome
> unmeasured", and the thing standing in the way is a provider key, a human
> participant, a device, a deployment target or a reviewer.

| Requirement (abridged) | Disposition | Blocked by |
|---|---|---|
| R01 one understandable platform, every capability reachable | Partial → **improved today** (F01–F05 closed; F06 forms + naming remain) | F06 |
| R02 guided creation: job → knowledge → access → checks → cost → review | foundation built, user qualification open | F06, F07 |
| R03 give an objective, see real execution and reuse | mechanisms integrated, live outcome open | **F07, F08** |
| R04 a computer the agent can operate dependably | bounded foundation, general acceptance open | F13 |
| R05 explore a SaaS and produce a narrated recorded walkthrough | **unfinished** | F16 |
| R06 run privately in the cloud, use from phone, keep working away | **deployment unverified** | F12, F14 |
| R07 accept many providers, adapt to new models | partial candidate, provider blocked | F07, F17 |
| R08 use screenshots directly in the governed loop | partial, provider blocked | T01, T02 |
| R09 integrate arbitrary tools/APIs through common contracts | unfinished broader scope | F17 |
| R10 modern MCP alongside the legacy adapter | unfinished broader transport | F09 |
| R11 A2A task-level interoperability | unfinished | F10 |
| R12 lifetime memory with a clean bounded active context | mechanisms tested, lifetime claim unverified | F14, F19 |
| R13 schema-validated isolated investigation of huge inputs | **bounded-input defect fixed today (F18)**; the schema-validated return remains | F18b |
| R14 schedule work partly for what will be learned | mechanisms/experiment, outcome open | F08, F19 |
| R15 route individual kinds of cognition | partial | F07, F19 |
| R16 cheap models become more effective at equal or lower cost | **unverified** | **F08** |
| R17 show learning on fresh tasks and transferable procedures | mechanisms tested, transfer outcome open | **F08** |
| R18 structural capability matching beyond wording | shadow only | F19 |
| R19 governed recursive improvement of the harness | infrastructure governed, experiment open | F19 |
| R20 specialized cheap models, test-time adaptation | experimental/conditional | F19 |
| R21 a cognitive Twin that predicts the owner | basic merged, depth candidate unaccepted | F15 |
| R22 monitoring, recurring work, pause and recovery controls | backend ahead of the UI → **F05 closed today** | F06, F13 |
| R23 accurate enforceable budgets and transparent costs | UI defect fixed, complete economic accounting open | F07, F08 |
| R24 honest public claims and evidence-backed readiness | **both named copy defects closed today (F03, F04)** | — |
| R25 full documentation and source package | source archive verified, handover alignment open | H01 (half-closed), H02, T14 |
| R26 keyboard and mobile usability, clear errors | **keyboard defect closed today (F02)**; broader acceptance open | T13 |
| R27 defensible research, external comparison | planned, results unestablished | F08, F19 |
| R28 continue the authorized work, merge only after review/CI | advanced, gates open | H02, F15, **F20** |
| R29 learn from books, documents, images, audio, video, courses, links | converters exist, universal ingestion unqualified | T10, T11 |
| R30 multiple specialist types collaborating | foundations built, live quality open | F06, F07 |

Count the right-hand column and the critical path is obvious: **F07 and F08
(a provider key and a budget) appear in eight rows; F20 (one GitHub setting)
gates the release identity; F14 (a deployment target) gates three.** Those
three unlocks move more of this matrix than any amount of further coding.

---

## 10. What can honestly be claimed to a buyer today

Useful to have written down, because the platform's own standard is that a
claim without a test is a defect.

**Say this.** 124 stdlib-only Python modules; 161 registered acceptance
scripts and 225 registered mutations; 6 CI jobs across Ubuntu and Windows ×
Python 3.11/3.12/3.13 green on the audited baseline; 0 execution-authority
bypasses across the tree; frozen caller-authored graders sealed outside the
worker's reach with a TAMPER verdict if edited; a model-free procedure
replay path proven end to end against a provider rigged to fail; a derived
six-level proof system no endpoint can set; a memory institution with
citations, expiry, supersession and a retraction feed; files the owner owns,
and any provider — or none.

**Do not say this yet.** That any of it has been measured against a live
commercial model; that learning or lift has been quantified; that hosted
sandboxes, a distributed worker fleet, third-party MCP servers or A2A peers
work; that general computer use or desktop control is supported; that an
unattended deployment has been demonstrated and recovered; that Screen Tutor
is a product.

The difference between those two lists is §6, and most of it is one API key,
one GitHub setting, one target host and a few human reviewers away.
