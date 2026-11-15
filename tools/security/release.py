"""Independent, fail-closed verification of a proposed release bundle.

The trusted policy is supplied out of band by the release reviewer. A policy
checked out from the same pull request is insufficient deployment authority.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


FIELDS = frozenset({
    "repository", "commit_sha", "program_id", "network", "genesis_hash",
    "artifact_sha256", "idl_sha256", "toolchain_versions", "sbom_sha256",
    "approval_identifier", "upgrade_authority_pubkey", "created_at",
})
HASH = re.compile(r"[0-9a-f]{64}\Z")
COMMIT = re.compile(r"[0-9a-f]{40}\Z")


class ReleaseRejected(ValueError):
    """The bundle cannot be used as release evidence."""


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise ReleaseRejected(reason)


def canonical(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def approval_identifier(manifest: dict) -> str:
    unsigned = {key: value for key, value in manifest.items() if key != "approval_identifier"}
    return hashlib.sha256(canonical(unsigned)).hexdigest()


def verify(manifest: dict, signature: dict, policy: dict, *, artifact: Path, idl: Path,
           sbom: Path, approved_identifier: str | None) -> dict:
    require(type(manifest) is dict and set(manifest) == FIELDS, "Manifest schema mismatch")
    require(type(signature) is dict and set(signature) == {"key_id", "ed25519_signature_base64"},
            "Signature envelope mismatch")
    require(type(policy) is dict, "Trusted policy missing")
    require(manifest["network"] == "solana:devnet" and policy.get("network") == "solana:devnet",
            "Mainnet and unapproved networks are disabled")
    for field in ("repository", "program_id", "genesis_hash", "upgrade_authority_pubkey"):
        require(type(manifest[field]) is str and manifest[field] == policy.get(field),
                f"Unapproved {field}")
    require(type(manifest["commit_sha"]) is str and COMMIT.fullmatch(manifest["commit_sha"]) is not None,
            "Invalid source commit")
    require(type(manifest["created_at"]) is str and manifest["created_at"].endswith("Z"),
            "UTC creation time required")
    require(type(manifest["toolchain_versions"]) is dict and
            manifest["toolchain_versions"] == policy.get("toolchain_versions"),
            "Toolchain mismatch")
    for key, path in (("artifact_sha256", artifact), ("idl_sha256", idl), ("sbom_sha256", sbom)):
        require(type(manifest[key]) is str and HASH.fullmatch(manifest[key]) is not None,
                f"Malformed {key}")
        require(path.is_file() and digest(path) == manifest[key], f"{key} differs from artifact")
    require(manifest["approval_identifier"] == approval_identifier(manifest),
            "Manifest approval identifier mismatch")
    require(type(approved_identifier) is str and approved_identifier == manifest["approval_identifier"],
            "Independent approval for this exact release is required")
    keys = policy.get("trusted_release_keys")
    require(type(keys) is dict and signature["key_id"] in keys,
            "No independently trusted release signing key")
    try:
        public_key = base64.b64decode(keys[signature["key_id"]], validate=True)
        signed_bytes = base64.b64decode(signature["ed25519_signature_base64"], validate=True)
        require(len(public_key) == 32 and len(signed_bytes) == 64, "Invalid Ed25519 encoding")
        Ed25519PublicKey.from_public_bytes(public_key).verify(signed_bytes, canonical(manifest))
    except (InvalidSignature, ValueError, TypeError) as exc:
        raise ReleaseRejected("Invalid release signature") from exc
    return {"status": "VERIFIED", "approval_identifier": approved_identifier,
            "artifact_sha256": manifest["artifact_sha256"], "network": manifest["network"]}


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a signed release; never deploys")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--signature", type=Path, required=True)
    parser.add_argument("--trusted-policy", type=Path, required=True,
                        help="Must come from an independent, protected approval channel")
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--idl", type=Path, required=True)
    parser.add_argument("--sbom", type=Path, required=True)
    parser.add_argument("--approved-identifier", required=True)
    args = parser.parse_args()
    try:
        repository_root = Path(__file__).resolve().parents[2]
        require(not args.trusted_policy.resolve().is_relative_to(repository_root),
                "Trusted policy must be outside the repository")
        result = verify(json.loads(args.manifest.read_text()), json.loads(args.signature.read_text()),
                        json.loads(args.trusted_policy.read_text()), artifact=args.artifact,
                        idl=args.idl, sbom=args.sbom, approved_identifier=args.approved_identifier)
    except (ReleaseRejected, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "FAILED", "reason": str(exc)}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
