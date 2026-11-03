"""Pinned CON-35 Devnet identity; an IDL supplied by a caller is never an anchor."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tools.discovery.agent_discovery import DiscoveryError, b58decode
from tools.deployment.devnet import DeploymentError, inspect_program
from .cards import CardError

ROOT = Path(__file__).resolve().parents[2]
VERIFIED_MANIFEST = ROOT / "evidence/con35/devnet-deployment.json"
DEPLOYMENT_CONFIG = ROOT / "tools/deployment/devnet.json"
APPROVED_IDL = ROOT / "evidence/con35/artifacts/aerosettle-idl.json"

# Independently pinned from the verified CON-35 deployment, not read from IDL.
PROGRAM_ID = "CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy"
GENESIS_HASH = "EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG"
NETWORK = "solana:devnet"
RPC_URL = "https://api.devnet.solana.com"
IDL_VERSION = "0.1.0"
IDL_SPEC = "0.1.0"
IDL_SHA256 = "a6e436aa1c6468b4f518b742e40a2664e38dcdf7bc1419e53e1624444888e15d"
DEPLOYMENT_ID = "06c7dfa7528460969a5ca1e8bd001f9c9f1f1f0df3d69fe36649e413e0b14ae6"
MANIFEST_SHA256 = "a47cf814f12e9f9e39ca5881b66ff4f9e96adb32ddbbcf867f877c5205154e58"
PROGRAM_DATA_ADDRESS = "7kYZxnujXJ9sKGhG9CbDwThJECb693WvvqVFHGmNSsrr"
UPGRADE_AUTHORITY = "DdHrtAxE5SwcVQUgoKRzoWatZ5yw9UdtBQnRwBizPK2D"
DEPLOYMENT_SLOT = 516258865


def _read_json(path: Path) -> tuple[bytes, dict]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("Object expected")
        return raw, value
    except (OSError, ValueError) as exc:
        raise CardError("INVALID_TRUST_POLICY") from exc


def verify_approved_identity(idl_path: Path, rpc_url: str) -> dict:
    """Recheck pinned CON-35 evidence and the complete IDL bytes before RPC."""
    manifest_raw, manifest = _read_json(VERIFIED_MANIFEST)
    _, config = _read_json(DEPLOYMENT_CONFIG)
    idl_raw, idl = _read_json(Path(idl_path))
    if (hashlib.sha256(manifest_raw).hexdigest() != MANIFEST_SHA256 or
            manifest.get("verification_status") != "VERIFIED" or
            manifest.get("deployment_id") != DEPLOYMENT_ID or
            manifest.get("program_id") != PROGRAM_ID or
            manifest.get("genesis_hash") != GENESIS_HASH or
            manifest.get("network") != NETWORK or
            manifest.get("idl_sha256") != IDL_SHA256 or
            manifest.get("program_data_address") != PROGRAM_DATA_ADDRESS or
            manifest.get("upgrade_authority_pubkey") != UPGRADE_AUTHORITY or
            manifest.get("deployment_slot") != DEPLOYMENT_SLOT or
            config.get("program_id") != PROGRAM_ID or
            config.get("genesis_hash") != GENESIS_HASH or
            config.get("network") != NETWORK or
            config.get("upgrade_authority_pubkey") != UPGRADE_AUTHORITY or
            config.get("rpc_url") != RPC_URL or rpc_url != RPC_URL or
            hashlib.sha256(idl_raw).hexdigest() != IDL_SHA256 or
            idl.get("address") != PROGRAM_ID or
            not isinstance(idl.get("metadata"), dict) or
            idl["metadata"].get("version") != IDL_VERSION or
            idl["metadata"].get("spec") != IDL_SPEC):
        raise CardError("INVALID_TRUST_POLICY")
    try:
        b58decode(PROGRAM_ID, 32)
        b58decode(GENESIS_HASH, 32)
    except DiscoveryError as exc:
        raise CardError("INVALID_TRUST_POLICY") from exc
    return idl


def verify_live_program(rpc) -> None:
    """Reuse CON-35's upgradeable-loader and ProgramData checks, read-only."""
    _, config = _read_json(DEPLOYMENT_CONFIG)
    try:
        observed = inspect_program(config, rpc)
    except (DeploymentError, DiscoveryError, OSError, ValueError, TypeError, KeyError) as exc:
        raise CardError("INVALID_IDENTITY") from exc
    if (not isinstance(observed, dict) or observed.get("exists") is not True or
            observed.get("program_id") != PROGRAM_ID or
            observed.get("program_data_address") != PROGRAM_DATA_ADDRESS or
            observed.get("upgrade_authority_pubkey") != UPGRADE_AUTHORITY or
            observed.get("deployment_slot") != DEPLOYMENT_SLOT or
            observed.get("executable") is not True):
        raise CardError("INVALID_IDENTITY")
