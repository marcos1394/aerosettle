"""Prepare, but never publish, a fresh CON-59 Pages release from finalized RPC.

This operator command requires a clean source tree and the local Wrangler
session. It prints the exact approval tuple for the separate guarded deploy.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

from tools.integration.devnet import gateway as g, snapshot


ROOT = Path(__file__).resolve().parents[3]
ACCOUNT_ID = "54cb929430c4a02b90d6ea3ce356d0d9"
PROJECT = "conatus-devnet-staging"
URL = "https://conatus-devnet-staging.pages.dev/"
WEB = ROOT / "apps/marketplace-web"
SCRIPTS = WEB / "scripts"


def command(*parts: str, capture: bool = False) -> str:
    completed = subprocess.run(list(parts), cwd=ROOT, check=True, text=True,
                               stdout=subprocess.PIPE if capture else None)
    return completed.stdout.strip() if capture else ""


def require_clean_source() -> str:
    if command("git", "status", "--porcelain", "--untracked-files=normal", capture=True):
        raise ValueError("SOURCE_TREE_DIRTY")
    sha = command("git", "rev-parse", "HEAD", capture=True)
    if len(sha) != 40 or any(character not in "0123456789abcdef" for character in sha):
        raise ValueError("SOURCE_COMMIT_INVALID")
    return sha


def prepare(artifact_dir: Path, wrangler: Path, *, now: datetime | None = None) -> dict:
    artifact_dir = artifact_dir.resolve()
    wrangler = wrangler.resolve()
    if not artifact_dir.is_absolute() or artifact_dir.exists() or not wrangler.is_file():
        raise ValueError("ARTIFACT_OR_WRANGLER_INVALID")
    sha = require_clean_source()
    observed = now or datetime.now(timezone.utc)
    if observed.tzinfo is None:
        raise ValueError("TIMEZONE_REQUIRED")
    command("npm", "run", "build:devnet", "--prefix", str(WEB))
    command("node", "--experimental-strip-types", str(SCRIPTS / "verify-build.mjs"), "devnet")

    # The existing indexer verifies complete CON-35 program/IDL/mint identity
    # before and after account reads. It sends only approved read-only RPC calls.
    index = g.Index(g.Provider("official-devnet", g.JsonRpc()))
    raw = snapshot.serialize(snapshot.create(index, now=datetime.now(timezone.utc)))
    artifact_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(WEB / "dist-devnet", artifact_dir)
    snapshot_file = artifact_dir.parent / (artifact_dir.name + ".snapshot.json")
    snapshot_file.write_bytes(raw)
    command("node", "--experimental-strip-types", str(SCRIPTS / "con59-package.mjs"),
            str(artifact_dir), str(snapshot_file))
    timestamp = observed.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    command("node", "--experimental-strip-types", str(SCRIPTS / "con58-release.mjs"),
            "prepare", str(artifact_dir), sha, timestamp)
    release = json.loads((artifact_dir / "release.json").read_text())
    release_id = release["release_id"]
    command("node", "--experimental-strip-types", str(SCRIPTS / "con58-release.mjs"),
            "verify", str(artifact_dir), release_id, sha)
    command("node", "--experimental-strip-types", str(SCRIPTS / "con58-pages-deploy.mjs"),
            "preflight", str(artifact_dir), release_id, sha, ACCOUNT_ID, PROJECT, URL, str(wrangler))
    return {"status": "PENDING_EXACT_HUMAN_APPROVAL", "source_commit": sha,
            "release_id": release_id, "artifact_digest": release["artifact_digest"],
            "manifest_sha256": release["manifest_sha256"],
            "idl_sha256": release["idl_sha256"],
            "snapshot_sha256": release["snapshot_sha256"],
            "snapshot_expires_at": release["snapshot_expires_at"],
            "snapshot_file_sha256": hashlib.sha256(raw).hexdigest(),
            "genesis_hash": release["genesis_hash"], "program_id": release["program_id"],
            "test_mint": release["token_mint"],
            "account_id": ACCOUNT_ID, "project": PROJECT, "url": URL,
            "artifact_dir": str(artifact_dir), "deployment_submitted": False,
            "solana_transactions_sent": 0}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact_dir", type=Path, help="New absolute private directory for upload bytes")
    parser.add_argument("wrangler_bin", type=Path, help="Local authenticated Wrangler executable")
    parser.add_argument("plan_file", type=Path, help="Private JSON approval plan path")
    args = parser.parse_args()
    if not args.artifact_dir.is_absolute() or not args.wrangler_bin.is_absolute():
        parser.error("artifact_dir and wrangler_bin must be absolute")
    if args.plan_file.exists():
        parser.error("plan_file already exists")
    plan = prepare(args.artifact_dir, args.wrangler_bin)
    args.plan_file.write_text(json.dumps(plan, sort_keys=True, indent=2) + "\n")
    print(json.dumps(plan, sort_keys=True))


if __name__ == "__main__":
    main()
