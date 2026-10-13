#!/usr/bin/env python3
"""AeroSettle EPIC 3.2 — read-only, IDL-driven discovery of on-chain accounts.

Python 3.11 stdlib only. No private keys, signing, writes or direct claims.
The JSON output is a validated input snapshot for EPIC 3.3's Rust matching adapter.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import struct
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
B58MAP = {c: i for i, c in enumerate(B58)}
CLOCK_SYSVAR = "SysvarC1ock11111111111111111111111111111111"
PDA_MARKER = b"ProgramDerivedAddress"


class DiscoveryError(Exception):
    pass


def b58encode(data: bytes) -> str:
    n = int.from_bytes(data, "big")
    chars = ""
    while n:
        n, r = divmod(n, 58)
        chars = B58[r] + chars
    return "1" * (len(data) - len(data.lstrip(b"\0"))) + chars


def b58decode(value: str, expected_len: int | None = None) -> bytes:
    if not isinstance(value, str) or not value:
        raise DiscoveryError("Invalid base58 string")
    n = 0
    for c in value:
        if c not in B58MAP:
            raise DiscoveryError(f"Invalid base58 character: {c!r}")
        n = n * 58 + B58MAP[c]
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    raw = b"\0" * (len(value) - len(value.lstrip("1"))) + raw
    if expected_len is not None and len(raw) != expected_len:
        raise DiscoveryError(f"Pubkey must be {expected_len} bytes, got {len(raw)}")
    if b58encode(raw) != value:
        raise DiscoveryError("Non-canonical base58")
    return raw


def is_ed25519_curve_point(compressed: bytes) -> bool:
    """Check compressed Edwards-y decompression for Solana findProgramAddress."""
    if len(compressed) != 32:
        return False
    p = 2**255 - 19
    yraw = int.from_bytes(compressed, "little")
    y, sign = yraw & ((1 << 255) - 1), yraw >> 255
    if y >= p:
        return False
    d = (-121665 * pow(121666, p - 2, p)) % p
    y2 = y * y % p
    numerator = (y2 - 1) % p
    denominator = (d * y2 + 1) % p
    if denominator == 0:
        return False
    x2 = numerator * pow(denominator, p - 2, p) % p
    x = pow(x2, (p + 3) // 8, p)
    if x * x % p != x2:
        x = x * pow(2, (p - 1) // 4, p) % p
    if x * x % p != x2 or (x == 0 and sign):
        return False
    return True


def find_program_address(seeds: list[bytes], program_id: str) -> str:
    if len(seeds) > 16 or any(len(seed) > 32 for seed in seeds):
        raise DiscoveryError("Invalid PDA seeds")
    program_bytes = b58decode(program_id, 32)
    for bump in range(255, -1, -1):
        h = hashlib.sha256(b"".join([*seeds, bytes([bump]), program_bytes, PDA_MARKER])).digest()
        if not is_ed25519_curve_point(h):
            return b58encode(h)
    raise DiscoveryError("No valid PDA bump")


def normalize_field(name: str) -> str:
    import re
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


class Reader:
    def __init__(self, data: bytes, types: dict[str, dict[str, Any]]):
        self.data, self.position, self.types = data, 0, types

    def read(self, n: int) -> bytes:
        if n < 0 or self.position + n > len(self.data):
            raise DiscoveryError("Truncated Borsh account")
        result = self.data[self.position:self.position + n]
        self.position += n
        return result

    def decode(self, kind: Any, depth: int = 0) -> Any:
        if depth > 32:
            raise DiscoveryError("Borsh nesting limit exceeded")
        if isinstance(kind, str):
            if kind in {"pubkey", "publicKey"}:
                return b58encode(self.read(32))
            primitives = {
                "u8": (1, False), "i8": (1, True), "u16": (2, False),
                "i16": (2, True), "u32": (4, False), "i32": (4, True),
                "u64": (8, False), "i64": (8, True),
                "u128": (16, False), "i128": (16, True),
            }
            if kind in primitives:
                n, signed = primitives[kind]
                return int.from_bytes(self.read(n), "little", signed=signed)
            if kind == "bool":
                value = self.read(1)[0]
                if value not in (0, 1):
                    raise DiscoveryError("Invalid Borsh bool")
                return bool(value)
            if kind == "string":
                n = self.decode("u32", depth + 1)
                if n > 1_000_000:
                    raise DiscoveryError("Oversized string")
                return self.read(n).decode("utf-8")
            if kind == "bytes":
                n = self.decode("u32", depth + 1)
                if n > 1_000_000:
                    raise DiscoveryError("Oversized bytes")
                return self.read(n).hex()
            raise DiscoveryError(f"Unsupported Borsh primitive: {kind}")
        if not isinstance(kind, dict) or len(kind) != 1:
            raise DiscoveryError(f"Invalid/unsupported IDL type: {kind}")
        tag, spec = next(iter(kind.items()))
        if tag == "array":
            inner, n = spec
            if not isinstance(n, int) or n > 1_000_000:
                raise DiscoveryError("Invalid array length")
            if inner == "u8":
                return self.read(n).hex()
            return [self.decode(inner, depth + 1) for _ in range(n)]
        if tag == "vec":
            n = self.decode("u32", depth + 1)
            if n > 100_000:
                raise DiscoveryError("Oversized Borsh vector")
            return [self.decode(spec, depth + 1) for _ in range(n)]
        if tag == "option":
            flag = self.read(1)[0]
            if flag not in (0, 1):
                raise DiscoveryError("Invalid option flag")
            return self.decode(spec, depth + 1) if flag else None
        if tag == "defined":
            name = spec if isinstance(spec, str) else spec.get("name")
            if name not in self.types:
                raise DiscoveryError(f"IDL type definition missing: {name}")
            definition = self.types[name]
            if definition["kind"] == "struct":
                fields = definition.get("fields", [])
                if fields and isinstance(fields[0], dict):
                    return self.decode_fields(fields, depth + 1)
                return [self.decode(field, depth + 1) for field in fields]
            if definition["kind"] == "enum":
                variants = definition.get("variants", [])
                index = self.read(1)[0]
                if index >= len(variants):
                    raise DiscoveryError(f"Invalid enum variant {name}[{index}]")
                variant = variants[index]
                fields = variant.get("fields", [])
                if not fields:
                    return variant["name"]
                if isinstance(fields[0], dict):
                    val = self.decode_fields(fields, depth + 1)
                else:
                    val = [self.decode(f, depth + 1) for f in fields]
                return {"variant": variant["name"], "fields": val}
            raise DiscoveryError(f"Unsupported type definition: {name}")
        raise DiscoveryError(f"Unsupported Borsh type: {tag}")

    def decode_fields(self, fields: list[dict], depth: int = 0) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for field in fields:
            key = normalize_field(field["name"])
            if key in result:
                raise DiscoveryError(f"Duplicate normalized field: {key}")
            result[key] = self.decode(field["type"], depth + 1)
        return result


def idl_name_key(name: str) -> str:
    """Normalize Anchor names, including qualified Rust paths."""
    short_name = name.rsplit("::", 1)[-1]

    return "".join(
        char.lower()
        for char in short_name
        if char.isalnum()
    )


class Idl:
    def __init__(self, payload: dict[str, Any]):
        self.address = payload.get("address")
        b58decode(self.address, 32)

        accounts_by_name = {
            account["name"]: account
            for account in payload.get("accounts", [])
        }
        self.types = {
            definition["name"]: definition["type"]
            for definition in payload.get("types", [])
        }
        self.accounts: dict[str, bytes] = {}

        for canonical in ("ProtocolConfig", "AgentAccount", "WorkOrderAccount"):
            account_matches = [
                account for name, account in accounts_by_name.items()
                if idl_name_key(name) == idl_name_key(canonical)
            ]
            type_matches = [
                (name, definition) for name, definition in self.types.items()
                if idl_name_key(name) == idl_name_key(canonical)
            ]
            if len(account_matches) != 1 or len(type_matches) != 1:
                raise DiscoveryError(
                    f"Missing/ambiguous account schema for {canonical}. "
                    f"IDL accounts={list(accounts_by_name)}, types={list(self.types)}. "
                    "Rebuild the IDL with anchor build --arch v0 if needed."
                )

            raw = account_matches[0].get("discriminator")
            if (
                not isinstance(raw, list)
                or len(raw) != 8
                or any(
                    not isinstance(value, int) or not 0 <= value <= 255
                    for value in raw
                )
            ):
                raise DiscoveryError(
                    f"Missing/invalid 8-byte IDL discriminator for {canonical}"
                )

            self.accounts[canonical] = bytes(raw)
            # Preserve exact IDL discriminator and schema; only alias their names.
            self.types[canonical] = type_matches[0][1]

    def validate_marketplace_contract(self) -> None:
        """Fail before RPC if the generated Anchor IDL cannot support discovery."""
        required = {
            "ProtocolConfig": {"paused", "program_id"},
            "AgentAccount": {"protocol_config", "agent_id", "capabilities", "status"},
            "WorkOrderAccount": {
                "protocol_config", "creator", "work_order_id",
                "required_capabilities", "execution_deadline", "status",
            },
        }
        for typename, expected in required.items():
            definition = self.types[typename]
            if definition.get("kind") != "struct":
                raise DiscoveryError(f"IDL {typename} must be a struct")
            names = {normalize_field(field["name"]) for field in definition["fields"]}
            missing = expected - names
            if missing:
                raise DiscoveryError(f"IDL {typename} missing fields: {sorted(missing)}")

    def decode_account(self, name: str, data: bytes) -> dict[str, Any]:
        discriminator = self.accounts[name]
        if data[:8] != discriminator:
            raise DiscoveryError(f"Account discriminator mismatch: {name}")
        reader = Reader(data[8:], self.types)
        decoded = reader.decode({"defined": name})
        if not isinstance(decoded, dict):
            raise DiscoveryError(f"Expected struct: {name}")
        # Account space may contain zero padding; nonzero trailing bytes are invalid.
        if any(reader.data[reader.position:]):
            raise DiscoveryError(f"Nonzero trailing account bytes: {name}")
        return decoded


class Rpc:
    def __init__(self, url: str, timeout: int = 20):
        if not url.startswith(("https://", "http://")):
            raise DiscoveryError("RPC URL must be http(s)")
        self.url, self.timeout, self.count = url, timeout, 0

    def call(self, method: str, params: list[Any]) -> Any:
        self.count += 1
        payload = json.dumps({"jsonrpc": "2.0", "id": self.count,
                              "method": method, "params": params}).encode()
        request = urllib.request.Request(self.url, data=payload,
                                         headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                decoded = json.loads(response.read(20_000_000))
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise DiscoveryError(f"RPC {method} failed: {exc}") from exc
        if "error" in decoded:
            raise DiscoveryError(f"RPC {method}: {decoded['error']}")
        if "result" not in decoded:
            raise DiscoveryError(f"RPC {method}: missing result")
        return decoded["result"]


def parse_rpc_account(info: dict[str, Any], program_id: str | None) -> bytes:
    if not isinstance(info, dict):
        raise DiscoveryError("Missing account")
    if program_id is not None and info.get("owner") != program_id:
        raise DiscoveryError("Unexpected Solana program owner")
    if info.get("executable", False):
        raise DiscoveryError("Executable account unexpected")
    data = info.get("data")
    if not isinstance(data, list) or len(data) < 2 or data[1] != "base64":
        raise DiscoveryError("RPC must return base64 account data")
    try:
        return base64.b64decode(data[0], validate=True)
    except ValueError as exc:
        raise DiscoveryError("Malformed base64 account") from exc


def query_account(rpc: Rpc, pubkey: str, commitment: str, min_slot: int | None = None):
    options: dict[str, Any] = {"encoding": "base64", "commitment": commitment}
    if min_slot is not None:
        options["minContextSlot"] = min_slot
    response = rpc.call("getAccountInfo", [pubkey, options])
    return response["context"]["slot"], response["value"]


def query_program_accounts(rpc: Rpc, pid: str, discriminator: bytes,
                           commitment: str, min_slot: int):
    response = rpc.call("getProgramAccounts", [pid, {
        "encoding": "base64", "commitment": commitment,
        "withContext": True, "minContextSlot": min_slot,
        "filters": [{"memcmp": {"offset": 0, "bytes": b58encode(discriminator)}}],
    }])
    return response["context"]["slot"], response["value"]


def require_key(account: dict, name: str) -> str:
    value = account.get(name)
    b58decode(value, 32)
    return value


def require_id(account: dict, name: str) -> bytes:
    value = account.get(name)
    if not isinstance(value, str) or len(value) != 64:
        raise DiscoveryError(f"Invalid ID [u8;32]: {name}")
    try:
        return bytes.fromhex(value)
    except ValueError as exc:
        raise DiscoveryError(f"Invalid hex ID: {name}") from exc


def require_uint(account: dict, name: str, maximum: int) -> int:
    value = account.get(name)
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= maximum:
        raise DiscoveryError(f"Invalid integer field: {name}")
    return value


def discover(rpc: Rpc, idl: Idl, commitment: str = "confirmed") -> dict[str, Any]:
    idl.validate_marketplace_contract()
    pid = idl.address
    config_key = find_program_address([b"protocol_config"], pid)
    slots: dict[str, int] = {}
    slots["config"], info = query_account(rpc, config_key, commitment)
    if info is None:
        raise DiscoveryError("ProtocolConfig absent. Is AeroSettle initialized on this RPC cluster?")
    config = idl.decode_account("ProtocolConfig", parse_rpc_account(info, pid))
    if "program_id" in config and config["program_id"] != pid:
        raise DiscoveryError("ProtocolConfig.program_id mismatches IDL program ID")
    if not isinstance(config.get("paused"), bool):
        raise DiscoveryError("ProtocolConfig.paused invalid")

    agents: list[dict[str, Any]] = []
    orders: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    agent_ids: set[str] = set()
    order_ids: set[str] = set()
    min_slot = slots["config"]

    for typename, output, seeds_prefix in (
        ("AgentAccount", agents, b"agent"),
        ("WorkOrderAccount", orders, b"work_order"),
    ):
        slot, entries = query_program_accounts(rpc, pid, idl.accounts[typename], commitment, min_slot)
        slots[typename] = slot
        min_slot = max(min_slot, slot)
        for entry in entries:
            key = entry["pubkey"]
            b58decode(key, 32)
            if key in seen_keys:
                raise DiscoveryError(f"Duplicate account pubkey: {key}")
            seen_keys.add(key)
            body = idl.decode_account(typename, parse_rpc_account(entry["account"], pid))
            if require_key(body, "protocol_config") != config_key:
                raise DiscoveryError(f"Cross-protocol account: {key}")
            if typename == "AgentAccount":
                raw_id = require_id(body, "agent_id")
                expected = find_program_address([seeds_prefix, b58decode(config_key, 32), raw_id], pid)
                if expected != key:
                    raise DiscoveryError(f"Invalid AgentAccount PDA: {key}")
                if body["agent_id"] in agent_ids:
                    raise DiscoveryError("Duplicate agent_id")
                agent_ids.add(body["agent_id"])
                status = body.get("status")
                if status not in ("Active", "OwnerSuspended", "AdminSuspended", "Revoked"):
                    raise DiscoveryError(f"Unknown AgentStatus: {status}")
                capabilities = require_uint(body, "capabilities", 2**64 - 1)
                output.append({
                    "agent_account": key, "agent_id": body["agent_id"],
                    "protocol_config": config_key, "capabilities": capabilities,
                    "active": status == "Active", "status": status,
                })
            else:
                raw_id = require_id(body, "work_order_id")
                creator = require_key(body, "creator")
                expected = find_program_address([seeds_prefix, b58decode(config_key, 32),
                                                 b58decode(creator, 32), raw_id], pid)
                if expected != key:
                    raise DiscoveryError(f"Invalid WorkOrderAccount PDA: {key}")
                if key in order_ids:
                    raise DiscoveryError("Duplicate work order")
                order_ids.add(key)
                status = body.get("status")
                if not isinstance(status, str):
                    raise DiscoveryError("Unexpected WorkOrderStatus representation")
                output.append({
                    "work_order_account": key, "work_order_id": body["work_order_id"],
                    "creator": creator, "protocol_config": config_key,
                    "required_capabilities": require_uint(body, "required_capabilities", 2**64 - 1),
                    "execution_deadline": body["execution_deadline"],
                    "is_open": status == "Open", "status": status,
                })

    slots["clock"], clock_info = query_account(rpc, CLOCK_SYSVAR, commitment, min_slot)
    clock_data = parse_rpc_account(clock_info, None)
    if len(clock_data) < 40:
        raise DiscoveryError("Invalid Clock sysvar length")
    chain_slot = int.from_bytes(clock_data[:8], "little")
    chain_unix = int.from_bytes(clock_data[32:40], "little", signed=True)
    # No claim of atomic cross-call snapshot; retain every observed RPC context slot.
    agents.sort(key=lambda a: (a["agent_id"], a["agent_account"]))
    orders.sort(key=lambda o: o["work_order_account"])
    return {
        "schema_version": "aerosettle.discovery.v1", "program_id": pid,
        "protocol_config": config_key, "protocol_paused": config["paused"],
        "commitment": commitment, "rpc_context_slots": slots,
        "clock_slot": chain_slot, "now_unix": chain_unix,
        "agents": agents, "work_orders": orders,
        "eligible_agents_by_order": {
            o["work_order_account"]: [a["agent_account"] for a in agents
                if not config["paused"] and o["is_open"] and chain_unix < o["execution_deadline"]
                and a["active"] and a["protocol_config"] == o["protocol_config"]
                and (o["required_capabilities"] & ~a["capabilities"]) == 0]
            for o in orders if o["is_open"]
        },
        "note": "Advisory off-chain snapshot only; revalidate in claim_work_order. "
                "RPC reads are not atomic across requests.",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rpc-url", default="http://127.0.0.1:8899")
    parser.add_argument("--idl", default="target/idl/aerosettle.json")
    parser.add_argument("--commitment", choices=["processed", "confirmed", "finalized"],
                        default="confirmed")
    parser.add_argument("--output", default="-", help="JSON path or '-' for stdout")
    parser.add_argument("--check-idl", action="store_true", help="Validate generated Anchor IDL, no RPC calls")
    args = parser.parse_args(argv)
    try:
        idl = Idl(json.loads(Path(args.idl).read_text()))
        idl.validate_marketplace_contract()
        if args.check_idl:
            print(f"IDL OK | program_id={idl.address} | ProtocolConfig, AgentAccount, WorkOrderAccount")
            return 0
        snapshot = discover(Rpc(args.rpc_url), idl, args.commitment)
        text = json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n"
        if args.output == "-":
            print(text, end="")
        else:
            Path(args.output).write_text(text)
            print(f"Discovery guardado en {args.output}", file=sys.stderr)
        return 0
    except (DiscoveryError, OSError, KeyError, TypeError, UnicodeDecodeError,
            json.JSONDecodeError, IndexError) as exc:
        print(f"Discovery ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
