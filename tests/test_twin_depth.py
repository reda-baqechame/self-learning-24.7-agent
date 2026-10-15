#!/usr/bin/env python3
"""Phase 10.1 exit benchmark — twin depth, held green.

docs/DESIGN-P10.1-twin-depth.md preregistered exactly this:

  1. CAPTURE       panel audit rows, a named history file and a named
                   directory produce events exactly once; a command with a
                   key-shaped token is stored redacted; an edit stores
                   counts, never content; nothing named -> nothing captured
  2. ROUTINES      a habit in the command stream is mined as a routine;
                   held-out next-act accuracy beats the majority baseline;
                   the OWNER block carries the workflow line
  3. COLD START    interview answers land in the kernel and the block; 24
                   vignettes answered by a known policy fit a kernel; a
                   re-answer is a retest and measures self-consistency
  4. OBJECTIVES    a mission and a goal appear in objectives() and the
                   block; predict(at=) cites only earlier episodes and
                   reports what was knowable
  5. AUGMENTATION  three scripted lenses aggregate by vote with evidence
                   and a disputed assumption; three calls metered; the
                   simulation reports stability and a flip point; the
                   divergence queues a question; the kernel does not move
  6. BENCHMARK     attention, preference, temporal (the era version wins
                   after a confirmed drift), outcome and workflow fidelity
                   are reported; without data each says not measured
  7. SIGNATURES    with a key every output verifies; a tampered body
                   fails; without a key outputs say unsigned
  8. ALTERNATIVES  consider() returns the options weighed in similar
                   situations; history() lists versions, drifts, interview
  9. REGISTRATION  run_all, evidence, proof, doctor, leakage, REFERENCE,
                   MANUAL, settings

Run from the agent/ directory:  python tests/test_twin_depth.py
"""
import io
import json
import os
import random
import sys

from common import AGENT_DIR, make_sandbox

sys.path.insert(0, AGENT_DIR)
import approvals                # noqa: E402
import doctor                   # noqa: E402
import fleet                    # noqa: E402
import loop                     # noqa: E402
import modelgateway             # noqa: E402
import org                      # noqa: E402
import twin                     # noqa: E402
import twinaugment as A         # noqa: E402
import twincapture as C         # noqa: E402
import twinmath as M            # noqa: E402

GRANT_DENY = [{"id": "grant", "text": "approve the offer"},
              {"id": "deny", "text": "reject the offer"}]


def _settings(root, extra=(), script=None):
    s = ['[agent]', 'sandbox = "host"', 'allow_unsafe_host = true',
         'poll_interval_seconds = 1', 'max_task_usd = 0', 'reflect_after = []',
         'max_done_rejects = 2', 'max_task_retries = 0', '',
         '[agent.twin]', 'role = "r_m"'] + list(extra) + [
         '', '[providers.m]', 'type = "mock"', 'script = "scripts/m.json"', '',
         '[roles.default]', 'provider = "m"', 'model = "mock"', '',
         '[roles.r_m]', 'provider = "m"', 'model = "mock"', '']
    io.open(os.path.join(root, "settings.toml"), "w",
            encoding="utf-8").write("\n".join(s))
    os.makedirs(os.path.join(root, "scripts"), exist_ok=True)
    json.dump(script or [{"tool": "finish_task", "args": {"summary": "ok"}}],
              io.open(os.path.join(root, "scripts", "m.json"), "w", encoding="utf-8"))


def _expert(home, name, extra=(), script=None):
    root = fleet.create(home, name, "is modeled in depth")
    _settings(root, extra, script)
    twin.consent_grant(root, "advise")
    return root


def _policy(risk, margin, cp):
    if cp == "alice":
        return "grant"
    return "deny" if (risk > 0.5 and margin < 0.3) else "grant"


def _seed(root, n=150, seed=11):
    rng = random.Random(seed)
    for i in range(n):
        risk = round(rng.random(), 2)
        margin = round(rng.random() * 0.6, 2)
        cp = rng.choice(["alice", "bob", "carol"])
        twin.observe(root, {"text": f"supplier offer number {i}",
                            "features": {"risk": risk, "margin": margin}},
                     GRANT_DENY, _policy(risk, margin, cp), counterpart=cp,
                     source="test")


def _pending(root, key, server):
    return approvals.request(root, key, server, "post_order", {"k": key}, "ship it", "-")


# --------------------------------------------------------------- 1 capture
def check_capture_consent(home):
    root = os.path.join(home, "no-capture-consent")
    os.makedirs(root, exist_ok=True)
    history = os.path.join(root, "fixture-history.txt")
    with open(history, "w", encoding="utf-8") as stream:
        stream.write("git status\n")
    cfg = {"agent": {"twin": {"capture_history": history}}}
    for revoked in (False, True):
        if revoked:
            twin.consent_grant(root, "predict")
            twin.consent_revoke(root)
        try:
            C.tick(root, cfg)
        except twin.Refused:
            pass
        else:
            raise AssertionError("capture ran without active Twin consent")
        assert not os.path.exists(os.path.join(root, C.STATE))
        assert C.events(root) == []
    print("[capture-consent] direct capture refuses absent and revoked consent before creating state or reading named history")


def check_capture_owner(home):
    from unittest.mock import patch
    root = os.path.join(home, "capture-owner")
    os.makedirs(root, exist_ok=True)
    twin.consent_grant(root, "predict", by="owner-a")
    rows = [{"actor": actor, "at": "2026-09-05T10:00:00",
             "action": "steer", "object_kind": "goal", "object": "same-goal"}
            for actor in ("owner-a", "owner-b", "agent:worker", "")]
    # Existing pre-reconciliation events remain byte-for-byte intact.
    legacy = "panel:2026-09-05T10:00:00:steer:same-goal"
    C._record(root, set(), "panel", "legacy owner action", legacy,
              meta={"actor": "owner-a"})
    path = os.path.join(root, C.EVENTS)
    with open(path, "rb") as stream:
        original = stream.read()
    with patch.object(org, "trail", return_value=rows):
        assert C.tick(root, {})["panel"] == 0, "captured another human or duplicated legacy owner"
        twin.consent_grant(root, "predict", by="owner-b")
        assert C.tick(root, {})["panel"] == 1, "same-time actor collision lost the new owner's event"
        assert C.tick(root, {})["panel"] == 0, "repeat tick duplicated a panel event"
    with open(path, "rb") as stream:
        assert stream.read().startswith(original), "legacy event history was rewritten"
    assert [e["meta"]["actor"] for e in C.events(root)] == ["owner-a", "owner-b"]
    fresh = os.path.join(home, "capture-owner-fresh")
    os.makedirs(fresh, exist_ok=True)
    twin.consent_grant(fresh, "predict", by="owner-a")
    with patch.object(org, "trail", return_value=rows):
        assert C.tick(fresh, {})["panel"] == 1
    assert [e["meta"]["actor"] for e in C.events(fresh)] == ["owner-a"]
    print("[capture-owner] only the consented actor is added; same-time actors do not collide; legacy bytes and repeat-tick deduplication are preserved")


def check_capture(home):
    hist = os.path.join(home, "history.txt")
    watched = os.path.join(home, "watched")
    os.makedirs(watched, exist_ok=True)
    io.open(os.path.join(watched, "a.py"), "w", encoding="utf-8").write("x = 1\ny = 2\n")
    # Construct the redaction decoy at runtime, as test_package does. The
    # shipped test source should not need a whole-file credential exemption.
    decoy = "sk-" + "abcdefghijklmnopqrstuvwxyz0123456789ABCD"
    io.open(hist, "w", encoding="utf-8").write(
        f"git status\ncurl -H 'Authorization: Bearer {decoy}' https://x\n")
    root = _expert(home, "captured", extra=[
        f'capture_history = {json.dumps(hist)}',
        f'capture_dirs = [{json.dumps(watched)}]'])
    cfg = twin._cfg(root)
    org.audit(home, "owner", "queue_work", "expert", "captured", "via the control panel")
    org.audit(home, "owner", "steer", "goal", "g-1", "")
    org.audit(home, "agent:worker", "queue_work", "expert", "captured", "")
    r1 = C.tick(root, cfg)
    assert r1["panel"] == 2 and r1["command"] == 2 and r1["edit"] == 0, r1
    evs = C.events(root)
    cmds = [e for e in evs if e["kind"] == "command"]
    assert any(e["text"] == "git status" for e in cmds)
    assert any(e["text"] == "[redacted command]" and e["meta"]["redacted"] for e in cmds)
    raw = io.open(os.path.join(root, C.EVENTS), encoding="utf-8").read()
    assert decoy not in raw and "Bearer" not in raw
    # an edit: counts, never content
    io.open(os.path.join(watched, "a.py"), "w", encoding="utf-8").write(
        "x = 1\ny = 2\nSECRET_LINE = 3\nz = 4\n")
    io.open(os.path.join(watched, "b.txt"), "w", encoding="utf-8").write("hello\n")
    r2 = C.tick(root, cfg)
    assert r2["edit"] == 2 and r2["command"] == 0 and r2["panel"] == 0, r2
    edits = [e for e in C.events(root) if e["kind"] == "edit"]
    a = next(e for e in edits if e["meta"]["path"] == "a.py")
    assert a["meta"]["added"] == 2 and a["meta"]["removed"] == 0 and a["meta"]["ext"] == ".py"
    raw = io.open(os.path.join(root, C.EVENTS), encoding="utf-8").read()
    assert "SECRET_LINE" not in raw and "hello" not in raw
    r3 = C.tick(root, cfg)
    assert r3 == {"panel": 0, "command": 0, "edit": 0}, r3
    # nothing named -> nothing captured, even with the same file on disk
    bare = _expert(home, "unnamed")
    rb = C.tick(bare, twin._cfg(bare))
    assert rb["command"] == 0 and rb["edit"] == 0, rb
    print("[capture] two owner panel rows (an agent's row ignored), two commands "
          "(one redacted, the key absent from the ledger) and two edits "
          "(counts and extension, the content absent) were captured exactly "
          "once; a third tick captured nothing; an expert naming no source "
          "captured no command and no edit")
    return root


# -------------------------------------------------------------- 2 routines
def check_routines(home):
    hist = os.path.join(home, "habits.txt")
    lines = []
    rng = random.Random(3)
    for i in range(12):
        lines += ["git add .", f"git commit -m 'step {i}'", "git push"]
        if i % 3 == 0:
            lines.append(rng.choice(["ls -la", "python doctor.py", "cat notes.md"]))
    io.open(hist, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    root = _expert(home, "habitual", extra=[f'capture_history = {json.dumps(hist)}'])
    C.tick(root, twin._cfg(root))
    r = C.routines(C.events(root))
    assert any(h["after"] == "cmd:git commit" and h["then"] == "cmd:git push"
               and h["support"] >= 10 for h in r["habits"]), r["habits"]
    assert any(c["steps"] == ["cmd:git add", "cmd:git commit", "cmd:git push"]
               for c in r["chains"]), r["chains"]
    wf = C.workflow_fidelity(C.events(root))
    assert wf["accuracy"] is not None and wf["accuracy"] > wf["baseline"], wf
    _seed(root, n=40)
    twin.learn(root)
    block = twin.render(root)
    assert "how they work (observed)" in block and "git push" in block
    print(f"[routines] the add -> commit -> push habit was mined as a routine "
          f"({r['habits'][0]['support']}/{r['habits'][0]['of']}) and as a chain; "
          f"held-out next-act accuracy {wf['accuracy']} beat the majority "
          f"baseline {wf['baseline']}; the OWNER block carries the workflow line")


# ------------------------------------------------------------- 3 cold start
def check_cold_start(home):
    root = _expert(home, "interviewed")
    k = twin.load_kernel(root)
    A.interview_answer(k, "optimize", "Margin first, then whether I can undo it.")
    A.interview_answer(k, "risk", "I take reputational risk, never solvency risk.")
    twin.save_kernel(root, k)
    bank = A.interview_bank(twin.load_kernel(root))
    assert sum(1 for q in bank if q["answer"]) == 2 and len(bank) == len(A.INTERVIEW)
    try:
        A.interview_answer(k, "nope", "x")
        raise AssertionError("an unknown question was accepted")
    except ValueError:
        pass
    vs = A.generate(twin._cfg(root), 24)
    assert len(vs) == 24 and len({v["id"] for v in vs}) == 24
    assert vs == A.generate(twin._cfg(root), 24), "vignettes are not deterministic"
    for v in vs:
        f = v["features"]
        choice = "deny" if (f["risk"] > 0.5 and f["margin"] < 0.3) else "grant"
        out = twin.vignette_answer(root, v, choice)
        assert out["new"] and out["round"] == 0 and not out["retest"]
    st = A.vignette_status(vs, twin.episodes(root))
    assert all(v["answered"] == 1 for v in st)
    res = twin.learn(root)
    fitted = twin.current_version(twin.load_kernel(root))
    assert res["status"] == "fit"
    assert res["n_fit"] + len(fitted["validation_ids"]) + res["n_holdout"] == 24
    partitions = [set(fitted[key]) for key in ("fit_ids", "validation_ids", "test_ids")]
    assert not any(a & b for i, a in enumerate(partitions) for b in partitions[i + 1:])
    for v in vs[:3]:
        f = v["features"]
        out = twin.vignette_answer(root, v, "deny" if (f["risk"] > 0.5 and f["margin"] < 0.3)
                                   else "grant")
        assert out["retest"] and out["round"] == 1
    rep = twin.fidelity(root)
    assert rep["self_consistency"]["pairs"] == 3 and rep["self_consistency"]["agreement"] == 1.0
    block = twin.render(root)
    assert "in their words on optimize" in block and "Margin first" in block
    print("[cold-start] two interview answers landed in the kernel and the OWNER "
          "block; 24 deterministic vignettes answered by a known policy fit a "
          "first kernel; re-answering three of them counted as retests and "
          "measured self-consistency 1.0")


# ------------------------------------------------------------- 4 objectives
def check_objectives(home):
    root = _expert(home, "purposeful")
    _seed(root, n=150)
    twin.learn(root)
    import mission
    m = mission.create(root, "win the northern supplier contract",
                       ["a signed term sheet", "landed cost under benchmark"])
    mid = m["id"] if isinstance(m, dict) else m
    os.makedirs(os.path.join(root, "goals", "g-objective"), exist_ok=True)
    json.dump({"goal": "audit every supplier quote this quarter", "state": "planning"},
              io.open(os.path.join(root, "goals", "g-objective", "goal.json"), "w",
                      encoding="utf-8"))
    ob = twin.objectives(root)
    assert any(x["id"] == mid for x in ob["missions"]), ob
    assert any(x["id"] == "g-objective" for x in ob["goals"]), ob
    block = twin.render(root)
    assert "what they are pursuing now" in block and "northern supplier" in block
    sit = {"text": "supplier offer number 3", "features": {"risk": 0.7, "margin": 0.1}}
    early = twin.predict(root, sit, GRANT_DENY, "bob", at="2001-01-01T00:00:00")
    later = twin.predict(root, sit, GRANT_DENY, "bob", at="2099-01-01T00:00:00")
    assert early["known_before"]["episodes"] == 0 and early["neighbors"] == []
    assert later["known_before"]["episodes"] == 150 and later["neighbors"]
    assert early["as_of"] == "2001-01-01T00:00:00"
    print("[objectives] a mission and a goal were read into objectives() and the "
          "OWNER block; a prediction as of 2001 cited no episode and reported "
          "zero earlier recorded episodes; a 2099 cutoff counted 150 records "
          "and allowed frozen training neighbors, not all 150 as citations; "
          "historical trained-state reconstruction is not tested")
    return root


# ----------------------------------------------------------- 5 augmentation
def check_augmentation(home):
    # Three INDEPENDENT calls must get three different answers: the scripted
    # mock indexes by assistant turns in the conversation (always zero for a
    # fresh lens), so the loopback provider — which consumes its queue in
    # request order — is the honest double here.
    from fake_provider import FakeProvider, provider_block

    def lens(choice, reason, disputed, evidence):
        return "Analysis: " + json.dumps(
            {"choice": choice, "reason": reason, "disputed_assumption": disputed,
             "evidence": evidence})
    srv = FakeProvider()
    root = fleet.create(home, "augmented", "is augmented")
    s = ['[agent]', 'sandbox = "host"', 'allow_unsafe_host = true',
         'max_task_usd = 0', 'reflect_after = []', '',
         '[agent.twin]', 'role = "r_m"', 'lenses = ["finance", "risk", "relationships"]',
         '', provider_block("live", srv.base_url, key="sk-fake-lens-key"), '',
         '[roles.default]', 'provider = "live"', 'model = "fake"', '',
         '[roles.r_m]', 'provider = "live"', 'model = "fake"', '']
    io.open(os.path.join(root, "settings.toml"), "w", encoding="utf-8").write("\n".join(s))
    twin.consent_grant(root, "advise")
    srv.reply(text=lens("grant", "the SLA was fixed last quarter",
                        "risky-api still misses deadlines", ["uptime 99.9% for 90 days"]))
    srv.reply(text=lens("grant", "margin is fine at this volume", None, ["cohort margin 34%"]))
    srv.reply(text=lens("deny", "the counterpart has churned twice", "bob is reliable",
                        ["two prior exits"]))
    _seed(root, n=60)
    twin.learn(root)
    before = twin.current_version(twin.load_kernel(root))["hash"]
    agent = loop.Agent(root)
    sit = {"text": "supplier offer number 9", "features": {"risk": 0.9, "margin": 0.1}}
    try:
        out = twin.superself(root, agent, sit, GRANT_DENY, "bob")
    finally:
        srv.stop()
    assert out["label"] == twin.SUPER_LABEL and out["self"]["argmax"] == "deny"
    sup = out["super"]
    assert sup["votes"] == {"grant": 2, "deny": 1} and sup["choice"] == "grant", sup
    assert len(sup["lenses"]) == 3 and "risky-api still misses deadlines" in sup["disputed_assumptions"]
    assert "uptime 99.9% for 90 days" in sup["evidence"] and "two prior exits" in sup["evidence"]
    rows = [r for r in modelgateway.calls(root) if r.get("purpose") == "twin"]
    assert len(rows) == 3, len(rows)
    sim = out["simulation"]
    assert 0.0 <= sim["stability"] <= 1.0 and sim["samples"] == 400
    assert any(f["feature"] in ("risk", "margin") for f in sim["flips"]), sim
    assert out["diverges"] and out["question"] and out["kernel_unchanged"]
    assert twin.current_version(twin.load_kernel(root))["hash"] == before
    q = twin.questions(root, "open")[0]
    assert q["kind"] == "policy_update" and "3 lenses" in q["text"]
    print(f"[augmentation] three scripted lenses voted grant 2 / deny 1 with their "
          f"evidence pooled and a disputed assumption named; three calls were "
          f"metered as 'twin'; the simulation reported stability "
          f"{sim['stability']} over 400 perturbed situations and a flip point on "
          f"{sim['flips'][0]['feature']}; the divergence queued a policy-update "
          f"question and the kernel hash did not move")


# -------------------------------------------------------------- 6 benchmark
def check_benchmark(home, kernel_root):
    # attention: a why answered with a top feature
    ep = twin.decisions(twin.episodes(kernel_root))[0]
    q = twin.ask(kernel_root, ep["id"], "confident miss", "what decided it?",
                 ["risk", "margin", "something else"])
    twin.answer(kernel_root, q["id"], "risk")
    rep = twin.fidelity(kernel_root)
    assert rep["attention_fidelity"]["named"] == 1 and rep["attention_fidelity"]["share"] == 1.0
    assert rep["preference_fidelity"]["agreement"] is not None
    assert rep["preference_fidelity"]["agreement"] >= 0.6, rep["preference_fidelity"]
    assert rep["workflow_fidelity"]["accuracy"] is None
    assert "workflow_fidelity" in rep["not_measured"]
    assert rep["temporal_fidelity"]["era_version_wins"] is None
    assert rep["outcome_fidelity"]["good_rate_agreed"] is None
    # outcome: twelve marked decisions
    marked = twin.decisions(twin.episodes(kernel_root))[:12]
    for e in marked:
        twin.record_outcome(kernel_root, e["id"], "good" if e["choice"] == "grant" else "bad")
    rep = twin.fidelity(kernel_root)
    of = rep["outcome_fidelity"]
    assert of["n"] == 12 and of["good_rate_agreed"] is not None, of
    try:
        twin.record_outcome(kernel_root, marked[0]["id"], "meh")
        raise AssertionError("a non-binary outcome was accepted")
    except twin.Refused:
        pass
    # temporal: after a confirmed drift the era version must win
    root = _expert(home, "eras")

    def drive(n, flip, tag):
        for i in range(n):
            server = "safe-api" if i % 2 else "risky-api"
            rec = _pending(root, f"{tag}-{i}", server)
            twin.tick(root)
            approvals.decide(root, rec["id"], (server == "safe-api") != flip, "")
            twin.tick(root)
    drive(30, False, "era1")
    drive(24, True, "era2")
    assert twin.drift_status(root)["notice"]["status"] == "open"
    twin.drift_confirm(root, "owner")
    drive(16, True, "era3")
    rep2 = twin.fidelity(root)
    tf = rep2["temporal_fidelity"]
    assert tf["versions"] == 2 and tf["era"] == 2 and tf["era_version_wins"] is True, tf
    print(f"[benchmark] attention fidelity {rep['attention_fidelity']['share']} from one "
          f"answered why; preference fidelity {rep['preference_fidelity']['agreement']} "
          f"on held-out refit; outcome fidelity computed over 12 marked decisions "
          f"(agreed good-rate {of['good_rate_agreed']}); workflow and temporal "
          f"reported not measured without data; after a confirmed drift the era's "
          f"own version scored {tf['by_version'][2]} against v1's "
          f"{tf['by_version'][1]} on the era's held-out rows")


# -------------------------------------------------------------- 7 signatures
def check_signatures(home, kernel_root):
    sit = {"text": "supplier offer number 5", "features": {"risk": 0.2, "margin": 0.5}}
    os.environ.pop("TWIN_SIGNING_KEY", None)
    p = twin.predict(kernel_root, sit, GRANT_DENY, "bob")
    assert p["signed"] is False and p["signature"] is None
    assert twin.verify(kernel_root, p)["signed"] is False
    os.environ["TWIN_SIGNING_KEY"] = "test-signing-secret-1234"
    try:
        p = twin.predict(kernel_root, sit, GRANT_DENY, "bob")
        assert p["signed"] and len(p["signature"]) == 64
        v = twin.verify(kernel_root, p)
        assert v["valid"] is True, v
        bad = json.loads(json.dumps(p))
        bad["probs"] = {"grant": 0.01, "deny": 0.99}
        v = twin.verify(kernel_root, bad)
        assert v["valid"] is False and "TAMPER" in v["why"], v
        agent = loop.Agent(kernel_root)
        twin.consent_grant(kernel_root, "draft")
        d = twin.draft(kernel_root, agent, "say no politely")
        assert d["signed"] and twin.verify(kernel_root, d)["valid"]
        assert twin.status(kernel_root)["signing"] is True
    finally:
        os.environ.pop("TWIN_SIGNING_KEY", None)
    print("[signatures] without a key a prediction said unsigned; with one, "
          "predictions and drafts carried an HMAC that verified, and a body "
          "edited under its signature verified as TAMPER")


# ----------------------------------------------------------- 8 alternatives
def check_alternatives(home, kernel_root):
    c = twin.consider(kernel_root, {"text": "supplier offer number 77",
                                    "features": {"risk": 0.6, "margin": 0.2}}, "bob")
    ids = {o["id"] for o in c["options"]}
    assert ids == {"grant", "deny"} and c["from_episodes"], c
    assert all(o["seen"] >= 1 for o in c["options"])
    h = twin.history(kernel_root)
    assert h["versions"] and h["versions"][0]["v"] == 1
    assert h["interview"]["of"] == len(A.INTERVIEW) and h["consent"]["scope"] == "draft"
    print("[alternatives] consider() returned the options the owner weighed in "
          "similar situations with how often each was seen and chosen; "
          "history() listed the versions, the interview progress and the consent")


# ------------------------------------------------------------ 9 registration
def check_registration():
    me = os.path.basename(__file__)
    for name in ("tests/run_all.py", "evidence.py", "proof.py"):
        text = io.open(os.path.join(AGENT_DIR, name), encoding="utf-8").read()
        assert me in text, f"{me} is not declared in {name}"
    assert "twincapture" in doctor.CORE_MODULES and "twinaugment" in doctor.CORE_MODULES
    leak = io.open(os.path.join(AGENT_DIR, "tests", "test_promotion_leakage.py"),
                   encoding="utf-8").read()
    assert '"twin/events.jsonl"' in leak
    ref = io.open(os.path.join(AGENT_DIR, "REFERENCE.md"), encoding="utf-8").read()
    assert "DESIGN-P10.1" in ref and "`twincapture.py`" in ref
    manual = io.open(os.path.join(AGENT_DIR, "MANUAL.md"), encoding="utf-8").read()
    assert "vignettes" in manual and "capture_history" in manual
    settings = io.open(os.path.join(AGENT_DIR, "settings.toml"), encoding="utf-8").read()
    assert "capture_dirs" in settings and "TWIN_SIGNING_KEY" in settings
    print("[registration] declared in run_all, evidence and proof; the doctor "
          "imports the capture and augmentation modules; the work stream is in "
          "the leakage enumeration; REFERENCE, MANUAL and settings name the "
          "phase")


def main():
    home = make_sandbox("twin-depth", providers={"m": {"script": "s.json"}},
                        roles={"r_m": "m"}, scripts={"s.json": []})
    check_capture_consent(home)
    check_capture_owner(home)
    check_capture(home)
    check_routines(home)
    check_cold_start(home)
    kernel_root = check_objectives(home)
    check_augmentation(home)
    check_benchmark(home, kernel_root)
    check_signatures(home, kernel_root)
    check_alternatives(home, kernel_root)
    check_registration()
    print("PASS test_twin_depth")


if __name__ == "__main__":
    main()
