#!/usr/bin/env python3
"""Qualification contracts: synthetic tests, never independent acceptance."""
import hashlib
import hmac
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    import computerbench as B
except ImportError:
    B = None


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def pack():
    frozen = {
        "model": {"provider": "external-provider", "name": "frozen-model",
                  "version": "model-revision"},
        "tool": {"name": "external-tool", "version": "tool-revision",
                 "sha256": "1" * 64},
        "policy": {"revision": "policy-revision", "sha256": "2" * 64},
        "budget": {"max_steps": 20, "max_seconds": 120,
                   "max_cost_usd": 1.0},
        "retries": 0,
        "human_help": "none",
    }
    cases = []
    for index, track in enumerate(B.TRACKS if B else
                                  ("browser_only", "native_desktop", "api_assisted")):
        cases.append({
            "id": f"external-{index}", "track": track,
            "variants": {"layout": "held-out", "wording": "held-out",
                         "timing": "held-out", "authentication": "held-out",
                         "multistep": "held-out"},
            "acceptance": {"kind": "owner_grader", "contract": "external"},
        })
    return {"schema": "computerbench.acceptance-pack.v1",
            "pack_id": "external-pack-1", "frozen": frozen, "cases": cases}


def write_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


def trust():
    return {"schema": "computerbench.owner-trust.v1",
            "authority_id": "independent-owner", "scope": "computerbench",
            "key_hex": "ab" * 32}


def seal(path, kind, owner):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    body = {"schema": "computerbench.seal.v1", "artifact_kind": kind,
            "authority_id": owner["authority_id"], "sha256": digest}
    body["hmac_sha256"] = hmac.new(bytes.fromhex(owner["key_hex"]),
                                    canonical(body), hashlib.sha256).hexdigest()
    return body


class Contract(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(B, "computerbench.py is missing")
        temp_parent = Path(os.getenv("AGENT_TEST_TMP") or ROOT / "tests" / "tmp")
        temp_parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="computerbench-",
                                                dir=temp_parent)
        self.addCleanup(self.temp.cleanup)
        self.external = Path(self.temp.name)
        self.worker_root = self.external / "repository"
        self.worker_root.mkdir()

    def material(self, base=None):
        base = base or self.external
        base.mkdir(parents=True, exist_ok=True)
        owner = trust()
        trust_path = self.external / "owner-trust.json"
        pack_path = base / "pack.json"
        seal_path = self.external / (base.name + "-pack-seal.json")
        write_json(trust_path, owner)
        write_json(pack_path, pack())
        write_json(seal_path, seal(pack_path, "acceptance_pack", owner))
        return pack_path, seal_path, trust_path

    def assess(self, pack_path=None, seal_path=None, trust_path=None,
               results_path=None, results_seal_path=None):
        return B.assess_acceptance(
            pack_path=pack_path, seal_path=seal_path, trust_path=trust_path,
            results_path=results_path, results_seal_path=results_seal_path,
            repository_root=self.worker_root)

    def test_valid_separately_sealed_contract_still_needs_execution(self):
        pack_path, seal_path, trust_path = self.material()
        report = self.assess(pack_path, seal_path, trust_path)
        self.assertTrue(report["contract_valid"], report)
        self.assertTrue(report["provenance_bound"], report)
        self.assertFalse(report["acceptance_complete"])
        self.assertFalse(report["release_ready"])
        self.assertIn("sealed_external_results", report["missing_evidence"])
        self.assertEqual(set(report["capability_matrix"]), set(B.TRACKS))
        self.assertTrue(all(not row["accepted"] for row in
                            report["capability_matrix"].values()))

    def test_malformed_repository_authored_changed_and_unsealed_refuse(self):
        pack_path, seal_path, trust_path = self.material()
        malformed = self.external / "malformed.json"
        write_json(malformed, {"schema": "computerbench.acceptance-pack.v1"})
        write_json(self.external / "malformed-seal.json",
                   seal(malformed, "acceptance_pack", trust()))
        bad = self.assess(malformed, self.external / "malformed-seal.json", trust_path)
        self.assertFalse(bad["acceptance_complete"])
        self.assertFalse(bad["contract_valid"])

        repo_pack, repo_seal, repo_trust = self.material(self.worker_root)
        authored = self.assess(repo_pack, repo_seal, repo_trust)
        self.assertFalse(authored["acceptance_complete"])
        self.assertIn("pack_inside_repository", authored["missing_evidence"])

        pack_path.write_text(pack_path.read_text(encoding="utf-8") + "\n",
                             encoding="utf-8")
        changed = self.assess(pack_path, seal_path, trust_path)
        self.assertFalse(changed["acceptance_complete"])
        self.assertIn("pack_content_seal", changed["missing_evidence"])

        write_json(pack_path, pack())
        forged = seal(pack_path, "acceptance_pack", trust())
        forged["hmac_sha256"] = "0" * 64
        write_json(seal_path, forged)
        unauthenticated = self.assess(pack_path, seal_path, trust_path)
        self.assertFalse(unauthenticated["provenance_bound"])
        self.assertFalse(unauthenticated["acceptance_complete"])
        self.assertIn("pack_content_seal", unauthenticated["missing_evidence"])

        unsealed = self.assess(pack_path, None, trust_path)
        self.assertFalse(unsealed["acceptance_complete"])
        self.assertIn("pack_content_seal", unsealed["missing_evidence"])

    def test_author_string_or_self_hash_never_establishes_independence(self):
        value = pack()
        value["author"] = "independent owner"
        value["self_sha256"] = hashlib.sha256(canonical(value)).hexdigest()
        path = self.external / "self-asserted.json"
        write_json(path, value)
        report = self.assess(path, None, None)
        self.assertFalse(report["provenance_bound"])
        self.assertFalse(report["acceptance_complete"])
        self.assertIn("independent_owner_trust", report["missing_evidence"])

    def test_schema_freezes_every_run_dimension_and_labels_tracks(self):
        value = pack()
        B.validate_pack(value)
        for field in ("model", "tool", "policy", "budget", "retries",
                      "human_help"):
            broken = json.loads(json.dumps(value))
            del broken["frozen"][field]
            with self.assertRaises(B.ContractError, msg=field):
                B.validate_pack(broken)
        for field in B.VARIANT_DIMENSIONS:
            broken = json.loads(json.dumps(value))
            del broken["cases"][0]["variants"][field]
            with self.assertRaises(B.ContractError, msg=field):
                B.validate_pack(broken)

    def test_results_must_match_frozen_pack_and_budgets(self):
        value = pack()
        digest = hashlib.sha256(canonical(value)).hexdigest()
        rows = [{"id": case["id"], "track": case["track"],
                 "outcome": "passed", "evidence_sha256": "3" * 64,
                 "attempts": 1, "human_help_used": False,
                 "steps": 1, "seconds": 1.0, "cost_usd": 0.0}
                for case in value["cases"]]
        result = {"schema": "computerbench.acceptance-results.v1",
                  "pack_sha256": digest, "run_id": "external-run-1",
                  "frozen": value["frozen"], "cases": rows}
        B.validate_results(result, value, digest)
        for change in ("settings", "retries", "help", "track", "steps",
                       "budget"):
            broken = json.loads(json.dumps(result))
            if change == "settings": broken["frozen"]["model"]["version"] = "changed"
            if change == "retries": broken["cases"][0]["attempts"] = 2
            if change == "help": broken["cases"][0]["human_help_used"] = True
            if change == "track": broken["cases"][0]["track"] = "api_assisted"
            if change == "steps": broken["cases"][0]["steps"] = 21
            if change == "budget": broken["cases"][0]["seconds"] = 121
            with self.assertRaises(B.ContractError, msg=change):
                B.validate_results(broken, value, digest)

    def test_development_status_requires_observed_protocol_evidence(self):
        base = {"case": "ambiguous", "controller_outcome": "refused",
                "artifact_outcome": "rejected", "cleanup": {"confirmed": True}}
        self.assertEqual(B._development_status(base), "safe_refusal")
        changed = dict(base, controller_outcome="completed")
        self.assertEqual(B._development_status(changed), "unresolved")

        rejected = dict(base, case="corrupt", controller_outcome="completed")
        self.assertEqual(B._development_status(rejected), "rejected_artifacts")
        changed = dict(rejected, controller_outcome="refused")
        self.assertEqual(B._development_status(changed), "unresolved")

        interrupted = dict(rejected, case="interrupted",
                           controller_outcome="unknown")
        self.assertEqual(B._development_status(interrupted),
                         "rejected_artifacts")
        cross_origin = dict(interrupted, case="cross_origin")
        self.assertEqual(B._development_status(cross_origin), "safe_refusal")

        verified = dict(base, case="normal", controller_outcome="completed",
                        artifact_outcome="verified")
        self.assertEqual(B._development_status(verified),
                         "verified_completion")
        self.assertEqual(B._development_status(
            dict(verified, controller_outcome="unknown")), "unresolved")

    def test_development_summary_separates_refusals_from_retrievals(self):
        rows = []
        for case, expected in B.DEVELOPMENT_EXPECTED.items():
            rows.extend({"case": case, "repeat": repeat, "status": expected,
                         "expected": expected, "development_expectation_met": True,
                         "cleanup": {"confirmed": True}, "actions": []}
                        for repeat in range(1, 4))
        report = B.summarize_development(rows)
        self.assertEqual(report["statuses"], {
            "verified_completion": 12, "safe_refusal": 15,
            "rejected_artifacts": 9})
        self.assertEqual(report["retrievals_verified"], 12)
        self.assertEqual(report["safe_refusals"], 15)
        self.assertFalse(report["acceptance_complete"])
        self.assertFalse(report["release_ready"])
        rows[0]["cleanup"]["confirmed"] = False
        rows[0]["status"] = "unresolved"
        changed = B.summarize_development(rows)
        self.assertEqual(changed["statuses"]["unresolved"], 1)
        self.assertFalse(changed["development_complete"])

    def test_portal_source_is_exactly_pinned_and_session_owned(self):
        fixture = ROOT / B.PORTAL_FIXTURE_REL
        self.assertEqual(hashlib.sha256(fixture.read_bytes()).hexdigest(),
                         B.PORTAL_FIXTURE_SHA256)
        source = (ROOT / "computerbench.py").read_text(encoding="utf-8")
        self.assertIn("computersession.ComputerSession", source)
        self.assertNotIn("mcp.connect(", source)
        self.assertNotIn("BrowserAuthority(", source)
        spec = B.portal_spec("docker", ROOT / "out")
        self.assertIn("--network=none", spec["args"])
        self.assertIn("--pull=never", spec["args"])
        self.assertIn("--isolated", " ".join(spec["args"]))
        self.assertEqual(spec["integrity"], B.PLAYWRIGHT_IMAGE.split("@sha256:")[1])
        fixture_mount = spec["args"][spec["args"].index("--mount") + 1]
        self.assertIn("source=" + str(fixture.parent), fixture_mount)
        self.assertNotIn("source=" + str(fixture) + ",", fixture_mount)
        command = spec["args"][-1]
        self.assertIn("for attempt in $(seq 1 100)", command)
        self.assertIn("fetch('http://127.0.0.1:8765/health')", command)
        self.assertLess(command.index("for attempt"), command.index("exec node"))

    def test_moved_variant_only_uses_a_stale_click_after_observed_change(self):
        before = {"observation": {"state_sha256": "a" * 64}}
        same = {"observation": {"state_sha256": "a" * 64}}
        changed = {"observation": {"state_sha256": "b" * 64}}
        self.assertFalse(B.receipt_state_changed(before, same))
        self.assertTrue(B.receipt_state_changed(before, changed))
        source = (ROOT / "computerbench.py").read_text(encoding="utf-8")
        refresh = source.index('"moved-refresh"')
        stale = source.index('"stale_moved_click"')
        self.assertLess(refresh, stale)

if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(Contract)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        print("[computerbench-contract] sealed external owner trust, frozen run settings, all five variant dimensions and separate browser/desktop/API tracks are required; synthetic tests do not set acceptance or release true")
    raise SystemExit(0 if result.wasSuccessful() else 1)
