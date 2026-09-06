"""Independent artifact checks for the bounded browser phase; not browser authority.

The trusted harness supplies the expected manifest and its pinned digest. Never
accept that pair from the worker being evaluated. This module grants no effects,
does not drive a browser, and cannot establish session or observation freshness.
See docs/DESIGN-bounded-computer-use.md.
"""
import hashlib
import json
import os
import re
import stat

import fileauth

MAX_INVOICES = 1000
MAX_BYTES = 10_000_000


class Refused(ValueError):
    pass


def digest_manifest(manifest):
    return hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode("utf-8")).hexdigest()


def _manifest(manifest, expected_digest):
    if digest_manifest(manifest) != expected_digest:
        raise Refused("expected manifest binding changed")
    if not isinstance(manifest, dict) or set(manifest) != {"month", "invoices"}:
        raise Refused("invalid manifest shape")
    if not isinstance(manifest["month"], str) or not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", manifest["month"]):
        raise Refused("invalid invoice month")
    rows = manifest["invoices"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_INVOICES:
        raise Refused("invalid expected invoice count")
    ids, paths = set(), set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"id", "file", "sha256", "bytes"}:
            raise Refused("invalid invoice record")
        invoice_id, name = row["id"], row["file"]
        if not isinstance(invoice_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", invoice_id):
            raise Refused("invalid invoice identity")
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}\.json", name):
            raise Refused("invoice paths must be simple JSON filenames")
        if invoice_id in ids or name.casefold() in paths:
            raise Refused("duplicate invoice identity or path")
        ids.add(invoice_id)
        paths.add(name.casefold())
        if not isinstance(row["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"]):
            raise Refused("invalid invoice digest")
        if type(row["bytes"]) is not int or not 1 <= row["bytes"] <= MAX_BYTES:
            raise Refused("invalid invoice byte count")
    return rows


def _no_links(path):
    st = os.lstat(path)
    if stat.S_ISLNK(st.st_mode) or getattr(st, "st_file_attributes", 0) & 0x400:
        raise Refused("linked or reparse-point artifact refused")
    return st


def verify_invoices(root, output_dir, manifest, expected_digest):
    """Check quiescent output after the browser is stopped; never a live-write seal.

    Only the synthetic JSON invoice envelope is supported in this phase. Digest
    equality certifies bytes, not the authenticity of a real-world invoice.
    Callers must hold independent write exclusion during and after this check.
    """
    rows = _manifest(manifest, expected_digest)
    # Check lexical components as well as File Authority's resolved containment.
    if not isinstance(output_dir, str) or not output_dir or os.path.isabs(output_dir):
        raise Refused("output must be a relative confined directory")
    parts = output_dir.replace("\\", "/").split("/")
    if any(p in ("", ".", "..") or ":" in p for p in parts):
        raise Refused("invalid output path")
    base = os.path.abspath(root)
    _no_links(base)
    for part in parts:
        base = os.path.join(base, part)
        if not stat.S_ISDIR(_no_links(base).st_mode):
            raise Refused("output ancestor is not a directory")
    fileauth.resolve(root, output_dir, "read", actor="agent")
    names = set(os.listdir(base))
    if names != {r["file"] for r in rows}:
        raise Refused("artifact set differs: missing, duplicate, partial or extra file")
    verified = []
    for row in rows:
        rel = os.path.join(output_dir, row["file"])
        path = fileauth.resolve(root, rel, "read", actor="agent")
        before = _no_links(os.path.join(base, row["file"]))
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise Refused("artifact is not an unlinked regular file")
        if before.st_size != row["bytes"]:
            raise Refused("artifact byte count differs")
        with open(path, "rb") as stream:
            opened = os.fstat(stream.fileno())
            if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                raise Refused("artifact replaced before read")
            data = stream.read(row["bytes"] + 1)
            after = os.fstat(stream.fileno())
        if len(data) != row["bytes"] or hashlib.sha256(data).hexdigest() != row["sha256"]:
            raise Refused("artifact content digest differs")
        current = _no_links(os.path.join(base, row["file"]))
        signature = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_nlink)
        # File timestamps cannot establish unchanged content. Identity, size
        # and link count detect replacement; the trusted digest establishes
        # the bytes read. Independent write exclusion is still mandatory.
        if (signature(before) != signature(current) or signature(opened) != signature(after)
                or signature(before) != signature(opened)):
            raise Refused("artifact changed during verification")
        try:
            content = json.loads(data.decode("utf-8"))
        except (ValueError, UnicodeError) as error:
            raise Refused("artifact is not a JSON invoice") from error
        if not isinstance(content, dict) or content.get("id") != row["id"] or content.get("month") != manifest["month"]:
            raise Refused("invoice identity or month differs")
        verified.append({"id": row["id"], "file": row["file"], "sha256": row["sha256"], "bytes": len(data)})
    if set(os.listdir(base)) != names:
        raise Refused("artifact set changed during verification")
    return {"status": "VERIFIED_ARTIFACTS", "manifest_sha256": expected_digest,
            "invoices": verified, "browser_authority_verified": False,
            "release_ready": False, "requires_quiescent_output": True}
