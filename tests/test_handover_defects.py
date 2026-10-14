#!/usr/bin/env python3
"""THE HANDOVER DEFECTS — seven findings from the 2026-10-12 readiness audit.

The audit that preceded a handover found a class of defect the suite could
not have caught, because the suite tested the *mechanisms* and these are
claims and states the operator reads. Each check below fails if its fix is
reverted.

  1. (F01) four palette shortcuts set a sub-view and then called go(),
     whose first act is to clear the selection — so "Steer a running
     pursuit" with an agent open landed on the roster.
  2. (F02) the dialog was a styled div: no dialog role, no name, no focus
     containment. Tab from the trigger walked onto a button behind the
     overlay, and nothing told a screen reader a dialog had opened.
  3. (F03) one tag claimed both the creation LANE and measured training, so
     a brand-new expert with no course, task or exam read TRAINED.
  4. (F04) Home claimed every task is gated and examined. `check_done`
     trusts a task that declared no gate — by design, in its own docstring
     — so the blanket sentence was false for the first thing a visitor
     tries.
  5. (F05) a failed procedure read rendered the same screen as an empty
     library, because any response without a `runbooks` key became [].
  6. (F18) `subquery` read the whole file with readlines() before cutting
     out the requested slice, so peak memory scaled with the material —
     the opposite of the claim the tool exists to make.
  7. (F21) the docker cleanup check diffed every container on the daemon,
     so one unrelated container started during the window was reported as
     a leak while its own timed-out container was already gone.

Run from the agent/ directory:  python tests/test_handover_defects.py
"""

import io
import os
import sys
import tracemalloc

from common import AGENT_DIR, make_sandbox

sys.path.insert(0, AGENT_DIR)
import loop                    # noqa: E402


def _read(name):
    with io.open(os.path.join(AGENT_DIR, name), encoding="utf-8") as f:
        return f.read()


# ------------------------------------------------------------------ F01
def check_shortcuts_keep_the_selected_agent():
    page = _read("ui.html")
    # go() still clears the selection — that is correct for a nav jump, and
    # is exactly why a shortcut that wants the OPEN agent must not use it.
    assert "function go(view){ S.view=view; S.sel=null;" in page, \
        "go() no longer clears the selection, so this check is testing nothing"
    for sub in ("goals", "graph", "mastery", "teach"):
        assert f"S.sub='{sub}';go('agents')" not in page, (
            f"the {sub!r} shortcut still clears the selected agent by "
            f"routing through go('agents')")
        assert f"openAgentAction('{sub}')" in page, \
            f"the {sub!r} shortcut no longer reaches an agent-scoped view"
    # and the rule it routes through is the one that keeps a selection
    body = page[page.index("function openAgentAction(sub)"):][:400]
    assert "S.sel||" in body and "openAgent(slug,sub)" in body, body
    print("[F01] the four agent-scoped shortcuts (steering, graph, mastery, "
          "freshness) go through openAgentAction, which keeps the open agent "
          "and asks when there are several — go() still clears the selection, "
          "which is why using it here was the defect")


# ------------------------------------------------------------------ F02
def check_dialogs_are_dialogs():
    page = _read("ui.html")
    dlg = page[page.index('<div id="ovl">'):][:400]
    for attr in ('role="dialog"', 'aria-modal="true"',
                 'aria-labelledby="dlgT"', 'tabindex="-1"'):
        assert attr in dlg, f"the overlay has no {attr}: {dlg[:200]!r}"
    assert "function dlgTrap(" in page and \
        'document.addEventListener("keydown", dlgTrap, true)' in page, \
        "nothing contains Tab inside an open dialog"
    assert "dlgReturn = document.activeElement" in page and \
        "dlgReturn.focus()" in page, \
        "focus is not restored to the control that opened the dialog"
    show = page[page.index("function showDlg(title"):][:900]
    assert "dlgPairLabels()" in show and "(first || dlg).focus()" in show, \
        "showDlg does not move focus into the dialog"
    pair = page[page.index("function dlgPairLabels()"):][:1200]
    assert 'lb.setAttribute("for", n.id)' in pair, \
        "dialog labels are still not associated with their control"
    print("[F02] the overlay is a named modal (role=dialog, aria-modal, "
          "aria-labelledby), Tab is contained inside it, focus moves in on "
          "open and returns to the opener on close, and every dialog label "
          "is paired with its control in one place rather than in each of "
          "the dialog templates")


# ------------------------------------------------------------------ F03
def check_the_creation_lane_is_not_a_competence_claim():
    page = _read("ui.html")
    # ENUMERATE, do not count what you remembered. The first pass of this
    # fix looked for `e.quick` and patched the two sites that matched, and
    # the agent's OWN page kept printing TRAINED from `row.quick` until a
    # browser showed it. So the assertion is now about the SHAPE, wherever
    # it appears and whatever the variable is called.
    assert '?"QUICK":"TRAINED"' not in page, (
        "a creation lane is still rendered as the word TRAINED somewhere, "
        "which a brand-new expert with no course and no exam does not earn")
    fn = page[page.index("function laneTag(e)"):][:1200]
    assert "UNTRAINED" in fn and "COURSE" in fn, fn[:200]
    assert "e.courses" in fn, "the state tag is not read from evidence on disk"
    sites = page.count("${laneTag(")
    assert sites == 3, (
        f"the home roster, the agent cards and the agent's own page must all "
        f"use the one helper; found {sites} call site(s)")
    print("[F03] all three places an agent is named \u2014 the home roster, the "
          "agent cards and the agent's own page \u2014 render the one helper; "
          "the creation lane (QUICK / FULL) and the training state are "
          "two tags from two facts: the state is read from the courses on "
          "disk and says UNTRAINED when there are none, so a creation choice "
          "can no longer be read as demonstrated competence")


# ------------------------------------------------------------------ F04
def check_the_gate_claim_names_its_boundary():
    page = _read("ui.html")
    assert "every task here is <b>gated</b>" not in page, (
        "Home still claims every task is gated; check_done trusts a task "
        "that declared no done_check")
    assert "a task that declares a done-check is <b>gated</b>" in page, \
        "the corrected claim is not on Home"
    fn = page[page.index("function statusPill(t)"):][:800]
    assert 'done (unverified)' in fn and "!t.done_check" in fn, fn[:200]
    assert page.count("${statusPill(t)}") == 2, (
        "both the task table and the task page must label ungated work")
    # the claim is only honest if the panel is actually told which tasks
    # carry a gate
    assert '"done_check"' in _read("ui.py"), \
        "the API no longer exposes done_check, so the label cannot be computed"
    # and the runtime behaviour the claim is about is unchanged
    assert "no done_check is trusted (returns True)" in _read("loop.py"), \
        "check_done no longer documents the boundary this claim names"
    print("[F04] Home states the law and its boundary (a task is gated by "
          "the done-check it declares), and work that declared no check is "
          "labelled 'done (unverified)' in both places a task status is "
          "read — the panel is told which tasks carry a gate, so the label "
          "is computed rather than assumed")


# ------------------------------------------------------------------ F05
def check_a_failed_read_is_not_an_empty_library():
    page = _read("ui.html")
    fn = page[page.index("async function loadProcedures()"):][:1600]
    assert fn.index("if (!d || d.error)") < fn.index("nothing compiled yet"), (
        "the failure branch must come before the empty-library message, or a "
        "failed read still renders as 'nothing compiled yet'")
    assert "failed read, not an empty library" in fn, fn[:300]
    assert "onclick=\"loadProcedures()\"" in fn, "there is no retry"
    assert "reading the procedure library" in fn, "there is no loading state"
    print("[F05] a procedure library that cannot be read says so, names the "
          "error, offers a retry and shows a loading state first — four "
          "states instead of one, so a failed read is no longer indistin"
          "guishable from an expert that has compiled nothing")


# ------------------------------------------------------------------ F18
def check_subquery_reads_only_its_slice():
    sb = make_sandbox("handover_slice", providers={"m": {"script": "s.json"}},
                      roles={"watcher": "m"}, scripts={"s.json": []})
    path = os.path.join(sb, "corpus.txt")
    line = "x" * 199 + "\n"
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        for _ in range(100_000):            # ~20 MB
            f.write(line)
    size = os.path.getsize(path)
    assert size > 15_000_000, size

    tracemalloc.start()
    text, a, b = loop.read_slice(path, 1, 2)
    _cur, slice_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert text.count("\n") == 2 and (a, b) == (1, 2), (len(text), a, b)

    # The same two lines through the implementation this replaced. The point
    # is not that readlines() is slow — it is that its memory is the FILE's,
    # and the material a subquery exists for is exactly the large thing.
    tracemalloc.start()
    with io.open(path, encoding="utf-8", errors="replace") as f:
        whole = f.readlines()
    _cur, whole_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    del whole
    assert slice_peak * 50 < whole_peak, (
        f"a two-line slice peaked at {slice_peak} bytes against "
        f"{whole_peak} for the whole file — the read is not bounded by "
        f"the slice")

    # a line past end_line is never read, so the tail cannot cost anything
    tail, a, b = loop.read_slice(path, 5, 7)
    assert tail.count("\n") == 3 and (a, b) == (5, 7)

    # an end_line past the end of the file is labelled with the last line
    # that EXISTS — the label is provenance, and must not name lines that
    # were never there
    short = os.path.join(sb, "short.txt")
    with io.open(short, "w", encoding="utf-8", newline="\n") as f:
        f.write("".join(f"row {i}\n" for i in range(10)))
    _t, a, b = loop.read_slice(short, 1, 5000)
    assert (a, b) == (1, 10), (a, b)

    # the budget is named, with the remedy, and refuses rather than truncates
    try:
        loop.read_slice(path, 1, 100_000)
        raise AssertionError("an oversized slice was not refused")
    except loop.SliceTooBig as e:
        assert "keep slices under" in str(e), str(e)
        assert str(loop.SUBQUERY_MAX_CHARS) in str(e), str(e)
    # and the refusal happens while reading, not after the slice is resident
    tracemalloc.start()
    try:
        loop.read_slice(path, 1, 100_000)
    except loop.SliceTooBig:
        pass
    _cur, refuse_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert refuse_peak < 4 * loop.SUBQUERY_MAX_CHARS, refuse_peak

    for bad in ((9, 3), (10_000_000, None)):
        try:
            loop.read_slice(path, bad[0], bad[1])
            raise AssertionError(f"{bad} selected something")
        except ValueError as e:
            assert "empty slice" in str(e), str(e)
    print(f"[F18] a two-line slice of a {size // 1_000_000} MB corpus peaked "
          f"at {slice_peak / 1024:.0f} KB against {whole_peak / 1_000_000:.0f} "
          f"MB for the readlines() this replaced; a line past end_line is "
          f"never read, an oversized slice is refused while reading (naming "
          f"the cap and the remedy) and an empty range is an error, not an "
          f"empty answer")


# ------------------------------------------------------------------ F21
def check_the_cleanup_check_watches_what_it_owns():
    src = _read(os.path.join("tests", "test_docker_live.py"))
    fn = src[src.index("def check_a_timeout_kills_the_container"):][:3500]
    assert "set(after) - set(before)" not in fn, (
        "the cleanup check still diffs every container on the daemon, so a "
        "container started by anything else is reported as this test's leak")
    assert '"--name" in list(argv)' in fn, \
        "the check does not learn the name of the container it owns"
    assert "_running(mine)" in fn and "_running(stranger)" in fn, (
        "the check must assert its OWN container is gone and that an "
        "unrelated one is ignored")
    helper = src[src.index("def _running(name)"):][:400]
    assert '"--filter", f"name=^{name}$"' in helper, helper[:200]
    print("[F21] the timeout check identifies the container it started by "
          "name, requires that one to be gone, and keeps an unrelated "
          "container running throughout — the exact case the old daemon-wide "
          "diff reported as a leak")


def main():
    check_shortcuts_keep_the_selected_agent()
    check_dialogs_are_dialogs()
    check_the_creation_lane_is_not_a_competence_claim()
    check_the_gate_claim_names_its_boundary()
    check_a_failed_read_is_not_an_empty_library()
    check_subquery_reads_only_its_slice()
    check_the_cleanup_check_watches_what_it_owns()
    print("PASS test_handover_defects")


if __name__ == "__main__":
    main()
