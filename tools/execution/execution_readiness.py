#!/usr/bin/env python3
"""AeroSettle Execution Readiness — read-only."""

import base64
import hashlib
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

sys.path.insert(
    0, str(ROOT / "tools/discovery")
)

import agent_discovery as d

RPC = "http://127.0.0.1:8899"
API = "http://127.0.0.1:8787"

GENESIS = (
    "HP9XKTusRPGC78EFDpR9xdEq6simL2vqyDdrMvn6Vacg"
)
PROGRAM = (
    "CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy"
)
ORDER = (
    "EnkZQWDqF5HeFeusZ7xnj7tngVN9xASofmKvXtDLeqbx"
)
AGENT = (
    "DcusvnYAdFFKzNDVzUkUvmgZ9fDhzszeRR5Fj8F5dMbB"
)
DEVICE = (
    "C5kqBc9ntqCAqSNDN3ywdK3Hkay29zixMsxrvesQLtnt"
)
OWNER = (
    "8rPDpYsLZxNBm8Q8GKSKki8Ag6dodkasedhUT9x3Ec1D"
)

ALPHABET = (
    "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
)


def b58encode(data):
    number = int.from_bytes(data, "big")
    result = ""

    while number:
        number, remainder = divmod(number, 58)
        result = ALPHABET[remainder] + result

    leading = len(data) - len(data.lstrip(b"\x00"))
    return "1" * leading + result


def rpc(method, params=None):
    body = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params or [],
    }).encode()

    request = urllib.request.Request(
        RPC,
        data=body,
        headers={"Content-Type": "application/json"},
    )

    with urllib.request.urlopen(
        request, timeout=20
    ) as response:
        payload = json.load(response)

    if "error" in payload:
        raise RuntimeError(payload["error"])

    return payload["result"]


def get_account(address):
    value = rpc("getAccountInfo", [
        address,
        {
            "encoding": "base64",
            "commitment": "confirmed",
        },
    ])["value"]

    if value is None:
        raise RuntimeError(
            f"Cuenta inexistente: {address}"
        )

    if value["owner"] != PROGRAM:
        raise RuntimeError(
            f"Propietario de programa incorrecto: {address}"
        )

    return value


def main():
    if rpc("getGenesisHash") != GENESIS:
        raise RuntimeError("Genesis incorrecto")

    device_file = (
        ROOT / ".aerosettle-local/drone-a-device.json"
    )

    if not device_file.is_file():
        raise RuntimeError(
            "No existe la wallet del dispositivo"
        )

    pubkey = subprocess.check_output([
        "solana-keygen",
        "pubkey",
        str(device_file),
    ], text=True).strip()

    if pubkey != DEVICE:
        raise RuntimeError(
            "La identidad local de Drone A cambió"
        )

    with urllib.request.urlopen(
        API + "/v1/work-orders/" + ORDER,
        timeout=20,
    ) as response:
        payload = json.load(response)

    order = payload["data"]
    meta = payload["meta"]

    if meta["program_id"] != PROGRAM:
        raise RuntimeError(
            "Marketplace API usa otro programa"
        )

    if order["status"] != "Claimed":
        raise RuntimeError(
            "La orden ya no está en estado Claimed"
        )

    if order["is_open"] is not False:
        raise RuntimeError(
            "Estado Open inconsistente"
        )

    agent_info = get_account(AGENT)
    agent_data = base64.b64decode(
        agent_info["data"][0],
        validate=True,
    )

    expected = hashlib.sha256(
        b"account:AgentAccount"
    ).digest()[:8]

    if (
        len(agent_data) < 196
        or agent_data[:8] != expected
    ):
        raise RuntimeError(
            "Layout AgentAccount inválido"
        )

    actual_owner = b58encode(
        agent_data[73:105]
    )
    actual_signer = b58encode(
        agent_data[105:137]
    )

    if (
        actual_owner != OWNER
        or actual_signer != DEVICE
    ):
        raise RuntimeError(
            "La autoridad o propietario del agente cambió"
        )

    work_info = get_account(ORDER)

    idl_raw = json.loads(
        (
            ROOT / "target/idl/aerosettle.discovery.json"
        ).read_text()
    )

    idl = d.Idl(idl_raw)

    if idl.address != PROGRAM:
        raise RuntimeError("IDL incompatible")

    decoded = idl.decode_account(
        "WorkOrderAccount",
        d.parse_rpc_account(
            work_info, PROGRAM
        ),
    )

    now = int(meta["chain_now_unix"])
    deadline = int(order["execution_deadline"])
    remaining = deadline - now

    print("=== AEROSETTLE EXECUTION READINESS ===")
    print("Genesis:", GENESIS)
    print("WorkOrder:", ORDER)
    print("API status:", order["status"])
    print("Agent:", AGENT)
    print("Signing authority:", actual_signer)
    print("Owner:", actual_owner)
    print("Execution deadline:", deadline)
    print("Chain now:", now)
    print("Remaining seconds:", remaining)

    print("\n=== WORKORDER ON-CHAIN ===")

    for key in [
        "status",
        "claimed_agent",
        "claimed_at",
        "settlement_beneficiary",
        "execution_signer",
        "execution_deadline",
    ]:
        print(key + ":", decoded.get(key, "<not exposed>"))

    print("\n=== SUBMISSION INTERFACE ===")

    submission = [
        ix for ix in idl_raw.get("instructions", [])
        if ix.get("name") == "submit_execution"
    ]

    if len(submission) != 1:
        raise RuntimeError(
            "submit_execution no está definido "
            "de forma única en el IDL"
        )

    ix = submission[0]

    print("Discriminator:", ix.get("discriminator"))

    print("Accounts:")
    for account in ix.get("accounts", []):
        print(
            " -",
            account["name"],
            "signer:", account.get("signer", False),
            "writable:", account.get("writable", False),
        )

    print("Arguments:")
    for argument in ix.get("args", []):
        print(
            " -",
            argument["name"],
            argument["type"],
        )

    if remaining <= 0:
        print(
            "\n⚠️ Execution deadline alcanzado. "
            "Revisar las reglas Rust antes de enviar evidencia."
        )
    else:
        print(
            "\n✅ Mission Claimed y dispositivo autorizado"
        )

    print("Read-only: 0 transactions sent")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(
            "❌ EXECUTION READINESS FAIL-CLOSED:",
            exc,
            file=sys.stderr,
        )
        sys.exit(1)
