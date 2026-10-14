# Research Foundations

**Why Expert Fleet is built the way it is — the idea, the studies behind each
decision, the inspirations from outside machine learning, and exactly what
would prove or disprove the claim that it beats the alternatives.**

This is the lab's account of its own design. Every mechanism below is traced
to the finding that motivated it, to the module that implements it, and to
the test that would fail without it. Every paper cited was checked against
the arXiv API (or, for classics and blog posts, against the publisher) on
14 October 2026; the full list is at the end.

Each claim carries one of three labels, because this lab's first rule is
that a claim without evidence is a defect:

| Label | Meaning |
|---|---|
| **MECHANISM-TESTED** | the behaviour exists and an acceptance test plus a mutation prove it holds — on scripted model calls, not a live model |
| **PREREGISTERED** | the hypothesis, arms, metrics and pass/fail thresholds are frozen in `experiments/` *before* any data exists; the result is not yet in |
| **DESIGN RATIONALE** | why the literature makes this the right bet; argued, not yet measured here |

Nothing in this document is labelled MEASURED-LIVE, because no experiment
has yet run against a real provider. §12 says what that will take.

---

## 0. The thesis

> **Capability comes from the system around the model, not from the model
> alone — and the most important thing that system does is decide, by a
> check the model cannot edit, whether the work is actually done.**

A language model with a shell is not an employee. It forgets between
sessions, drifts inside a long task, cannot be held to a specification
nobody wrote down, and — the most expensive failure — reports work finished
when it is not. None of that is fixable *inside* the model, because the
model is the thing being asked. The research of the last three years points
the same way from several directions: models are poor judges of their own
correctness (§1), self-improvement compounds only when it is grounded in
signals from outside the model (§2), long context degrades rather than
scales (§4), memory and retrieved text are attack surfaces (§6), and more
agents help only where the work separates cleanly (§7).

Expert Fleet's bet is to take each of those findings literally and build the
counter-measure into the platform as a **law with a test**, rather than a
feature with a description.

---

## 1. The verification bottleneck — "done" is a check the worker cannot edit

**The finding.** Huang et al. (ICLR 2024) showed that large language models
struggle to correct their own reasoning *without external feedback*, and
that performance can even degrade after intrinsic self-correction.
Lightman et al. (2023) showed that supervising the *process* — checking each
step — produces more reliable verifiers than supervising only the final
answer. The field's most-cited agent benchmark, SWE-bench (Jimenez et al.,
2023), scores agents by **hidden tests the agent never sees**, which is the
same principle stated as an evaluation method. And Jiang et al. (2025,
*Feedback Friction*) found that models struggle to fully incorporate even
correct external feedback, especially when it arrives as a large undigested
dump.

**What it implies.** If the worker can author, read or edit the check that
decides whether it succeeded, the check measures the worker's opinion of
itself. The only reliable signal is one produced *outside* the worker's
reach.

**What we built.**

- **The gate** (`loop.py`, `check_done`): a task may declare a done-check
  command; `finish_task` runs it under the same containment as any command,
  and a non-zero exit refuses the finish and returns the failure. The count
  of refusals is kept as the platform's most honest reliability number.
- **Frozen, sealed graders** (`contract.py`): a goal's acceptance tests come
  from the caller, are hashed and sealed *outside the expert's root* before
  planning begins, and are run only by the harness. A worker that shells
  around the File Authority and edits them gets a **TAMPER** verdict — nothing
  runs, nothing passes.
- **The judge is overruled** (`goal.py`): a goal can end *achieved* on a
  judge's opinion but never *verified* without the frozen graders, and when
  the two disagree the graders win.
- **Repair receives small, explicit feedback** (`repair.py`, `goal.py`): the
  failing check's recorded error, verbatim and bounded — a direct response to
  *Feedback Friction*.

**Status:** MECHANISM-TESTED — `test_contract.py`, `test_goal.py`,
`test_repair.py`, plus mutations that remove the seal, the tamper check and
the overrule, each of which turns the suite red.

---

## 2. Self-improvement that cannot fool itself

**The findings.** Reflexion (Shinn et al., NeurIPS 2023) improved agents by
storing verbal reflections — but its gains came from tasks with real
feedback signals. Voyager (Wang et al., 2023) built a lifelong skill library
of executable code, and its loop is grounded in **environment feedback,
execution errors and self-verification**, not in re-reading its own output.
Self-Refine (Madaan et al., 2023) showed self-feedback helps on many
generation tasks — which, read beside Huang et al., locates the boundary:
self-feedback can polish *style*; it cannot certify *correctness*. The
Darwin Gödel Machine (Zhang et al., 2025) let a coding agent rewrite its own
code and kept a modification **only when it was empirically validated on a
benchmark afterwards**, maintaining an archive of variants rather than a
single lineage. Agentic Context Engineering (Zhang et al., 2025) treated
contexts as evolving playbooks, and named the failure modes of naive
accumulation — brevity bias and context collapse.

**What it implies.** A system that learns from its own runs must decide
what counts as a *win* with a signal it cannot generate itself, must keep
lineage so a regression can be undone, and must stop when it oscillates.

**What we built.**

- **Earned trust for procedures** (`runbook.py`): a runbook is promoted from
  candidate to proven only after **three wins in which its own steps
  verified *and* the caller's independent acceptance test passed
  afterwards**. The trust ledger is CONTROL-zoned — a runbook cannot promote
  itself, and a self-declared `"status": "proven"` is ignored.
- **Induction proven on unseen instances** (`procedure.py`): a procedure
  induced from repeated, independently judged trajectories earns PROVEN only
  by passing an owner-sealed suite of instances it has never seen — the DGM
  principle (validate empirically, after) applied to procedures.
- **Grounded repair under four laws** (`repair.py`): every repair cites the
  failing check's recorded error; revisions keep lineage beside their parent;
  budget and tamper blocks route to the owner alone; repair can move a goal
  back to running but can never grade it.
- **Demonstration is a claim, not evidence** (`runbook.py record`): a
  recorded demo becomes a CANDIDATE; replaying it proves it *runs*, and earns
  no trust, because a procedure grading its own replay is still the
  procedure grading itself.
- **Oscillation stops the lane**: a pursuit that hits the same wall twice is
  stopped with the wall named, instead of burning its budget on it.

**Status:** MECHANISM-TESTED (`test_runbook.py`, `test_procedure_v2.py`,
`test_procedural_learning.py`, `test_repair.py`). Whether this produces
*measurable* improvement over time is **PREREGISTERED** as LEARN-001 (§12).

---

## 3. The machine runs what is proven — the economics of amortization

**The inspiration — from before machine learning.** The agents that did
regulated, high-stakes work reliably for decades were not intelligent.
Web crawlers, workflow engines, spacecraft autonomy and cluster controllers
worked because the work was **written down as executable procedure** and a
machine replayed it, verifying as it went. Borg, Omega and Kubernetes (Burns
et al., 2016) made the *reconciliation loop* — observe actual state, compare
it with desired state, act on the difference, repeat — the backbone of
modern infrastructure. Spacecraft fault protection contributed the *safe
mode*: when something unexpected happens, drop to a minimal, known-good
configuration and wait for the ground.

**The modern finding.** Voyager's skill library, and the 2026 surveys of
agent skills (Xu et al., 2026; Xia et al., 2026), converge on the same
architecture from the model side: capabilities that are captured once as
reusable, inspectable procedures, and invoked rather than re-derived.

**What it implies.** Paying a model to re-derive, every time, a procedure it
has already got right is the most expensive way to run recurring work —
and the least auditable. The model should be spent at the *frontier*; the
machine should replay what is proven.

**What we built.**

- **Runbooks with zero model calls** (`runbook.py`): typed steps, each
  `do` + `verify`, executed through the Execution Authority. Applicability is
  typed (`when.not` negative triggers, `when.requires` live preconditions),
  and runbooks compose, each sub-runbook keeping its own trust gate.
- **The model-free goal loop** (`runbook.py reconcile`): observe the frozen
  acceptance tests, apply the matching proven runbook, re-verify, repeat —
  the Kubernetes reconciliation pattern applied to goals. `goal.pursue` tries
  it *before* spending a model cycle. Proven end to end: a pursuit completed
  VERIFIED with zero tasks created, against a mock provider rigged to fail.
- **Reconcilers, watchdog and sentinels** (`reconciler.py`, `watchdog.py`):
  standing responsibilities and spacecraft-style safe mode beneath the model.
- **Blocked with the frontier named**: where no procedure matches, the
  result is a named block, never improvisation — brittleness at the frontier
  is what killed the old deterministic agents, and the frontier is exactly
  where the model belongs.
- **Amortization as a metric** (`metrics.py`): earlier versus later model
  steps per verified success, by family.

**Status:** MECHANISM-TESTED (`test_runbook.py`, `test_reconciler.py`,
`test_watchdog.py`, `test_sentinels.py`). The *economic* claim — cost per
verified outcome falls as experience accumulates — is **PREREGISTERED** as
LEARN-001 H2 and requires a priced provider.

---

## 4. Context is compiled, not accumulated

**The findings.** Liu et al. (2023, *Lost in the Middle*) showed that models
use information at the start and end of a long context far better than
information in the middle — a longer window is not a proportionally better
one. MemGPT (Packer et al., 2023) borrowed the operating-system idea of
paging: a small active context, with the rest stored and fetched on demand.
Recursive Language Models (Zhang, Kraska & Khattab, 2025) went further: keep
the material **out** of the orchestrating window entirely, let the model
query slices through disposable sub-calls, and combine only the distilled
answers — a strategy the authors report beating much larger models on
long-context benchmarks at lower cost. ReAct (Yao et al., 2022) established
the reason-act-observe loop that every tool-using agent, including this one,
is built on.

**What we built.**

- **The context compiler** (`context.py`): every task's window is
  *compiled* from budgeted sources — the mission contract, the role's
  prompt, the memory kinds the router allows, gotchas, cases — never an
  append-only pile. Untrusted material enters fenced and marked.
- **The mission contract is recompiled into every window**: a compaction, a
  restart or a model swap cannot erase the objective.
- **The compaction-cliff law**: safety rules are never summarised.
- **Recursive sub-calls** (`loop.py`, `subquery`): RLM under the house
  laws — the slice is path-contained, the sub-call is metered through the
  Model Gateway under its own purpose, it has no tools (one level, no runaway
  recursion), and its answer returns fenced as untrusted. Since 14 October
  2026 the slice itself is *streamed*: a two-line slice of a 20 MB corpus
  peaks at 25 KB of memory, not 25 MB.

**Status:** MECHANISM-TESTED (`test_context.py`, `test_compaction.py`,
`test_subquery.py`, `test_handover_defects.py`).

---

## 5. Memory is an institution, not a vector store

**The findings.** CoALA (Sumers et al., 2023) gave language agents a
vocabulary from cognitive science — working, episodic, semantic and
procedural memory — and argued that each needs different storage and
different rules. Generative Agents (Park et al., 2023) retrieved memories by
recency, importance and relevance, and synthesised them through reflection.
A-MEM (Xu et al., 2025) and Mem0 (Chhikara et al., 2025) built linked,
evolving memory for production agents. The 2026 surveys (Du, 2026; Luo et
al., 2026) and LongMemEval-V2 (Wu et al., 2026) frame the open problem as
memory for an *experienced colleague* — one who remembers what worked, what
failed, and what has since changed.

**What it implies.** One undifferentiated store is the wrong shape. Different
kinds of memory need different gates, different lifetimes, and different
rules about *who may read them*.

**What we built** (`memory.py`, `memrouter.py`, `skills.py`, `commons.py`,
`gotchas.py`, `cases.py`, `freshness.py`, `recall.py`):

- **Cited atoms** — every learned claim carries its source; the grounding
  rule is mechanically checkable (`memcheck.py`, `citecheck.py`).
- **A memory router** decides which kinds each role may see. The Student
  sees the course and nothing else, because a closed-book exam is not
  closed-book if the answers are in the window.
- **Failures in sixteen categories**, **gotchas** this expert already paid
  for, and **cases** that record whether a fix actually *held*.
- **Freshness** — expiry, supersession with lineage, and a fleet-wide
  **retraction feed**: retract a source once and every atom citing it is
  flagged. Flags, never deletions; the owner decides.
- **Recall** across the whole mind, including what compaction paged out.

**Status:** MECHANISM-TESTED (`test_memory.py`, `test_memory_kinds.py`,
`test_freshness.py`, `test_cases.py`, `test_gotcha_retire.py`,
`test_recall.py`). Lifetime behaviour over months is unmeasured (§12).

---

## 6. Memory and inputs are attack surfaces

**The findings.** Greshake et al. (2023) showed *indirect prompt injection*:
instructions planted in data an LLM application retrieves can hijack it.
AgentPoison (Chen et al., NeurIPS 2024) poisoned agents' memory and
knowledge bases with triggers; Dong et al. (2025) showed memory injection
through ordinary query-only interaction, with no write access at all. Meta's
*Agents Rule of Two* (October 2025) — building on Chromium's Rule of 2 and
Simon Willison's "lethal trifecta" — argued that until injection can be
reliably detected, an agent session should combine at most two of: handling
untrusted input, reaching sensitive data or systems, and changing state or
communicating externally. And the oldest principle of all is Saltzer and
Schroeder's (1975) **complete mediation**: every access to every object must
be checked by one mechanism that cannot be bypassed.

**What it implies.** Security cannot be a set of checks at the call sites
their authors were thinking about. A forensic audit of this codebase found
exactly that pattern: *a control defends the path its author was thinking
about, and does not know about the other paths.*

**What we built.**

- **Six mandatory authorities** — Execution, File, Credential, Model Gateway,
  Effect, Control Plane — one gateway per kind of power: complete mediation,
  enforced. `python execution.py --audit` scans the whole tree and fails the
  build on any bypass (0 violations across 124 modules).
- **The Control Plane Authority** (`controlplane.py`): the files that define
  every other control are read-only binds under docker (the kernel prevents
  writes) and seal-and-revert on the developer host. `test_controlplane.py`
  crosses every control path with every way a shell changes a file — 100
  attacks, 0 durable changes.
- **Per-role tool allowlists** — the Rule of Two as configuration: roles that
  read untrusted material do not hold `run_command`.
- **Fenced untrusted content**, and **directive-shaped memory flagged at the
  source** (`freshness.py`) — atoms that command money, claim the owner's
  voice or carry injection idioms are flagged with the matched shape and
  source, the memory-poisoning attack surface named by AgentPoison and Dong
  et al. Memory is evidence here, never instruction.

**Status:** MECHANISM-TESTED (`test_invariants.py`, `test_controlplane.py`,
`test_execution_containment.py`, `test_guardrails.py`, `test_freshness.py`).
No external penetration test has been performed (§12).

---

## 7. Many agents only where the work separates

**The finding.** Cemri et al. (NeurIPS 2025, *Why Do Multi-Agent LLM Systems
Fail?*) catalogued fourteen failure modes in three clusters — system design,
inter-agent misalignment, and task verification — and found multi-agent
systems are often no better than a single agent. Project Sid (Altera, 2024)
demonstrated large many-agent simulations built from parallel stateless
modules.

**What we built.** `swarm.py` multiplies workers **only where the evidence
says the work is separable**, with graders held centrally so no worker
verifies its own share. `team.py` keeps teams to two-to-four specialists
with file handoffs and a lead's synthesis. Project Sid's PIANO architecture
was considered and rejected for this platform, with the reasoning recorded
in `ARCHITECTURE_DECISIONS.md`.

**Status:** MECHANISM-TESTED (`test_swarm.py`, `test_team.py`).

---

## 8. Spend compute in proportion to doubt

**The findings.** Snell et al. (2024) showed that allocating *test-time*
compute well can be more effective than scaling model parameters. Guo et al.
(ICML 2017) showed modern neural networks are systematically miscalibrated;
Tian et al. (2023) studied eliciting calibrated confidence from
instruction-tuned models; conformal prediction (Angelopoulos & Bates, 2021)
gives distribution-free guarantees; and learning to defer (Madras et al.,
2018) formalised when a system should hand a decision to a human.

**What we built.** `confidence.py` maps doubt to an escalation ladder
instead of spending the same effort everywhere — and computes that doubt
**without ever asking the model how confident it is**, because
self-reported confidence is the least reliable signal available (Guo et
al.; Sharma et al.). Every input is something the harness already measured:
did the gate pass, do the cited atoms exist, is a point contested, does
verified memory contradict the goal, what is this expert's measured record,
how often did the gate refuse along the way. `candidates.py` implements
Snell-style best-of-N test-time compute and scores candidates with the
verifiers that already gate the work — a candidate that fails the hard
done-check cannot win at any score; no model is asked "is this good?".
`calibration.py` computes held-out reliability curves (and says plainly that
it has no production caller yet). `modelrouter.py` promotes a cheaper model
only from measured outcomes, with sample sizes shown.

**Status:** MECHANISM-TESTED (`test_candidates.py`, `test_modelrouter.py`).

---

## 9. The Twin — modelling the owner, honestly

**The findings.** Park et al. (2024) built agents grounded in interviews
with over a thousand people that reproduced those people's survey answers
approaching the participants' own two-week test-retest consistency. Centaur
(Binz et al., 2024) and Twin-2K-500 (Toubia et al., 2025) pushed models of
human behaviour further. But Wang et al. (2025) concluded that LLM-based
human simulations **have not yet been reliable**, and Sharma et al. (2023)
documented sycophancy — models telling people what they want to hear. For
*when* to ask, value-of-information (Dong et al., 2026), clarification-timing
studies (Gulati et al., 2026; Deng et al., 2026) and Bayesian active
learning (Houlsby et al., 2011) all argue for asking rarely and well. For
noticing that a person has *changed*, changepoint detection (Page, 1954;
Adams & MacKay, 2007).

**What it implies.** A model of the owner must be **measured, not
asserted**: its predictions sealed before the owner acts, scored after, and
versioned when the owner changes — and it must never quietly start acting as
the owner.

**What we built** (`twin.py`, `twinmath.py`, `twinmeasurement.py`;
`docs/DESIGN-P10-twin.md`, `docs/research/`): a consent chain; a **shadow
seal** (predictions written before the decision, scored against it after);
a drift notice when the owner's pattern changes; and an OWNER context block
that informs agents without ever granting them the owner's authority.

**Status:** MECHANISM-TESTED for the merged Twin (`test_twin.py`,
`test_twin_measurement.py`). The deeper Twin (capture, cold start,
augmentation) is an unaccepted candidate. Prospective prediction accuracy
on a real owner is unmeasured.

---

## 10. Harness engineering is becoming a discipline — and this is one

In 2026 the field began naming what this platform had been building. Hu Wei
(2026) catalogued the architectural design decisions inside agent harnesses;
Lin et al. (2026) evolved coding-agent harnesses automatically from
observability data; and Ahn et al. (2026, *From Prompts to Contracts*) argued
that enterprise agents must move from prompts to **auditable contracts**.
That is the move this platform made at its foundation: the goal contract,
the gate catalogue, the proof system, the control-zoned ledgers. `harness.py`
exposes the harness itself as an inspectable object with a health ritual and
contract checks (`python harness.py --check`).

---

## 11. Evidence about the evidence

A passing test proves nothing unless it would fail with the feature removed.
**Mutation testing** (DeMillo, Lipton & Sayward, 1978) makes that checkable:
`mutate_check.py` breaks each load-bearing behaviour in turn — 225 registered
mutations — and requires the test that claims to cover it to go red. A
MISSED row is a test that measures nothing.

**Preregistration** (Nosek et al., 2018) — freezing the hypothesis, arms,
metrics and thresholds before collecting data — is the remedy for moved
goalposts. Every claim this lab intends to make about benefit is
preregistered in `experiments/` and committed before any provider key
existed in the installation (§12).

**Derived proof** (`proof.py`): six levels from SPEC to PRODUCTION PROVEN,
computed from evidence bound to a code hash; change a file a capability
covers and its level drops by itself; live evidence expires; **no endpoint
accepts a level**. `evidence.py` reports thirteen systems, each with the
sentences its tests printed and a **stated blind spot**.

---

## 12. Against the state of the art — what is structural, and what is still to be proven

The popular agent frameworks of 2026 have enormous integration ecosystems,
hosted polish and mobile apps that this local-first platform does not chase
(`README.md` names them and the comparison). The differences claimed here are
**structural** — properties of how the system is built, each held by a test:

| Property | The common pattern | Expert Fleet | Status |
|---|---|---|---|
| Who decides "done" | the model, or its framework, judges its own run | caller-authored graders sealed outside the worker's reach; TAMPER if edited; the judge overruled | MECHANISM-TESTED |
| Self-improvement | trust the loop to compound | a procedure is PROVEN only after independent acceptance; induction proven on unseen instances | MECHANISM-TESTED |
| Recurring work | re-derived by the model every time | replayed by the machine with zero model calls under earned trust | MECHANISM-TESTED |
| Security | wrappers around the framework | six mandatory authorities inside the platform; 0 bypasses enforced in CI | MECHANISM-TESTED |
| Long context | a bigger window | compiled windows and recursive sub-calls; the material never enters the window | MECHANISM-TESTED |
| Competence claims | self-reported | sealed capability packs the student cannot read or edit; the author never sits its own exam | MECHANISM-TESTED |
| Benefit over a bare model | asserted | preregistered head-to-head experiments | **PREREGISTERED — NOT_RUN** |

**Why we expect it to win.** Three mechanisms, each grounded above: (1) the
verification bottleneck (§1) means a system that cannot be fooled about
completion fails *less often* per attempt than one that can; (2)
amortization (§3) means recurring work gets *cheaper* over time instead of
costing the same every time; (3) complete mediation (§6) means the system
can be given *more autonomy safely*, which is where long-horizon value is.

**What would prove it — or disprove it.**

| Experiment | Question | Arms | Status |
|---|---|---|---|
| `experiments/LIFT-001.md` | does the harness make a cheap model smarter and cheaper, or dumber and more expensive? | bare model vs harnessed, same model and tasks | PREREGISTERED, NOT_RUN |
| `experiments/LIFT-001A.md` | the amended protocol: 20 tasks across 10 workload families | raw · minimal iterative · harness without persistence · full harness (· optional reference) | PREREGISTERED, NOT_RUN |
| `experiments/LEARN-001.md` | does accumulated verified experience reduce the marginal cognition needed for recurring work, without reducing reliability? | the same families run repeatedly with learning on | PREREGISTERED, NOT_RUN (instrument validated on mocks) |
| SIG-001 | may structural capability signatures take routing authority from the lexical floor? | shadow comparison | gate defined, not built |

Each runner exists (`benchmark.py`, `learn_bench.py`) and each refuses to
touch a real provider without explicit opt-in. **What they need is a
provider key and a spend budget.** The commitment, written into LIFT-001
before any data existed: *if the numbers come out against the platform, the
finding is published in the same directory, not buried.*

Until those experiments run, this lab claims the **structure** and not the
**benefit** — and says so, here and in every document that makes a
comparison.

---

## 13. Inspirations beyond the literature

- **Cluster controllers** — reconciliation as the shape of a standing
  responsibility (`reconciler.py`, `runbook.py reconcile`).
- **Spacecraft autonomy** — fault protection and safe mode beneath the
  intelligent layer (`watchdog.py`).
- **Workflow engines** — fixed stages with a gate between each, before
  autonomy (`workflows.py`).
- **Operating systems** — paging for context (MemGPT), a kernel-enforced
  boundary for control files (`controlplane.py`), complete mediation for
  every kind of power (the authorities).
- **Libraries and scholarly infrastructure** — the expert finds its sources
  in *catalogues* (OpenAlex, Crossref, DOAJ, PubMed, Zenodo, Software
  Heritage, the Library of Congress), deliberately not in a search engine,
  because a general index is ranked for engagement and changes hourly, and
  citing it cites nothing (`discover.py`, `sources.py`).
- **Science itself** — preregistration, falsifiers written in advance, blind
  spots stated next to every result, and an audit record
  (`GAPS_RISKS_AND_UNFINISHED.md`) that preserves what was wrong and how it
  was proven, because that is the half a changelog loses.

---

## References

Verified against the arXiv API on 14 October 2026 (arXiv identifiers) or
against the publisher (classics, blog posts). Where the platform's code
cites a paper, the module is named.

**Verification, self-correction and evaluation**

- Huang, J. et al. *Large Language Models Cannot Self-Correct Reasoning Yet.* ICLR 2024. [arXiv:2310.01798](https://arxiv.org/abs/2310.01798) — `goal.py`
- Jiang, D. et al. *Feedback Friction: LLMs Struggle to Fully Incorporate External Feedback.* 2025. [arXiv:2506.11930](https://arxiv.org/abs/2506.11930) — `goal.py`
- Lightman, H. et al. *Let's Verify Step by Step.* 2023. [arXiv:2305.20050](https://arxiv.org/abs/2305.20050)
- Jimenez, C. E. et al. *SWE-bench: Can Language Models Resolve Real-World GitHub Issues?* 2023. [arXiv:2310.06770](https://arxiv.org/abs/2310.06770)

**Self-improvement and skills**

- Shinn, N. et al. *Reflexion: Language Agents with Verbal Reinforcement Learning.* NeurIPS 2023. [arXiv:2303.11366](https://arxiv.org/abs/2303.11366)
- Wang, G. et al. *Voyager: An Open-Ended Embodied Agent with Large Language Models.* 2023. [arXiv:2305.16291](https://arxiv.org/abs/2305.16291) — `repair.py`
- Madaan, A. et al. *Self-Refine: Iterative Refinement with Self-Feedback.* 2023. [arXiv:2303.17651](https://arxiv.org/abs/2303.17651)
- Zhang, J. et al. *Darwin Gödel Machine: Open-Ended Evolution of Self-Improving Agents.* 2025. [arXiv:2505.22954](https://arxiv.org/abs/2505.22954) — `repair.py`
- Zhang, Q. et al. *Agentic Context Engineering: Evolving Contexts for Self-Improving Language Models.* 2025. [arXiv:2510.04618](https://arxiv.org/abs/2510.04618) — `commons.py`
- Xu, R. et al. *Agent Skills for Large Language Models: Architecture, Acquisition, Security, and the Path Forward.* 2026. [arXiv:2602.12430](https://arxiv.org/abs/2602.12430) — `skills.py`
- Xia, B. et al. *Harnessing Agent Skills: Architectural Patterns and a Reference Architecture for Skill-Mediated LLM Agents.* 2026. [arXiv:2606.20631](https://arxiv.org/abs/2606.20631) — `skills.py`

**Agents, context and memory**

- Yao, S. et al. *ReAct: Synergizing Reasoning and Acting in Language Models.* 2022. [arXiv:2210.03629](https://arxiv.org/abs/2210.03629)
- Liu, N. F. et al. *Lost in the Middle: How Language Models Use Long Contexts.* 2023. [arXiv:2307.03172](https://arxiv.org/abs/2307.03172)
- Packer, C. et al. *MemGPT: Towards LLMs as Operating Systems.* 2023. [arXiv:2310.08560](https://arxiv.org/abs/2310.08560)
- Zhang, A. L., Kraska, T. & Khattab, O. *Recursive Language Models.* 2025. [arXiv:2512.24601](https://arxiv.org/abs/2512.24601) — `loop.py`
- Sumers, T. R. et al. *Cognitive Architectures for Language Agents.* TMLR 2024. [arXiv:2309.02427](https://arxiv.org/abs/2309.02427)
- Park, J. S. et al. *Generative Agents: Interactive Simulacra of Human Behavior.* 2023. [arXiv:2304.03442](https://arxiv.org/abs/2304.03442)
- Xu, W. et al. *A-MEM: Agentic Memory for LLM Agents.* 2025. [arXiv:2502.12110](https://arxiv.org/abs/2502.12110)
- Chhikara, P. et al. *Mem0: Building Production-Ready AI Agents with Scalable Long-Term Memory.* 2025. [arXiv:2504.19413](https://arxiv.org/abs/2504.19413)
- Du, P. *Memory for Autonomous LLM Agents: Mechanisms, Evaluation, and Emerging Frontiers.* 2026. [arXiv:2603.07670](https://arxiv.org/abs/2603.07670) — `memrouter.py`
- Luo, J. et al. *From Storage to Experience: A Survey on the Evolution of LLM Agent Memory Mechanisms.* 2026. [arXiv:2605.06716](https://arxiv.org/abs/2605.06716)
- Wu, D. et al. *LongMemEval-V2: Evaluating Long-Term Agent Memory Toward Experienced Colleagues.* 2026. [arXiv:2605.12493](https://arxiv.org/abs/2605.12493) — `gotchas.py`

**Security**

- Saltzer, J. H. & Schroeder, M. D. *The Protection of Information in Computer Systems.* Proceedings of the IEEE 63(9), 1975.
- Greshake, K. et al. *Not what you've signed up for: Compromising Real-World LLM-Integrated Applications with Indirect Prompt Injection.* 2023. [arXiv:2302.12173](https://arxiv.org/abs/2302.12173)
- Chen, Z. et al. *AgentPoison: Red-teaming LLM Agents via Poisoning Memory or Knowledge Bases.* NeurIPS 2024. [arXiv:2407.12784](https://arxiv.org/abs/2407.12784)
- Dong, S. et al. *Memory Injection Attacks on LLM Agents via Query-Only Interaction.* 2025. [arXiv:2503.03704](https://arxiv.org/abs/2503.03704)
- Meta AI. *Agents Rule of Two: A Practical Approach to AI Agent Security.* 31 October 2025. <https://ai.meta.com/blog/practical-ai-agent-security/>

**Multi-agent systems**

- Cemri, M. et al. *Why Do Multi-Agent LLM Systems Fail?* NeurIPS 2025. [arXiv:2503.13657](https://arxiv.org/abs/2503.13657) — `swarm.py`
- Altera.AL et al. *Project Sid: Many-agent simulations toward AI civilization.* 2024. [arXiv:2411.00114](https://arxiv.org/abs/2411.00114) — `ARCHITECTURE_DECISIONS.md`

**Compute, calibration and deferral**

- Snell, C. et al. *Scaling LLM Test-Time Compute Optimally can be More Effective than Scaling Model Parameters.* 2024. [arXiv:2408.03314](https://arxiv.org/abs/2408.03314)
- Guo, C. et al. *On Calibration of Modern Neural Networks.* ICML 2017. [arXiv:1706.04599](https://arxiv.org/abs/1706.04599)
- Tian, K. et al. *Just Ask for Calibration: Strategies for Eliciting Calibrated Confidence Scores from Language Models Fine-Tuned with Human Feedback.* 2023. [arXiv:2305.14975](https://arxiv.org/abs/2305.14975)
- Angelopoulos, A. N. & Bates, S. *A Gentle Introduction to Conformal Prediction and Distribution-Free Uncertainty Quantification.* 2021. [arXiv:2107.07511](https://arxiv.org/abs/2107.07511)
- Madras, D., Pitassi, T. & Zemel, R. *Predict Responsibly: Improving Fairness and Accuracy by Learning to Defer.* NeurIPS 2018. [arXiv:1711.06664](https://arxiv.org/abs/1711.06664)

**Modelling people — the Twin**

- Park, J. S. et al. *LLM Agents Grounded in Self-Reports Enable General-Purpose Simulation of Individuals* (v1: *Generative Agent Simulations of 1,000 People*). 2024. [arXiv:2411.10109](https://arxiv.org/abs/2411.10109) — `docs/DESIGN-P10-twin.md`
- Binz, M. et al. *Centaur: a foundation model of human cognition.* 2024. [arXiv:2410.20268](https://arxiv.org/abs/2410.20268)
- Toubia, O. et al. *Twin-2K-500: A dataset for building digital twins of over 2,000 people.* 2025. [arXiv:2505.17479](https://arxiv.org/abs/2505.17479)
- Wang, Q. et al. *LLM-based Human Simulations Have Not Yet Been Reliable.* 2025. [arXiv:2501.08579](https://arxiv.org/abs/2501.08579)
- Sharma, M. et al. *Towards Understanding Sycophancy in Language Models.* 2023. [arXiv:2310.13548](https://arxiv.org/abs/2310.13548)
- Houlsby, N. et al. *Bayesian Active Learning for Classification and Preference Learning.* 2011. [arXiv:1112.5745](https://arxiv.org/abs/1112.5745)
- Dong, Y. R. et al. *Value of Information: A Framework for Human-Agent Communication.* 2026. [arXiv:2601.06407](https://arxiv.org/abs/2601.06407)
- Gulati, A. et al. *Ask Early, Ask Late, Ask Right: When Does Clarification Timing Matter for Long-Horizon Agents?* 2026. [arXiv:2605.07937](https://arxiv.org/abs/2605.07937)
- Deng, M. et al. *Uncertainty-Aware Clarification in LLM Agents with Information Gain.* 2026. [arXiv:2606.03135](https://arxiv.org/abs/2606.03135)
- Page, E. S. *Continuous Inspection Schemes.* Biometrika 41, 1954.
- Adams, R. P. & MacKay, D. J. C. *Bayesian Online Changepoint Detection.* 2007. [arXiv:0710.3742](https://arxiv.org/abs/0710.3742)

**Harness engineering**

- Hu Wei. *Architectural Design Decisions in AI Agent Harnesses.* 2026. [arXiv:2604.18071](https://arxiv.org/abs/2604.18071) — `harness.py`
- Lin, J. et al. *Agentic Harness Engineering: Observability-Driven Automatic Evolution of Coding-Agent Harnesses.* 2026. [arXiv:2604.25850](https://arxiv.org/abs/2604.25850) — `harness.py`
- Ahn, J. et al. *From Prompts to Contracts: Harness Engineering for Auditable Enterprise LLM Agents.* 2026. [arXiv:2607.08028](https://arxiv.org/abs/2607.08028) — `tests/test_faults.py`

**Method**

- DeMillo, R. A., Lipton, R. J. & Sayward, F. G. *Hints on Test Data Selection: Help for the Practicing Programmer.* IEEE Computer 11(4), 1978.
- Nosek, B. A. et al. *The preregistration revolution.* PNAS 115(11), 2018.
- Burns, B. et al. *Borg, Omega, and Kubernetes.* ACM Queue 14(1), 2016.

The Twin's full research notes, with a further twenty-odd verified sources
on personalisation, persona agents, writing-style imitation and inverse
reinforcement learning, are in `docs/research/P10-twin-research-A.md` and
`-B.md`.
