"""Externally installed ComputerBench acceptance verifier.

This source may ship as an installation template, but production operations
refuse unless this exact module is installed under the fixed root-owned verifier
location and run as its dedicated nonroot verifier identity. Candidate archives
are parsed only as inert ZIP data and are never imported or executed.
"""
import sys as _bootstrap_sys


_BOOTSTRAP_INTERPRETER = "/usr/bin/python3"
_BOOTSTRAP_VERIFIER = ("/opt/expert-fleet/computerbench-verifier/"
                       "computerbench_verifier.py")
_BOOTSTRAP_LAUNCHER = ("/opt/expert-fleet/computerbench-verifier/"
                       "computerbench-verifier")


def _bootstrap_entry_contract():
    """Refuse direct/shebang entry before any file-backed import occurs."""
    flags = _bootstrap_sys.flags
    expected = [_BOOTSTRAP_INTERPRETER, "-I", "-S", _BOOTSTRAP_VERIFIER]
    if (getattr(flags, "isolated", 0) != 1
            or getattr(flags, "no_site", 0) != 1
            or getattr(flags, "ignore_environment", 0) != 1
            or not getattr(flags, "safe_path", False)
            or _bootstrap_sys.executable != _BOOTSTRAP_INTERPRETER
            or list(getattr(_bootstrap_sys, "orig_argv", ()))[:4] != expected):
        raise SystemExit("refused: use the fixed external verifier launcher")


if __name__ == "__main__":
    _bootstrap_entry_contract()

import argparse
import contextlib
import hashlib
import hmac
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import secrets
import stat
import tempfile
import threading
import time
import zipfile


TRACKS = ("browser_only", "native_desktop", "api_assisted")
VARIANT_DIMENSIONS = ("layout", "wording", "timing", "authentication",
                      "multistep")
_HEX = re.compile(r"[0-9a-f]{64}")
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
_MAX_DOCUMENT = 10_000_000
_MAX_ARCHIVE = 100_000_000
_MAX_ARCHIVE_MEMBERS = 10_000
_MAX_ARCHIVE_UNCOMPRESSED = 500_000_000
_CHALLENGE_MAX_SECONDS = 3600
_FIXED_INSTALL_ROOT = Path("/opt/expert-fleet/computerbench-verifier")
_FIXED_VERIFIER_FILE = _FIXED_INSTALL_ROOT / "computerbench_verifier.py"
_FIXED_LAUNCHER_FILE = _FIXED_INSTALL_ROOT / "computerbench-verifier"
_FIXED_INTERPRETER = Path("/usr/bin/python3")
_LAUNCH_ENVIRONMENT = {
    "PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C",
    "COMPUTERBENCH_VERIFIER_LAUNCHER": _BOOTSTRAP_LAUNCHER,
}
_OWNER_STORE = (Path("C:/ProgramData/ExpertFleet/computerbench")
                if os.name == "nt" else
                Path("/etc/expert-fleet/computerbench"))
_VERIFIER_STATE = (Path("C:/ProgramData/ExpertFleet/computerbench-state")
                   if os.name == "nt" else
                   Path("/var/lib/expert-fleet/computerbench"))
_SHA256_DIGEST_INFO = bytes.fromhex(
    "3031300d060960864801650304020105000420")
_INTERNAL_LOCKS = {}
_INTERNAL_LOCKS_GUARD = threading.Lock()


class ContractError(ValueError):
    """The supplied artifact cannot satisfy the acceptance contract."""


def _validate_launch_facts(executable, original_argv, flags, environment):
    """Validate the exact launcher-created interpreter process contract."""
    expected = [_BOOTSTRAP_INTERPRETER, "-I", "-S", _BOOTSTRAP_VERIFIER]
    if (executable != expected[0]
            or not isinstance(original_argv, (list, tuple))
            or list(original_argv)[:4] != expected
            or getattr(flags, "isolated", 0) != 1
            or getattr(flags, "no_site", 0) != 1
            or getattr(flags, "ignore_environment", 0) != 1
            or getattr(flags, "safe_path", False) is not True
            or environment != _LAUNCH_ENVIRONMENT):
        raise ContractError("external verifier launch contract is unsafe")


def _validate_interpreter_root():
    for directory in (Path("/usr"), Path("/usr/bin")):
        info = os.stat(directory, follow_symlinks=False)
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != 0
                or stat.S_IMODE(info.st_mode) & 0o022):
            raise ContractError("fixed interpreter directory is unsafe")
    link = os.stat(_FIXED_INTERPRETER, follow_symlinks=False)
    if (link.st_uid != 0
            or not (stat.S_ISREG(link.st_mode) or stat.S_ISLNK(link.st_mode))
            or (stat.S_ISREG(link.st_mode)
                and stat.S_IMODE(link.st_mode) & 0o022)):
        raise ContractError("fixed interpreter path is unsafe")
    resolved = _FIXED_INTERPRETER.resolve(strict=True)
    if resolved.parent != Path("/usr/bin"):
        raise ContractError("fixed interpreter resolves outside /usr/bin")
    target = os.stat(resolved, follow_symlinks=False)
    if (not stat.S_ISREG(target.st_mode) or target.st_uid != 0
            or stat.S_IMODE(target.st_mode) & 0o022):
        raise ContractError("fixed interpreter target is unsafe")


def _validate_launch_contract():
    if os.name != "posix":
        raise ContractError("external verifier launch is unavailable")
    _validate_launch_facts(_bootstrap_sys.executable,
                           list(_bootstrap_sys.orig_argv),
                           _bootstrap_sys.flags, dict(os.environ))
    _validate_interpreter_root()


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


def _archive_member_path(name):
    if (not isinstance(name, str) or not name or len(name) > 4096
            or "\\x00" in name or "\\" in name or name.startswith("/")
            or re.match(r"^[A-Za-z]:", name)):
        raise ContractError("candidate archive member path is invalid")
    parts = name.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ContractError("candidate archive member path is invalid")
    if any(ord(character) < 32 for character in name):
        raise ContractError("candidate archive member path has control bytes")
    return "/".join(parts)


def _candidate_from_archive_bytes(raw, trust_metadata_sha256,
                                  verifier_build_sha256):
    _digest(trust_metadata_sha256, "trust metadata digest")
    _digest(verifier_build_sha256, "verifier build digest")
    if not 0 < len(raw) <= _MAX_ARCHIVE:
        raise ContractError("candidate archive is empty or unbounded")
    rows = []
    seen = set()
    folded = set()
    total = 0
    configuration_rows = []
    runtime_rows = []
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw), "r")
        infos = archive.infolist()
        if not 1 <= len(infos) <= _MAX_ARCHIVE_MEMBERS:
            raise ContractError("candidate archive member count is unbounded")
        for info in infos:
            path = _archive_member_path(info.filename)
            folded_path = path.casefold()
            if path in seen or folded_path in folded:
                raise ContractError("candidate archive has duplicate identities")
            seen.add(path)
            folded.add(folded_path)
            if info.is_dir() or info.flag_bits & 0x1:
                raise ContractError("candidate archive has unsupported members")
            mode = (info.external_attr >> 16) & 0xffff
            kind = stat.S_IFMT(mode)
            if kind not in (0, stat.S_IFREG):
                raise ContractError("candidate archive has links or special files")
            if info.file_size < 0 or info.file_size > _MAX_ARCHIVE_UNCOMPRESSED:
                raise ContractError("candidate archive member is unbounded")
            total += info.file_size
            if total > _MAX_ARCHIVE_UNCOMPRESSED:
                raise ContractError("candidate archive expands beyond its bound")
            member = archive.read(info)
            if len(member) != info.file_size:
                raise ContractError("candidate archive member length differs")
            row = {"path": path, "bytes": len(member),
                   "sha256": hashlib.sha256(member).hexdigest()}
            rows.append(row)
            if path.endswith(".py"):
                runtime_rows.append(row)
            if (path == "settings.toml" or path.endswith(".policy.json")
                    or path.startswith("config/")):
                configuration_rows.append(row)
        archive.close()
    except (OSError, ValueError, zipfile.BadZipFile, RuntimeError) as error:
        raise ContractError("candidate archive is invalid") from error
    rows.sort(key=lambda row: row["path"])
    runtime_rows.sort(key=lambda row: row["path"])
    configuration_rows.sort(key=lambda row: row["path"])
    if "computerbench.py" not in seen or "settings.toml" not in seen:
        raise ContractError("candidate archive omits runtime or configuration")
    manifest_digest = hashlib.sha256(_canonical(rows)).hexdigest()
    return {
        "archive_sha256": hashlib.sha256(raw).hexdigest(),
        "manifest_sha256": manifest_digest,
        "manifest": rows,
        "runtime_sha256": hashlib.sha256(_canonical(runtime_rows)).hexdigest(),
        "configuration_sha256": hashlib.sha256(
            _canonical(configuration_rows)).hexdigest(),
        "verifier_build_sha256": verifier_build_sha256,
        "trust_metadata_sha256": trust_metadata_sha256,
    }


def _candidate_identity(archive_path, trust_metadata_sha256, install_root,
                        internal=False):
    raw = _secure_external_bytes(archive_path, "candidate archive",
                                 install_root, internal, _MAX_ARCHIVE)
    verifier_file = Path(__file__).resolve()
    resolved_install = Path(install_root).resolve()
    expected = resolved_install / "computerbench_verifier.py"
    if verifier_file != expected:
        raise ContractError("verifier module is not running from its installation")
    build_rows = []
    for name, path in (("computerbench-verifier",
                        resolved_install / "computerbench-verifier"),
                       ("computerbench_verifier.py", verifier_file)):
        if os.name == "posix":
            build = _read_open_fd(_posix_open_nofollow(
                path, "verifier build"), "verifier build")[0]
        elif internal:
            info = os.lstat(path)
            if (stat.S_ISLNK(info.st_mode)
                    or getattr(info, "st_file_attributes", 0) & 0x400):
                raise ContractError("verifier build reparse path refused")
            build = _read_open_fd(os.open(
                path, os.O_RDONLY | getattr(os, "O_BINARY", 0)),
                "verifier build")[0]
        else:
            raise ContractError("verifier build secure read is unsupported")
        build_rows.append({"path": name, "bytes": len(build),
                           "sha256": hashlib.sha256(build).hexdigest()})
    return _candidate_from_archive_bytes(
        raw, trust_metadata_sha256,
        hashlib.sha256(_canonical(build_rows)).hexdigest())


def _validate_candidate(value, label="candidate"):
    keys = ("archive_sha256", "runtime_sha256", "configuration_sha256",
            "verifier_build_sha256", "manifest_sha256", "manifest",
            "trust_metadata_sha256")
    _exact(value, keys, label)
    for field in keys:
        if field != "manifest":
            _digest(value[field], label + "." + field)
    rows = value["manifest"]
    if not isinstance(rows, list) or not rows:
        raise ContractError(label + ".manifest is empty")
    paths = []
    for row in rows:
        _exact(row, ("path", "bytes", "sha256"), label + ".manifest row")
        path = _archive_member_path(row["path"])
        if type(row["bytes"]) is not int or row["bytes"] < 0:
            raise ContractError(label + ".manifest bytes is invalid")
        _digest(row["sha256"], label + ".manifest digest")
        paths.append(path)
    if paths != sorted(paths) or len(paths) != len(set(paths)) \
            or len({path.casefold() for path in paths}) != len(paths):
        raise ContractError(label + ".manifest order or identity is invalid")
    if hashlib.sha256(_canonical(rows)).hexdigest() != value["manifest_sha256"]:
        raise ContractError(label + ".manifest digest differs")


def _validate_challenge(value, label="challenge"):
    _exact(value, ("trust_id", "nonce", "issued_at", "expires_at",
                   "trust_metadata_sha256", "candidate"), label)
    _name(value["trust_id"], label + ".trust_id")
    if not isinstance(value["nonce"], str) \
            or not re.fullmatch(r"[0-9a-f]{32}", value["nonce"]):
        raise ContractError(label + ".nonce is invalid")
    if (type(value["issued_at"]) is not int
            or type(value["expires_at"]) is not int
            or value["issued_at"] < 0
            or not value["issued_at"] < value["expires_at"]
            or value["expires_at"] - value["issued_at"] > _CHALLENGE_MAX_SECONDS):
        raise ContractError(label + " validity window is invalid")
    _validate_candidate(value["candidate"], label + ".candidate")
    _digest(value["trust_metadata_sha256"], label + ".trust_metadata_sha256")
    if value["candidate"]["trust_metadata_sha256"] != \
            value["trust_metadata_sha256"]:
        raise ContractError(label + " trust metadata binding differs")


def validate_pack(pack):
    """Validate schema and frozen dimensions; return the same JSON value."""
    _exact(pack, ("schema", "pack_id", "candidate", "challenge", "frozen",
                  "cases"), "pack")
    if pack["schema"] != "computerbench.acceptance-pack.v1":
        raise ContractError("unsupported acceptance-pack schema")
    _name(pack["pack_id"], "pack_id")
    _validate_candidate(pack["candidate"])
    _validate_challenge(pack["challenge"])
    if pack["challenge"]["candidate"] != pack["candidate"]:
        raise ContractError("pack candidate differs from issued challenge")
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
    _exact(results, ("schema", "pack_sha256", "run_id", "candidate",
                     "challenge", "frozen", "cases"), "results")
    if results["schema"] != "computerbench.acceptance-results.v1":
        raise ContractError("unsupported acceptance-results schema")
    _digest(results["pack_sha256"], "results.pack_sha256")
    if results["pack_sha256"] != pack_sha256:
        raise ContractError("results are not bound to these pack bytes")
    _name(results["run_id"], "results.run_id")
    _validate_candidate(results["candidate"], "results.candidate")
    _validate_challenge(results["challenge"], "results.challenge")
    if (results["candidate"] != pack["candidate"]
            or results["challenge"] != pack["challenge"]):
        raise ContractError("results candidate or challenge differs from pack")
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
        if pack["frozen"]["human_help"] == "required" \
                and not row["human_help_used"]:
            raise ContractError("result omitted required human help")
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


def _atomic_json(path, value, exclusive=False):
    """Durably publish owner state without ever printing credential bytes."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | (os.O_EXCL if exclusive else 0)
    temporary = path.with_name("." + path.name + "-" + secrets.token_hex(8))
    fd = os.open(temporary, flags | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(_canonical(value) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        if exclusive:
            os.link(temporary, path)
            os.unlink(temporary)
        else:
            os.replace(temporary, path)
        try:
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except OSError:
            pass
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _posix_open_nofollow(path, label):
    """Open every path component by descriptor; never reopen by pathname."""
    absolute = Path(path)
    if not absolute.is_absolute() or not hasattr(os, "O_NOFOLLOW"):
        raise ContractError(label + " secure descriptor reads are unsupported")
    parts = absolute.parts
    directory = os.open(parts[0], os.O_RDONLY | os.O_DIRECTORY)
    try:
        for component in parts[1:-1]:
            if component in ("", ".", ".."):
                raise ContractError(label + " path is invalid")
            next_fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY |
                              os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = next_fd
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
        return fd
    except OSError as error:
        raise ContractError(label + " secure open refused") from error
    finally:
        os.close(directory)


def _read_open_fd(fd, label, limit=_MAX_DOCUMENT):
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or not 0 < before.st_size <= limit
                or getattr(before, "st_file_attributes", 0) & 0x400):
            raise ContractError(label + " must be one bounded unlinked regular file")
        chunks, remaining = [], limit + 1
        while remaining:
            chunk = os.read(fd, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(fd)
        identity = (before.st_dev, before.st_ino, before.st_size,
                    before.st_nlink)
        if len(raw) > limit or identity != (
                after.st_dev, after.st_ino, after.st_size, after.st_nlink):
            raise ContractError(label + " changed during descriptor read")
        return raw, (before.st_dev, before.st_ino)
    finally:
        os.close(fd)


def _lexically_outside(path, repository_root):
    candidate = os.path.normcase(os.path.abspath(os.fspath(path)))
    repository = os.path.normcase(os.path.abspath(os.fspath(repository_root)))
    try:
        return os.path.commonpath((candidate, repository)) != repository
    except ValueError:
        return True


def _secure_external_bytes(path, label, repository_root, internal=False,
                           limit=_MAX_DOCUMENT):
    if path is None:
        raise ContractError(label + " is missing")
    absolute = os.path.abspath(os.fspath(path))
    if not _lexically_outside(absolute, repository_root):
        raise ContractError(label + " is inside the repository")
    if os.name == "posix":
        return _read_open_fd(_posix_open_nofollow(absolute, label), label,
                             limit)[0]
    # Python exposes no Windows open-relative/no-reparse primitive. Production
    # therefore refuses instead of substituting a check-then-open pathname.
    if not internal:
        raise ContractError(label + " secure descriptor reads are unsupported")
    # Unit fixtures use this explicitly internal seam. Check every component,
    # then read once from one descriptor; it is not reachable from the CLI.
    try:
        current = Path(absolute).anchor
        for component in Path(absolute).parts[1:]:
            current = os.path.join(current, component)
            info = os.lstat(current)
            if (stat.S_ISLNK(info.st_mode)
                    or getattr(info, "st_file_attributes", 0) & 0x400):
                raise ContractError(label + " reparse or alias path refused")
        return _read_open_fd(os.open(
            absolute, os.O_RDONLY | getattr(os, "O_BINARY", 0)),
            label, limit)[0]
    except ContractError:
        raise
    except OSError as error:
        raise ContractError(label + " secure open refused") from error


def _json(raw, label):
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError) as error:
        raise ContractError(label + " is not valid UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise ContractError(label + " must be a JSON object")
    return value


def _validate_public_key(value, label):
    _exact(value, ("key_id", "principal", "algorithm", "n_hex", "e"), label)
    _name(value["key_id"], label + ".key_id")
    _name(value["principal"], label + ".principal")
    if value["algorithm"] != "rsa-pkcs1-v1_5-sha256":
        raise ContractError(label + " algorithm is unsupported")
    if (not isinstance(value["n_hex"], str)
            or not 512 <= len(value["n_hex"]) <= 2048
            or not re.fullmatch(r"[0-9a-f]+", value["n_hex"] or "")
            or value["n_hex"].startswith("0")):
        raise ContractError(label + " modulus is invalid")
    modulus = int(value["n_hex"], 16)
    exponent = value["e"]
    if (not 2048 <= modulus.bit_length() <= 8192 or modulus % 2 == 0
            or type(exponent) is not int or not 3 <= exponent <= 0xffffffff
            or exponent % 2 == 0 or exponent >= modulus):
        raise ContractError(label + " public key is weak or invalid")
    return modulus, exponent


def _rsa_verify(message, signature_hex, modulus, exponent):
    """Strict stdlib RSA PKCS#1 v1.5 SHA-256 signature verification."""
    if (type(modulus) is not int
            or not 2048 <= modulus.bit_length() <= 8192
            or modulus % 2 == 0 or type(exponent) is not int
            or not 3 <= exponent <= 0xffffffff or exponent % 2 == 0
            or exponent >= modulus):
        return False
    size = (modulus.bit_length() + 7) // 8
    if (not isinstance(signature_hex, str)
            or not re.fullmatch(r"[0-9a-f]+", signature_hex or "")
            or len(signature_hex) != size * 2):
        return False
    signature = int(signature_hex, 16)
    if signature <= 0 or signature >= modulus:
        return False
    encoded = pow(signature, exponent, modulus).to_bytes(size, "big")
    digest_info = _SHA256_DIGEST_INFO + hashlib.sha256(message).digest()
    padding_length = size - len(digest_info) - 3
    if padding_length < 8:
        return False
    expected = b"\x00\x01" + b"\xff" * padding_length + b"\x00" + digest_info
    return hmac.compare_digest(encoded, expected)


def _fsync_directory(path):
    try:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError:
        # Windows cannot fsync directories. It is only used by the internal
        # test seam; production is POSIX-only and requires the operation.
        if os.name == "posix":
            raise


def _validate_installation_facts(absolute_file, resolved_file, directories,
                                 file_info, launcher_info):
    if (Path(absolute_file) != _FIXED_VERIFIER_FILE
            or Path(resolved_file) != _FIXED_VERIFIER_FILE):
        raise ContractError("verifier is not running from the fixed installation")
    for info in directories:
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != 0
                or stat.S_IMODE(info.st_mode) & 0o022):
            raise ContractError("verifier installation directory is unsafe")
    if (not stat.S_ISREG(file_info.st_mode) or file_info.st_uid != 0
            or file_info.st_nlink != 1
            or stat.S_IMODE(file_info.st_mode) & 0o133):
        raise ContractError("verifier installation file is unsafe")
    if (not stat.S_ISREG(launcher_info.st_mode) or launcher_info.st_uid != 0
            or launcher_info.st_nlink != 1
            or stat.S_IMODE(launcher_info.st_mode) & 0o022
            or not stat.S_IMODE(launcher_info.st_mode) & 0o111):
        raise ContractError("verifier launcher is unsafe")


def _validate_installation_root():
    """Require the immutable external verifier installation, never this checkout."""
    if os.name != "posix" or not hasattr(os, "geteuid"):
        raise ContractError("external verifier installation is unavailable")
    directories = [os.stat(directory, follow_symlinks=False)
                   for directory in (Path("/opt"), Path("/opt/expert-fleet"),
                                     _FIXED_INSTALL_ROOT)]
    descriptor = _posix_open_nofollow(_FIXED_VERIFIER_FILE,
                                      "verifier installation")
    info = os.fstat(descriptor)
    os.close(descriptor)
    launcher_descriptor = _posix_open_nofollow(
        _FIXED_LAUNCHER_FILE, "verifier launcher")
    launcher_info = os.fstat(launcher_descriptor)
    os.close(launcher_descriptor)
    _validate_installation_facts(Path(os.path.abspath(__file__)),
                                 Path(__file__).resolve(), directories, info,
                                 launcher_info)


class _OwnerBackend:
    """Fixed public trust verifier and durable one-run challenge store."""
    def __init__(self, root, candidate_archive, state_root=None,
                 install_root=_FIXED_INSTALL_ROOT, internal=False,
                 test_profile=None):
        self.root = Path(root)
        self.candidate_archive = Path(candidate_archive)
        self.install_root = Path(install_root)
        self.state_root = Path(state_root or (self.root / "state"))
        self.internal = bool(internal)
        self._test_profile = test_profile
        self._profile_digests = {}
        if self.internal:
            self.root.mkdir(parents=True, exist_ok=True)
            self.state_root.mkdir(parents=True, exist_ok=True)
            if test_profile is None:
                raise ContractError("internal backend requires a public profile")
            _atomic_json(self._profile_path(test_profile["trust_id"]),
                         test_profile, exclusive=True)

    def _profile_path(self, trust_id):
        _name(trust_id, "trust_id")
        return self.root / "authorities" / (trust_id + ".json")

    def _issued_path(self, nonce):
        return self.state_root / "issued" / (nonce + ".json")

    def _consumed_path(self, nonce):
        return self.state_root / "consumed" / (nonce + ".json")

    def _validate_production_roots(self, verifier_uid=None):
        if (self.internal or os.name != "posix" or not hasattr(os, "geteuid")
                or self.root != _OWNER_STORE or self.state_root != _VERIFIER_STATE):
            if self.internal:
                return
            raise ContractError("secure public verification authority is unavailable")
        _validate_installation_root()
        trust = os.stat(self.root, follow_symlinks=False)
        if (trust.st_uid != 0 or not stat.S_ISDIR(trust.st_mode)
                or stat.S_IMODE(trust.st_mode) & 0o022):
            raise ContractError("public trust store permissions or identity are unsafe")
        authorities = os.stat(self.root / "authorities", follow_symlinks=False)
        if (authorities.st_uid != 0 or not stat.S_ISDIR(authorities.st_mode)
                or stat.S_IMODE(authorities.st_mode) & 0o022):
            raise ContractError("public authority directory is unsafe")
        if verifier_uid is not None:
            state_info = os.stat(self.state_root, follow_symlinks=False)
            if (not stat.S_ISDIR(state_info.st_mode)
                    or state_info.st_uid != verifier_uid
                    or stat.S_IMODE(state_info.st_mode) != 0o700
                    or os.geteuid() != verifier_uid):
                raise ContractError("dedicated verifier state or process identity differs")
            for child in (self.state_root / "issued",
                          self.state_root / "consumed"):
                info = os.stat(child, follow_symlinks=False)
                if (not stat.S_ISDIR(info.st_mode)
                        or info.st_uid != verifier_uid
                        or stat.S_IMODE(info.st_mode) != 0o700):
                    raise ContractError("challenge state permissions or identity are unsafe")

    def _owner_bytes(self, path, label):
        if self.internal:
            try:
                return Path(path).read_bytes()
            except OSError as error:
                raise ContractError(label + " is unavailable") from error
        self._validate_production_roots()
        fd = _posix_open_nofollow(path, label)
        info = os.fstat(fd)
        if info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o022:
            os.close(fd)
            raise ContractError(label + " is not root-owned and non-writable")
        return _read_open_fd(fd, label)[0]

    def _state_json(self, path, label, verifier_uid):
        if self.internal:
            try:
                return _json(Path(path).read_bytes(), label)
            except OSError as error:
                raise ContractError(label + " is unavailable") from error
        fd = _posix_open_nofollow(path, label)
        info = os.fstat(fd)
        if (info.st_uid != verifier_uid
                or stat.S_IMODE(info.st_mode) != 0o600):
            os.close(fd)
            raise ContractError(label + " owner or permissions differ")
        return _json(_read_open_fd(fd, label)[0], label)

    def _has_tombstone(self, nonce):
        try:
            os.stat(self._consumed_path(nonce), follow_symlinks=False)
            return True
        except FileNotFoundError:
            return False
        except OSError as error:
            raise ContractError("consumed challenge state is unsafe") from error

    def profile(self, trust_id):
        raw = self._owner_bytes(self._profile_path(trust_id), "owner profile")
        value = _json(raw, "owner profile")
        _exact(value, ("schema", "trust_id", "verifier_uid", "worker_uid",
                       "pack_issuer", "results_evaluator"),
               "owner profile")
        if value["schema"] != "computerbench.public-trust.v1" \
                or value["trust_id"] != trust_id:
            raise ContractError("owner profile identity differs")
        if (type(value["verifier_uid"]) is not int
                or type(value["worker_uid"]) is not int
                or value["verifier_uid"] <= 0
                or value["verifier_uid"] == value["worker_uid"]):
            raise ContractError("dedicated verifier and worker identities differ")
        for role in ("pack_issuer", "results_evaluator"):
            _validate_public_key(value[role], role)
        if (value["pack_issuer"]["key_id"] == value["results_evaluator"]["key_id"]
                or value["pack_issuer"]["principal"] ==
                value["results_evaluator"]["principal"]
                or value["pack_issuer"]["n_hex"] ==
                value["results_evaluator"]["n_hex"]):
            raise ContractError("pack issuer and results evaluator must be distinct")
        self._validate_production_roots(value["verifier_uid"])
        self._profile_digests[trust_id] = hashlib.sha256(raw).hexdigest()
        return value

    def profile_digest(self, trust_id):
        self.profile(trust_id)
        return self._profile_digests[trust_id]

    def candidate(self, trust_digest):
        # Re-read exact inert archive bytes at every validation boundary.
        # A challenge never blesses a pathname whose bytes can later change.
        return _candidate_identity(self.candidate_archive, trust_digest,
                                   self.install_root, self.internal)

    def issue_challenge(self, trust_id, ttl=300):
        profile = self.profile(trust_id)
        trust_digest = self._profile_digests[trust_id]
        now = int(time.time())
        if type(ttl) is not int or not 1 <= ttl <= _CHALLENGE_MAX_SECONDS:
            raise ContractError("challenge ttl is invalid")
        value = {"trust_id": trust_id, "nonce": secrets.token_hex(16),
                 "issued_at": now, "expires_at": now + ttl,
                 "trust_metadata_sha256": trust_digest,
                 "candidate": self.candidate(trust_digest)}
        path = self._issued_path(value["nonce"])
        _atomic_json(path, value, exclusive=True)
        return value

    def challenge(self, value):
        _validate_challenge(value)
        if self._has_tombstone(value["nonce"]):
            raise ContractError("challenge is unavailable, consumed or replayed")
        path = self._issued_path(value["nonce"])
        profile = self.profile(value["trust_id"])
        try:
            stored = self._state_json(path, "issued challenge",
                                      profile["verifier_uid"])
        except ContractError as error:
            raise ContractError("challenge is unavailable, consumed or replayed") from error
        trust_digest = self._profile_digests[value["trust_id"]]
        if (stored != value or value["trust_metadata_sha256"] != trust_digest
                or value["candidate"] != self.candidate(trust_digest)):
            raise ContractError("challenge candidate or stored identity differs")
        now = int(time.time())
        if not value["issued_at"] <= now < value["expires_at"]:
            raise ContractError("challenge is not currently valid")
        return path

    @contextlib.contextmanager
    def _transition_lock(self, nonce):
        lock_path = self.state_root / ("." + nonce + ".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with _INTERNAL_LOCKS_GUARD:
            local = _INTERNAL_LOCKS.setdefault(os.fspath(lock_path),
                                               threading.Lock())
        local.acquire()
        flags = os.O_RDWR | os.O_CREAT
        if os.name == "posix":
            flags |= os.O_NOFOLLOW
        descriptor = os.open(lock_path, flags, 0o600)
        try:
            info = os.fstat(descriptor)
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                    or (not self.internal and
                        (info.st_uid != os.geteuid()
                         or stat.S_IMODE(info.st_mode) != 0o600))):
                raise ContractError("challenge transition lock is unsafe")
            if os.name == "posix":
                import fcntl
                fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            if os.name == "posix":
                import fcntl
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)
            local.release()

    def consume(self, value):
        _validate_challenge(value)
        with self._transition_lock(value["nonce"]):
            source = self.challenge(value)
            target = self._consumed_path(value["nonce"])
            target.parent.mkdir(parents=True, exist_ok=True)
            tombstone = {"schema": "computerbench.consumed-challenge.v1",
                         "challenge_sha256": hashlib.sha256(
                             _canonical(value)).hexdigest()}
            try:
                descriptor = os.open(target, os.O_WRONLY | os.O_CREAT |
                                     os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(_canonical(tombstone) + b"\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                _fsync_directory(target.parent)
            except OSError as error:
                raise ContractError(
                    "challenge was concurrently consumed or replayed") from error
            try:
                os.unlink(source)
                _fsync_directory(source.parent)
            except OSError as error:
                # The durable tombstone already dominates any issued copy.
                raise ContractError("challenge consumption cleanup failed") from error


def _production_backend(candidate_archive=None):
    _validate_launch_contract()
    _validate_installation_root()
    return _OwnerBackend(_OWNER_STORE, candidate_archive,
                         state_root=_VERIFIER_STATE,
                         install_root=_FIXED_INSTALL_ROOT)


def _test_backend(root, state_root, candidate_archive, public_profile,
                  install_root):
    """Explicit internal unit seam; deliberately absent from CLI arguments."""
    return _OwnerBackend(root, candidate_archive, state_root=state_root,
                         install_root=install_root, internal=True,
                         test_profile=public_profile)


def _sealed(artifact_path, seal_path, profile, backend, kind):
    raw = _secure_external_bytes(artifact_path, kind, backend.install_root,
                                 backend.internal)
    seal = _json(_secure_external_bytes(
        seal_path, kind + " seal", backend.install_root, backend.internal),
        kind + " seal")
    _exact(seal, ("schema", "artifact_kind", "key_id", "principal",
                  "sha256", "signature_hex"), kind + " seal")
    role = "pack_issuer" if kind == "acceptance_pack" else "results_evaluator"
    authority = profile[role]
    if seal["schema"] != "computerbench.rsa-seal.v1" \
            or seal["artifact_kind"] != kind \
            or seal["key_id"] != authority["key_id"] \
            or seal["principal"] != authority["principal"]:
        raise ContractError(kind + " seal identity is invalid")
    _digest(seal["sha256"], kind + " seal digest")
    if not hmac.compare_digest(seal["sha256"], hashlib.sha256(raw).hexdigest()):
        raise ContractError(kind + " content seal differs")
    modulus, exponent = _validate_public_key(authority, role)
    body = {name: seal[name] for name in seal if name != "signature_hex"}
    if not _rsa_verify(_canonical(body), seal["signature_hex"], modulus,
                       exponent):
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


def assess_acceptance(pack_path=None, seal_path=None, trust_id=None,
                      results_path=None, results_seal_path=None, _backend=None):
    """Assess externally supplied bytes; never infer provenance from prose."""
    backend = _backend or _production_backend()
    report = {"contract_valid": False, "provenance_bound": False,
              "results_valid": False, "acceptance_complete": False,
              "release_ready": False, "missing_evidence": [],
              "capability_matrix": _matrix(),
              "scope": "external acceptance contract; not release qualification"}
    try:
        profile = backend.profile(trust_id)
    except ContractError:
        report["missing_evidence"].append("independent_owner_trust")
        return report
    try:
        value, digest = _sealed(pack_path, seal_path, profile, backend,
                                "acceptance_pack")
    except ContractError as error:
        message = str(error)
        report["missing_evidence"].append(
            "pack_inside_repository" if "inside the repository" in message
            and "acceptance_pack is" in message else "pack_content_seal")
        return report
    report["provenance_bound"] = True
    try:
        pack = validate_pack(value)
        backend.challenge(pack["challenge"])
        trust_digest = backend._profile_digests[trust_id]
        if (pack["challenge"]["trust_id"] != trust_id
                or pack["challenge"]["trust_metadata_sha256"] != trust_digest
                or pack["candidate"] != backend.candidate(trust_digest)):
            raise ContractError("pack is not bound to selected trust or candidate")
    except ContractError:
        report["missing_evidence"].append("valid_pack_contract")
        return report
    report["contract_valid"] = True
    report["capability_matrix"] = _matrix(pack)
    try:
        results_value, _ = _sealed(results_path, results_seal_path, profile,
                                   backend, "acceptance_results")
        results = validate_results(results_value, pack, digest)
    except ContractError:
        report["missing_evidence"].append("sealed_external_results")
        return report
    report["results_valid"] = True
    try:
        backend.consume(pack["challenge"])
    except ContractError:
        report["results_valid"] = False
        report["missing_evidence"].append("fresh_single_use_challenge")
        return report
    report["capability_matrix"] = _matrix(pack, results)
    report["acceptance_complete"] = (not backend.internal and all(
        row["accepted"] for row in report["capability_matrix"].values()))
    if backend.internal:
        report["missing_evidence"].append("independent_owner_authority")
    # Independent acceptance is one gate, not release. Live model/provider,
    # native platform matrix, soak, rollback and review remain separate.
    report["release_ready"] = False
    return report


def _build_parser():
    parser = argparse.ArgumentParser(
        description="Externally installed ComputerBench acceptance verifier")
    commands = parser.add_subparsers(dest="command", required=True)
    challenge = commands.add_parser("issue-challenge")
    challenge.add_argument("--trust-id", required=True)
    challenge.add_argument("--candidate-archive", required=True)
    challenge.add_argument("--ttl", type=int, default=300)
    acceptance = commands.add_parser("acceptance")
    acceptance.add_argument("--trust-id", required=True)
    acceptance.add_argument("--candidate-archive", required=True)
    acceptance.add_argument("--pack", required=True)
    acceptance.add_argument("--pack-seal", required=True)
    acceptance.add_argument("--results", required=True)
    acceptance.add_argument("--results-seal", required=True)
    return parser


def main(argv=None):
    _validate_launch_contract()
    parser = _build_parser()
    args = parser.parse_args(argv)
    backend = _production_backend(args.candidate_archive)
    if args.command == "issue-challenge":
        print(json.dumps(backend.issue_challenge(args.trust_id, args.ttl),
                         indent=2, sort_keys=True))
        return 0
    report = assess_acceptance(args.pack, args.pack_seal, args.trust_id,
                               args.results, args.results_seal,
                               _backend=backend)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["acceptance_complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
