"""Bounded browser authority, host-owned Playwright clicks, and artifact checks.

Dispatch is not workflow verification. Network containment is owner configured.
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

# These objects live on the Playwright HOST Page, never in the page JS realm.
# MCP 0.0.79 creates a new VM per run-code call but passes the same Page object.
_HOST_OBSERVE = """async page => {
  const observe = %s;
  let host=page.__boundedComputer;
  if(!host){
    host={tab:%s,frame:%s,document:1,main:page.mainFrame(),handles:[]};
    page.__boundedComputer=host;
    const clear=()=>{const old=host.handles;host.handles=[];
      for(const h of old) h.dispose().catch(()=>{});};
    page.on('framenavigated',f=>{if(f===page.mainFrame()){host.document++;clear();}});
    page.on('close',clear);
  }
  const old=host.handles;host.handles=[];
  await Promise.all(old.map(h=>h.dispose().catch(()=>{})));
  const generation=host.document;
  const handles=await page.locator('a[data-invoice]').elementHandles();
  if(handles.length>1000){await Promise.all(handles.map(h=>h.dispose()));throw Error('too many targets');}
  host.handles=handles;
  const state=await page.evaluate(observe);
  let viewport=null,scale=null;
  try {viewport=page.viewportSize();} catch(e){}
  try {scale=await page.evaluate(()=>window.devicePixelRatio);} catch(e){}
  state.view_context={viewport,viewport_source:viewport?'playwright_host':'unavailable',
    device_scale:Number.isFinite(scale)&&scale>0?scale:null,
    device_scale_source:Number.isFinite(scale)&&scale>0?'page_untrusted':'unavailable'};
  if(generation!==host.document || host.main!==page.mainFrame())throw Error('document changed during observation');
  state.binding={tab:host.tab,frame:host.frame,document:host.document};
  return state;
}"""

_HOST_CLICK = """async page => {
  const p=%s, deadline=%d, host=page.__boundedComputer;
  const remaining=()=>Math.max(1,deadline-Date.now());
  const bindingOK=()=>host && !page.isClosed() && host.main===page.mainFrame() &&
    host.tab===p.binding.tab && host.frame===p.binding.frame && host.document===p.binding.document;
  if(!bindingOK())return {refused:'tab/frame/document changed'};
  const locator=page.locator('a[data-invoice="'+p.target.id+'"]');
  let original;
  for(const h of host.handles){
    try {if(await h.getAttribute('data-invoice')===p.target.id){original=h;break;}} catch(e){}
  }
  if(!original)return {refused:'observed element unavailable'};
  const check=async()=>{
    if(Date.now()>=deadline)return 'deadline';
    if(!bindingOK())return 'tab/frame/document changed';
    if(page.url()!==p.page_url)return 'page changed';
    if(p.view_context){
      const current=page.viewportSize(),expected=p.view_context.viewport;
      if((current===null)!==(expected===null)||current&&
        (current.width!==expected.width||current.height!==expected.height))return 'viewport changed';
    }
    if(await locator.count()!==1)return 'target absent or ambiguous';
    if(!await locator.evaluate((a,old)=>a===old,original))return 'element replaced';
    return await locator.evaluate((a,p)=>{
      if(document.querySelector('dialog[open],input[type=password]'))return 'blocked state';
      const r=a.getBoundingClientRect(),s=getComputedStyle(a);
      if(s.visibility!=='visible'||s.display==='none'||r.width<=0||r.height<=0)return 'not visible';
      if(a.closest('[disabled],[aria-disabled="true"],[inert]'))return 'not enabled';
      const hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);
      if(!hit || !(a===hit || a.contains(hit)))return 'not hit-testable';
      if(!a.isConnected||a.ownerDocument!==document)return 'detached';
      if(a.href!==p.target.href||a.textContent!==p.target.text||
        r.x!==p.target.box.x||r.y!==p.target.box.y||r.width!==p.target.box.width||r.height!==p.target.box.height)return 'target changed';
      if(location.href!==p.page_url||new URL(a.href).origin!==p.allowed_origin)return 'origin changed';
      return null;
    },p);
  };
  try {
    let reason=await check();if(reason)return {refused:reason};
    await locator.click({trial:true,force:false,timeout:remaining()});
    reason=await check();if(reason)return {refused:reason};
  } catch(e){return {refused:'preflight actionability failed'};}
  // Trial and dispatch are separate operations: this is NOT an atomic check+act.
  // Any exception from this point can follow input dispatch and is UNKNOWN.
  await locator.click({force:false,timeout:remaining()});
  return {status:'ACTION_DISPATCHED',precondition_sha256:p.state_sha256,
    clicked:true,destination:p.target.href};
}"""


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


def _locator_opt_in(spec):
    if (spec.get("computer_locator_tool") != "browser_run_code_unsafe"
            or not isinstance(spec.get("trust_identity"), str) or not spec["trust_identity"]):
        raise Refused("owner must review and pin the host locator tool")


def playwright_observe(server, root, trace=None, task_context=None, artifacts=None):
    """Fixed read-only observation for the bounded invoice adapter."""
    import mcp
    spec = getattr(server, "spec", {}) or {}
    if spec.get("atomic_browser_adapter") is not True:
        raise Refused("MCP server is not trusted for the atomic browser adapter")
    _locator_opt_in(spec)
    try:
        mcp.validate_identity(spec)
    except ValueError as error:
        raise Refused(str(error)) from error
    started = time.monotonic()
    code = _HOST_OBSERVE % (PLAYWRIGHT_OBSERVE, json.dumps(secrets.token_hex(16)),
                            json.dumps(secrets.token_hex(16)))
    attribution = {"task_context": task_context} if task_context is not None else {}
    result, how = mcp.computer_guarded_call(server, "browser_run_code_unsafe",
        {"code": code}, root=root, fresh=True, **attribution)
    if artifacts is not None:
        mcp.render_result(result, root=root, artifacts=artifacts)
    if trace is not None:
        trace.append({"tool":"browser_run_code_unsafe", "how":how,
                      "error":bool((result or {}).get("isError")),
                      "seconds":round(time.monotonic()-started,3),
                      "arguments":{"code":code}, "result":result})
    if how != "live" or (result or {}).get("isError"):
        raise Unresolved("browser observation failed")
    parsed = _playwright_json(result)
    if trace is not None:
        trace[-1]["observation"] = parsed
    if task_context is None:
        parsed.pop('view_context',None)  # Legacy BrowserAuthority keeps its exact state schema.
    return parsed


def playwright_atomic_click(server, root, preconditions, trace=None,
                            task_context=None, before_send=None, artifacts=None):
    """Bounded locator click; legacy name does not imply atomic check-and-act.

    The owner must opt this adapter into the MCP server's trusted identity.
    Network containment remains the server configuration's responsibility.
    """
    import mcp
    spec = getattr(server, "spec", {}) or {}
    if spec.get("atomic_browser_adapter") is not True:
        raise Refused("MCP server is not trusted for the atomic browser adapter")
    _locator_opt_in(spec)
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
    target = p.get("target", {})
    if not isinstance(target, dict) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", str(target.get("id", ""))):
        raise Refused("invalid exact locator identity")
    if not isinstance(p.get("binding"), dict):
        raise Refused("missing host browser identity")
    deadline_epoch = int(time.time() * 1000 + remaining * 1000)
    code = _HOST_CLICK % (json.dumps(p, separators=(",", ":"), allow_nan=False), deadline_epoch)
    started = time.monotonic()
    attribution = {"task_context": task_context} if task_context is not None else {}
    if before_send is not None:
        attribution["before_send"] = before_send
    result, how = mcp.computer_guarded_call(server, "browser_run_code_unsafe",
                                            {"code": code}, root=root, fresh=True, **attribution)
    if trace is not None:
        trace.append({"tool": "browser_run_code_unsafe", "how": how,
                      "error": bool((result or {}).get("isError")),
                      "seconds": round(time.monotonic() - started, 3),
                      "arguments": {"code": code}, "result": result})
    if how in ("denied", "approval_required"):
        raise Refused("atomic browser adapter refused before action: " + how)
    if how != "live" or (result or {}).get("isError"):
        raise Unresolved("atomic browser action result is unknown; do not retry")
    parsed = _playwright_json(result)
    if trace is not None:
        trace[-1]["atomic_result"] = parsed
    if parsed.get("refused"):
        raise Refused("atomic precondition refused: " + str(parsed["refused"]))
    if parsed.get("status") != "ACTION_DISPATCHED" or parsed.get("clicked") is not True:
        raise Unresolved("browser dispatch acknowledgment missing")
    try:
        parsed["post_observation"] = (playwright_observe(server, root, trace, task_context=task_context,artifacts=artifacts)
                                      if task_context is not None else playwright_observe(server, root, trace))
    except Exception as error:
        raise Unresolved("click dispatched but post-observation failed; do not retry") from error
    return parsed


class BrowserAuthority:
    """Seal one-session observations and authorize one-use bounded adapter calls.

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
        """Validate observable data; blocking flags and empty targets are evidence."""
        if not isinstance(state, dict) or set(state) != {"url", "title", "dialog", "expired", "links", "binding"}:
            raise Refused("invalid browser observation shape")
        binding = state["binding"]
        if (not isinstance(binding, dict) or set(binding) != {"tab", "frame", "document"}
                or any(not isinstance(binding[k], str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", binding[k]) for k in ("tab", "frame"))
                or type(binding["document"]) is not int or binding["document"] < 1):
            raise Refused("invalid host browser identity")
        if not isinstance(state["title"], str) or len(state["title"]) > 500:
            raise Refused("invalid browser title")
        if type(state["dialog"]) is not bool or type(state["expired"]) is not bool:
            raise Refused("invalid browser blocking state")
        if _origin(state["url"]) != self.allowed_origin:
            raise Refused("page is outside the allowed browser origin")
        links = state["links"]
        if not isinstance(links, list) or not 0 <= len(links) <= MAX_INVOICES:
            raise Refused("invalid bounded target collection")
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
            if state["dialog"] or state["expired"]:
                raise Refused("browser action blocked by dialog or authentication state")
            if receipt["mac"] in self._consumed:
                raise Refused("browser action authorization was already consumed")
            targets = [x for x in state["links"] if x["id"] == target_id]
            if len(targets) != 1:
                raise Refused("browser action target is absent or ambiguous")
            preconditions = {"session": self.session_id,
                "revision": receipt["revision"], "state_sha256": digest,
                "page_url": state["url"], "target": targets[0],
                "binding": state["binding"],
                "allowed_origin": self.allowed_origin, "deadline": float(deadline),
                "valid_for_seconds": float(deadline) - float(self.clock())}
            self._consumed.add(receipt["mac"])
            try:
                result = atomic_adapter(preconditions)
            except Refused:
                # The trusted adapter contract permits this only when its
                # preflight predicates failed before input dispatch.
                raise
            except Exception as error:
                raise Unresolved("browser action outcome is unknown; do not retry") from error
            if (not isinstance(result, dict) or result.get("clicked") is not True
                    or result.get("status") != "ACTION_DISPATCHED"
                    or result.get("precondition_sha256") != digest):
                raise Unresolved("atomic adapter receipt does not prove the requested action")
            try:
                destination = result["destination"]
                if _origin(destination) != self.allowed_origin:
                    raise ValueError
                post = self._state(result["post_observation"])
            except (KeyError, Refused, ValueError) as error:
                raise Unresolved("browser dispatch destination or post-observation is invalid") from error
            return {"status":"ACTION_DISPATCHED", "session":self.session_id,
                    "revision":receipt["revision"], "target_id":target_id,
                    "destination":destination, "state_sha256":digest,
                    "browser_authority_verified":True, "workflow_verified":False,
                    "post_observation":post, "release_ready":False}


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
