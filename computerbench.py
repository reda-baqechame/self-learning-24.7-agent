#!/usr/bin/env python3
"""Bounded ComputerBench development qualification.

This candidate module runs only the known synthetic development contract.
Independent acceptance is performed solely by the separately installed,
root-managed computerbench_verifier component. This candidate cannot issue
acceptance challenges or return acceptance_complete=true.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
import time


TRACKS = ("browser_only", "native_desktop", "api_assisted")
VARIANT_DIMENSIONS = ("layout", "wording", "timing", "authentication",
                      "multistep")
_MAX_DOCUMENT = 10_000_000

PLAYWRIGHT_IMAGE = ("mcr.microsoft.com/playwright/mcp@sha256:"
                    "add8756264bc95962597d2e5095b66317acb1d89a7c8b64f264e7d2dee140bc9")
PORTAL_ORIGIN = "http://127.0.0.1:8765"
PORTAL_FIXTURE_REL = "tests/computerbench-portal-fixture/server.cjs"
PORTAL_FIXTURE_SHA256 = "a2439e64c586860161fc289f09450978bc60cc8c48fb199a5efdde695d773eff"
DEVELOPMENT_EXPECTED = {
    "normal": "verified_completion",
    "delayed": "verified_completion",
    "moved": "verified_completion",
    "ambiguous": "safe_refusal",
    "dialog": "safe_refusal",
    "expired": "safe_refusal",
    "interrupted": "rejected_artifacts",
    "restart": "safe_refusal",
    "injection": "verified_completion",
    "cross_origin": "safe_refusal",
    "corrupt": "rejected_artifacts",
    "duplicate_missing": "rejected_artifacts",
}


class ContractError(ValueError):
    """The development evidence cannot satisfy its declared contract."""


def _canonical(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ContractError("development contract is not canonical JSON") from error


def invoice_manifest():
    rows = []
    for index in range(3):
        identity = "INV-" + str(index)
        raw = json.dumps({"id": identity, "month": "2026-08",
                          "account": "fixture-owner@example.invalid",
                          "total_cents": 1200 + index},
                         separators=(",", ":")).encode("utf-8")
        rows.append({"id": identity, "file": identity + ".json",
                     "bytes": len(raw),
                     "sha256": hashlib.sha256(raw).hexdigest(),
                     "total_cents": 1200 + index})
    return {"month": "2026-08", "account": "fixture-owner@example.invalid",
            "invoices": rows}


def portal_spec(docker, output_dir):
    """Owner-reviewed, isolated process specification for one synthetic trial."""
    fixture = Path(__file__).resolve().parent / PORTAL_FIXTURE_REL
    output = Path(output_dir).resolve()
    digest = PLAYWRIGHT_IMAGE.split("@sha256:", 1)[1]
    command = ("node /fixture/server.cjs & ready=; "
               "for attempt in $(seq 1 100); do "
               "node -e \"fetch('http://127.0.0.1:8765/health',"
               "{signal:AbortSignal.timeout(250)}).then(r=>"
               "process.exit(r.ok?0:1))"
               ".catch(()=>process.exit(1))\" "
               "&& { ready=1; break; }; sleep 0.02; done; "
               "[ \"$ready\" = 1 ] || exit 70; "
               "exec node /app/cli.js --headless "
               "--browser chromium --no-sandbox --isolated "
               "--snapshot-mode=none --output-dir=/artifacts "
               "--timeout-action=1500 --timeout-navigation=3000")
    spec = {"cmd": os.fspath(docker),
            "args": ["run", "-i", "--rm", "--init", "--pull=never",
                     "--network=none", "--read-only",
                     "--tmpfs=/tmp:rw,nosuid,nodev,size=256m",
                     "--tmpfs=/home/node:rw,nosuid,nodev,size=64m,uid=1000,gid=1000",
                     "--memory=1g", "--pids-limit=256", "--cap-drop=ALL",
                     "--security-opt=no-new-privileges", "--mount",
                      "type=bind,source=" + os.fspath(fixture.parent)
                     + ",target=/fixture,readonly", "--mount",
                     "type=bind,source=" + os.fspath(output)
                     + ",target=/artifacts", "--entrypoint=sh",
                     PLAYWRIGHT_IMAGE, "-c", command],
            "env_allow": [], "allow_roles": ["benchmark"],
            "allow_tools": ["browser_navigate", "browser_run_code_unsafe"],
            "approval": "none", "version": "0.0.79", "integrity": digest,
            "atomic_browser_adapter": True,
            "computer_locator_tool": "browser_run_code_unsafe",
            "computer_policy": {"revision": "computerbench-dev-v1",
                                "allowed_origin": PORTAL_ORIGIN}}
    import mcp
    spec["trust_identity"] = mcp.server_identity(spec)
    return spec


def _write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="." + path.name + "-",
                                     suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _source_hashes(spec):
    home = Path(__file__).resolve().parent
    names = ("computerbench.py", "computersession.py", "computeruse.py",
             "computerverify.py",
             "computerprocess.py", "mcp.py", PORTAL_FIXTURE_REL)
    hashes = {name: hashlib.sha256((home / name).read_bytes()).hexdigest()
              for name in names}
    hashes["mcp_configuration"] = hashlib.sha256(
        _canonical(spec)).hexdigest()
    return hashes


def _timed(record, operation, function):
    started = time.monotonic()
    try:
        value = function()
    except BaseException as error:
        record["timing"].append({"operation": operation,
                                  "seconds": round(time.monotonic() - started, 3),
                                  "outcome": type(error).__name__})
        raise
    record["timing"].append({"operation": operation,
                              "seconds": round(time.monotonic() - started, 3),
                              "outcome": "returned"})
    return value


def _remember_receipt(record, label, receipt):
    record["receipts"].append({"label": label, "receipt": receipt})
    return receipt


def receipt_state_changed(before, after):
    """Compare sealed observation identities, not timing or page wording."""
    return (before["observation"]["state_sha256"]
            != after["observation"]["state_sha256"])


def _ordered_intent_links(receipt, intents):
    """Resolve the current links in caller-frozen intent order."""
    try:
        links = receipt["state"]["links"]
    except (KeyError, TypeError) as error:
        raise ContractError("current receipt has no link state") from error
    if (not isinstance(links, list)
            or any(not isinstance(link, dict)
                   or not isinstance(link.get("id"), str)
                   or not isinstance(link.get("href"), str)
                   for link in links)):
        raise ContractError("current receipt link state is malformed")
    ordered = []
    for intent in intents:
        matches = [link for link in links
                   if link["id"] == intent["target_id"]
                   and link["href"] == intent["destination"]]
        if len(matches) != 1:
            raise ContractError("current receipt does not uniquely satisfy frozen intent")
        ordered.append(matches[0])
    return ordered


def _environment(session, seen):
    import computerprocess
    relative = session._load().get("environment")
    if not relative or relative in {item["relative"] for item in seen}:
        return None
    metadata = computerprocess.read(session.root, relative)
    item = {"relative": relative,
            "metadata_sha256": hashlib.sha256(_canonical(metadata)).hexdigest()}
    if metadata.get("docker"):
        deadline = time.monotonic() + 5
        while True:
            try:
                item["container_id"] = computerprocess._cid(
                    session.root, metadata["docker"]["cidfile"])
                break
            except FileNotFoundError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("owned Docker cidfile was not published")
                time.sleep(.03)
        item["daemon_sha256"] = hashlib.sha256(
            metadata["docker"]["daemon_id"].encode("utf-8")).hexdigest()
    seen.append(item)
    return item


def _platform_call(root, command, reason):
    import execution
    rc, out, err = execution.run("platform_spawn", command, os.fspath(root),
                                 timeout=20, reason=reason)
    if rc:
        raise RuntimeError(reason + " failed: " + err[:300])
    return out


def _inspect_environment(root, environment):
    import computerprocess
    metadata = computerprocess.read(os.fspath(root), environment["relative"])
    docker = metadata.get("docker")
    if not docker:
        raise RuntimeError("development browser is not an owned Docker process")
    command = computerprocess._docker_verified(os.fspath(root), docker)
    raw = _platform_call(root, command + ["inspect", environment["container_id"]],
                         "inspect owned development container")
    try:
        state = json.loads(raw)[0]
    except (ValueError, IndexError, TypeError) as error:
        raise RuntimeError("owned container inspection was malformed") from error
    mounts = state.get("Mounts") or []
    fixture_mount = [item for item in mounts if item.get("Destination") == "/fixture"]
    output_mount = [item for item in mounts if item.get("Destination") == "/artifacts"]
    checks = {"network_none": state.get("HostConfig", {}).get("NetworkMode") == "none",
              "readonly_root": state.get("HostConfig", {}).get("ReadonlyRootfs") is True,
              "nonroot_node": state.get("Config", {}).get("User") == "node",
              "fixture_readonly": len(fixture_mount) == 1
                                  and fixture_mount[0].get("RW") is False,
              "output_only_writable_mount": len(output_mount) == 1
                                           and output_mount[0].get("RW") is True
                                           and len(mounts) == 2,
              "pinned_image": state.get("Config", {}).get("Image") == PLAYWRIGHT_IMAGE}
    if not all(checks.values()):
        raise RuntimeError("owned container isolation checks failed: "
                           + ",".join(name for name, ok in checks.items() if not ok))
    return checks


def _confirm_cleanup(root, environment):
    import computerprocess
    metadata = computerprocess.read(os.fspath(root), environment["relative"])
    docker = metadata.get("docker")
    result = {"relative": environment["relative"],
              "environment_state": metadata.get("state"),
              "container_id": environment.get("container_id"),
              "confirmed": False}
    if not docker or not environment.get("container_id"):
        result["reason"] = "owned Docker identity unavailable"
        return result
    try:
        command = computerprocess._docker_verified(os.fspath(root), docker)
        out = _platform_call(root, command + ["container", "ls", "-a",
            "--no-trunc", "--filter", "id=" + environment["container_id"],
            "--format", "{{.ID}}"], "read back owned container cleanup")
        result["container_absent"] = not bool(out.strip())
        result["confirmed"] = (metadata.get("state") == "closed"
                               and result["container_absent"])
        if not result["confirmed"]:
            result["reason"] = "closed metadata and daemon absence did not agree"
    except BaseException as error:
        result["reason"] = type(error).__name__ + ": " + str(error)[:300]
    return result


def _artifact_manifest(output):
    rows = []
    invoice_ids = []
    for path in sorted(Path(output).iterdir(), key=lambda item: item.name):
        info = path.lstat()
        row = {"name": path.name, "bytes": info.st_size,
               "links": info.st_nlink,
               "regular": stat.S_ISREG(info.st_mode) and not path.is_symlink()}
        if row["regular"] and info.st_nlink == 1 and info.st_size <= _MAX_DOCUMENT:
            raw = path.read_bytes()
            row["sha256"] = hashlib.sha256(raw).hexdigest()
            try:
                value = json.loads(raw.decode("utf-8"))
                if isinstance(value, dict) and isinstance(value.get("id"), str):
                    invoice_ids.append(value["id"])
                    row["invoice_id"] = value["id"]
            except (UnicodeError, ValueError):
                pass
        rows.append(row)
    return rows, len(invoice_ids) - len(set(invoice_ids))


def _development_status(record):
    if not isinstance(record, dict):
        return "unresolved"
    cleanup = record.get("cleanup")
    if (record.get("trial_error") or not isinstance(cleanup, dict)
            or cleanup.get("confirmed") is not True
            or record.get("artifact_outcome") not in ("verified", "rejected")):
        return "unresolved"
    if "action_read_error" in record:
        return "unresolved"
    actions = record.get("actions")
    attempted = record.get("action_attempted")
    if (type(attempted) is not bool or not isinstance(actions, list)
            or any(not isinstance(action, dict)
                   or action.get("operation") not in ("open", "click")
                   or action.get("state") not in ("VERIFIED", "REFUSED",
                                                   "FAILED_WITH_KNOWN_NO_EFFECT",
                                                   "FAILED_POSTCONDITION")
                   for action in actions)):
        return "unresolved"
    clicks = [action for action in actions if action.get("operation") == "click"]
    required_clicks = [action for action in clicks
                       if action.get("required_for_task") is True]
    outcome = record.get("controller_outcome")
    failed_postcondition = any(action["state"] == "FAILED_POSTCONDITION"
                               for action in clicks)
    if failed_postcondition:
        return "rejected_artifacts" if record["artifact_outcome"] == "rejected" \
            and outcome == "refused" else "unresolved"
    if (outcome not in ("completed", "refused")
            or (outcome == "completed"
                and (not attempted
                     or not required_clicks
                     or not all(action["state"] == "VERIFIED"
                                for action in required_clicks)
                     or any(action["state"] not in
                            ("VERIFIED", "REFUSED",
                             "FAILED_WITH_KNOWN_NO_EFFECT")
                            for action in clicks)
                     or record.get("postcondition_completion", {}).get("passed")
                        is not True))
            or (outcome == "refused"
                and any(action["state"] not in
                        ("REFUSED", "FAILED_WITH_KNOWN_NO_EFFECT")
                        for action in clicks))):
        return "unresolved"
    if outcome == "refused":
        return "safe_refusal"
    if record["artifact_outcome"] == "verified":
        if outcome == "completed":
            return "verified_completion"
        return "unresolved"
    if outcome == "completed":
        return "rejected_artifacts"
    return "unresolved"


def run_development_trial(case, repeat, trial_root, docker):
    """Run one preserved portal variant through the task-owned runtime."""
    import computerprocess
    import computersession
    import computeruse
    import computerverify
    import mcp
    import org

    if case not in DEVELOPMENT_EXPECTED or type(repeat) is not int or repeat < 1:
        raise ContractError("invalid development case or repeat")
    started = time.monotonic()
    root = Path(trial_root)
    root.mkdir(parents=True, exist_ok=False)
    output_rel = "effects/computer/artifacts"
    output = root / output_rel
    output.mkdir(parents=True)
    org.create(os.fspath(root), "Synthetic ComputerBench portal",
               "fixture-owner@example.invalid")
    org.set_policy(os.fspath(root), "fixture-owner@example.invalid",
                   "agents_may_reach_internal_network", True)
    spec = portal_spec(docker, output)
    _write_json(root / "mcp.json", {"servers": {"portal": spec}})
    record = {"case": case, "repeat": repeat,
              "expected": DEVELOPMENT_EXPECTED[case],
              "status": "unresolved", "controller_outcome": "not_started",
              "artifact_outcome": "not_run", "provider_calls": 0,
              "action_attempted": False,
              "receipts": [], "timing": [], "environments": [],
              "verification_receipts": [],
              "acceptance_complete": False, "release_ready": False,
              "scope": "known deterministic synthetic development fixture",
              "source_hashes": _source_hashes(spec),
              "browser_image": PLAYWRIGHT_IMAGE,
              "tool_version": spec["version"],
              "trust_identity": spec["trust_identity"]}
    task = {"id": "portal-" + case + "-" + str(repeat),
            "lineage": "portal-" + case + "-" + str(repeat),
            "role": "benchmark", "status": "running"}
    sessions = []
    current = None
    receipt = None
    workflow = None
    expected = invoice_manifest()
    expected_digest = computerverify.canonical_digest(expected)
    expectation_source = {
        "identity": "computerbench.synthetic-owner-manifest",
        "version": "2026-08-v1", "sha256": expected_digest}
    intents = [{"target_id": "INV-" + str(index),
                "invoice_id": "INV-" + str(index),
                "destination": PORTAL_ORIGIN + "/invoice/INV-" + str(index)
                               + "?case=" + case}
               for index in range(3)]
    try:
        current = computersession.ComputerSession(
            os.fspath(root), task, "portal", "computerbench-dev-v1")
        sessions.append(current)
        opened = _timed(record, "open", lambda: current.open(
            PORTAL_ORIGIN + "/?case=" + case))
        receipt = _remember_receipt(record, "open", opened["observation"])
        environment = _environment(current, record["environments"])
        if environment:
            record["isolation"] = _inspect_environment(root, environment)

        if case == "restart":
            old = receipt
            _timed(record, "close_before_restart",
                   lambda: current.close("synthetic restart"))
            current = computersession.ComputerSession(
                os.fspath(root), task, "portal", "computerbench-dev-v1")
            sessions.append(current)
            opened = _timed(record, "open_after_restart", lambda: current.open(
                PORTAL_ORIGIN + "/?case=" + case))
            receipt = _remember_receipt(record, "restart-open",
                                        opened["observation"])
            environment = _environment(current, record["environments"])
            if environment:
                record.setdefault("isolation_after_restart", []).append(
                    _inspect_environment(root, environment))
            try:
                record["action_attempted"] = True
                _timed(record, "old_receipt_after_restart",
                       lambda: current.click(old, "INV-0"))
                raise RuntimeError("old session receipt authorized after restart")
            except computeruse.Refused as error:
                record["controller_outcome"] = "refused"
                record["controller_reason"] = str(error)
        else:
            state = receipt["state"]
            deadline = time.monotonic() + 3
            while not state["links"] and not state["expired"]:
                if time.monotonic() >= deadline:
                    raise computeruse.Refused("invoice links did not become observable")
                time.sleep(.05)
                receipt = _remember_receipt(record, "poll", _timed(
                    record, "observe", current.observe))
                state = receipt["state"]
            if state["dialog"] or state["expired"]:
                if state["links"]:
                    workflow = current.freeze_invoice_workflow(
                        output_rel, expected, expectation_source,
                        expected["account"], intents, deadline_seconds=30)
                    record["action_attempted"] = True
                    _timed(record, "blocked_click",
                           lambda: current.click(receipt, state["links"][0]["id"],
                                                 workflow_id=workflow["workflow_id"]))
                raise computeruse.Refused("dialog or authentication state blocked retrieval")
            workflow = current.freeze_invoice_workflow(
                output_rel, expected, expectation_source, expected["account"],
                intents, deadline_seconds=30)
            if case == "moved":
                old = receipt
                time.sleep(.35)
                receipt = _remember_receipt(record, "moved-refresh",
                                            _timed(record, "observe", current.observe))
                record["moved_state_changed"] = receipt_state_changed(old, receipt)
                if record["moved_state_changed"]:
                    try:
                        record["action_attempted"] = True
                        _timed(record, "stale_moved_click",
                               lambda: current.click(old, "INV-0"))
                        raise RuntimeError("moved target accepted without re-observation")
                    except computeruse.Refused as error:
                        record["moved_receipt_refused"] = str(error)
                else:
                    record["moved_receipt_refused"] = (
                        "not exercised: movement preceded the first sealed receipt")
            planned = _ordered_intent_links(receipt, intents)
            for position, link in enumerate(planned):
                if position:
                    reopened = _timed(record, "reopen-" + link["id"],
                                      lambda: current.open(
                                          PORTAL_ORIGIN + "/?case=" + case))
                    receipt = _remember_receipt(
                        record, "reopen-" + link["id"], reopened["observation"])
                record["action_attempted"] = True
                fresh = _remember_receipt(record, "pre-click-" + link["id"],
                                          _timed(record, "observe", current.observe))
                clicked = _timed(record, "click-" + link["id"],
                                 lambda link=link, fresh=fresh:
                                 current.click(fresh, link["id"],
                                               workflow_id=workflow["workflow_id"]))
                _remember_receipt(record, "post-click-" + link["id"],
                                  clicked["observation"])
                verified = _timed(
                    record, "verify-" + link["id"],
                    lambda clicked=clicked: current.verify_invoice_action(
                        clicked["action_id"], workflow["workflow_id"]))
                record["verification_receipts"].append(verified)
            record["controller_outcome"] = "completed"
    except computeruse.Refused as error:
        record["controller_outcome"] = "refused"
        record["controller_reason"] = str(error)[:500]
    except computeruse.Unresolved as error:
        record["controller_outcome"] = "unknown"
        record["controller_reason"] = str(error)[:500]
    except BaseException as error:
        record["controller_outcome"] = "unknown"
        record["trial_error"] = type(error).__name__ + ": " + str(error)[:500]
    finally:
        for session in sessions:
            try:
                _environment(session, record["environments"])
            except BaseException as error:
                record.setdefault("environment_errors", []).append(
                    type(error).__name__ + ": " + str(error)[:300])
        if current is not None:
            try:
                record["actions_before_cleanup"] = current.actions()
            except BaseException as error:
                record["actions_before_cleanup_error"] = str(error)[:300]
        for session in reversed(sessions):
            try:
                _timed(record, "close", lambda session=session:
                       session.close("development trial complete"))
            except BaseException as error:
                record.setdefault("cleanup_errors", []).append(
                    type(error).__name__ + ": " + str(error)[:300])

    cleanup_rows = [_confirm_cleanup(root, environment)
                    for environment in record["environments"]]
    record["cleanup"] = {"environments": cleanup_rows,
                         "confirmed": bool(cleanup_rows)
                                      and all(row["confirmed"] for row in cleanup_rows)
                                      and not record.get("cleanup_errors")}
    try:
        record["actions"] = (current.actions() if current is not None else [])
    except BaseException as error:
        record["actions"] = None
        record["action_read_error"] = str(error)[:300]

    record["expected_manifest"] = expected
    record["expected_manifest_sha256"] = expected_digest
    passed, why = computerverify.completion_status(os.fspath(root), task)
    record["postcondition_completion"] = {"passed": passed, "reason": why}
    record["verification"] = {"status": "VERIFIED_ARTIFACTS",
                              "manifest_sha256": expected_digest,
                              "receipts": list(record["verification_receipts"]),
                              "release_ready": False} if passed else None
    record["artifact_outcome"] = "verified" if passed else "rejected"
    if not passed: record["verification_reason"] = why[:500]
    try:
        record["artifact_manifest"], record["duplicate_invoice_ids"] = \
            _artifact_manifest(output)
    except BaseException as error:
        record["artifact_manifest"] = []
        record["artifact_manifest_error"] = type(error).__name__ + ": " + str(error)[:300]
        record["trial_error"] = record["artifact_manifest_error"]
    record["status"] = _development_status(record)
    record["development_expectation_met"] = record["status"] == record["expected"]
    record["seconds"] = round(time.monotonic() - started, 3)
    _write_json(root / "TRIAL.json", record)
    return record


def summarize_development(rows):
    statuses = {}
    action_states = {}
    for row in rows:
        statuses[row["status"]] = statuses.get(row["status"], 0) + 1
        actions = row.get("actions")
        for action in actions if isinstance(actions, list) else []:
            state = action.get("state", "missing") if isinstance(action, dict) \
                else "malformed"
            action_states[state] = action_states.get(state, 0) + 1
    selection_complete = bool(rows) and all(
        row.get("development_expectation_met")
        and row.get("cleanup", {}).get("confirmed")
        and row.get("status") != "unresolved"
        and _development_status(row) == row.get("status") for row in rows)
    return {"trials": len(rows), "expectations_met": sum(
                bool(row.get("development_expectation_met")) for row in rows),
            "statuses": statuses,
            "retrievals_verified": statuses.get("verified_completion", 0),
            "safe_refusals": statuses.get("safe_refusal", 0),
            "rejected_artifact_sets": statuses.get("rejected_artifacts", 0),
            "unresolved_trials": statuses.get("unresolved", 0),
            "duplicate_invoice_ids": sum(row.get("duplicate_invoice_ids", 0)
                                         for row in rows),
            "cleanup_confirmed": sum(bool(row.get("cleanup", {}).get("confirmed"))
                                     for row in rows),
            "durable_action_states": action_states,
            "selection_complete": selection_complete,
            "development_complete": len(rows) == 36 and selection_complete,
            "acceptance_complete": False, "release_ready": False,
            "provider_calls": sum(row.get("provider_calls", 0) for row in rows),
            "scope": "known deterministic development fixtures; not independent acceptance"}


def run_development(run_dir, docker=None, cases=None, repeats=3):
    fixture = Path(__file__).resolve().parent / PORTAL_FIXTURE_REL
    if hashlib.sha256(fixture.read_bytes()).hexdigest() != PORTAL_FIXTURE_SHA256:
        raise ContractError("pinned synthetic portal fixture differs")
    docker = docker or shutil.which("docker")
    if not docker:
        raise ContractError("Docker is unavailable; unsafe host fallback is forbidden")
    run = Path(run_dir)
    if run.exists():
        raise ContractError("development run directory must be new")
    run.mkdir(parents=True)
    selected = list(cases or DEVELOPMENT_EXPECTED)
    if (not selected or any(case not in DEVELOPMENT_EXPECTED for case in selected)
            or type(repeats) is not int or not 1 <= repeats <= 3):
        raise ContractError("invalid development case selection")
    rows = []
    for case in selected:
        for repeat in range(1, repeats + 1):
            trial_root = run / (case + "-" + str(repeat))
            row = run_development_trial(case, repeat, trial_root, docker)
            rows.append(row)
            print(case, repeat, row["status"],
                  "cleanup=" + str(row["cleanup"]["confirmed"]), flush=True)
    summary = summarize_development(rows)
    summary["fixture_source_sha256"] = PORTAL_FIXTURE_SHA256
    summary["browser_image"] = PLAYWRIGHT_IMAGE
    summary["trial_receipts"] = [str(Path(row["case"] + "-" + str(row["repeat"]))
                                     / "TRIAL.json") for row in rows]
    _write_json(run / "SUMMARY.json", summary)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Computer-use development qualification")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "acceptance",
        help="fail closed; use the separately installed external verifier")
    development = commands.add_parser("development")
    development.add_argument("--opt-in", action="store_true", required=True)
    development.add_argument("--run-dir", required=True)
    development.add_argument("--docker")
    development.add_argument("--case", choices=tuple(DEVELOPMENT_EXPECTED))
    development.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args(argv)
    if args.command == "acceptance":
        report = {
            "acceptance_complete": False,
            "release_ready": False,
            "missing_evidence": ["external_verifier_required"],
            "scope": ("candidate development CLI cannot verify acceptance; "
                      "use the fixed root-installed external verifier"),
        }
        print(json.dumps(report, indent=2, sort_keys=True))
        return 2
    report = run_development(args.run_dir, args.docker,
                             [args.case] if args.case else None,
                             args.repeats)
    print(json.dumps(report, indent=2, sort_keys=True))
    complete = (report.get("selection_complete") if args.case
                else report.get("development_complete"))
    return 0 if complete is True else 2


if __name__ == "__main__":
    raise SystemExit(main())
