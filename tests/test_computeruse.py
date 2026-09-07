"""Independent synthetic invoice checks, not executed browser trials."""
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import computeruse as C
import mcp


class Artifacts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="computer-artifacts-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.out = self.root / "output"
        self.out.mkdir()
        self.manifest = {"month": "2026-08", "invoices": []}
        for number in range(3):
            identity = f"INV-{number}"
            data = json.dumps({"id": identity, "month": "2026-08", "total_cents": 1200 + number}).encode()
            name = identity + ".json"
            (self.out / name).write_bytes(data)
            self.manifest["invoices"].append({"id": identity, "file": name,
                "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
        self.pin = C.digest_manifest(self.manifest)

    def verify(self, manifest=None, pin=None, output="output"):
        return C.verify_invoices(str(self.root), output, manifest or self.manifest, pin or self.pin)

    def test_exact_artifacts_not_browser_success(self):
        result = self.verify()
        self.assertEqual(result["status"], "VERIFIED_ARTIFACTS")
        self.assertEqual(len(result["invoices"]), 3)
        self.assertFalse(result["browser_authority_verified"])
        self.assertFalse(result["release_ready"])
        print("[exact-artifacts] three exact synthetic invoices verify without certifying browser authority or release")

    def test_missing_extra_partial_and_duplicate(self):
        first = self.out / "INV-0.json"
        saved = first.read_bytes()
        for mode in ("missing", "extra", "partial", "duplicate"):
            with self.subTest(mode=mode):
                if mode == "missing":
                    first.unlink()
                else:
                    (self.out / (mode + ".json")).write_bytes(saved)
                with self.assertRaises(C.Refused):
                    self.verify()
                first.write_bytes(saved)
                if mode != "missing":
                    (self.out / (mode + ".json")).unlink()
        print("[exact-set] missing, extra, partial and duplicate artifacts refuse")

    def test_corrupt_truncated_and_growing_content(self):
        path = self.out / "INV-0.json"
        original = path.read_bytes()
        for data in (original.replace(b"1200", b"9999"), b"x" * len(original), original[:-1], original + b"x"):
            path.write_bytes(data)
            with self.assertRaises(C.Refused):
                self.verify()
        print("[content] same-length corruption, truncation and excess bytes refuse")

    def test_manifest_binding(self):
        altered = copy.deepcopy(self.manifest)
        # Keep all other checks satisfiable: only the pinned ordering changes.
        altered["invoices"].reverse()
        with self.assertRaises(C.Refused):
            self.verify(altered)
        print("[manifest-binding] changed expectations cannot reuse the trusted manifest pin")

    def test_schema_and_duplicate_ids(self):
        alterations = [lambda m: m["invoices"].append(m["invoices"][0]),
                       lambda m: m["invoices"][0].update(file="../outside.json"),
                       lambda m: m["invoices"][0].update(bytes=True),
                       lambda m: m["invoices"][0].update(bytes=C.MAX_BYTES + 1),
                       lambda m: m.update(month="2026-13"),
                       lambda m: m["invoices"][0].update(sha256="bad")]
        for change in alterations:
            altered = copy.deepcopy(self.manifest)
            change(altered)
            with self.assertRaises(C.Refused):
                self.verify(altered, C.digest_manifest(altered))
        print("[manifest-schema] duplicate IDs, traversal, boolean sizes, oversize, invalid month and digest refuse")

    def test_wrong_identity_despite_matching_digest(self):
        for key, value in (("id", "other"), ("month", "2026-07")):
            data = json.dumps({"id": "INV-0", "month": "2026-08", key: value}).encode()
            (self.out / "INV-0.json").write_bytes(data)
            altered = copy.deepcopy(self.manifest)
            altered["invoices"][0].update(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
            with self.assertRaises(C.Refused):
                self.verify(altered, C.digest_manifest(altered))
        print("[invoice-identity] matching bytes alone cannot substitute another invoice identity or month")

    def test_path_refusals(self):
        for path in ("../output", str(self.out), "output/../output", "output//", "C:output"):
            with self.assertRaises(C.Refused):
                self.verify(output=path)
        print("[containment] absolute, parent, empty-component and drive-relative output paths refuse")

    def test_hardlink_refused(self):
        path = self.out / "INV-0.json"
        os.link(path, self.root / "alias.json")
        with self.assertRaises(C.Refused):
            self.verify()
        print("[hardlink] an artifact aliased outside its output directory refuses")

    def test_browser_click_selector_is_not_a_url(self):
        calls=[]
        server=SimpleNamespace(name="fixture-browser", spec={"approval":"all", "no_approval":["browser_click"]},
            tool_def=lambda name: {"name":name, "annotations":{"readOnlyHint":False}},
            call=lambda name,args: (calls.append((name,args)) or {"content":[]}))
        result, how=mcp.guarded_call(server,"browser_click",{'target':'a[data-invoice="INV-0"]'},root=str(self.root))
        self.assertEqual(how,"live")
        self.assertEqual(len(calls),1)
        for target in ("file:///agent.env", "http://127.0.0.1/private"):
            result, how=mcp.guarded_call(server,"browser_click",{'target':target},root=str(self.root))
            self.assertEqual(how,"denied")
        self.assertEqual(len(calls),1)
        print("[browser-selector] a click selector reaches the server; file and private-network URL targets still refuse")


class BrowserAuthority(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="browser-authority-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.now = [100.0]
        self.auth = C.BrowserAuthority("http://portal.test", session_id="session-a",
                                       clock=lambda: self.now[0], max_age=5.0)
        self.state = {"url":"http://portal.test/invoices", "title":"Invoices",
            "dialog":False, "expired":False,
            "links":[{"id":"INV-0", "href":"http://portal.test/invoice/INV-0",
                      "text":"Download INV-0",
                      "box":{"x":10,"y":20,"width":100,"height":20}}]}

    def test_receipt_forgery_staleness_restart_and_deadline_refuse(self):
        receipt = self.auth.observe(self.state)
        forged = copy.deepcopy(receipt); forged["state"]["title"] = "forged"
        # The digest is public and recomputable; only the authority's MAC is a seal.
        forged["state_sha256"] = hashlib.sha256(C._canonical(forged["state"])).hexdigest()
        with self.assertRaises(C.Refused): self.auth.execute_click(forged,"INV-0",104.0,lambda p: {})
        self.auth.observe(dict(self.state,title="new observation"))
        with self.assertRaises(C.Refused): self.auth.execute_click(receipt,"INV-0",104.0,lambda p: {})
        other = C.BrowserAuthority("http://portal.test",session_id="session-b",clock=lambda:self.now[0])
        with self.assertRaises(C.Refused): other.execute_click(receipt,"INV-0",104.0,lambda p: {})
        fresh = self.auth.observe(self.state); self.now[0] = 106.0
        with self.assertRaises(C.Refused): self.auth.execute_click(fresh,"INV-0",104.0,lambda p: {})
        print("[browser-receipt] forged, superseded, restarted-session and expired observations refuse")

    def test_target_and_destination_are_exact(self):
        for changed in (
            dict(self.state,links=[]),
            dict(self.state,links=self.state["links"]*2),
            dict(self.state,links=[dict(self.state["links"][0],href="https://elsewhere.test/x")]),
            dict(self.state,links=[dict(self.state["links"][0],box={"x":0,"y":0,"width":0,"height":1})]),
            dict(self.state,dialog=True), dict(self.state,expired=True)):
            with self.subTest(changed=changed):
                with self.assertRaises(C.Refused): self.auth.observe(changed)
        print("[browser-target] absent, duplicate, off-origin, dialog-blocked and expired states refuse")

    def test_one_use_atomic_action_and_uncertain_failure(self):
        receipt=self.auth.observe(self.state)
        seen=[]
        def adapter(preconditions):
            seen.append(preconditions)
            return {"precondition_sha256":preconditions["state_sha256"],"clicked":True,
                    "destination":"http://portal.test/invoice/INV-0"}
        result=self.auth.execute_click(receipt,"INV-0",104.0,adapter)
        self.assertTrue(result["browser_authority_verified"])
        self.assertFalse(result["release_ready"])
        self.assertEqual(len(seen),1)
        with self.assertRaises(C.Refused): self.auth.execute_click(receipt,"INV-0",104.0,adapter)
        receipt2=self.auth.observe(self.state)
        with self.assertRaises(C.Unresolved):
            self.auth.execute_click(receipt2,"INV-0",104.0,
                                    lambda p: (_ for _ in ()).throw(RuntimeError("lost response")))
        with self.assertRaises(C.Refused): self.auth.execute_click(receipt2,"INV-0",104.0,adapter)
        receipt3=self.auth.observe(self.state)
        with self.assertRaises(C.Refused):
            self.auth.execute_click(receipt3,"INV-0",104.0,
                                    lambda p: (_ for _ in ()).throw(C.Refused("precondition changed")))
        print("[browser-action] exact preconditions execute once; uncertain adapter failure cannot retry")

    def test_shipped_playwright_adapter_is_identity_bound_and_fail_closed(self):
        receipt=self.auth.observe(self.state)
        calls=[]
        spec={"cmd":"fixture", "args":[], "atomic_browser_adapter":True,
              "approval":"all", "no_approval":["browser_evaluate"],
              "allow_tools":["browser_evaluate"]}
        spec["trust_identity"]=mcp.server_identity(spec)
        self.assertNotEqual(spec["trust_identity"],mcp.server_identity(dict(spec,atomic_browser_adapter=False)))
        def reply(_name,args):
            calls.append(args)
            body=(self.state if args.get("function")==C.PLAYWRIGHT_OBSERVE else
                  {"precondition_sha256":receipt["state_sha256"],"clicked":True,
                   "destination":"http://portal.test/invoice/INV-0"})
            return {"content":[{"type":"text","text":"### Result\n"+json.dumps(body)+"\n### Done"}]}
        server=SimpleNamespace(name="fixture-browser",spec=spec,
            tool_def=lambda name:{"name":name,"annotations":{"readOnlyHint":False}},call=reply)
        _,how=mcp.guarded_call(server,"browser_evaluate",{"function":"() => document.title"},root=str(self.root),fresh=True)
        self.assertEqual(how,"denied");self.assertEqual(calls,[])
        self.assertEqual(C.playwright_observe(server,str(self.root)),self.state)
        result=self.auth.execute_click(receipt,"INV-0",104.0,
            lambda p:C.playwright_atomic_click(server,str(self.root),p))
        self.assertTrue(result["browser_authority_verified"]);self.assertEqual(len(calls),2)
        disabled_spec=dict(spec,atomic_browser_adapter=False)
        disabled_spec["trust_identity"]=mcp.server_identity(disabled_spec)
        disabled=SimpleNamespace(name="disabled",spec=disabled_spec,call=reply)
        with self.assertRaises(C.Refused): C.playwright_observe(disabled,str(self.root))
        with self.assertRaises(C.Refused): C.playwright_atomic_click(disabled,str(self.root),{"valid_for_seconds":1})
        for payload,error in (({"refused":"target changed"},C.Refused),({},C.Unresolved)):
            auth=C.BrowserAuthority("http://portal.test",clock=lambda:self.now[0])
            rec=auth.observe(self.state)
            bad=SimpleNamespace(name="bad",spec=spec,
                tool_def=server.tool_def,call=lambda n,a,p=payload:{"content":[{"type":"text","text":"### Result\n"+json.dumps(p)+"\n### Done"}]})
            with self.assertRaises(error):
                auth.execute_click(rec,"INV-0",104.0,lambda p:C.playwright_atomic_click(bad,str(self.root),p))
        print("[playwright-adapter] shipped atomic executor is identity-bound and refuses precondition or malformed readback")


if __name__ == "__main__":
    result = unittest.main(exit=False)
    if not result.result.wasSuccessful():
        raise SystemExit(1)
    print("PASS test_computeruse")
