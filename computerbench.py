#!/usr/bin/env python3
"""External ComputerBench acceptance contract and development qualification.

This module does not supply an acceptance pack or claim that repository-authored
fixtures are independent. Acceptance requires separately supplied, sealed pack
and result bytes authenticated by owner trust outside the repository.
"""
import argparse
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import time


TRACKS = ("browser_only", "native_desktop", "api_assisted")
VARIANT_DIMENSIONS = ("layout", "wording", "timing", "authentication",
                      "multistep")
_HEX = re.compile(r"[0-9a-f]{64}")
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
_MAX_DOCUMENT = 10_000_000

PLAYWRIGHT_IMAGE = ("mcr.microsoft.com/playwright/mcp@sha256:"
                    "add8756264bc95962597d2e5095b66317acb1d89a7c8b64f264e7d2dee140bc9")
PORTAL_ORIGIN = "http://127.0.0.1:8765"
PORTAL_FIXTURE_REL = "tests/computerbench-portal-fixture/server.cjs"
PORTAL_FIXTURE_SHA256 = "a2528e5f3e57d472a4e37d8317661a07a8148ac9b6998f643f59a713a7b5f5c2"
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
    """The supplied artifact cannot satisfy the acceptance contract."""


def _canonical(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ContractError("contract is not canonical JSON") from error


def _exact(value, keys, label):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ContractError(label + " has an invalid shape")


def _name(value, label):
    if not isinstance(value, str) or not _NAME.fullmatch(value):
        raise ContractError(label + " is invalid")


def _digest(value, label):
    if not isinstance(value, str) or not _HEX.fullmatch(value):
        raise ContractError(label + " must be a lowercase SHA-256")


def _positive_number(value, label, allow_zero=False):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value < 0
            or (not allow_zero and value == 0)):
        raise ContractError(label + " must be a bounded number")


def validate_pack(pack):
    """Validate schema and frozen dimensions; return the same JSON value."""
    _exact(pack, ("schema", "pack_id", "frozen", "cases"), "pack")
    if pack["schema"] != "computerbench.acceptance-pack.v1":
        raise ContractError("unsupported acceptance-pack schema")
    _name(pack["pack_id"], "pack_id")
    frozen = pack["frozen"]
    _exact(frozen, ("model", "tool", "policy", "budget", "retries",
                    "human_help"), "frozen settings")
    _exact(frozen["model"], ("provider", "name", "version"), "model")
    for field in ("provider", "name", "version"):
        _name(frozen["model"][field], "model." + field)
    _exact(frozen["tool"], ("name", "version", "sha256"), "tool")
    _name(frozen["tool"]["name"], "tool.name")
    _name(frozen["tool"]["version"], "tool.version")
    _digest(frozen["tool"]["sha256"], "tool.sha256")
    _exact(frozen["policy"], ("revision", "sha256"), "policy")
    _name(frozen["policy"]["revision"], "policy.revision")
    _digest(frozen["policy"]["sha256"], "policy.sha256")
    _exact(frozen["budget"], ("max_steps", "max_seconds", "max_cost_usd"),
           "budget")
    if (type(frozen["budget"]["max_steps"]) is not int
            or not 1 <= frozen["budget"]["max_steps"] <= 100_000):
        raise ContractError("budget.max_steps is invalid")
    _positive_number(frozen["budget"]["max_seconds"], "budget.max_seconds")
    _positive_number(frozen["budget"]["max_cost_usd"],
                     "budget.max_cost_usd", allow_zero=True)
    if (type(frozen["retries"]) is not int
            or not 0 <= frozen["retries"] <= 100):
        raise ContractError("retries is invalid")
    if frozen["human_help"] not in ("none", "allowed", "required"):
        raise ContractError("human_help is invalid")

    cases = pack["cases"]
    if not isinstance(cases, list) or not 3 <= len(cases) <= 10_000:
        raise ContractError("pack cases are missing or unbounded")
    identities = set()
    seen_tracks = set()
    for case in cases:
        _exact(case, ("id", "track", "variants", "acceptance"), "case")
        _name(case["id"], "case.id")
        if case["id"] in identities:
            raise ContractError("duplicate case identity")
        identities.add(case["id"])
        if case["track"] not in TRACKS:
            raise ContractError("case track is not independently labelled")
        seen_tracks.add(case["track"])
        _exact(case["variants"], VARIANT_DIMENSIONS, "case variants")
        for field in VARIANT_DIMENSIONS:
            value = case["variants"][field]
            if not isinstance(value, str) or not value.strip() or len(value) > 500:
                raise ContractError("case variant " + field + " is invalid")
        _exact(case["acceptance"], ("kind", "contract"), "case acceptance")
        _name(case["acceptance"]["kind"], "acceptance.kind")
        value = case["acceptance"]["contract"]
        if not isinstance(value, str) or not value.strip() or len(value) > 2_000:
            raise ContractError("acceptance.contract is invalid")
    if seen_tracks != set(TRACKS):
        raise ContractError("browser, native desktop and API-assisted tracks are required")
    _canonical(pack)
    return pack


def validate_results(results, pack, pack_sha256):
    """Validate external result rows against every frozen pack field."""
    _exact(results, ("schema", "pack_sha256", "run_id", "frozen", "cases"),
           "results")
    if results["schema"] != "computerbench.acceptance-results.v1":
        raise ContractError("unsupported acceptance-results schema")
    _digest(results["pack_sha256"], "results.pack_sha256")
    if results["pack_sha256"] != pack_sha256:
        raise ContractError("results are not bound to these pack bytes")
    _name(results["run_id"], "results.run_id")
    if results["frozen"] != pack["frozen"]:
        raise ContractError("result settings differ from the frozen pack")
    expected = {case["id"]: case for case in pack["cases"]}
    rows = results["cases"]
    if not isinstance(rows, list) or len(rows) != len(expected):
        raise ContractError("results do not cover every pack case exactly once")
    seen = set()
    total_steps = 0
    total_seconds = 0.0
    total_cost = 0.0
    for row in rows:
        _exact(row, ("id", "track", "outcome", "evidence_sha256",
                     "attempts", "human_help_used", "steps", "seconds",
                     "cost_usd"),
               "result row")
        identity = row["id"]
        if identity not in expected or identity in seen:
            raise ContractError("unknown or duplicate result case")
        seen.add(identity)
        if row["track"] != expected[identity]["track"]:
            raise ContractError("result track differs from the pack")
        if row["outcome"] not in ("passed", "failed", "skipped"):
            raise ContractError("result outcome is invalid")
        _digest(row["evidence_sha256"], "result evidence")
        if (type(row["attempts"]) is not int or row["attempts"] < 1
                or row["attempts"] > 1 + pack["frozen"]["retries"]):
            raise ContractError("result attempts exceed the frozen retry setting")
        if type(row["human_help_used"]) is not bool:
            raise ContractError("human_help_used must be boolean")
        if pack["frozen"]["human_help"] == "none" and row["human_help_used"]:
            raise ContractError("result used human help despite the frozen setting")
        if type(row["steps"]) is not int or row["steps"] < 0:
            raise ContractError("result steps must be a non-negative integer")
        _positive_number(row["seconds"], "result seconds", allow_zero=True)
        _positive_number(row["cost_usd"], "result cost", allow_zero=True)
        total_steps += row["steps"]
        total_seconds += row["seconds"]
        total_cost += row["cost_usd"]
    budget = pack["frozen"]["budget"]
    if (total_steps > budget["max_steps"]
            or total_seconds > budget["max_seconds"]
            or total_cost > budget["max_cost_usd"]):
        raise ContractError("results exceed the frozen step, time or cost budget")
    return results


def _path(path, label):
    if path is None:
        raise ContractError(label + " is missing")
    candidate = os.path.realpath(os.fspath(path))
    try:
        info = os.lstat(candidate)
    except OSError as error:
        raise ContractError(label + " is unavailable") from error
    if (not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or info.st_nlink != 1 or not 0 < info.st_size <= _MAX_DOCUMENT
            or getattr(info, "st_file_attributes", 0) & 0x400):
        raise ContractError(label + " must be one bounded unlinked regular file")
    return candidate


def _outside(path, repository_root):
    repo = os.path.normcase(os.path.realpath(os.fspath(repository_root)))
    candidate = os.path.normcase(os.path.realpath(path))
    try:
        return os.path.commonpath((repo, candidate)) != repo
    except ValueError:
        return True


def _bytes(path):
    with open(path, "rb") as stream:
        before = os.fstat(stream.fileno())
        raw = stream.read(_MAX_DOCUMENT + 1)
        after = os.fstat(stream.fileno())
    if len(raw) > _MAX_DOCUMENT or (before.st_dev, before.st_ino,
            before.st_size, before.st_nlink) != (after.st_dev, after.st_ino,
            after.st_size, after.st_nlink):
        raise ContractError("external artifact changed during read")
    return raw


def _json(raw, label):
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError) as error:
        raise ContractError(label + " is not valid UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise ContractError(label + " must be a JSON object")
    return value


def _trust(path, repository_root):
    path = _path(path, "independent owner trust")
    if not _outside(path, repository_root):
        raise ContractError("independent owner trust is inside the repository")
    value = _json(_bytes(path), "independent owner trust")
    _exact(value, ("schema", "authority_id", "scope", "key_hex"),
           "independent owner trust")
    if value["schema"] != "computerbench.owner-trust.v1" \
            or value["scope"] != "computerbench":
        raise ContractError("independent owner trust scope is invalid")
    _name(value["authority_id"], "owner authority")
    if (not isinstance(value["key_hex"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", value["key_hex"])):
        raise ContractError("independent owner trust key is invalid")
    return value, bytes.fromhex(value["key_hex"])


def _sealed(artifact_path, seal_path, trust, key, repository_root, kind):
    artifact_path = _path(artifact_path, kind)
    seal_path = _path(seal_path, kind + " seal")
    if not _outside(artifact_path, repository_root):
        raise ContractError(kind + " is inside the repository")
    if not _outside(seal_path, repository_root):
        raise ContractError(kind + " seal is inside the repository")
    raw = _bytes(artifact_path)
    seal = _json(_bytes(seal_path), kind + " seal")
    _exact(seal, ("schema", "artifact_kind", "authority_id", "sha256",
                  "hmac_sha256"), kind + " seal")
    if seal["schema"] != "computerbench.seal.v1" \
            or seal["artifact_kind"] != kind \
            or seal["authority_id"] != trust["authority_id"]:
        raise ContractError(kind + " seal identity is invalid")
    _digest(seal["sha256"], kind + " seal digest")
    _digest(seal["hmac_sha256"], kind + " seal MAC")
    if not hmac.compare_digest(seal["sha256"], hashlib.sha256(raw).hexdigest()):
        raise ContractError(kind + " content seal differs")
    body = {name: seal[name] for name in seal if name != "hmac_sha256"}
    expected = hmac.new(key, _canonical(body), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(seal["hmac_sha256"], expected):
        raise ContractError(kind + " owner authentication differs")
    return _json(raw, kind), seal["sha256"]


def _matrix(pack=None, results=None):
    matrix = {}
    for track in TRACKS:
        cases = [case for case in (pack or {}).get("cases", [])
                 if case.get("track") == track]
        rows = [row for row in (results or {}).get("cases", [])
                if row.get("track") == track]
        matrix[track] = {"declared_cases": len(cases),
                         "reported_cases": len(rows),
                         "passed": sum(row.get("outcome") == "passed"
                                       for row in rows),
                         "failed": sum(row.get("outcome") == "failed"
                                       for row in rows),
                         "skipped": sum(row.get("outcome") == "skipped"
                                        for row in rows),
                         "accepted": bool(cases and len(rows) == len(cases)
                                          and all(row.get("outcome") == "passed"
                                                  for row in rows))}
    return matrix


def assess_acceptance(pack_path=None, seal_path=None, trust_path=None,
                      results_path=None, results_seal_path=None,
                      repository_root=None):
    """Assess externally supplied bytes; never infer provenance from prose."""
    repository_root = repository_root or Path(__file__).resolve().parent
    report = {"contract_valid": False, "provenance_bound": False,
              "results_valid": False, "acceptance_complete": False,
              "release_ready": False, "missing_evidence": [],
              "capability_matrix": _matrix(),
              "scope": "external acceptance contract; not release qualification"}
    try:
        owner, key = _trust(trust_path, repository_root)
    except ContractError:
        report["missing_evidence"].append("independent_owner_trust")
        return report
    try:
        value, digest = _sealed(pack_path, seal_path, owner, key,
                                repository_root, "acceptance_pack")
    except ContractError as error:
        message = str(error)
        report["missing_evidence"].append(
            "pack_inside_repository" if "inside the repository" in message
            and "acceptance_pack is" in message else "pack_content_seal")
        return report
    report["provenance_bound"] = True
    try:
        pack = validate_pack(value)
    except ContractError:
        report["missing_evidence"].append("valid_pack_contract")
        return report
    report["contract_valid"] = True
    report["capability_matrix"] = _matrix(pack)
    try:
        results_value, _ = _sealed(results_path, results_seal_path, owner, key,
                                   repository_root, "acceptance_results")
        results = validate_results(results_value, pack, digest)
    except ContractError:
        report["missing_evidence"].append("sealed_external_results")
        return report
    report["results_valid"] = True
    report["capability_matrix"] = _matrix(pack, results)
    report["acceptance_complete"] = all(
        row["accepted"] for row in report["capability_matrix"].values())
    # Independent acceptance is one gate, not release. Live model/provider,
    # native platform matrix, soak, rollback and review remain separate.
    report["release_ready"] = False
    return report


def invoice_manifest():
    rows = []
    for index in range(3):
        identity = "INV-" + str(index)
        raw = json.dumps({"id": identity, "month": "2026-08",
                          "total_cents": 1200 + index},
                         separators=(",", ":")).encode("utf-8")
        rows.append({"id": identity, "file": identity + ".json",
                     "bytes": len(raw),
                     "sha256": hashlib.sha256(raw).hexdigest()})
    return {"month": "2026-08", "invoices": rows}


def portal_spec(docker, output_dir):
    """Owner-reviewed, isolated process specification for one synthetic trial."""
    fixture = Path(__file__).resolve().parent / PORTAL_FIXTURE_REL
    output = Path(output_dir).resolve()
    digest = PLAYWRIGHT_IMAGE.split("@sha256:", 1)[1]
    command = ("node /fixture/server.cjs & ready=; "
               "for attempt in $(seq 1 100); do "
               "node -e \"fetch('http://127.0.0.1:8765/health').then(r=>"
               "process.exit(r.ok?0:1)).catch(()=>process.exit(1))\" "
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
    if (record.get("trial_error") or not record.get("cleanup", {}).get("confirmed")
            or record.get("artifact_outcome") not in ("verified", "rejected")):
        return "unresolved"
    if record["artifact_outcome"] == "verified":
        if record.get("controller_outcome") == "completed":
            return "verified_completion"
        return "unresolved"
    case = record["case"]
    outcome = record.get("controller_outcome")
    if (outcome == "completed"
            and case in ("corrupt", "duplicate_missing")):
        return "rejected_artifacts"
    if outcome == "unknown" and case == "interrupted":
        return "rejected_artifacts"
    if (outcome == "refused"
            and case in ("ambiguous", "dialog", "expired", "restart",
                         "cross_origin")):
        return "safe_refusal"
    if outcome == "unknown" and case == "cross_origin":
        return "safe_refusal"
    return "unresolved"


def run_development_trial(case, repeat, trial_root, docker):
    """Run one preserved portal variant through the task-owned runtime."""
    import computerprocess
    import computersession
    import computeruse
    import mcp
    import org

    if case not in DEVELOPMENT_EXPECTED or type(repeat) is not int or repeat < 1:
        raise ContractError("invalid development case or repeat")
    started = time.monotonic()
    root = Path(trial_root)
    root.mkdir(parents=True, exist_ok=False)
    output = root / "output"
    output.mkdir()
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
              "receipts": [], "timing": [], "environments": [],
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
                    _timed(record, "blocked_click",
                           lambda: current.click(receipt, state["links"][0]["id"]))
                raise computeruse.Refused("dialog or authentication state blocked retrieval")
            if case == "moved":
                old = receipt
                time.sleep(.35)
                receipt = _remember_receipt(record, "moved-refresh",
                                            _timed(record, "observe", current.observe))
                record["moved_state_changed"] = receipt_state_changed(old, receipt)
                if record["moved_state_changed"]:
                    try:
                        _timed(record, "stale_moved_click",
                               lambda: current.click(old, "INV-0"))
                        raise RuntimeError("moved target accepted without re-observation")
                    except computeruse.Refused as error:
                        record["moved_receipt_refused"] = str(error)
                else:
                    record["moved_receipt_refused"] = (
                        "not exercised: movement preceded the first sealed receipt")
            for link in list(receipt["state"]["links"]):
                fresh = _remember_receipt(record, "pre-click-" + link["id"],
                                          _timed(record, "observe", current.observe))
                clicked = _timed(record, "click-" + link["id"],
                                 lambda link=link, fresh=fresh:
                                 current.click(fresh, link["id"]))
                _remember_receipt(record, "post-click-" + link["id"],
                                  clicked["observation"])
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
        record["actions"] = []
        record["action_read_error"] = str(error)[:300]

    expected = invoice_manifest()
    expected_digest = computeruse.digest_manifest(expected)
    record["expected_manifest"] = expected
    record["expected_manifest_sha256"] = expected_digest
    try:
        record["verification"] = computeruse.verify_invoices(
            os.fspath(root), "output", expected, expected_digest)
        record["artifact_outcome"] = "verified"
    except (ValueError, OSError) as error:
        record["artifact_outcome"] = "rejected"
        record["verification_reason"] = str(error)[:500]
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
        for action in row.get("actions", []):
            state = action.get("state", "missing")
            action_states[state] = action_states.get(state, 0) + 1
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
            "development_complete": len(rows) == 36
                                    and all(row.get("development_expectation_met")
                                            and row.get("cleanup", {}).get("confirmed")
                                            for row in rows),
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
    parser = argparse.ArgumentParser(description="Computer-use qualification contracts")
    commands = parser.add_subparsers(dest="command", required=True)
    acceptance = commands.add_parser("acceptance")
    acceptance.add_argument("--pack")
    acceptance.add_argument("--pack-seal")
    acceptance.add_argument("--owner-trust")
    acceptance.add_argument("--results")
    acceptance.add_argument("--results-seal")
    acceptance.add_argument("--repository-root",
                            default=str(Path(__file__).resolve().parent))
    development = commands.add_parser("development")
    development.add_argument("--opt-in", action="store_true", required=True)
    development.add_argument("--run-dir", required=True)
    development.add_argument("--docker")
    development.add_argument("--case", choices=tuple(DEVELOPMENT_EXPECTED))
    development.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args(argv)
    if args.command == "development":
        report = run_development(args.run_dir, args.docker,
                                 [args.case] if args.case else None,
                                 args.repeats)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report["development_complete"] or args.case else 2
    report = assess_acceptance(args.pack, args.pack_seal, args.owner_trust,
                               args.results, args.results_seal, args.repository_root)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["contract_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
