# User workflow completion: first-use integrity

Base: fc08b7f4a65f07bc77b269e7ef2b03cbfb548be2. Branch:
`codex/user-workflow-completion`. Computer runtime work remains owned by
`codex/bounded-computer-use`; do not modify its checkout or runtime modules.

## Problem and scope

The panel accepts malformed spend limits and raw shell acceptance commands.
It describes a saved mission as started, advertises unsupported quality
percentages, and loses context when navigating. This phase makes owner intent
explicit and preserves existing authority boundaries before adding launch paths.

HTTP goal acceptance must use the existing named gate catalogue. Terminal
operators retain CLI command checks. Validate spend, time and cycle limits before
launching, writing goal artifacts, or resolving universal work. Zero retains its
historical meaning of no additional goal spend/time cap; display this meaning.
Reject nonfinite, negative, boolean and malformed limits, never silently repair.

Saved missions must be labelled saved. A mission task must name its criterion,
expected evidence and approved gate, and retain its durable mission linkage.
Queueing, process launch and verified completion are distinct states. Navigation
must preserve selected expert and mission, with working reload and Back/Forward.
Quality copy describes measured evidence only, with no invented success rates.

## Preregistered acceptance and benchmark

1. HTTP goal and universal requests reject raw command checks, injection strings,
   invalid lists and excess checks, before launch or resolver effects. Approved
   gates preserve their exact generated commands. CLI free-form checks still work.
2. NaN, infinities, negative numbers, booleans, null and numeric suffixes fail
   before any goal write or process spawn. Finite nonnegative spend and whole
   time limits work; cycles must be a positive whole number. Zero compatibility
   is tested explicitly, not treated as a free-only budget.
3. Mission save never claims to start execution. Linked tasks retain criterion
   and expected evidence; missing/fulfilled criteria fail before dispatch.
4. Rendered fixture journeys cover goal validation, mission save and task link,
   context selection, deep links, reload, Back/Forward, and visible errors.
5. Negative behavioral tests and mutations remove each load-bearing validation
   and require red. Test fixtures never invoke paid models or personal capture.

Register acceptance tests in run_all.py and evidence.py. Run focused regressions,
the full local suite, execution authority audit, and generate evidence from that
run. Review final diff and resolve findings before integration; six-platform CI
and applicable mutations remain merge gates. Test skips remain explicit.

## Remaining program

The audit in ../audit-2026-09-07/BUILD_AND_CLAUDE_REQUEST_AUDIT.md remains the
requirement ledger. Guided workflows, monitoring, accessibility/recovery, twin
reconciliation, qualification and live product proof remain open until their
own evidence exists. This phase does not certify the entire build. Shared test
registries and documentation require deliberate reconciliation with the other
agent at integration. No automatic merge or unsupported completion claims.
