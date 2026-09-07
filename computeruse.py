"""Independent artifact checks for the bounded browser phase; not browser authority.

The trusted harness supplies the expected manifest and its pinned digest. Never
accept that pair from the worker being evaluated. This module grants no effects,
does not drive a browser, and cannot establish session or observation freshness.
See docs/DESIGN-bounded-computer-use.md.
"""
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import stat
import threading
import time
from urllib.parse import urlsplit

import fileauth

MAX_INVOICES = 1000
MAX_BYTES = 10_000_000
PLAYWRIGHT_OBSERVE = """() => ({url:location.href, title:document.title,
  dialog:!!document.querySelector('dialog[open]'), expired:!!document.querySelector('input[type=password]'),
  links:Array.from(document.querySelectorAll('a[data-invoice]')).map(a=>{const r=a.getBoundingClientRect();return {
    id:a.dataset.invoice,href:a.href,text:a.textContent,
    box:{x:r.x,y:r.y,width:r.width,height:r.height}}})})"""


class Refused(ValueError):
    pass


class Unresolved(RuntimeError):
    """An action may have happened, so automatic retry is unsafe."""


def _canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _origin(value, configured=False):
    if not isinstance(value, str) or len(value) > 2048:
        raise Refused("invalid browser URL")
    p = urlsplit(value)
    if p.scheme not in ("http", "https") or not p.hostname or p.username or p.password:
        raise Refused("browser URL must be an uncredentialed HTTP origin")
    if configured and (p.path not in ("", "/") or p.query or p.fragment):
        raise Refused("allowed browser origin cannot include a path, query or fragment")
    try:
        port = p.port
    except ValueError as error:
        raise Refused("invalid browser URL port") from error
    host = p.hostname.lower()
    if ":" in host:
        host = "[" + host + "]"
    default = (p.scheme == "http" and port in (None, 80)) or (p.scheme == "https" and port in (None, 443))
    return f"{p.scheme}://{host}" + ("" if default else f":{port}")


def _playwright_json(result):
    text = "\n".join(c.get("text", "") for c in (result or {}).get("content", [])
                     if isinstance(c, dict))
    match = re.search(r"### Result\s*\n(.*?)(?:\n### |\Z)", text, re.S)
    if not match:
        raise Unresolved("atomic browser adapter returned no structured result")
    raw = match.group(1).strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```\w*\s*|\s*```$", "", raw)
    try:
        parsed = json.loads(raw)
    except ValueError as error:
        raise Unresolved("atomic browser adapter returned malformed JSON") from error
    if not isinstance(parsed, dict):
        raise Unresolved("atomic browser adapter returned a non-object result")
    return parsed


def playwright_observe(server, root, trace=None):
    """Fixed read-only observation for the bounded invoice adapter."""
    import mcp
    spec = getattr(server, "spec", {}) or {}
    if spec.get("atomic_browser_adapter") is not True:
        raise Refused("MCP server is not trusted for the atomic browser adapter")
    try:
        mcp.validate_identity(spec)
    except ValueError as error:
        raise Refused(str(error)) from error
    started = time.monotonic()
    result, how = mcp.computer_guarded_call(server, "browser_evaluate",
        {"function": PLAYWRIGHT_OBSERVE}, root=root, fresh=True)
    if trace is not None:
        trace.append({"tool":"browser_evaluate", "how":how,
                      "error":bool((result or {}).get("isError")),
                      "seconds":round(time.monotonic()-started,3),
                      "arguments":{"function":PLAYWRIGHT_OBSERVE}, "result":result})
    if how != "live" or (result or {}).get("isError"):
        raise Unresolved("browser observation failed")
    parsed = _playwright_json(result)
    if trace is not None:
        trace[-1]["observation"] = parsed
    return parsed


def playwright_atomic_click(server, root, preconditions, trace=None):
    """Enforce one invoice target and click in one Playwright JavaScript turn.

    The owner must opt this adapter into the MCP server's trusted identity.
    Network containment remains the server configuration's responsibility.
    """
    import mcp
    spec = getattr(server, "spec", {}) or {}
    if spec.get("atomic_browser_adapter") is not True:
        raise Refused("MCP server is not trusted for the atomic browser adapter")
    try:
        mcp.validate_identity(spec)
    except ValueError as error:
        raise Refused(str(error)) from error
    if not isinstance(preconditions, dict) or not isinstance(preconditions.get("valid_for_seconds"), (int, float)):
        raise Refused("invalid atomic browser preconditions")
    p = dict(preconditions)
    remaining = p.pop("valid_for_seconds")
    if isinstance(remaining, bool) or not 0 < remaining <= 60:
        raise Refused("atomic browser deadline already expired")
    deadline_epoch = int(time.time() * 1000 + remaining * 1000)
    function = """() => {const p=%s, deadline=%d;
      if(Date.now()>deadline)return {refused:'deadline'};
      if(location.href!==p.page_url)return {refused:'page changed'};
      if(document.querySelector('dialog[open],input[type=password]'))return {refused:'blocked state'};
      const matches=Array.from(document.querySelectorAll('a[data-invoice]')).filter(a=>a.dataset.invoice===p.target.id);
      if(matches.length!==1)return {refused:'target absent or ambiguous'};
      const a=matches[0],r=a.getBoundingClientRect();
      const current={id:a.dataset.invoice,href:a.href,text:a.textContent,
        box:{x:r.x,y:r.y,width:r.width,height:r.height}};
      const same=current.id===p.target.id&&current.href===p.target.href&&current.text===p.target.text&&
        current.box.x===p.target.box.x&&current.box.y===p.target.box.y&&
        current.box.width===p.target.box.width&&current.box.height===p.target.box.height;
      if(!same)return {refused:'target changed',current,expected:p.target};
      if(new URL(a.href).origin!==p.allowed_origin)return {refused:'destination changed'};
      const destination=a.href;a.click();
      return {precondition_sha256:p.state_sha256,clicked:true,destination};} """ % (
          json.dumps(p, separators=(",", ":")), deadline_epoch)
    started = time.monotonic()
    result, how = mcp.computer_guarded_call(server, "browser_evaluate",
                                            {"function": function}, root=root, fresh=True)
    if trace is not None:
        trace.append({"tool": "browser_evaluate", "how": how,
                      "error": bool((result or {}).get("isError")),
                      "seconds": round(time.monotonic() - started, 3),
                      "arguments": {"function": function}, "result": result})
    if how in ("denied", "approval_required"):
        raise Refused("atomic browser adapter refused before action: " + how)
    if how != "live" or (result or {}).get("isError"):
        raise Unresolved("atomic browser action result is unknown; do not retry")
    parsed = _playwright_json(result)
    if trace is not None:
        trace[-1]["atomic_result"] = parsed
    if parsed.get("refused"):
        raise Refused("atomic precondition refused: " + str(parsed["refused"]))
    return parsed


class BrowserAuthority:
    """Seal one-session observations and authorize one-use atomic adapter calls.

    This is an authority contract, not a browser implementation. The supplied
    adapter must enforce every precondition and return its receipt from the same
    serialized browser context. An exception is unresolved and consumes the
    authorization, because the click may already have happened.
    """

    def __init__(self, allowed_origin, session_id=None, clock=None, max_age=5.0):
        self.allowed_origin = _origin(allowed_origin, configured=True)
        self.session_id = session_id or secrets.token_hex(16)
        if not isinstance(self.session_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", self.session_id):
            raise Refused("invalid browser session identity")
        if isinstance(max_age, bool) or not isinstance(max_age, (int, float)) or not 0 < max_age <= 60:
            raise Refused("invalid observation lifetime")
        self.max_age = float(max_age)
        self.clock = clock or time.monotonic
        self._key = secrets.token_bytes(32)
        self._revision = 0
        self._consumed = set()
        self._lock = threading.RLock()

    def _state(self, state):
        if not isinstance(state, dict) or set(state) != {"url", "title", "dialog", "expired", "links"}:
            raise Refused("invalid browser observation shape")
        if not isinstance(state["title"], str) or len(state["title"]) > 500:
            raise Refused("invalid browser title")
        if type(state["dialog"]) is not bool or type(state["expired"]) is not bool:
            raise Refused("invalid browser blocking state")
        if state["dialog"] or state["expired"]:
            raise Refused("browser action blocked by dialog or authentication state")
        if _origin(state["url"]) != self.allowed_origin:
            raise Refused("page is outside the allowed browser origin")
        links = state["links"]
        if not isinstance(links, list) or not 1 <= len(links) <= MAX_INVOICES:
            raise Refused("browser observation has no bounded targets")
        ids = set()
        for link in links:
            if not isinstance(link, dict) or set(link) != {"id", "href", "text", "box"}:
                raise Refused("invalid browser target shape")
            identity = link["id"]
            if not isinstance(identity, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", identity):
                raise Refused("invalid browser target identity")
            if identity in ids:
                raise Refused("ambiguous browser target identity")
            ids.add(identity)
            if not isinstance(link["text"], str) or not link["text"] or len(link["text"]) > 500:
                raise Refused("invalid browser target text")
            box = link["box"]
            if (not isinstance(box, dict) or set(box) != {"x", "y", "width", "height"}
                    or any(isinstance(v, bool) or not isinstance(v, (int, float))
                           or not math.isfinite(v) or abs(v) > 10_000_000 for v in box.values())
                    or box["width"] <= 0 or box["height"] <= 0):
                raise Refused("invalid browser target geometry")
            if _origin(link["href"]) != self.allowed_origin:
                raise Refused("browser target leaves the allowed origin")
        return json.loads(_canonical(state).decode("utf-8"))

    def _mac(self, body):
        return hmac.new(self._key, _canonical(body), hashlib.sha256).hexdigest()

    def observe(self, state):
        with self._lock:
            clean = self._state(state)
            self._revision += 1
            body = {"session": self.session_id, "revision": self._revision,
                    "observed_at": float(self.clock()),
                    "state_sha256": hashlib.sha256(_canonical(clean)).hexdigest(),
                    "state": clean}
            return dict(body, mac=self._mac(body))

    def _verified(self, receipt, deadline):
        if not isinstance(receipt, dict) or set(receipt) != {
                "session", "revision", "observed_at", "state_sha256", "state", "mac"}:
            raise Refused("invalid browser receipt shape")
        body = {k: receipt[k] for k in receipt if k != "mac"}
        if not isinstance(receipt["mac"], str) or not hmac.compare_digest(self._mac(body), receipt["mac"]):
            raise Refused("browser receipt signature differs")
        if receipt["session"] != self.session_id or receipt["revision"] != self._revision:
            raise Refused("browser receipt is stale or belongs to another session")
        now = float(self.clock())
        observed = receipt["observed_at"]
        if isinstance(deadline, bool) or not isinstance(deadline, (int, float)):
            raise Refused("invalid browser action deadline")
        if not isinstance(observed, (int, float)) or now < observed or now - observed > self.max_age:
            raise Refused("browser observation is stale")
        if deadline < now or deadline > observed + self.max_age:
            raise Refused("browser action deadline is expired or exceeds observation lifetime")
        clean = self._state(receipt["state"])
        digest = hashlib.sha256(_canonical(clean)).hexdigest()
        if digest != receipt["state_sha256"]:
            raise Refused("browser observation digest differs")
        return clean, digest

    def execute_click(self, receipt, target_id, deadline, atomic_adapter):
        """Execute once; adapter failure or malformed readback is unresolved."""
        with self._lock:
            state, digest = self._verified(receipt, deadline)
            if receipt["mac"] in self._consumed:
                raise Refused("browser action authorization was already consumed")
            targets = [x for x in state["links"] if x["id"] == target_id]
            if len(targets) != 1:
                raise Refused("browser action target is absent or ambiguous")
            preconditions = {"session": self.session_id,
                "revision": receipt["revision"], "state_sha256": digest,
                "page_url": state["url"], "target": targets[0],
                "allowed_origin": self.allowed_origin, "deadline": float(deadline),
                "valid_for_seconds": float(deadline) - float(self.clock())}
            self._consumed.add(receipt["mac"])
            try:
                result = atomic_adapter(preconditions)
            except Refused:
                # The trusted adapter contract permits this only when its
                # atomic preconditions failed before the action.
                raise
            except Exception as error:
                raise Unresolved("browser action outcome is unknown; do not retry") from error
            if (not isinstance(result, dict) or result.get("clicked") is not True
                    or result.get("precondition_sha256") != digest):
                raise Unresolved("atomic adapter receipt does not prove the requested action")
            try:
                destination = result["destination"]
                if _origin(destination) != self.allowed_origin:
                    raise ValueError
            except (KeyError, Refused, ValueError) as error:
                raise Unresolved("browser action destination is not independently allowed") from error
            return {"status":"VERIFIED_BROWSER_ACTION", "session":self.session_id,
                    "revision":receipt["revision"], "target_id":target_id,
                    "destination":destination, "state_sha256":digest,
                    "browser_authority_verified":True, "release_ready":False}


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
