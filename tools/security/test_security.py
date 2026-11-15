import base64
import hashlib
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tools.security.dependency_audit import evaluate
from tools.security.release import ReleaseRejected, approval_identifier, canonical, verify
from tools.security.sbom import LOCKS, NPM_LOCKS, validate
from tools.security.workflow_policy import check_text


class SecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        folder = Path(self.temp.name)
        self.files = {}
        for name in ("artifact", "idl", "sbom"):
            path = folder / name
            path.write_bytes(name.encode())
            self.files[name] = path
        self.key = Ed25519PrivateKey.generate()
        public = self.key.public_key().public_bytes(serialization.Encoding.Raw,
                                                     serialization.PublicFormat.Raw)
        self.policy = {
            "repository": "marcos1394/aerosettle", "network": "solana:devnet",
            "genesis_hash": "devnet-genesis", "program_id": "approved-program",
            "upgrade_authority_pubkey": "approved-authority",
            "toolchain_versions": {"rust": "1.89.0", "solana": "4.1.2"},
            "trusted_release_keys": {"reviewer": base64.b64encode(public).decode()},
        }
        self.manifest = {
            "repository": self.policy["repository"], "commit_sha": "a" * 40,
            "program_id": self.policy["program_id"], "network": "solana:devnet",
            "genesis_hash": self.policy["genesis_hash"],
            "artifact_sha256": hashlib.sha256(b"artifact").hexdigest(),
            "idl_sha256": hashlib.sha256(b"idl").hexdigest(),
            "sbom_sha256": hashlib.sha256(b"sbom").hexdigest(),
            "toolchain_versions": self.policy["toolchain_versions"],
            "approval_identifier": "", "upgrade_authority_pubkey": "approved-authority",
            "created_at": "2026-11-08T00:00:00Z",
        }
        self.seal()

    def seal(self):
        self.manifest["approval_identifier"] = approval_identifier(self.manifest)
        self.signature = {"key_id": "reviewer", "ed25519_signature_base64":
                          base64.b64encode(self.key.sign(canonical(self.manifest))).decode()}

    def verify(self, approval=None):
        return verify(self.manifest, self.signature, self.policy,
                      artifact=self.files["artifact"], idl=self.files["idl"],
                      sbom=self.files["sbom"],
                      approved_identifier=self.manifest["approval_identifier"] if approval is None else approval)

    def test_valid_bundle(self):
        self.assertEqual(self.verify()["status"], "VERIFIED")

    def test_artifact_idl_and_sbom_substitution(self):
        for name in self.files:
            with self.subTest(name=name):
                self.files[name].write_bytes(b"substitution")
                with self.assertRaises(ReleaseRejected):
                    self.verify()
                self.files[name].write_bytes(name.encode())

    def test_manifest_context_signature_and_approval(self):
        for field in ("program_id", "genesis_hash", "upgrade_authority_pubkey"):
            with self.subTest(field=field):
                original = self.manifest[field]
                self.manifest[field] = "wrong"
                self.seal()
                with self.assertRaises(ReleaseRejected):
                    self.verify()
                self.manifest[field] = original
                self.seal()
        with self.assertRaisesRegex(ReleaseRejected, "approval"):
            self.verify(approval="wrong")
        self.signature["ed25519_signature_base64"] = base64.b64encode(b"0" * 64).decode()
        with self.assertRaisesRegex(ReleaseRejected, "signature"):
            self.verify()

    def test_mainnet_toolchain_and_untrusted_key_rejected(self):
        self.manifest["network"] = "solana:mainnet-beta"
        self.seal()
        with self.assertRaisesRegex(ReleaseRejected, "Mainnet"):
            self.verify()
        self.manifest["network"] = "solana:devnet"
        self.manifest["toolchain_versions"] = {"rust": "1.90.0"}
        self.seal()
        with self.assertRaisesRegex(ReleaseRejected, "Toolchain"):
            self.verify()
        self.manifest["toolchain_versions"] = self.policy["toolchain_versions"]
        self.seal()
        self.policy["trusted_release_keys"] = {}
        with self.assertRaisesRegex(ReleaseRejected, "trusted"):
            self.verify()

    def test_workflow_rejects_privilege_and_deployment(self):
        good = ("name: secure\non:\n  pull_request:\npermissions:\n  contents: read\n"
                "jobs:\n  check:\n    steps:\n"
                "      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262\n")
        self.assertEqual(check_text(good), [])
        for bad in ("  pull_request_target:\n", "  contents: write\n",
                    "      - run: solana program deploy binary.so\n",
                    "      - run: python tools/deployment/devnet.py deploy --submit\n",
                    "      - run: echo ${{ secrets.PRIVATE_KEY }}\n",
                    "      - uses: actions/checkout@v4\n",
                    "      - run: echo mainnet-beta\n",
                    "        continue-on-error: true\n"):
            with self.subTest(bad=bad):
                self.assertTrue(check_text(good + bad))

    def test_sbom_missing_scope_and_lock_hash(self):
        scopes = ("rust", "python", *NPM_LOCKS)
        components = [{"bom-ref": f"{x}:1", "properties": [{"name": "conatus:scope", "value": x}]}
                      for x in scopes]
        properties = [{"name": "conatus:manifest-sha256:" + x, "value": "0" * 64} for x in LOCKS]
        bom = {"bomFormat": "CycloneDX", "specVersion": "1.5", "components": components,
               "metadata": {"properties": properties}}
        validate(bom)
        bom["components"].pop()
        with self.assertRaisesRegex(ValueError, "omits"):
            validate(bom)

    def test_unexcepted_advisory_and_audit_error(self):
        root = Path(self.temp.name)
        for scope in NPM_LOCKS:
            path = root / scope
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"packages": {"node_modules/example": {"version": "1.0.0"}}}))
        reports = {scope: {"vulnerabilities": {}} for scope in NPM_LOCKS}
        reports[NPM_LOCKS[0]]["vulnerabilities"] = {"example": {"via": [{
            "name": "example", "severity": "high",
            "url": "https://github.com/advisories/GHSA-aaaa-bbbb-cccc"}]}}
        with self.assertRaisesRegex(ValueError, "Unexcepted"):
            evaluate(root, reports, [], today=date(2026, 11, 8))
        exception = json.loads(Path("tools/security/dependency-exceptions.json").read_text())[0]
        exception["review_date"] = "2020-01-01"
        with self.assertRaisesRegex(ValueError, "Expired"):
            evaluate(root, reports, [exception], today=date(2026, 11, 8))
        reports[NPM_LOCKS[0]] = {"error": "audit unavailable"}
        with self.assertRaisesRegex(ValueError, "unavailable"):
            evaluate(root, reports, [], today=date(2026, 11, 8))
