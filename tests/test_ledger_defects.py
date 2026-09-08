#!/usr/bin/env python3
"""Phase 7.2 exit benchmark — the ledger defects, held green.

docs/DESIGN-P7.2-ledger-defects.md preregistered exactly this: ten places
found by the Capability Ledger where the code said one thing and did
another, each closed by a property that FAILS on the tree before the fix:

  1. DOCTOR         an import failure is a PROBLEM, never "all modules
                    import"; the authority modules are in the core list
  2. PANEL GATE     the task dialog names a gate from the catalogue and
                    posts no free-form command; _net_gate accepts the
                    object it builds and still refuses a raw string
  3. INVITE         the invite dialog posts no actor field
  4. SUB-CALL       "subquery" is a declared gateway purpose
  5. CASE LEDGER    memory/cases.jsonl is CONTROL: agent write refused,
                    harness write allowed, enumerated in the leakage suite
  6. RECIPES        python toolbox.py --recipes prints the pinned recipes
  7. MANIFEST       the harness manifest's A2A entry says what federation
                    says
  8. PROSE          REFERENCE, MANUAL and README carry the counts the
                    tree has

Run from the agent/ directory:  python tests/test_ledger_defects.py
"""
import contextlib
import io
import os
import re
import subprocess
import sys
import tempfile

from common import AGENT_DIR, PY

sys.path.insert(0, AGENT_DIR)
import doctor                   # noqa: E402
import contract                 # noqa: E402
import federation               # noqa: E402
import fileauth                 # noqa: E402
import goal                     # noqa: E402
import harness                  # noqa: E402
import mission                  # noqa: E402
import modelgateway             # noqa: E402
import templates                # noqa: E402
import ui                       # noqa: E402


def _read(rel):
    return io.open(os.path.join(AGENT_DIR, rel), encoding="utf-8").read()


def _read_json(path):
    with io.open(path, encoding="utf-8") as f:
        return __import__("json").load(f)


# --------------------------------------------------------------- 1 doctor
def check_doctor_reports_import_failures():
    original = list(doctor.CORE_MODULES)
    doctor.CORE_MODULES = ["loop", "no_such_module_p72"]
    out = io.StringIO()
    try:
        r = doctor.Report()
        with contextlib.redirect_stdout(out):
            doctor.check_runtime(r)
    finally:
        doctor.CORE_MODULES = original
    text = out.getvalue()
    assert "PROBLEM import" in text and "no_such_module_p72" in text, text
    assert "core modules import" not in text, \
        "an import failure must never be reported as all modules importing"
    assert r.problems, r.problems
    for name in ("org", "controlplane", "fileauth", "execution",
                 "credentials", "modelgateway", "workers", "training",
                 "metrics", "gates", "scheduler", "procedure", "verifier",
                 "verification", "operators", "dbstate", "gitstate",
                 "xlsxstate", "tabular", "tabletypes"):
        assert name in doctor.CORE_MODULES, f"{name} is not import-checked"
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        doctor.check_runtime(doctor.Report())
    assert f"all {len(doctor.CORE_MODULES)} core modules import" in out.getvalue()
    print("[doctor] a failed import is reported as a PROBLEM and the "
          "all-clear line is withheld; every authority module is on the "
          "list; a clean tree still reports the all-clear")


# ------------------------------------------------------------ 2 panel gate
def check_panel_names_a_gate():
    page = _read("ui.html")
    assert 'id="ntCheck"' not in page, \
        "the free-form done-check field is still in the task dialog"
    assert 'id="ntGate"' in page and 'id="ntGateParam"' in page, \
        "the task dialog must carry a gate picker"
    for gate in ("exists", "designcheck", "citecheck", "verify", "memcheck"):
        assert f'value="{gate}"' in page, gate
    assert 'id="gAccept"' not in page and "what::command" not in page, (
        "the goal form still invites a browser caller to author shell")
    assert 'gGate"' in page and "collectGoalAcceptance" in page, (
        "the goal form needs a repeatable named-gate picker")
    built = ui._net_gate({"gate": "exists", "path": "out/index.html"})
    assert built and "out/index.html" in built, built
    built = ui._net_gate({"gate": "verify", "course": "onboarding"})
    assert built and "onboarding" in built, built
    assert ui._net_gate(None) is None and ui._net_gate({}) is None
    try:
        ui._net_gate("python check.py")
    except ValueError as exc:
        assert "free-form" in str(exc), exc
    else:
        raise AssertionError("a raw string must still be refused")

    accepted = ui._net_acceptance([
        {"gate": "exists", "path": "out/report.md",
         "what": "the report exists"},
        {"gate": "verify", "course": "onboarding"},
    ])
    assert [a["id"] for a in accepted] == ["A1", "A2"], accepted
    assert accepted[0]["what"] == "the report exists", accepted[0]
    assert "out/report.md" in accepted[0]["check"], accepted[0]
    assert "onboarding" in accepted[1]["check"], accepted[1]
    for bad in (
            ["report exists::python -c 'print(1)'"],
            {"gate": "exists", "path": "out/x"},
            [{"gate": "exists", "path": "out/x"}] * 13):
        try:
            ui._net_acceptance(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"network acceptance accepted {bad!r}")
    print("[panel] the task dialog names a gate from the catalogue (exists, "
          "designcheck, citecheck, verify, memcheck) with one parameter; "
          "goal graders use the same catalogue, preserve owner-facing meaning, "
          "and raw, malformed, or excess graders are refused")


def check_goal_limits_are_finite_before_work():
    parsed = ui._goal_request({
        "accept": [{"gate": "exists", "path": "out/report.md"}],
        "max_usd": "1.25", "max_minutes": "10", "cycles": 3})
    assert parsed["max_usd"] == 1.25 and parsed["max_minutes"] == 10, parsed
    assert parsed["cycles"] == 3 and len(parsed["accept"]) == 1, parsed
    assert ui._goal_request({}) == {
        "accept": [], "max_usd": 0.0, "max_minutes": 0, "cycles": 4}

    invalid = (
        {"max_usd": None}, {"max_usd": True}, {"max_usd": "5oops"},
        {"max_usd": "nan"}, {"max_usd": float("inf")}, {"max_usd": -0.01},
        {"max_minutes": 1.5}, {"max_minutes": -1},
        {"cycles": 0}, {"cycles": 2.5}, {"cycles": False},
    )
    for body in invalid:
        try:
            ui._goal_request(body)
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid goal limit was accepted: {body!r}")

    # The contract is a second boundary for CLI and direct callers. A bad
    # limit must fail before a contract directory or event is written.
    for value in (float("nan"), float("inf"), -1, True):
        with tempfile.TemporaryDirectory(prefix="goal-limit-") as root:
            try:
                contract.create(root, "g-bad", "goal", max_usd=value)
            except contract.ContractError:
                pass
            else:
                raise AssertionError(f"contract accepted max_usd={value!r}")
            assert not os.path.exists(os.path.join(root, "goals")), (
                "an invalid budget wrote goal state before refusing")
    print("[goal-input] goal spend, time and cycle limits are finite and in "
          "range before any state is written; zero retains its documented "
          "no-extra-cap meaning")


def check_contract_acceptance_is_complete_before_work():
    malformed = (
        [{"id": "A1", "what": "artifact exists", "check": True}],
        [{"id": "A1", "what": "artifact exists", "check": "   "}],
        [{"id": "", "what": "artifact exists", "check": "exit 0"}],
        [{"id": "A1", "what": "", "check": "exit 0"}],
        [{"id": "A1", "what": "one", "check": "exit 0"},
         {"id": "A1", "what": "two", "check": "exit 0"}],
        [{"id": "A1", "what": "artifact exists", "check": "exit 0",
          "group": False}],
        [{"id": "A1", "what": "artifact exists", "check": "exit 0",
          "group": "../escape"}],
    )
    for accept in malformed:
        with tempfile.TemporaryDirectory(prefix="goal-accept-") as root:
            try:
                contract.create(root, "g-bad", "goal", accept=accept)
            except contract.ContractError:
                pass
            else:
                raise AssertionError(
                    f"malformed contract acceptance was accepted: {accept!r}")
            assert not os.path.exists(os.path.join(root, "goals")), (
                "malformed acceptance wrote goal state before refusing")
    print("[goal-contract] direct callers must provide unique string ids, "
          "stated criteria, command strings and valid optional groups before "
          "any goal state is written")


def check_goal_identity_is_valid_before_artifacts():
    malformed = (
        {"gid": "../escape", "goal": "valid"},
        {"gid": "..", "goal": "valid"},
        {"gid": ".", "goal": "valid"},
        {"gid": "g-valid", "goal": "   "},
    )
    for values in malformed:
        with tempfile.TemporaryDirectory(prefix="goal-identity-") as root:
            try:
                contract.create(root, values["gid"], values["goal"])
            except contract.ContractError:
                pass
            else:
                raise AssertionError(
                    f"malformed goal identity was accepted: {values!r}")
            assert not os.path.exists(os.path.join(root, "goals")), (
                "malformed goal identity wrote state before refusing")

    # goal.pursue historically made goal.md and toolbox.md before contract
    # validation. A sentinel proves an invalid launch never enters _goal_dir.
    with tempfile.TemporaryDirectory(prefix="goal-pursue-") as home:
        os.makedirs(os.path.join(home, "experts", "probe"))
        original = goal._goal_dir
        goal._goal_dir = lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("invalid pursuit reached artifact creation"))
        try:
            for values in (("", "g-valid", 4, "probe"),
                           ("valid", "../escape", 4, "probe"),
                           ("valid", "..", 4, "probe"),
                           ("valid", "", 4, "probe"),
                           ("valid", "g-valid", 0, "probe"),
                           ("valid", "g-valid", 4, "..")):
                try:
                    goal.pursue(home, values[3], values[0], gid=values[1],
                                cycles=values[2])
                except contract.ContractError:
                    pass
                else:
                    raise AssertionError(
                        f"invalid pursuit reached work: {values!r}")
        finally:
            goal._goal_dir = original
    print("[goal-identity] contract ids, expert slugs and objectives are "
          "path-safe and non-empty; direct pursuits validate identity and "
          "limits before their first artifact")


def check_mission_work_is_bound_before_queueing():
    with tempfile.TemporaryDirectory(prefix="mission-work-") as root:
        with io.open(os.path.join(root, "settings.toml"), "w",
                     encoding="utf-8") as f:
            f.write('[agent]\nsandbox = "host"\nallow_unsafe_host = true\n')
        rec = mission.create(root, "publish a checked report",
                             ["the report exists", "citations pass"])
        out = ui.queue_mission_task("unused-home", "owner", root, {
            "mission": rec["id"], "criterion": "C1",
            "role": "practitioner", "goal": "write out/report.md",
            "expected_evidence": "out/report.md exists and is reviewable",
            "done_check": {"gate": "exists", "path": "out/report.md"},
        }, launch=False)
        assert out["criterion"] == "C1" and out["queued"], out
        state = _read_json(os.path.join(root, "state.json"))
        task = state["tasks"][-1]
        assert task["mission"] == rec["id"] and task["criterion"] == "C1", task
        assert "out/report.md" in task["done_check"], task
        saved = mission.load(root, rec["id"])
        assert saved["actions"][-1]["task"] == task["id"], saved["actions"]
        assert saved["actions"][-1]["expected_evidence"].startswith("out/report"), saved

        before = len(state["tasks"])
        for bad in (
                {"mission": rec["id"], "criterion": "C2", "goal": "cite it",
                 "expected_evidence": "citations pass"},
                {"mission": rec["id"], "criterion": "C9", "goal": "adjacent",
                 "expected_evidence": "something",
                 "done_check": {"gate": "exists", "path": "out/x"}}):
            try:
                ui.queue_mission_task("unused-home", "owner", root, bad,
                                      launch=False)
            except (KeyError, ValueError):
                pass
            else:
                raise AssertionError(f"unbound mission work was queued: {bad}")
        assert len(_read_json(os.path.join(root, "state.json"))["tasks"]) == before
        # loop.Agent attaches a Windows file handler; close it before the
        # temporary directory asks Windows to remove the log.
        __import__("logging").shutdown()
    print("[mission-work] queued mission work names its open criterion, "
          "expected evidence and catalogue gate; missing gates and unrelated "
          "criteria are refused before a task is queued")


def check_panel_language_and_routes_are_truthful():
    page = _read("ui.html")
    for unsupported in ("99–100%", "95–99%"):
        assert unsupported not in page, f"unsupported quality claim remains: {unsupported}"
    assert "mission saved" in page and "mission started" not in page, (
        "saving a contract is still described as execution")
    assert "/mission_task" in page and "Queue and start" in page, (
        "a saved mission has no explicit criterion-bound start path")
    assert "history.pushState" in page and '"#mission/"' in page, (
        "navigation still cannot preserve mission context in browser history")
    assert "routeChanged" in page and "decodeURIComponent" in page, (
        "deep links lack a guarded Back/Forward route handler")
    print("[panel-truth] quality copy names evidence instead of invented rates; "
          "mission save and execution are separate; goal and mission context "
          "have shareable Back/Forward routes")


# ---------------------------------------------------------------- 3 invite
def check_invite_posts_no_actor():
    page = _read("ui.html")
    body = page[page.index("async function doInvite"):][:600]
    assert "actor" not in body, body
    assert 'id="ivAs"' not in page
    print("[invite] the invite dialog no longer asks for an actor the server "
          "ignores; the token identity is the actor")


# -------------------------------------------------------------- 4 subquery
def check_subquery_purpose_is_declared():
    assert "subquery" in modelgateway.PURPOSES, modelgateway.PURPOSES
    with tempfile.TemporaryDirectory(prefix="p72-gw-") as root:
        modelgateway.record(root, purpose="subquery", role="r", provider="p",
                            model="m", usage=None, cost=0.0, task="t1", ms=1,
                            ok=True)
        rows = modelgateway.by_purpose(root)
    assert "subquery" in rows and "unknown" not in rows, rows
    print("[subquery] a sub-call is metered under its own purpose, not "
          "'unknown'")


# ------------------------------------------------------------ 5 case ledger
def check_case_ledger_is_control():
    import cases
    rel = cases.LEDGER.replace("\\", "/")
    assert fileauth.zone_of(rel) == fileauth.ZONE_CONTROL, fileauth.zone_of(rel)
    with tempfile.TemporaryDirectory(prefix="p72-cases-") as root:
        try:
            fileauth.resolve(root, rel, "write", "agent")
        except fileauth.Denied:
            pass
        else:
            raise AssertionError("the agent may still write the case ledger")
        assert fileauth.resolve(root, rel, "write", "harness")
    suite = _read(os.path.join("tests", "test_promotion_leakage.py"))
    assert rel in suite, "the case ledger is not enumerated in the leakage suite"
    print("[cases] memory/cases.jsonl is CONTROL: the agent's write is "
          "refused, the harness's allowed, and the path is enumerated in "
          "the promotion-leakage suite")


# ---------------------------------------------------------------- 6 recipes
def check_recipes_command():
    proc = subprocess.run([PY, os.path.join(AGENT_DIR, "toolbox.py"),
                           "--recipes"], capture_output=True, text=True,
                          cwd=AGENT_DIR, timeout=120)
    assert proc.returncode == 0, proc.stderr
    import toolbox
    for name in toolbox.ACQUIRE:
        assert name in proc.stdout, name
    comment = _read("toolbox.py")
    assert "toolbox.py recipes" not in comment, \
        "the comment still promises a subcommand that does not exist"
    print("[recipes] `python toolbox.py --recipes` prints every pinned "
          "acquisition recipe, and the comment names the flag that exists")


# --------------------------------------------------------------- 7 manifest
def check_manifest_tells_the_truth_about_a2a():
    with tempfile.TemporaryDirectory(prefix="p72-manifest-") as root:
        m = harness.manifest(root)
    a2a = m["versions"]["a2a"]
    assert isinstance(a2a, dict) and a2a.get("task_api") is False \
        and a2a.get("card") is True, a2a
    # the same fact federation states on its own card (test_lanes reads the
    # live card; this pins the manifest to the same declaration)
    src = _read("federation.py")
    assert '"a2a_task_api": False' in src, "federation's declaration moved"
    assert callable(federation.a2a_card)
    print("[manifest] the harness manifest's A2A entry states what "
          "federation states: a card is served, the task API is not "
          "implemented")


def _home():
    d = tempfile.mkdtemp(prefix="p72-home-")
    return d


# ----------------------------------------------------------------- 8 prose
def check_prose_matches_the_tree():
    ref = _read("REFERENCE.md")
    manual = _read("MANUAL.md")
    readme = _read("README.md")
    n_templates = len(templates.all_templates())
    assert str(n_templates) in ref and "twenty templates" not in ref.lower(), \
        f"REFERENCE must name {n_templates} templates"
    kinds = ["at", "every_days", "file_exists", "file_contains", "task_done",
             "event", "check"]
    src = _read("prospective.py")
    for k in kinds:
        assert f'"{k}"' in src, f"prospective.py no longer names kind {k}"
    assert "Four kinds:" not in ref and all(f"`{k}`" in ref for k in kinds), \
        "REFERENCE must list every intention kind"
    import proof
    n_caps = len(proof.REGISTRY)
    assert f"{n_caps} capabilities" in ref and f"{n_caps} capabilities" in manual
    test_files = {f for f in os.listdir(os.path.join(AGENT_DIR, "tests"))
                  if f.startswith("test_") and f.endswith(".py")}
    import run_all
    assert len(run_all.TESTS) == len(set(run_all.TESTS)), "duplicate suite entries"
    assert set(run_all.TESTS) == test_files, "suite registry differs from test files"
    tests = len(run_all.TESTS)
    # A static registry count cannot claim every test passed on this host.
    assert f"tests-{tests}%20registered" in readme, "README test badge is stale"
    import mutate_check
    assert f"mutation%20tests-{len(mutate_check.MUTATIONS)}%20registered" in readme, \
        "README mutation badge is stale"
    print(f"[prose] REFERENCE names {n_templates} templates and all {len(kinds)} "
          f"intention kinds; MANUAL and REFERENCE say {n_caps} capabilities; "
          f"the README badges carry {tests} tests and "
          f"{len(mutate_check.MUTATIONS)} mutations")


def main():
    check_doctor_reports_import_failures()
    check_panel_names_a_gate()
    check_goal_limits_are_finite_before_work()
    check_contract_acceptance_is_complete_before_work()
    check_goal_identity_is_valid_before_artifacts()
    check_mission_work_is_bound_before_queueing()
    check_panel_language_and_routes_are_truthful()
    check_invite_posts_no_actor()
    check_subquery_purpose_is_declared()
    check_case_ledger_is_control()
    check_recipes_command()
    check_manifest_tells_the_truth_about_a2a()
    check_prose_matches_the_tree()
    print("PASS test_ledger_defects")


if __name__ == "__main__":
    main()
