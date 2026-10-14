# Platform Map — what is what

**One document that answers "what is this, what is in it, and what does each
part actually do."** Written 14 October 2026 against the release candidate
below. It is a map, not a sales page: every count in it was read off the tree
by a command, and every claim about what is *proven* is bounded in §17.

| | |
|---|---|
| Product | **Expert Fleet** — a platform for building expert AI agents that work continuously, prove what they did, and remember what they learned |
| Second product, same tree | **Screen Tutor** — a native companion that watches a screen and teaches; partially built, see §16 |
| Code | 124 Python modules, 56.7k lines, **Python standard library only** — no framework, no database, no build step |
| Tests | 161 registered acceptance scripts · 223 registered mutations · 6 CI jobs (Ubuntu + Windows × Python 3.11/3.12/3.13) |
| Interfaces | one HTML control panel (49 HTTP endpoints) · 186 CLI subcommands across 42 modules |
| State | plain files on disk that the owner owns. No hosted component, nothing phones home |
| Model | provider-universal: OpenRouter, Anthropic, OpenAI, Gemini, xAI, DeepSeek, Groq, NVIDIA, Hugging Face, Cloudflare Workers AI, or a local Ollama with no key at all |
| Licence | AGPL-3.0 |

---

## 1. The idea in one paragraph

An LLM with a shell is not an employee. It forgets everything between
sessions, drifts off the objective inside a long task, cannot be held to a
specification nobody wrote down, and — most expensively — will report a job
finished when it is not. None of that is fixable inside the model, because
the model is the thing being asked. So this platform surrounds a cheap model
with the machinery that makes its output *verifiable*: a gate that must exit
zero before "done" is accepted, an objective held outside the transcript,
ledgers that make yesterday's failure cheap, and a proof system in which no
status can be set by hand.

**The law under everything: "done" is a mechanical check the worker cannot
edit.** Every lane in §4 is a different shape of that one law.

---

## 2. The two products, and which bytes are which

This repository is the home of both products. They are at very different
stages, and a handover has to name them separately.

| | Expert Fleet | Screen Tutor |
|---|---|---|
| Where | the repository root — the 124 modules in §15 | `companion/` (native .NET), `learning_contracts.py`, `teaching_packs/`, `tests/test_tutor_*.py`, `planning/screen-tutor-execution/` |
| Release state | committed, remote `main`, 6 CI jobs green on the audited baseline | **uncommitted work on a branch** (`codex/screen-tutor-build`), never in CI |
| Completeness | the machinery is built and tested; the gaps are qualification and polish | 5 of 38 work packages accepted, 13 partial, 20 not started |
| What a buyer can run today | everything in §4–§14 | foundations and contracts, not the visible lesson |

See `HANDOVER_STATUS_2026-10-14.md` for the exact commits, what was fixed
today, and what remains.

---

## 3. The eleven ideas the rest of the platform is made of

1. **"Done" is a command, not an opinion.** A task may carry a definition of
   done. When the model calls `finish_task`, the platform runs that command;
   a non-zero exit **refuses** the finish and hands the failure text back.
   The count of refusals is kept, because *how often it claimed completion
   and got caught* is the most honest reliability number here.
2. **The objective lives outside the conversation.** A mission is an
   objective plus success criteria, on disk, immutable (amendments are
   recorded and fingerprinted), recompiled into every context window — so a
   compaction, a restart or a model swap cannot erase the goal.
3. **Six authorities, not scattered checks.** One mandatory gateway per kind
   of power (§6), and a source audit that fails the build on a bypass.
4. **Proof is derived, never claimed.** Six levels computed from evidence
   bound to a code hash; change a file a capability covers and its badge
   drops by itself. **No endpoint accepts a level** (§12).
5. **Memory is an institution, not a vector store** (§7).
6. **It finds its own sources — from catalogues, never a search engine**
   (§8).
7. **A goal's graders are frozen before the work begins**, sealed outside the
   expert's root; a worker that edits them anyway gets a TAMPER verdict (§4,
   `contract.py`).
8. **The machine runs what is proven; the model is spent on the frontier**
   (§9) — the economic claim of the whole design.
9. **Competence is proven on sealed unseen work** the student can neither
   read nor edit (`capability.py`, `mastery.py`).
10. **You can steer a running pursuit — and steering is never a grader**
    (`steer.py`): advice lands in the planner's next cycle and on the ledger,
    and never touches a verdict.
11. **Learned claims age**: expiry, supersession and a fleet-wide retraction
    feed; directive-shaped memory is flagged at the source (`freshness.py`).

---

## 4. How work enters: three families, nine lanes

You never have to choose a lane yourself — `universal.py route` reads the
goal's shape with a deterministic rule, names the lane and says why. It is a
floor, not a ceiling: override it freely.

**WORK — you walk away with an outcome**

| Lane | Module | "Done" means |
|---|---|---|
| Task | `loop.py` | its done-check command exits 0 |
| Goal | `goal.py` + `contract.py` | VERIFIED: every sealed acceptance test passes in a harness run |
| Mission | `mission.py` | every criterion met by recorded evidence |
| Workflow | `workflows.py` | each stage's gate passed, in order |
| Team | `team.py` | the members' gates plus the lead's synthesis |

**COMPETENCE — you walk away with a capability, provable on unseen work**

| Lane | Module | "Done" means |
|---|---|---|
| Learning | `ingest.py`, `curriculum.py`, `verify.py` | spec 100% · closed-book exam ≥ threshold · zero gaps |
| Mastery | `mastery.py` + `capability.py` | harness-run validators clear the pack's frozen bars |
| Runbooks | `runbook.py` | every step's verify exits 0, under earned trust |

**ANSWERS — you walk away with a cited answer**

| Lane | Module | "Done" means |
|---|---|---|
| Consult | `consult.py` + `citecheck.py` | every claim's citation resolves, or NOT IN MY TRAINING |

The lanes resemble each other in pairs — a task is a goal with one grader, a
runbook is a workflow that earned zero-model trust, mastery is learning with
a sealed proof — but each difference is a tested law: who executes, who
grades, and whether the student can read its own exam. All nine enqueue into
the same task loop, one authority stack, one memory.

---

## 5. How a task actually runs, end to end

```
   owner (panel / CLI)                     an expert on disk
        │                                   experts/<slug>/
        │  queue a task                       identity.md  settings.toml
        ▼                                     state.json   courses/ memory/
  ┌───────────────┐                           logs/ contexts/ artifacts/
  │  state.json   │  the queue, the ledger, the archive
  └──────┬────────┘
         │  loop.py picks the next task under a cross-process lock
         ▼
  ┌──────────────────────────────────────────────────────────────┐
  │ context.py — COMPILE the window (never append a pile)        │
  │  · the mission contract        · the role's prompt           │
  │  · memory the memrouter allows this role to see              │
  │  · gotchas, cases, commons, premises                         │
  │  · untrusted material arrives FENCED and marked              │
  └──────┬───────────────────────────────────────────────────────┘
         │
         ▼  modelgateway.py — metered, attributed, budget-braked
  ┌──────────────┐     one of five tools, each behind an authority
  │  the model   │ ──► read_file / write_file  → fileauth.py
  └──────┬───────┘     run_command            → policy.py → execution.py → sandbox.py
         │             subquery (sub-call)    → modelgateway.py (own purpose)
         │             ask_human              → approvals / blocked.md
         │             finish_task            → the GATE
         ▼
  ┌──────────────────────────────────────────────────────────────┐
  │ check_done — run the task's done-check under the SAME        │
  │ containment as any other command. exit 0 → done.             │
  │ non-zero → the finish is REFUSED, the text goes back, and    │
  │ the refusal is counted.                                      │
  └──────┬───────────────────────────────────────────────────────┘
         │
         ▼
  trace.py (one span per task) · effects.py (exactly-once side effects)
  procedure.py (if this family of work has been judged before, induce a
  procedure) · memory.py / skills.py / cases.py (what outlived the task)
```

Brakes on every cycle: step ceilings, wall-clock deadlines, a daily spend
breaker, compaction at a token threshold (and safety rules are *never*
summarized), checkpoints so long tool work recovers instead of restarting,
and a watchdog with a safe mode beneath all of it.

---

## 6. The six authorities

One mandatory gateway per kind of power. `python execution.py --audit`
scans the whole tree and fails the build if any module bypasses one —
**0 violations across 124 modules, 19 declared platform-internal** (run
today).

| Authority | Module | What it owns |
|---|---|---|
| Execution | `execution.py` | every process the platform starts |
| File | `fileauth.py` | every model-influenced filesystem path — containment *and* how the bytes land (atomic, durable) |
| Credential | `credentials.py` | one model for four credential sources; scrubbed out of every subsystem that must not see them |
| Model Gateway | `modelgateway.py` | every provider call: metered, attributed to a task, bounded by budget, recorded by purpose |
| Effect | `effects.py` + `approvals.py` | outward side effects, exactly once, with a human in the loop where declared |
| Control Plane | `controlplane.py` | the files that define every other control — read-only binds under docker, seal-and-revert on `host` |

The sixth exists because the first five answered nothing *between* them: a
role holding `run_command` could rewrite `settings.toml` by running a
program while the file tool was being refused. `tests/test_controlplane.py`
crosses every control path with every way a shell changes a file.

---

## 7. The memory institution

Not a vector store — a set of ledgers with rules about who may read them.

| Kind | Module | What it holds |
|---|---|---|
| Courses & cited atoms | `memory.py`, `ingest.py` | what it studied, each claim carrying its citation |
| Skills | `skills.py` | procedural memory as a validated composable graph, promoted on outcomes |
| Commons | `commons.py` | what the whole fleet knows together, plus peer consultation |
| Failures | `memory.py` | sixteen categories, so a failure can be routed rather than just retried |
| Gotchas | `gotchas.py` | the environment failures this expert already paid for |
| Cases | `cases.py` | whether the fix actually *held* |
| Experience | `experience.py` | what a sibling already paid to learn |
| Recall | `recall.py` | search the entire mind, including what compaction paged out |
| Competence | `proof.py`, `metrics.py` | measured from gated results, never self-declared |
| Freshness | `freshness.py` | expiry, supersession, fleet-wide retraction, directive-shape flags |
| Self-model | `selfmodel.py` | facts about itself instead of a persona |
| The Twin | `twin.py`, `twinmath.py` | a Self Kernel of the **owner** beneath every agent: consent chain, shadow seal, drift notice |

`memrouter.py` decides which kinds each role may see — the Student sees the
course and nothing else, because a closed-book exam is not closed-book if
the answers are in the window.

---

## 8. Knowing what it knows

- `sources.py` — the source ledger: every claim knows where it came from and
  what that is worth (tiers). Search-engine hosts are pinned to tier 4 and
  can never clear the learn bar.
- `discover.py` — finds its own material from **catalogues, deliberately not
  a web search**: OpenAlex, Crossref, DOAJ, PubMed, Zenodo, Software
  Heritage, GitHub, the EU open-data portal, the Library of Congress. The
  goal is reduced to its subject first, and any result sharing no
  substantive term with the query is dropped *and counted*.
- `conflicts.py` — what to believe when material disagrees (tier decides).
- `standards.py` — the bar, extracted from the material and made checkable.
- `knowledge.py` — the knowledge graph: entities, edges, load-bearing source
  concentration, the claims resting below the learn bar.
- `citecheck.py`, `memcheck.py` — the grounding rule, made mechanical.
- `premise.py` — refuse to build on something already known false.
- `research.py`, `research_plan.py`, `retrieval.py` — agentic retrieval and
  hybrid ranking with metadata gates *before* any embedding call.

---

## 9. The economics: the machine runs what is proven

The pre-AI agents that did regulated work reliably were not intelligent —
the work was written down as executable procedure and a machine replayed it,
verifying as it went.

- `runbook.py` — typed steps, each `do` + `verify`, run through the Execution
  Authority with **zero model calls**. Trust is *earned*: three all-verified
  wins promote candidate → proven, the trust ledger is CONTROL-zoned (a
  runbook cannot promote itself), applicability is typed (`when.not`,
  `when.requires`), and runbooks compose with their own gates.
  `runbook.py reconcile` is the model-free goal loop.
- `procedure.py` — when a family of work has been done and independently
  judged more than once, induce an executable procedure from those
  trajectories and let it earn PROVEN on an owner-sealed suite of instances
  it has never seen.
- `operators.py`, `verifier.py`, `verification.py`, `capability_graph.py`,
  `signatures.py` (shadow only), `scheduler.py` (shadow by default).
- Typed worlds the operators act on: `dbstate.py` (SQLite), `gitstate.py`
  (git), `httpstate.py` (HTTP), `tabletypes.py`/`tabular.py`/`xlsxstate.py`
  (tables and workbooks).
- `metrics.py` reports the consequence as **Amortization**: earlier versus
  later model steps per verified success, by family.

`goal.pursue` tries all of this *before* spending a model cycle. Where no
procedure matches, the result is **blocked with the frontier named**, never
improvisation — and `repair.py` closes the loop from the failing check's
recorded error, never from the model re-reading its own work.

---

## 10. Getting new tools without getting new authority

- `frontier.py` — the capability frontier: an agent may **propose** a tool it
  lacks and may never author the test. It declares an import or a binary,
  the *platform* generates the probe, and the probe must FAIL before
  anything is installed. Readiness is decided by a seal outside the agent's
  reach; a human adopts it from a terminal.
- `acquire.py` — the acquisition ladder, in a sandbox, with its own backend.
- `toolbox.py` — a live capability scan of this machine.
- `grants.py` — the owner says yes once, inside a boundary that holds.

---

## 11. The interfaces

**The control panel** (`ui.py` + `ui.html`, 49 endpoints) — six job-shaped
tabs (Home, Work, Agents, Resources, Proof, Admin) plus the moved-but-live
views (Guide, Knowledge, Models, System). Home shows blockers with exact
fixes, an onboarding checklist that reads real state, and the systems map.
A goal's cockpit shows frozen graders with live PASS/FAIL, budget bars,
milestones, owner steering and the replayable ledger. Ctrl/Cmd-K opens a
searchable palette where **every entry also prints the CLI that does the
same thing**, so the panel teaches the terminal instead of hiding it.
`uicards.py` keeps agent-returned UI structured (cards, never markup).

**The CLI** — 186 subcommands across 42 modules; `MANUAL.md` is the operator
manual, and a test walks every command the manual promises and fails if
argparse refuses one.

**The rituals** — `python bootstrap.py` (one idempotent setup command),
`python doctor.py` (is the software healthy), `python preflight.py` (is it
fit to run a business unattended), `python demo.py` (the whole platform,
keyless, in one run), `python loop.py check` (the only live probe; needs
keys), `python backup.py` (the memory is the asset, so it is portable),
`python package.py` (a distributable archive that refuses to carry secrets
or expert data).

---

## 12. How belief is accounted for

| Layer | Module | What it is |
|---|---|---|
| Proof levels | `proof.py` | **20 capabilities**, each at one of 6 levels: SPEC → IMPLEMENTED → OFFLINE VERIFIED → LIVE VERIFIED → ADVERSARIAL/STRESS VERIFIED → PRODUCTION PROVEN. Evidence is bound to a code hash; live evidence expires; **no endpoint accepts a level** |
| Evidence report | `evidence.py` | **13 systems**, each with its tests *and its stated blind spot*; every test prints a sentence describing what it observed and the report quotes them |
| Acceptance suite | `tests/run_all.py` | 161 registered scripts; `tests/test_invariants.py` enumerates rather than exemplifies (every subprocess call site, every control file, every credential source against every subsystem, all CLI subcommands the manual promises …) |
| Mutation testing | `mutate_check.py` | 223 registered mutations: break the behaviour, require its test to go red. A MISSED row is a test that measures nothing |
| Held-out evaluation | `evalsuite.py` | a score you are allowed to believe: sealed holdouts recorded against the code hash that spent them |
| Lift / learning experiments | `benchmark.py`, `learn_bench.py` | what the harness adds to the rented model, and longitudinal amortization — **both still awaiting a provider key** (§17) |
| Metrics | `metrics.py` | the twelve numbers, including verified-success rate, false-success, autonomy and amortization |

---

## 13. Interop and where work runs

- `providers.py` — any model, from anywhere; roles point at rails.
- `modelrouter.py` — routing from measured outcomes, not vibes.
- `mcp.py` — a legacy MCP **stdio** client (2025-06-18 initialization and
  tools). Modern MCP and Streamable HTTP are *not* implemented, and the
  module says so.
- `federation.py` — another owner's agents working with yours without
  trust: a signed card, exposure the owner chose, citation-gated
  consultation. It is a **custom protocol**; A2A `SendMessage`/`GetTask`
  are not implemented, and `a2a_task_api` is false.
- `workers.py` — the computers work runs on, and *why this one was chosen*.
- `sandbox.py` — swappable execution backend: `host` (explicitly not
  isolation), `docker` (read-only control plane by kernel bind, egress off
  by default, memory/pid ceilings, named containers so a timeout cannot
  orphan one), and hosted backends (bounded, see §17).
- `computeruse.py`, `computersession.py`, `computerverify.py`,
  `computerbench.py` — bounded browser authority with sealed observations
  and independent postconditions.

---

## 14. Deployment shapes

| Shape | Command | What it gives |
|---|---|---|
| Desktop (Windows) | `install.ps1` | `%USERPROFILE%\ExpertFleet` + a Desktop/Start-Menu shortcut |
| Desktop (Linux/macOS) | `install.sh` | `~/ExpertFleet` + a `fleet` command that proves the wiring before starting anything |
| Cloud 24/7 | `get-fleet.sh` + `deploy/VPS.md` | unprivileged user, systemd units installed but **not** enabled, and the full suite passing *on the server* before anything may start; the panel reached privately (Tailscale or a Cloudflare Tunnel with `UI_TOKEN`), never a raw open port |
| Containers | `docker compose up -d` | the same fleet sandboxed and resource-braked; the image refuses to build unless the whole suite passes inside it |

---

## 15. Every module, and what it is for

124 modules, grouped by the job they do. The sentence is each module's own
first docstring line.

### The engine
| Module | Lines | What it is |
|---|---|---|
| `loop.py` | 4844 | the persistent autonomous agent loop |
| `context.py` | 945 | the context compiler — what the model sees is a COMPILED VIEW |
| `harness.py` | 503 | the harness, as an inspectable object |
| `policy.py` | 328 | a deterministic guard between the model and the shell |
| `sandbox.py` | 462 | where model-written commands actually run |
| `locks.py` | 159 | cross-process locks for mutating ledgers and settings |
| `checkpoint.py` | 138 | fiber-style checkpoints — recover, don't restart |
| `confidence.py` | 283 | spend compute in proportion to doubt |
| `candidates.py` | 714 | test-time compute — spend thinking, keep the best |
| `watchdog.py` | 316 | watchdog and safe mode, beneath the model |

### The six authorities
| Module | Lines | What it is |
|---|---|---|
| `execution.py` | 417 | the one gateway every process must pass through |
| `fileauth.py` | 514 | one gateway for every model-influenced filesystem path |
| `credentials.py` | 418 | one credential model for every subsystem |
| `modelgateway.py` | 359 | every provider call metered, attributed and bounded |
| `effects.py` | 177 | exactly-once side effects across retries |
| `controlplane.py` | 758 | the worker cannot change its own authority |
| `gates.py` | 175 | the gate catalogue — a definition of done you can name |
| `approvals.py` | 164 | approval-gated side effects: the human in the loop |

### Creating agents
| Module | Lines | What it is |
|---|---|---|
| `fleet.py` | 234 | mint and inspect expert agents |
| `quick.py` | 273 | quick specialists in seconds, not study-days |
| `templates.py` | 380 | 24 pre-built specialists |
| `team.py` | 361 | chosen specialists collaborating on one piece of work |
| `org.py` | 590 | several people sharing one fleet, with roles and an audit |
| `bootstrap.py` | 472 | one command to run the platform today |
| `demo.py` | 204 | no-keys demo: the entire ecosystem on your machine |

### Work systems
| Module | Lines | What it is |
|---|---|---|
| `goal.py` | 685 | state what you want; the system pursues it |
| `contract.py` | 677 | what "done" means, frozen before any work begins |
| `mission.py` | 579 | an objective that survives everything |
| `workflows.py` | 167 | fixed stages with gates, before autonomy |
| `consult.py` | 171 | the mode for fields an agent cannot execute |
| `prospective.py` | 519 | remembering to ACT, not just remembering facts |
| `routines.py` | 233 | show the work once, then have it done forever |
| `reconciler.py` | 422 | the cluster-controller pattern as a standing responsibility |
| `steer.py` | 148 | the owner's live guidance into a running pursuit |
| `repair.py` | 383 | a blocked goal fixes what blocked it, grounded in evidence |
| `swarm.py` | 315 | a goal multiplies its workers only where evidence says to |
| `universal.py` | 1163 | one goal in, a readiness verdict and real work out |
| `chief.py` | 326 | chief of staff — the personal strategic operator |

### Competence
| Module | Lines | What it is |
|---|---|---|
| `capability.py` | 463 | what competence MEANS, defined outside the student |
| `mastery.py` | 458 | learn a domain, prove it on unseen work, keep it |
| `curriculum.py` | 405 | study in a considered order |
| `ingest.py` | 1387 | every input type, exact path |
| `verify.py` | 134 | mechanical spec verification — L0 |
| `verifier.py` | 406 | mechanical gates as governed objects |
| `verification.py` | 137 | optional L1–L4 judges around an authoritative L0 |
| `evalsuite.py` | 475 | a held-out evaluation suite |
| `training.py` | 637 | the governed half of learning from verified experience |

### Memory and knowledge
| Module | Lines | What it is |
|---|---|---|
| `memory.py` | 518 | the categories that outlive every model |
| `memrouter.py` | 134 | which kinds of memory this task may see |
| `skills.py` | 746 | procedural memory as a validated, composable graph |
| `commons.py` | 480 | shared memory for the whole fleet |
| `recall.py` | 280 | search an expert's entire mind |
| `gotchas.py` | 551 | the failures this expert already paid for |
| `cases.py` | 268 | did the fix actually work? |
| `experience.py` | 350 | what a sibling already paid to learn |
| `premise.py` | 190 | refuse to build on something known false |
| `selfmodel.py` | 333 | facts about itself, not a persona |
| `twin.py` | 1534 | a Self Kernel of the OWNER, beneath every agent |
| `twinmath.py` | 626 | every number the Self Kernel reports |
| `twinmeasurement.py` | 178 | retrospective evaluation artifacts |
| `sources.py` | 1071 | every claim knows where it came from |
| `conflicts.py` | 528 | what to believe when the material disagrees |
| `standards.py` | 277 | the bar, extracted and made checkable |
| `discover.py` | 596 | real material to learn from, without a search engine |
| `discovery_web.py` | 96 | opt-in general-web candidate lane |
| `knowledge.py` | 424 | what the fleet knows, and how the pieces connect |
| `citecheck.py` | 111 | zero room for hallucinated authority |
| `memcheck.py` | 119 | the grounding rule, mechanically checkable |
| `freshness.py` | 313 | learned claims age, get superseded, get retracted |
| `research.py` | 211 | establish the facts before answering |
| `research_plan.py` | 241 | deterministic claim/evidence planning |
| `retrieval.py` | 150 | hybrid ranking with metadata gates first |
| `memory_policy.py` / `memory_benchmarks.py` / `adaptation.py` | 110/191/90 | experimental, opt-in, never a production authority |

### Procedural learning and operators
| Module | Lines | What it is |
|---|---|---|
| `procedure.py` | 1508 | conservative workflow induction from graded actions |
| `operators.py` | 325 | a small observable operator algebra |
| `capability_graph.py` | 456 | what this expert can actually do, in one view |
| `runbook.py` | 911 | the goal agent's power that needs no model at all |
| `signatures.py` | 194 | structure as identity, in shadow |
| `scheduler.py` | 256 | contextual expected-utility scheduling, no learned lift claim |
| `calibration.py` | 116 | reliability curves (no production caller yet, and it says so) |
| `dbstate.py` | 446 | SQLite state |
| `gitstate.py` | 635 | git repository state |
| `httpstate.py` | 400 | HTTP state |
| `tabletypes.py` / `tabular.py` / `xlsxstate.py` | 236/343/365 | typed tables, deterministic transforms, workbooks |
| `evaluation_policy.py` / `evaluation_workspace.py` / `evaluation_corpus.py` | 33/87/124 | owner-controlled experiment switches, disposable snapshots, the TRAIN corpus |
| `learning_authority.py` | 84 | owner-created immutable learning records |
| `trainer_integration.py` | 63 | the data/recipe boundary for external trainers |

### Proof, measurement, governance
| Module | Lines | What it is |
|---|---|---|
| `proof.py` | 822 | "finished" is a derived status, never a claim |
| `evidence.py` | 691 | why we believe each system works, and where belief runs out |
| `metrics.py` | 737 | the twelve numbers that say whether any of this is working |
| `mutate_check.py` | 1367 | break the feature, confirm the test notices |
| `benchmark.py` | 541 | what does the harness add to the rented model? |
| `learn_bench.py` | 468 | longitudinal inference amortization, measured |
| `replay.py` | 202 | measure a model (or charter) against recorded trajectories |
| `variants.py` | 550 | charter evolution, governed |
| `modelrouter.py` | 481 | pick the model from measured outcomes |
| `designcheck.py` | 389 | mechanical checks a produced interface must survive |
| `trace.py` | 282 | one trace per task: spans, costs, gates, tool error rates |
| `preflight.py` | 586 | is this fleet fit to run someone's business on? |
| `doctor.py` | 438 | is the whole platform healthy? |

### Capability acquisition and infrastructure
| Module | Lines | What it is |
|---|---|---|
| `frontier.py` | 1566 | how this fleet obtains a tool nobody anticipated |
| `acquire.py` | 879 | a new tool without new authority |
| `toolbox.py` | 379 | a live capability scan of this machine |
| `grants.py` | 439 | the owner says yes once, inside a boundary that holds |
| `workers.py` | 389 | the computers work runs on, and why this one |
| `providers.py` | 383 | any model, from anywhere |
| `mcp.py` | 1040 | legacy MCP stdio tool client |
| `federation.py` | 499 | another owner's agents, without trust |
| `backup.py` | 672 | the memory is the asset, so it is portable |
| `package.py` | 98 | the distributable archive |

### Computer use (bounded)
| Module | Lines | What it is |
|---|---|---|
| `computeruse.py` | 503 | bounded browser authority, host-owned clicks, artifact checks |
| `computersession.py` | 861 | task-owned stdio session, durable lineage-bound action state |
| `computerprocess.py` | 294 | an owned stdio process tree, no model entry point |
| `computerverify.py` | 676 | frozen CU-1 postconditions, no model or executor entry |
| `computerbench.py` | 681 | bounded development qualification |
| `computerbench_verifier.py` | 1070 | the externally installed acceptance verifier |

### Control plane
| Module | Lines | What it is |
|---|---|---|
| `ui.py` | 2768 | the control panel server — mission control for the whole system |
| `ui.html` | — | the single-page panel it serves |
| `uicards.py` | 184 | generative UI, safely: structured cards, never markup |

---

## 16. Screen Tutor, exactly as it stands

A native companion (`companion/`, .NET) plus Fleet-side learning contracts
that watch a screen, answer a question about what is on it, highlight the
answer, and set safe practice. The build is tracked packet by packet in
`planning/screen-tutor-execution/BUILD_STATE.json` (revision 66, status
**PAUSED** by owner instruction, 14 Oct 2026).

| State | Packets | Meaning |
|---|---|---|
| Accepted | **5** | preservation; protocol/permissions/cancellation; the locked environment; one in-process learning-service contract; limited native summon/capture/bridge |
| Partial, acceptance withheld | **13** | each blocked on a named external gate: an authorized provider route and budget, an independent subject-matter reviewer, consented human participants, physical audio devices, real accounts, or a signed release |
| Not started | **20** | the rest of the declared program |

What this means in plain terms: the *foundations and contracts* exist and are
tested against local fixtures and controlled native checks. The **visible
journey — pick a source → ask → get an answer → see it highlighted →
practise safely — is not connected end to end.** No part of the Tutor has
been through CI, because it is not committed.

---

## 17. The honest ceiling — what is NOT proven

This section is the reason the rest can be trusted. Nothing below is a
defect; each is a boundary of the evidence.

- **No live provider has been qualified.** Every model call in the suite goes
  to a scripted mock. Prompt effectiveness, real cost, genuine failover and
  cancellation against a commercial API are unmeasured. `python loop.py
  check` is the only live probe and it needs keys.
- **The learning and lift experiments have not been run** (LEARN-001,
  LIFT-001A). Mechanism validation is not measured benefit.
- **Hosted sandboxes (E2B/Daytona) refuse ordinary workspace execution** —
  only explicitly stateless workloads are allowed, because no authorized
  workspace round-trip is implemented. Hosted tests use a local imitation.
- **The computer registry is not a distributed dispatcher.** It registers
  capabilities and explains a choice; the regular task path still uses the
  expert's own sandbox configuration.
- **Bounded browser work is not general computer use.** The adapter is
  restricted to its bounded invoice-target vocabulary; native desktop, real
  accounts, held-out acceptance and live models remain separate.
- **MCP is the legacy stdio subset; federation is a custom protocol.** No
  third-party MCP server and no A2A peer has been qualified.
- **Unattended deployment and recovery are not demonstrated** at a buyer
  target: no long real-provider soak, no restored backup on fresh hardware,
  no production alerting or support runbook.
- **Structural routing, cognition-stage routing and the adaptation program
  are gated research** — `signatures.py` and `scheduler.py` run in shadow and
  hold no authority.
- **The panel is not rendered in CI.** Its HTML is parsed and its API driven;
  layout, contrast and touch targets are judged by eye.
- **24/7 behaviour at duration is untested** — memory growth, ledger size,
  log rotation and lock contention over weeks are unknown.
- **The Twin's deeper cognitive candidate is unmerged** and its capture,
  containment and recovery boundaries are unverified.
- **Screen Tutor** — see §16.

`EVIDENCE.md` states a blind spot for each of the 13 systems in those terms,
and `GAPS_RISKS_AND_UNFINISHED.md` is the preserved audit record of what was
once wrong and how it was proven.

---

## Reading order for the rest of the documentation

1. `README.md` — the tour, with the comparison table and the evidence summary
2. `QUICKSTART.md` — 15 minutes from zero to a first VERIFIED goal
3. `ARCHITECTURE.md` — the complete technical account
4. `REFERENCE.md` — every module, setting, endpoint and event name
5. `MANUAL.md` — the operator manual (every CLI command)
6. `EVIDENCE.md` — why we believe it, and where belief runs out
7. `GOAL_SPECIALIST.md` — the goal system in depth, with its gap register
8. `SECURITY.md`, `SYSTEM_DIAGRAMS.md`, `TRACEABILITY_MATRIX.md`,
   `docs/DESIGN-P*.md` — security model, diagrams, requirement traceability,
   and the design record for each phase
9. `HANDOVER_STATUS_2026-10-14.md` — what is done, what is not, and who must
   do each remaining thing
