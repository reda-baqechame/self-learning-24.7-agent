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
            "binding":{"tab":"tab-a", "frame":"frame-a", "document":1},
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
            dict(self.state,links=self.state["links"]*2),
            dict(self.state,links=[dict(self.state["links"][0],href="https://elsewhere.test/x")]),
            dict(self.state,links=[dict(self.state["links"][0],box={"x":0,"y":0,"width":0,"height":1})])):
            with self.subTest(changed=changed):
                with self.assertRaises(C.Refused): self.auth.observe(changed)
        print("[browser-target] duplicate, off-origin and invalid-geometry observations refuse")

    def test_blocked_and_empty_observations_are_preserved_but_cannot_click(self):
        for state in (dict(self.state,dialog=True),dict(self.state,expired=True),
                      dict(self.state,links=[])):
            with self.subTest(state=state):
                receipt=self.auth.observe(state)
                self.assertEqual(receipt['state'],state)
                calls=[]
                with self.assertRaises(C.Refused):
                    self.auth.execute_click(receipt,'INV-0',104.0,lambda p:calls.append(p))
                self.assertEqual(calls,[])
                self.assertNotIn(receipt['mac'],self.auth._consumed)
        print("[blocked-observation] blocked and empty states can be sealed for recovery but refuse click before consumption or adapter entry")

    def test_dispatch_preserves_blocked_post_state_but_rejects_malformed_state(self):
        for flag in ('dialog','expired'):
            with self.subTest(flag=flag):
                post=dict(self.state,**{flag:True})
                receipt=self.auth.observe(self.state)
                result=self.auth.execute_click(receipt,'INV-0',104.0,lambda p:{
                    'clicked':True,'status':'ACTION_DISPATCHED','precondition_sha256':p['state_sha256'],
                    'destination':self.state['links'][0]['href'],'post_observation':post})
                self.assertEqual(result['status'],'ACTION_DISPATCHED')
                self.assertEqual(result['post_observation'],post)
                self.assertFalse(result['workflow_verified'])
        for post in (dict(self.state,dialog='true'),dict(self.state,expired=1),
                     {k:v for k,v in self.state.items() if k!='binding'}):
            with self.subTest(post=post):
                receipt=self.auth.observe(self.state)
                with self.assertRaises(C.Unresolved):
                    self.auth.execute_click(receipt,'INV-0',104.0,lambda p:{
                        'clicked':True,'status':'ACTION_DISPATCHED','precondition_sha256':p['state_sha256'],
                        'destination':self.state['links'][0]['href'],'post_observation':post})
                self.assertIn(receipt['mac'],self.auth._consumed)
        print("[blocked-post-state] acknowledged dialog/auth transitions preserve ACTION_DISPATCHED and observation; malformed post-state remains unknown")

    def test_one_use_atomic_action_and_uncertain_failure(self):
        receipt=self.auth.observe(self.state)
        seen=[]
        def adapter(preconditions):
            seen.append(preconditions)
            return {"precondition_sha256":preconditions["state_sha256"],"clicked":True,
                    "status":"ACTION_DISPATCHED", "post_observation":self.state,
                    "destination":"http://portal.test/invoice/INV-0"}
        result=self.auth.execute_click(receipt,"INV-0",104.0,adapter)
        self.assertTrue(result["browser_authority_verified"])
        self.assertFalse(result["release_ready"])
        self.assertEqual(result["status"], "ACTION_DISPATCHED")
        self.assertFalse(result["workflow_verified"])
        self.assertEqual(result["post_observation"], self.state)
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
              "computer_locator_tool":"browser_run_code_unsafe",
              "approval":"all", "no_approval":["browser_evaluate", "browser_run_code_unsafe", "browser_run_code"],
              "allow_tools":["browser_evaluate", "browser_run_code_unsafe", "browser_run_code"]}
        spec["trust_identity"]=mcp.server_identity(spec)
        self.assertNotEqual(spec['trust_identity'],mcp.server_identity(dict(spec,computer_locator_tool='browser_evaluate')))
        for omission in ('computer_locator_tool','trust_identity'):
            unreviewed=dict(spec);unreviewed.pop(omission)
            with self.assertRaises(C.Refused):
                C.playwright_observe(SimpleNamespace(spec=unreviewed),str(self.root))
        mismatched=dict(spec,trust_identity='0'*64)
        with self.assertRaises(C.Refused):
            C.playwright_observe(SimpleNamespace(spec=mismatched),str(self.root))
        self.assertNotEqual(spec["trust_identity"],mcp.server_identity(dict(spec,atomic_browser_adapter=False)))
        def reply(_name,args):
            calls.append(args)
            body=(self.state if 'const observe =' in args.get("code", "") else
                  {"precondition_sha256":receipt["state_sha256"],"clicked":True,
                   "status":"ACTION_DISPATCHED",
                   "destination":"http://portal.test/invoice/INV-0"})
            return {"content":[{"type":"text","text":"### Result\n"+json.dumps(body)+"\n### Done"}]}
        server=SimpleNamespace(name="fixture-browser",spec=spec,
            tool_def=lambda name:{"name":name,"annotations":{"readOnlyHint":False}},call=reply)
        _,how=mcp.guarded_call(server,"browser_evaluate",{"function":"() => document.title"},root=str(self.root),fresh=True)
        self.assertEqual(how,"denied");self.assertEqual(calls,[])
        for tool in ("browser_run_code", "browser_run_code_unsafe"):
            _,how=mcp.guarded_call(server,tool,{"code":"async page => page.close()"},root=str(self.root),fresh=True)
            self.assertEqual(how,"denied");self.assertEqual(calls,[])
        self.assertEqual(C.playwright_observe(server,str(self.root)),self.state)
        result=self.auth.execute_click(receipt,"INV-0",104.0,
            lambda p:C.playwright_atomic_click(server,str(self.root),p))
        self.assertTrue(result["browser_authority_verified"]);self.assertEqual(len(calls),3)
        disabled_spec=dict(spec,atomic_browser_adapter=False)
        disabled_spec["trust_identity"]=mcp.server_identity(disabled_spec)
        disabled=SimpleNamespace(name="disabled",spec=disabled_spec,call=reply)
        with self.assertRaises(C.Refused): C.playwright_observe(disabled,str(self.root))
        with self.assertRaises(C.Refused): C.playwright_atomic_click(disabled,str(self.root),{"valid_for_seconds":1})
        with self.assertRaises(C.Refused):
            self.auth.execute_click(self.auth.observe(self.state),'INV-0',104.0,
                lambda p:C.playwright_atomic_click(disabled,str(self.root),p))
        for payload,error in (({"refused":"target changed"},C.Refused),({},C.Unresolved)):
            auth=C.BrowserAuthority("http://portal.test",clock=lambda:self.now[0])
            rec=auth.observe(self.state)
            bad=SimpleNamespace(name="bad",spec=spec,
                tool_def=server.tool_def,call=lambda n,a,p=payload:{"content":[{"type":"text","text":"### Result\n"+json.dumps(p)+"\n### Done"}]})
            with self.assertRaises(error):
                auth.execute_click(rec,"INV-0",104.0,lambda p:C.playwright_atomic_click(bad,str(self.root),p))
        print("[playwright-adapter] host locator executor is identity-bound, denies generic raw code, and refuses precondition or malformed readback")

    def test_click_requires_post_observation_and_host_actionability(self):
        receipt = self.auth.observe(self.state)
        with self.assertRaises(C.Unresolved):
            self.auth.execute_click(receipt, "INV-0", 104.0, lambda p: {
                "clicked":True, "status":"ACTION_DISPATCHED", "precondition_sha256":p["state_sha256"],
                "destination":self.state["links"][0]["href"]})
        print("[post-observation] a dispatched click without fresh post-observation remains unknown")


if __name__ == "__main__":
    result = unittest.main(exit=False)
    if not result.result.wasSuccessful():
        raise SystemExit(1)
    print("PASS test_computeruse")
