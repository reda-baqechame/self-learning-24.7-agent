#!/usr/bin/env python3
"""Qualification contracts: synthetic tests, never independent acceptance."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock
import zipfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    import computerbench as B
except ImportError:
    B = None


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


# Test-only private material. Production computerbench contains public n/e
# values only and has no signing operation.
ISSUER_N = int("b3762aaead99d23b4e207e9e8a1d9cb3fc8ccffbe6267a9437ab6b9d7c94c17332f3b26da56fee609bf79ae8d4d381081c43ef1af943520ee2a297d82bd4fda27808f54142b7bb997fd10e3bc68ac72c01150116ba9adfc797d67d13abb4776ff9f25c110361a94a27ea6e1245145d2bd91bd56f4919d0487e1dbccd7995c173d837b2ca2f5164ae3a6525a2072bab9281f287985972347ae6032748fc806284e6b4073cbc92474f6e8e4f2b941dafa19bd53bb7333c995f50d39dd8a99344b9b580b30420b45d055ecf145b2e0cb17bf94eda2190f95b11a3e97686f6bf47db8e71024aa088fc6b1ef32c2c22a0478b411f5e97561f9632671523a8551a5efd", 16)
ISSUER_D = int("2a7774b7b3a061f9832e18d062de098224e9dc609f306d52cc0e9e2f5cf6e58521623e0f88b5c13aaec5abac5b8a762ee96360fe28cc77ab4a918fad8987c4023175eb3567788b65d23371f30eb331d8f5a397079e1e3e84a06752df3803433d25f0263da767719438f856562fef16f22494dbcf93048eff4c8ab46e0a0eb841502cd878a6475259d72c76a3a9c5a6cf7638ffff1a0be334a9363c591211173e293e6d906833d9b734c3542b28ac7a65c364937c0d8ecf52d7c4e856c53e8db83172c2a7b0c2b68b376b984d04d948a41214fa11024bcbcf9977ff596a722b8ba5183bf52584fb26b012be36d8eabe5ce007a69529527b9d9804605280a33cc1", 16)
EVALUATOR_N = int("d7f1667c7131c8d26eb963b72e6830831e6705baafee4af14331ee5a17414d520c71140d26c5c24764443441fcf14d82323f332b4be084be3064058baaf749061f0c82ca652826a4d3777508feb0fff8c659320a6dabdc5547701e1b02838b684268913046094ef07c31d200edf1fa9e9646a6cdc56898c0200abbcd9e2e5d6910fe633aa645178c1827e53623826a039af724874c99bfb4082559d140c13320404aa01c958427a01c0108057b9c44a71e774af3b54ffaa085c53233164c010d54ceea8611bf1f9c8a911bb5f4dbdef360157d3dbed4a4ee5813e0965cf99c212aaaafb1479b3c3ce6ac68b6feb47cac250c4cc2533cb870a3c23987ab784955", 16)
EVALUATOR_D = int("11715aa7ad260a147364aeb90e7ad48656d79807212c64a9d1d56fed1f894313605566fafbf987eca7dcf982a609a0cae63fa424b86b91956247c609e6dcb42d9626f6ce9df6ad0e6dd56da2f51dbb836f1427de5f46fd547721879103763835cafd72d2dd2965d2b799779ee3198376b9694a127f82682a46bc4f38b7f10352f2000c77025ceca4eeb8276402f646b41566a64719aab3a3d847c5a4ac51f8b5980e0212db38bfe2a6e43cb382a0be82867a40ecb934861b0d936e2ac539c222b5855fb3ad2cf6dd4eef452f627817ead38f2a69af7c34d4198d072519312d6891099c6aeb8266425543d70acdb07c00248540d3b25b194843758198c4880971", 16)


def test_profile():
    return {"schema": "computerbench.public-trust.v1",
            "trust_id": "independent-owner", "verifier_uid": 1001,
            "worker_uid": 1002,
            "pack_issuer": {"key_id": "issuer-key-1",
                            "principal": "external-pack-issuer",
                            "algorithm": "rsa-pkcs1-v1_5-sha256",
                            "n_hex": format(ISSUER_N, "x"), "e": 65537},
            "results_evaluator": {"key_id": "evaluator-key-1",
                                  "principal": "external-results-evaluator",
                                  "algorithm": "rsa-pkcs1-v1_5-sha256",
                                  "n_hex": format(EVALUATOR_N, "x"),
                                  "e": 65537}}


def rsa_sign(raw, modulus, private_exponent):
    prefix = bytes.fromhex("3031300d060960864801650304020105000420")
    digest_info = prefix + hashlib.sha256(raw).digest()
    size = (modulus.bit_length() + 7) // 8
    encoded = b"\x00\x01" + b"\xff" * (size - len(digest_info) - 3) \
        + b"\x00" + digest_info
    return pow(int.from_bytes(encoded, "big"), private_exponent,
               modulus).to_bytes(size, "big").hex()


def signed_seal(path, kind):
    raw = path.read_bytes()
    if kind == "acceptance_pack":
        key_id, principal, modulus, private = (
            "issuer-key-1", "external-pack-issuer", ISSUER_N, ISSUER_D)
    else:
        key_id, principal, modulus, private = (
            "evaluator-key-1", "external-results-evaluator",
            EVALUATOR_N, EVALUATOR_D)
    body = {"schema": "computerbench.rsa-seal.v1", "artifact_kind": kind,
            "key_id": key_id, "principal": principal,
            "sha256": hashlib.sha256(raw).hexdigest()}
    body["signature_hex"] = rsa_sign(canonical(body), modulus, private)
    return body


_DEFAULT_CANDIDATE = None


def challenge(trust_id="independent-owner", candidate=None):
    global _DEFAULT_CANDIDATE
    now = int(__import__("time").time())
    if candidate is None:
        if _DEFAULT_CANDIDATE is None:
            raise AssertionError("test verifier candidate was not initialized")
        candidate = json.loads(json.dumps(_DEFAULT_CANDIDATE))
    return {"trust_id": trust_id, "nonce": "4" * 32,
            "issued_at": now, "expires_at": now + 300,
            "trust_metadata_sha256": candidate["trust_metadata_sha256"],
            "candidate": candidate}


def pack(challenge_value=None):
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
    challenge_value = challenge_value or challenge()
    return {"schema": "computerbench.acceptance-pack.v1",
            "pack_id": "external-pack-1",
            "candidate": json.loads(json.dumps(challenge_value["candidate"])),
            "challenge": challenge_value, "frozen": frozen, "cases": cases}


def write_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


class Contract(unittest.TestCase):
    def setUp(self):
        global _DEFAULT_CANDIDATE
        self.assertIsNotNone(B, "computerbench.py is missing")
        temp_parent = Path(os.getenv("AGENT_TEST_TMP") or ROOT / "tests" / "tmp")
        temp_parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="computerbench-",
                                                dir=temp_parent)
        self.addCleanup(self.temp.cleanup)
        self.external = Path(self.temp.name)
        self.worker_root = self.external / "repository"
        self.worker_root.mkdir()
        self.install_root = self.external / "installed-verifier"
        self.install_root.mkdir()
        verifier_path = self.install_root / "computerbench_verifier.py"
        shutil.copy2(ROOT / "computerbench_verifier.py", verifier_path)
        launcher_path = self.install_root / "computerbench-verifier"
        shutil.copy2(ROOT / "computerbench-verifier", launcher_path)
        spec = importlib.util.spec_from_file_location(
            "computerbench_verifier_fixture_" + self.external.name.replace("-", "_"),
            verifier_path)
        self.V = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.V)
        self.candidate_archive = self.external / "candidate.zip"
        self._write_candidate_archive(self.candidate_archive)
        self.backend = self.V._test_backend(
            self.external / "owner-store", self.external / "verifier-state",
            self.candidate_archive, test_profile(), self.install_root)
        trust_digest = self.backend.profile_digest("independent-owner")
        _DEFAULT_CANDIDATE = self.backend.candidate(trust_digest)

    @staticmethod
    def _write_candidate_archive(path, changes=None):
        members = {"computerbench.py": b"development-only",
                   "another_authority.py": b"authority-a",
                   "settings.toml": b"[policy]\nmode='a'\n",
                   "logs/.gitkeep": b"", "contexts/.gitkeep": b"",
                   "experts/.gitkeep": b""}
        members.update(changes or {})
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, raw in members.items():
                archive.writestr(name, raw)

    def material(self, base=None):
        base = base or self.external
        base.mkdir(parents=True, exist_ok=True)
        issued = self.backend.issue_challenge("independent-owner")
        pack_path = base / "pack.json"
        seal_path = self.external / (base.name + "-pack-seal.json")
        write_json(pack_path, pack(issued))
        write_json(seal_path, signed_seal(pack_path, "acceptance_pack"))
        return pack_path, seal_path

    def assess(self, pack_path=None, seal_path=None, trust_id="independent-owner",
               results_path=None, results_seal_path=None):
        return self.V.assess_acceptance(
            pack_path=pack_path, seal_path=seal_path, trust_id=trust_id,
            results_path=results_path, results_seal_path=results_seal_path,
            _backend=self.backend)

    def test_valid_separately_sealed_contract_still_needs_execution(self):
        pack_path, seal_path = self.material()
        report = self.assess(pack_path, seal_path)
        self.assertTrue(report["contract_valid"], report)
        self.assertTrue(report["provenance_bound"], report)
        self.assertFalse(report["acceptance_complete"])
        self.assertFalse(report["release_ready"])
        self.assertIn("sealed_external_results", report["missing_evidence"])
        self.assertEqual(set(report["capability_matrix"]), set(B.TRACKS))
        self.assertTrue(all(not row["accepted"] for row in
                            report["capability_matrix"].values()))

        with mock.patch.object(self.V, "_production_backend",
                               return_value=self.backend), \
                mock.patch.object(self.V, "_validate_launch_contract"), \
                mock.patch("sys.stdout", __import__("io").StringIO()):
            code = self.V.main([
                "acceptance", "--trust-id", "independent-owner",
                "--candidate-archive", str(self.candidate_archive),
                "--pack", str(pack_path), "--pack-seal", str(seal_path),
                "--results", str(self.external / "missing-results.json"),
                "--results-seal", str(self.external / "missing-seal.json")])
        self.assertNotEqual(code, 0)

    def test_results_use_distinct_evaluator_and_consume_challenge_once(self):
        pack_path, seal_path = self.material()
        value = json.loads(pack_path.read_text(encoding="utf-8"))
        digest = hashlib.sha256(pack_path.read_bytes()).hexdigest()
        rows = [{"id": case["id"], "track": case["track"],
                 "outcome": "passed", "evidence_sha256": "3" * 64,
                 "attempts": 1, "human_help_used": False, "steps": 1,
                 "seconds": 1.0, "cost_usd": 0.0}
                for case in value["cases"]]
        results = {"schema": "computerbench.acceptance-results.v1",
                   "pack_sha256": digest, "run_id": "external-run-1",
                   "candidate": value["candidate"],
                   "challenge": value["challenge"],
                   "frozen": value["frozen"], "cases": rows}
        results_path = self.external / "results.json"
        results_seal = self.external / "results-seal.json"
        write_json(results_path, results)
        write_json(results_seal, signed_seal(results_path,
                                             "acceptance_results"))
        profile = self.backend.profile("independent-owner")
        seal_value = json.loads(results_seal.read_text(encoding="utf-8"))
        self.assertNotEqual(profile["pack_issuer"]["key_id"],
                            profile["results_evaluator"]["key_id"])
        self.assertEqual(seal_value["key_id"],
                         profile["results_evaluator"]["key_id"])
        accepted = self.assess(pack_path, seal_path,
                               results_path=results_path,
                               results_seal_path=results_seal)
        self.assertTrue(accepted["results_valid"], accepted)
        self.assertFalse(accepted["acceptance_complete"], accepted)
        self.assertIn("independent_owner_authority",
                      accepted["missing_evidence"])
        replay = self.assess(pack_path, seal_path,
                             results_path=results_path,
                             results_seal_path=results_seal)
        self.assertFalse(replay["acceptance_complete"], replay)
        self.assertFalse(replay["results_valid"], replay)

    def test_malformed_repository_authored_changed_and_unsealed_refuse(self):
        pack_path, seal_path = self.material()
        malformed = self.external / "malformed.json"
        write_json(malformed, {"schema": "computerbench.acceptance-pack.v1"})
        write_json(self.external / "malformed-seal.json",
                   signed_seal(malformed, "acceptance_pack"))
        bad = self.assess(malformed, self.external / "malformed-seal.json")
        self.assertFalse(bad["acceptance_complete"])
        self.assertFalse(bad["contract_valid"])

        repo_pack = self.worker_root / "pack.json"
        repo_pack.write_bytes(pack_path.read_bytes())
        authored = self.assess(repo_pack, seal_path)
        self.assertFalse(authored["acceptance_complete"])
        self.assertTrue(authored["contract_valid"], authored)
        self.assertIn("sealed_external_results", authored["missing_evidence"])

        pack_path.write_text(pack_path.read_text(encoding="utf-8") + "\n",
                             encoding="utf-8")
        changed = self.assess(pack_path, seal_path)
        self.assertFalse(changed["acceptance_complete"])
        self.assertIn("pack_content_seal", changed["missing_evidence"])

        issued = self.backend.issue_challenge("independent-owner")
        write_json(pack_path, pack(issued))
        forged = signed_seal(pack_path, "acceptance_pack")
        forged["signature_hex"] = "0" * len(forged["signature_hex"])
        write_json(seal_path, forged)
        unauthenticated = self.assess(pack_path, seal_path)
        self.assertFalse(unauthenticated["provenance_bound"])
        self.assertFalse(unauthenticated["acceptance_complete"])
        self.assertIn("pack_content_seal", unauthenticated["missing_evidence"])

        unsealed = self.assess(pack_path, None)
        self.assertFalse(unsealed["acceptance_complete"])
        self.assertIn("pack_content_seal", unsealed["missing_evidence"])

    def test_author_string_or_self_hash_never_establishes_independence(self):
        value = pack()
        value["author"] = "independent owner"
        value["self_sha256"] = hashlib.sha256(canonical(value)).hexdigest()
        path = self.external / "self-asserted.json"
        write_json(path, value)
        report = self.assess(path, None, "not-installed")
        self.assertFalse(report["provenance_bound"])
        self.assertFalse(report["acceptance_complete"])
        self.assertIn("independent_owner_trust", report["missing_evidence"])

    def test_schema_freezes_every_run_dimension_and_labels_tracks(self):
        value = pack()
        self.V.validate_pack(value)
        for field in ("model", "tool", "policy", "budget", "retries",
                      "human_help"):
            broken = json.loads(json.dumps(value))
            del broken["frozen"][field]
            with self.assertRaises(self.V.ContractError, msg=field):
                self.V.validate_pack(broken)
        for field in self.V.VARIANT_DIMENSIONS:
            broken = json.loads(json.dumps(value))
            del broken["cases"][0]["variants"][field]
            with self.assertRaises(self.V.ContractError, msg=field):
                self.V.validate_pack(broken)

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
                  "candidate": value["candidate"],
                  "challenge": value["challenge"],
                  "frozen": value["frozen"], "cases": rows}
        self.V.validate_results(result, value, digest)
        for change in ("settings", "retries", "help", "track", "steps",
                       "budget"):
            broken = json.loads(json.dumps(result))
            if change == "settings": broken["frozen"]["model"]["version"] = "changed"
            if change == "retries": broken["cases"][0]["attempts"] = 2
            if change == "help": broken["cases"][0]["human_help_used"] = True
            if change == "track": broken["cases"][0]["track"] = "api_assisted"
            if change == "steps": broken["cases"][0]["steps"] = 21
            if change == "budget": broken["cases"][0]["seconds"] = 121
            with self.assertRaises(self.V.ContractError, msg=change):
                self.V.validate_results(broken, value, digest)

    def test_production_cli_exposes_only_preinstalled_trust_identity(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "computerbench.py"), "acceptance",
             "--help"], capture_output=True, text=True, check=True)
        self.assertNotIn("--trust-id", result.stdout)
        self.assertNotIn("--owner-trust", result.stdout)
        self.assertNotIn("--repository-root", result.stdout)
        root_help = subprocess.run(
            [sys.executable, str(ROOT / "computerbench.py"), "--help"],
            capture_output=True, text=True, check=True).stdout
        self.assertNotIn("seal-pack", root_help)
        self.assertNotIn("seal-results", root_help)
        self.assertNotIn("provision", root_help)
        with self.assertRaises(self.V.ContractError):
            self.V.main(["--help"])
        verifier_help = self.V._build_parser().format_help()
        self.assertIn("issue-challenge", verifier_help)
        self.assertIn("acceptance", verifier_help)
        source = (ROOT / "computerbench.py").read_text(encoding="utf-8")
        self.assertNotIn("key_hex", source)
        self.assertNotIn("hmac.new", source)
        # _lexically_outside is true here: the fixed store cannot be packaged,
        # backed up with the repository, or written through worker paths.
        self.assertTrue(self.V._lexically_outside(self.V._OWNER_STORE, ROOT))

    def test_pack_and_results_require_candidate_and_one_run_challenge(self):
        old = pack()
        del old["candidate"]
        del old["challenge"]
        with self.assertRaises(self.V.ContractError):
            self.V.validate_pack(old)
        mismatched = pack()
        mismatched["challenge"]["candidate"]["archive_sha256"] = "5" * 64
        with self.assertRaises(self.V.ContractError):
            self.V.validate_pack(mismatched)

    def test_required_human_help_must_be_observed(self):
        value = pack()
        value["frozen"]["human_help"] = "required"
        digest = hashlib.sha256(canonical(value)).hexdigest()
        rows = [{"id": case["id"], "track": case["track"],
                 "outcome": "passed", "evidence_sha256": "3" * 64,
                 "attempts": 1, "human_help_used": False,
                 "steps": 1, "seconds": 1.0, "cost_usd": 0.0}
                for case in value["cases"]]
        result = {"schema": "computerbench.acceptance-results.v1",
                  "pack_sha256": digest, "run_id": "external-run-1",
                  "candidate": value["candidate"],
                  "challenge": value["challenge"],
                  "frozen": value["frozen"], "cases": rows}
        with self.assertRaises(self.V.ContractError):
            self.V.validate_results(result, value, digest)

    def test_readiness_probe_bounds_each_fetch_attempt(self):
        command = B.portal_spec("docker", ROOT / "out")["args"][-1]
        self.assertIn("fetch('http://127.0.0.1:8765/health',{signal:AbortSignal.timeout(250)})",
                      command)

    def test_external_read_refuses_aliases_or_platform_fails_closed(self):
        target = self.external / "external.json"
        alias = self.external / "alias.json"
        target.write_text("{}", encoding="utf-8")
        if os.name == "posix":
            with self.assertRaises(self.V.ContractError):
                self.V._secure_external_bytes(
                    self.external / "missing.json", "artifact",
                    self.install_root, internal=self.backend.internal)
        if os.name == "nt":
            real_lstat = os.lstat
            class ReparseInfo:
                def __init__(self, original):
                    self._original = original
                    self.st_mode = original.st_mode
                    self.st_file_attributes = 0x400
                def __getattr__(self, name):
                    return getattr(self._original, name)
            def instrumented(path):
                info = real_lstat(path)
                return ReparseInfo(info) if Path(path) == target else info
            with mock.patch.object(self.V.os, "lstat", side_effect=instrumented):
                with self.assertRaises(self.V.ContractError):
                    self.V._secure_external_bytes(
                        target, "artifact", self.install_root, internal=True)
        try:
            alias.symlink_to(target)
        except OSError:
            if os.name == "nt":
                with self.assertRaises(self.V.ContractError):
                    self.V._secure_external_bytes(
                        target, "artifact", self.install_root, internal=False)
            return
        with self.assertRaises(self.V.ContractError):
            self.V._secure_external_bytes(
                alias, "artifact", self.install_root,
                internal=self.backend.internal)

    def test_production_acceptance_refuses_inside_agent_task(self):
        with self.assertRaises(self.V.ContractError):
            self.V._production_backend(self.candidate_archive)

    def test_development_status_requires_observed_protocol_evidence(self):
        base = {"case": "ambiguous", "controller_outcome": "refused",
                "artifact_outcome": "rejected", "cleanup": {"confirmed": True},
                "action_attempted": False, "actions": []}
        self.assertEqual(B._development_status(base), "safe_refusal")
        self.assertEqual(B._development_status(dict(
            base, artifact_outcome="verified")), "safe_refusal")
        changed = dict(base, controller_outcome="completed",
                       action_attempted=True,
                       actions=[{"state": "VERIFIED", "operation": "click",
                                 "required_for_task": True}])
        self.assertEqual(B._development_status(changed), "unresolved")

        rejected = dict(base, case="corrupt", controller_outcome="completed",
                        action_attempted=True,
                        actions=[{"state": "VERIFIED", "operation": "click",
                                  "required_for_task": True}])
        self.assertEqual(B._development_status(rejected), "unresolved")
        rejected = dict(base, case="corrupt", controller_outcome="refused",
                        action_attempted=True,
                        actions=[{"state": "FAILED_POSTCONDITION",
                                  "operation": "click"}])
        self.assertEqual(B._development_status(rejected), "rejected_artifacts")
        changed = dict(rejected, controller_outcome="refused",
                       action_attempted=False, actions=[])
        self.assertEqual(B._development_status(changed), "safe_refusal")

        interrupted = dict(rejected, case="interrupted",
                           controller_outcome="unknown")
        self.assertEqual(B._development_status(interrupted), "unresolved")
        cross_origin = dict(interrupted, case="cross_origin")
        self.assertEqual(B._development_status(cross_origin), "unresolved")
        durable_unknown = dict(base, action_attempted=True,
                               actions=[{"state": "UNKNOWN"}])
        self.assertEqual(B._development_status(durable_unknown), "unresolved")

        verified = dict(base, case="normal", controller_outcome="completed",
                         artifact_outcome="verified", action_attempted=True,
                         actions=[{"state": "VERIFIED", "operation": "click",
                                   "required_for_task": True}],
                         postcondition_completion={"passed": True})
        self.assertEqual(B._development_status(verified),
                         "verified_completion")
        self.assertEqual(B._development_status(
            dict(verified, controller_outcome="unknown")), "unresolved")

        # Scenario labels are comparison metadata, never verdict authority.
        evidence = dict(base, actions=[])
        statuses = {B._development_status(dict(evidence, case=name))
                    for name in list(B.DEVELOPMENT_EXPECTED) +
                    ["fabricated-terminal-label"]}
        self.assertEqual(statuses, {"safe_refusal"})
        rejected_evidence = dict(
            verified, artifact_outcome="rejected")
        statuses = {B._development_status(dict(rejected_evidence, case=name))
                    for name in list(B.DEVELOPMENT_EXPECTED) +
                    ["fabricated-terminal-label"]}
        self.assertEqual(statuses, {"rejected_artifacts"})

    def test_development_summary_separates_refusals_from_retrievals(self):
        rows = []
        for case, expected in B.DEVELOPMENT_EXPECTED.items():
            completed = expected == "verified_completion"
            rejected = expected == "rejected_artifacts"
            rows.extend({
                "case": case, "repeat": repeat, "status": expected,
                "expected": expected, "development_expectation_met": True,
                "cleanup": {"confirmed": True},
                "controller_outcome": "completed" if completed else "refused",
                "artifact_outcome": ("verified" if expected ==
                                      "verified_completion" else "rejected"),
                "action_attempted": completed or rejected,
                "postcondition_completion": {"passed": completed},
                "actions": ([{"state": "VERIFIED", "operation": "click",
                               "required_for_task": True}]
                            if completed else
                            ([{"state": "FAILED_POSTCONDITION",
                               "operation": "click"}] if rejected else []))}
                for repeat in range(1, 4))
        report = B.summarize_development(rows)
        self.assertEqual(report["statuses"], {
            "verified_completion": 12, "safe_refusal": 15,
            "rejected_artifacts": 9})
        self.assertEqual(report["retrievals_verified"], 12)
        self.assertEqual(report["safe_refusals"], 15)
        self.assertTrue(report["selection_complete"])
        self.assertFalse(report["acceptance_complete"])
        self.assertFalse(report["release_ready"])
        rows[0]["cleanup"]["confirmed"] = False
        rows[0]["status"] = "unresolved"
        changed = B.summarize_development(rows)
        self.assertEqual(changed["statuses"]["unresolved"], 1)
        self.assertFalse(changed["development_complete"])

    def test_rsa_verifier_rejects_wrong_role_weak_key_and_padding(self):
        pack_path, seal_path = self.material()
        valid = json.loads(seal_path.read_text(encoding="utf-8"))
        raw = pack_path.read_bytes()
        self.assertTrue(self.V._rsa_verify(canonical(
            {k: v for k, v in valid.items() if k != "signature_hex"}),
            valid["signature_hex"], ISSUER_N, 65537))
        wrong_role = dict(valid, key_id="evaluator-key-1",
                          principal="external-results-evaluator")
        wrong_role["signature_hex"] = rsa_sign(
            canonical({k: v for k, v in wrong_role.items()
                       if k != "signature_hex"}), EVALUATOR_N, EVALUATOR_D)
        write_json(seal_path, wrong_role)
        self.assertFalse(self.assess(pack_path, seal_path)["provenance_bound"])
        with self.assertRaises(self.V.ContractError):
            self.V._validate_public_key(
                {"key_id": "weak", "principal": "weak",
                 "algorithm": "rsa-pkcs1-v1_5-sha256",
                 "n_hex": "f" * 128, "e": 3}, "key")
        # This value satisfies the encoded-length and oddness checks but its
        # high nibble leaves the actual modulus below 2048 bits.  Keep this
        # separate from the cheap length rejection so the strength bound is
        # itself measured by the negative control.
        with self.assertRaises(self.V.ContractError):
            self.V._validate_public_key(
                {"key_id": "short-bits", "principal": "short-bits",
                 "algorithm": "rsa-pkcs1-v1_5-sha256",
                 "n_hex": "1" + "0" * 510 + "1", "e": 3}, "key")
        with self.assertRaises(self.V.ContractError):
            self.V._validate_public_key(
                {"key_id": "huge", "principal": "huge",
                 "algorithm": "rsa-pkcs1-v1_5-sha256",
                 "n_hex": "f" * 2050, "e": 65537}, "key")
        with self.assertRaises(self.V.ContractError):
            self.V._validate_public_key(
                {"key_id": "exponent", "principal": "exponent",
                 "algorithm": "rsa-pkcs1-v1_5-sha256",
                 "n_hex": format(ISSUER_N, "x"), "e": 0x100000001}, "key")
        with mock.patch("builtins.pow", side_effect=AssertionError(
                "invalid RSA parameters reached modular exponentiation")):
            oversized = (1 << 8193) | 1
            oversized_size = (oversized.bit_length() + 7) // 8
            self.assertFalse(self.V._rsa_verify(
                b"message", "01" * oversized_size, oversized, 65537))
            self.assertFalse(self.V._rsa_verify(
                b"message", "01" * 256, ISSUER_N, 0x100000001))
        malformed = bytearray.fromhex(valid["signature_hex"])
        malformed[-1] ^= 1
        self.assertFalse(self.V._rsa_verify(
            canonical({k: v for k, v in valid.items()
                       if k != "signature_hex"}), malformed.hex(),
            ISSUER_N, 65537))

    def test_consumed_tombstone_dominates_restore_and_concurrency(self):
        issued = self.backend.issue_challenge("independent-owner")
        issued_path = self.backend._issued_path(issued["nonce"])
        original = issued_path.read_bytes()
        self.backend.consume(issued)
        consumed = self.backend._consumed_path(issued["nonce"])
        self.assertTrue(consumed.exists())
        issued_path.parent.mkdir(parents=True, exist_ok=True)
        issued_path.write_bytes(original)  # restored backup cannot revive it
        with self.assertRaises(self.V.ContractError):
            self.backend.challenge(issued)
        with self.assertRaises(self.V.ContractError):
            self.backend.consume(issued)

        fresh = self.backend.issue_challenge("independent-owner")
        import concurrent.futures
        def consume_once():
            try:
                self.backend.consume(fresh)
                return True
            except self.V.ContractError:
                return False
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda _index: consume_once(), range(2)))
        self.assertEqual(sorted(outcomes), [False, True])

        # A crash/failure after durable tombstone creation must fail the
        # operation but can never make the challenge replayable.
        crash = self.backend.issue_challenge("independent-owner")
        crash_source = self.backend._issued_path(crash["nonce"])
        real_unlink = self.V.os.unlink
        def fail_issued_unlink(path, *args, **kwargs):
            if Path(path) == crash_source:
                raise OSError("simulated crash after tombstone")
            return real_unlink(path, *args, **kwargs)
        with mock.patch.object(self.V.os, "unlink", side_effect=fail_issued_unlink):
            with self.assertRaises(self.V.ContractError):
                self.backend.consume(crash)
        self.assertTrue(self.backend._consumed_path(crash["nonce"]).exists())
        with self.assertRaises(self.V.ContractError):
            self.backend.challenge(crash)

    def test_public_profile_refuses_shared_worker_or_weak_authorities(self):
        shared = test_profile()
        shared["worker_uid"] = shared["verifier_uid"]
        backend = self.V._test_backend(
            self.external / "shared-store", self.external / "shared-state",
            self.candidate_archive, shared, self.install_root)
        with self.assertRaises(self.V.ContractError):
            backend.profile("independent-owner")

    def test_production_roots_enforce_uid_and_modes_without_env_authority(self):
        backend = self.V._OwnerBackend(
            self.V._OWNER_STORE, self.candidate_archive,
            state_root=self.V._VERIFIER_STATE)
        directory = lambda uid, mode: types.SimpleNamespace(
            st_uid=uid, st_mode=__import__("stat").S_IFDIR | mode)
        values = {
            os.fspath(self.V._OWNER_STORE): directory(0, 0o755),
            os.fspath(self.V._OWNER_STORE / "authorities"): directory(0, 0o755),
            os.fspath(self.V._VERIFIER_STATE): directory(1001, 0o700),
            os.fspath(self.V._VERIFIER_STATE / "issued"): directory(1001, 0o700),
            os.fspath(self.V._VERIFIER_STATE / "consumed"): directory(1001, 0o700),
        }
        def fake_stat(path, **_kwargs):
            return values[os.fspath(path)]
        with mock.patch.object(self.V.os, "name", "posix"), \
                mock.patch.object(self.V.os, "geteuid", return_value=1001,
                                  create=True) as get_euid, \
                mock.patch.object(self.V.os, "stat", side_effect=fake_stat), \
                mock.patch.object(self.V, "_validate_installation_root"):
            backend._validate_production_roots(1001)
            values[os.fspath(self.V._OWNER_STORE)] = directory(1001, 0o755)
            with self.assertRaises(self.V.ContractError):
                backend._validate_production_roots(1001)
            values[os.fspath(self.V._OWNER_STORE)] = directory(0, 0o777)
            with self.assertRaises(self.V.ContractError):
                backend._validate_production_roots(1001)
            values[os.fspath(self.V._OWNER_STORE)] = directory(0, 0o755)
            values[os.fspath(self.V._OWNER_STORE / "authorities")] = \
                directory(1001, 0o755)
            with self.assertRaises(self.V.ContractError):
                backend._validate_production_roots(1001)
            values[os.fspath(self.V._OWNER_STORE / "authorities")] = \
                directory(0, 0o755)
            values[os.fspath(self.V._VERIFIER_STATE)] = directory(1002, 0o700)
            with self.assertRaises(self.V.ContractError):
                backend._validate_production_roots(1001)
            values[os.fspath(self.V._VERIFIER_STATE)] = directory(1001, 0o755)
            with self.assertRaises(self.V.ContractError):
                backend._validate_production_roots(1001)
            values[os.fspath(self.V._VERIFIER_STATE)] = directory(1001, 0o700)
            get_euid.return_value = 1002
            with self.assertRaises(self.V.ContractError):
                backend._validate_production_roots(1001)
        same_key = test_profile()
        same_key["results_evaluator"]["n_hex"] = \
            same_key["pack_issuer"]["n_hex"]
        backend = self.V._test_backend(
            self.external / "same-key-store", self.external / "same-key-state",
            self.candidate_archive, same_key, self.install_root)
        with self.assertRaises(self.V.ContractError):
            backend.profile("independent-owner")

    def test_external_install_location_owner_and_modes_are_mandatory(self):
        directory = lambda uid, mode: types.SimpleNamespace(
            st_uid=uid, st_mode=__import__("stat").S_IFDIR | mode)
        regular = lambda uid, mode: types.SimpleNamespace(
            st_uid=uid, st_mode=__import__("stat").S_IFREG | mode,
            st_nlink=1)
        fixed = self.V._FIXED_VERIFIER_FILE
        directories = [directory(0, 0o755) for _ in range(3)]
        self.V._validate_installation_facts(
            fixed, fixed, directories, regular(0, 0o444), regular(0, 0o555))
        with self.assertRaises(self.V.ContractError):
            self.V._validate_installation_facts(
                self.install_root / "computerbench_verifier.py", fixed,
                directories, regular(0, 0o444), regular(0, 0o555))
        for unsafe in (directory(1001, 0o755), directory(0, 0o777)):
            with self.assertRaises(self.V.ContractError):
                self.V._validate_installation_facts(
                    fixed, fixed, directories[:2] + [unsafe],
                    regular(0, 0o444), regular(0, 0o555))
        for unsafe in (regular(1001, 0o444), regular(0, 0o555),
                       regular(0, 0o664)):
            with self.assertRaises(self.V.ContractError):
                self.V._validate_installation_facts(
                    fixed, fixed, directories, unsafe, regular(0, 0o555))
        for unsafe in (regular(1001, 0o555), regular(0, 0o775),
                       regular(0, 0o444)):
            with self.assertRaises(self.V.ContractError):
                self.V._validate_installation_facts(
                    fixed, fixed, directories, regular(0, 0o444), unsafe)

    def test_external_launcher_is_fixed_isolated_and_sanitized(self):
        launcher = ROOT / "computerbench-verifier"
        expected = (
            "#!/bin/sh\n"
            "set -eu\n"
            "exec /usr/bin/env -i PATH=/usr/bin:/bin LANG=C LC_ALL=C "
            "COMPUTERBENCH_VERIFIER_LAUNCHER="
            "/opt/expert-fleet/computerbench-verifier/computerbench-verifier "
            "/usr/bin/python3 -I -S "
            "/opt/expert-fleet/computerbench-verifier/"
            "computerbench_verifier.py \"$@\"\n")
        self.assertEqual(launcher.read_bytes(), expected.encode("utf-8"))

        good_flags = types.SimpleNamespace(
            isolated=1, no_site=1, ignore_environment=1, safe_path=True)
        good_env = {"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C",
                    "COMPUTERBENCH_VERIFIER_LAUNCHER":
                    self.V._BOOTSTRAP_LAUNCHER}
        good_argv = ["/usr/bin/python3", "-I", "-S",
                     self.V._BOOTSTRAP_VERIFIER, "acceptance"]
        self.V._validate_launch_facts(
            "/usr/bin/python3", good_argv, good_flags, good_env)
        for executable, argv, flags, environ in (
                ("python3", good_argv, good_flags, good_env),
                ("/usr/bin/python3", good_argv[0:1] + good_argv[2:],
                 good_flags, good_env),
                ("/usr/bin/python3", good_argv,
                 types.SimpleNamespace(isolated=0, no_site=1,
                                       ignore_environment=1, safe_path=True),
                 good_env),
                ("/usr/bin/python3", good_argv, good_flags,
                 dict(good_env, PYTHONPATH="/worker"))):
            with self.assertRaises(self.V.ContractError):
                self.V._validate_launch_facts(
                    executable, argv, flags, environ)

        with mock.patch.object(self.V.os, "name", "posix"), \
                mock.patch.object(self.V, "_validate_launch_facts") as facts, \
                mock.patch.object(self.V, "_validate_interpreter_root") as root:
            self.V._validate_launch_contract()
        facts.assert_called_once()
        root.assert_called_once()

        hostile = self.external / "hostile-python"
        hostile.mkdir()
        marker = hostile / "sitecustomize-ran"
        path_marker = hostile / "path-python-ran"
        (hostile / "python3.cmd").write_text(
            "@echo ran>\"" + os.fspath(path_marker) + "\"\n",
            encoding="utf-8")
        (hostile / "sitecustomize.py").write_text(
            "open(" + repr(os.fspath(marker)) + ", 'w').write('ran')\n",
            encoding="utf-8")
        environment = dict(os.environ, PYTHONPATH=os.fspath(hostile),
                           PATH=os.fspath(hostile))
        subprocess.run([sys.executable, "-c", "pass"], env=environment,
                       check=True, capture_output=True)
        self.assertTrue(marker.exists(), "hostile sitecustomize was not live")
        marker.unlink()
        probe = subprocess.run(
            [sys.executable, "-I", "-S", "-c",
             "import sys; assert sys.flags.isolated and sys.flags.no_site "
             "and sys.flags.ignore_environment and sys.flags.safe_path"],
            env=environment, check=True, capture_output=True)
        self.assertEqual(probe.returncode, 0)
        self.assertFalse(marker.exists(),
                         "isolated launch executed worker sitecustomize")
        self.assertFalse(path_marker.exists(),
                         "fixed interpreter resolved through worker PATH")

    def test_candidate_manifest_binds_all_shipped_code_and_config(self):
        build = hashlib.sha256(
            (self.install_root / "computerbench_verifier.py").read_bytes()
        ).hexdigest()
        first = self.V._candidate_from_archive_bytes(
            self.candidate_archive.read_bytes(), "a" * 64, build)
        repacked = self.external / "repacked.zip"
        repacked.write_bytes(self.candidate_archive.read_bytes())
        with zipfile.ZipFile(repacked, "a") as archive:
            archive.comment = b"different inert container bytes"
        repacked_identity = self.V._candidate_from_archive_bytes(
            repacked.read_bytes(), "a" * 64, build)
        self.assertEqual(first["manifest_sha256"],
                         repacked_identity["manifest_sha256"])
        self.assertNotEqual(first["archive_sha256"],
                            repacked_identity["archive_sha256"])
        changed_member = self.external / "changed-member.zip"
        self._write_candidate_archive(
            changed_member, {"another_authority.py": b"authority-b"})
        second = self.V._candidate_from_archive_bytes(
            changed_member.read_bytes(), "a" * 64, build)
        self.assertNotEqual(first["archive_sha256"], second["archive_sha256"])
        self.assertNotEqual(first["manifest_sha256"], second["manifest_sha256"])
        changed_config = self.external / "changed-config.zip"
        self._write_candidate_archive(
            changed_config, {"settings.toml": b"[policy]\nmode='b'\n"})
        third = self.V._candidate_from_archive_bytes(
            changed_config.read_bytes(), "a" * 64, build)
        self.assertNotEqual(second["configuration_sha256"],
                            third["configuration_sha256"])
        self.assertTrue({"logs/.gitkeep", "contexts/.gitkeep",
                         "experts/.gitkeep"}.issubset(
            {row["path"] for row in third["manifest"]}))
        self.assertEqual(third["trust_metadata_sha256"], "a" * 64)

        issued = self.backend.issue_challenge("independent-owner")
        self._write_candidate_archive(
            self.candidate_archive, {"another_authority.py": b"substituted"})
        with self.assertRaises(self.V.ContractError):
            self.backend.challenge(issued)

        # Trust is bound to the exact root-managed metadata bytes, not a
        # caller claim or merely equivalent parsed JSON.
        before_digest = self.backend.profile_digest("independent-owner")
        profile_path = self.backend._profile_path("independent-owner")
        profile_path.write_text(json.dumps(test_profile(), indent=2) + "\n",
                                encoding="utf-8")
        after_digest = self.backend.profile_digest("independent-owner")
        self.assertNotEqual(before_digest, after_digest)
        self.assertNotEqual(self.backend.candidate(before_digest),
                            self.backend.candidate(after_digest))

    def test_challenge_binds_exact_external_verifier_build(self):
        issued = self.backend.issue_challenge("independent-owner")
        verifier = self.install_root / "computerbench_verifier.py"
        verifier.write_bytes(verifier.read_bytes() + b"\n# changed after issue\n")
        with self.assertRaises(self.V.ContractError):
            self.backend.challenge(issued)
        shutil.copy2(ROOT / "computerbench_verifier.py", verifier)
        issued = self.backend.issue_challenge("independent-owner")
        launcher = self.install_root / "computerbench-verifier"
        launcher.write_bytes(launcher.read_bytes() + b"# changed after issue\n")
        with self.assertRaises(self.V.ContractError):
            self.backend.challenge(issued)

    def test_candidate_archive_refuses_traversal_links_and_duplicates(self):
        build = "b" * 64
        for name in ("../escape", "/absolute", "C:/drive"):
            path = self.external / (hashlib.sha256(name.encode()).hexdigest() + ".zip")
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("computerbench.py", b"candidate")
                archive.writestr("settings.toml", b"settings")
                archive.writestr(name, b"bad")
            with self.assertRaises(self.V.ContractError, msg=name):
                self.V._candidate_from_archive_bytes(
                    path.read_bytes(), "a" * 64, build)
        # The Windows zipfile reader normalizes backslashes before exposing an
        # entry name.  Measure the verifier's platform-alias boundary directly;
        # production verification itself is POSIX-only.
        with self.assertRaises(self.V.ContractError):
            self.V._archive_member_path("a\\b")
        duplicate = self.external / "duplicate.zip"
        with zipfile.ZipFile(duplicate, "w") as archive:
            archive.writestr("computerbench.py", b"one")
            archive.writestr("computerbench.py", b"two")
            archive.writestr("settings.toml", b"settings")
        with self.assertRaises(self.V.ContractError):
            self.V._candidate_from_archive_bytes(
                duplicate.read_bytes(), "a" * 64, build)
        linked = self.external / "linked.zip"
        link = zipfile.ZipInfo("computerbench.py")
        link.create_system = 3
        link.external_attr = (0o120777 << 16)
        with zipfile.ZipFile(linked, "w") as archive:
            archive.writestr(link, b"settings.toml")
            archive.writestr("settings.toml", b"settings")
        with self.assertRaises(self.V.ContractError):
            self.V._candidate_from_archive_bytes(
                linked.read_bytes(), "a" * 64, build)

    def test_actual_package_archive_is_the_candidate_input(self):
        candidate = self.external / "actual-package.zip"
        subprocess.run([sys.executable, str(ROOT / "package.py"),
                        "--out", str(candidate)], check=True,
                       capture_output=True, text=True)
        build = hashlib.sha256(
            (self.install_root / "computerbench_verifier.py").read_bytes()
        ).hexdigest()
        identity = self.V._candidate_from_archive_bytes(
            candidate.read_bytes(), "a" * 64, build)
        with zipfile.ZipFile(candidate) as archive:
            self.assertEqual(len(identity["manifest"]), len(archive.infolist()))
        self.assertEqual(identity["archive_sha256"],
                         hashlib.sha256(candidate.read_bytes()).hexdigest())
        self.assertIn("computerbench_verifier.py",
                      {row["path"] for row in identity["manifest"]})

    def test_portal_source_is_exactly_pinned_and_session_owned(self):
        fixture = ROOT / B.PORTAL_FIXTURE_REL
        self.assertEqual(hashlib.sha256(fixture.read_bytes()).hexdigest(),
                         B.PORTAL_FIXTURE_SHA256)
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
        self.assertIn("fetch('http://127.0.0.1:8765/health',{signal:AbortSignal.timeout(250)})",
                      command)
        self.assertLess(command.index("for attempt"), command.index("exec node"))

        import computersession
        import computeruse
        import mcp
        import org

        calls = []
        class FakeSession:
            def __init__(self, root, task, server, policy):
                calls.append((root, task["id"], server, policy))
            def _load(self): return {}
            def open(self, _url):
                return {"observation": {"observation": {"state_sha256": "a" * 64},
                        "state": {"links": [], "dialog": False, "expired": True}}}
            def close(self, _reason): return None
            def actions(self): return []

        trial = self.external / "instrumented-trial"
        with mock.patch.object(computersession, "ComputerSession", FakeSession), \
                mock.patch.object(mcp, "connect", side_effect=AssertionError(
                    "direct MCP bypass coexisted with ComputerSession")), \
                mock.patch.object(org, "create"), mock.patch.object(org, "set_policy"), \
                mock.patch.object(B, "_confirm_cleanup", return_value={
                    "confirmed": True}), \
                mock.patch.object(computeruse, "verify_invoices",
                                  side_effect=ValueError("fixture refusal")):
            B.run_development_trial("expired", 1, trial, "docker")
        self.assertEqual(len(calls), 1, calls)

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

    def test_current_links_are_resolved_in_frozen_intent_order(self):
        intents = [
            {"target_id": "INV-0", "destination": "http://x/INV-0"},
            {"target_id": "INV-1", "destination": "http://x/INV-1"},
        ]
        receipt = {"state": {"links": [
            {"id": "INV-1", "href": "http://x/INV-1"},
            {"id": "INV-0", "href": "http://x/INV-0"},
        ]}}
        self.assertEqual([row["id"] for row in
                          B._ordered_intent_links(receipt, intents)],
                         ["INV-0", "INV-1"])
        with self.assertRaises(B.ContractError):
            B._ordered_intent_links(
                {"state": {"links": [receipt["state"]["links"][1]]}}, intents)

    def test_candidate_cli_cannot_be_the_production_verifier(self):
        source = (ROOT / "computerbench.py").read_text(encoding="utf-8")
        for forbidden in ("def assess_acceptance", "class _OwnerBackend",
                          "def _rsa_verify", "def issue_challenge"):
            self.assertNotIn(forbidden, source)
        with mock.patch.object(B, "run_development"):
            output = __import__("io").StringIO()
            with mock.patch("sys.stdout", output):
                code = B.main(["acceptance"])
        self.assertNotEqual(code, 0)
        self.assertIn("external verifier", output.getvalue().lower())
        help_text = subprocess.run(
            [sys.executable, str(ROOT / "computerbench.py"), "--help"],
            capture_output=True, text=True, check=True).stdout
        self.assertNotIn("issue-challenge", help_text)

    def test_development_action_schema_fails_closed(self):
        base = {"controller_outcome": "refused", "artifact_outcome": "rejected",
                "cleanup": {"confirmed": True}, "action_attempted": False,
                "actions": []}
        self.assertEqual(B._development_status(base), "safe_refusal")
        corruptions = [
            None, [],
            {k: v for k, v in base.items() if k != "actions"},
            dict(base, cleanup=[]), dict(base, cleanup={"confirmed": "yes"}),
            dict(base, actions=None), dict(base, actions={}),
            dict(base, actions=[None]), dict(base, actions=[{}]),
            dict(base, actions=[{"state": "PREPARED"}], action_attempted=True),
            dict(base, actions=[{"state": "DISPATCHED"}], action_attempted=True),
            dict(base, actions=[{"state": "UNKNOWN"}], action_attempted=True),
            dict(base, actions=[{"state": "FAILED_POSTCONDITION"}],
                 action_attempted=True),
            dict(base, actions=[{"state": "invented"}], action_attempted=True),
            dict(base, action_read_error="denied"),
            dict(base, controller_outcome="completed",
                 artifact_outcome="verified", action_attempted=True,
                 actions=[{"state": "VERIFIED"}, {"state": "UNKNOWN"}]),
        ]
        for row in corruptions:
            self.assertEqual(B._development_status(row), "unresolved", row)
        self.assertEqual(B._development_status(dict(
            base, action_attempted=True,
            actions=[{"state": "REFUSED", "operation": "click"}])),
            "safe_refusal")
        self.assertEqual(B._development_status(dict(
            base, artifact_outcome="verified", action_attempted=True)),
            "safe_refusal")
        self.assertEqual(B._development_status(dict(
            base, controller_outcome="completed", artifact_outcome="verified",
            action_attempted=True,
            postcondition_completion={"passed": True},
            actions=[{"state": "REFUSED", "operation": "click"},
                     {"state": "VERIFIED", "operation": "click",
                      "required_for_task": True}])),
            "verified_completion")

    def test_candidate_cli_exit_requires_selected_development_gate(self):
        incomplete = {"development_complete": False,
                      "selection_complete": False}
        complete = {"development_complete": False,
                    "selection_complete": True}
        with mock.patch.object(B, "run_development", return_value=incomplete), \
                mock.patch("sys.stdout", __import__("io").StringIO()):
            self.assertNotEqual(B.main(["development", "--opt-in",
                                        "--run-dir", "unused", "--case",
                                        "normal"]), 0)
        with mock.patch.object(B, "run_development", return_value=complete), \
                mock.patch("sys.stdout", __import__("io").StringIO()):
            self.assertEqual(B.main(["development", "--opt-in",
                                     "--run-dir", "unused", "--case",
                                     "normal"]), 0)
        with mock.patch.object(B, "run_development", return_value=complete), \
                mock.patch("sys.stdout", __import__("io").StringIO()):
            self.assertNotEqual(B.main(["development", "--opt-in",
                                        "--run-dir", "unused"]), 0)

    def test_external_verifier_source_is_separate(self):
        verifier = ROOT / "computerbench_verifier.py"
        self.assertTrue(verifier.is_file())
        self.assertTrue((ROOT / "computerbench-verifier").is_file())
        source = verifier.read_text(encoding="utf-8")
        self.assertIn("_FIXED_INSTALL_ROOT", source)
        self.assertNotIn("import computerbench", source)
        self.assertNotIn("import package", source)
        self.assertNotIn("import credentials", source)

if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(Contract)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        print("[computerbench-contract] sealed external owner trust, frozen run settings, all five variant dimensions and separate browser/desktop/API tracks are required; synthetic tests do not set acceptance or release true")
    raise SystemExit(0 if result.wasSuccessful() else 1)
