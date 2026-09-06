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


if __name__ == "__main__":
    result = unittest.main(exit=False)
    if not result.result.wasSuccessful():
        raise SystemExit(1)
    print("PASS test_computeruse")
