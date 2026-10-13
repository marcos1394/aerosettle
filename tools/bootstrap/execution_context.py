#!/usr/bin/env python3
"""Read-only AeroSettle execution context."""

from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT / "tools" / "discovery"))

import agent_discovery as ad

RPC_URL = "http://127.0.0.1:8899"

PROGRAM_ID = (
    "CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy"
)

GENESIS = (
    "HP9XKTusRPGC78EFDpR9xdEq6simL2vqyDdrMvn6Vacg"
)

TAG = os.environ.get(
    "AEROSETTLE_ORDER_TAG", "claim-v2"
)

if (
    not TAG
    or len(TAG) > 40
    or not all(
        c.isalnum() or c in "_-"
        for c in TAG
    )
):
    raise SystemExit("Order tag inválido")

idl_file = ROOT / "target/idl/aerosettle.discovery.json"

idl = ad.Idl(
    json.loads(idl_file.read_text())
)

if idl.address != PROGRAM_ID:
    raise SystemExit("IDL Program ID incorrecto")

rpc = ad.Rpc(RPC_URL)

if rpc.call("getGenesisHash", []) != GENESIS:
    raise SystemExit(
        "Genesis hash incorrecto. "
        "Comprueba que utilizas el mismo ledger."
    )

wallet_file = (
    Path.home() / ".config/solana/id.json"
)

owner = subprocess.check_output(
    [
        "solana-keygen",
        "pubkey",
        str(wallet_file),
    ],
    text=True,
).strip()


def sha256(value):
    return hashlib.sha256(
        value.encode("utf-8")
    ).digest()


config_pda = ad.find_program_address(
    [b"protocol_config"],
    PROGRAM_ID,
)

order_id = sha256(
    f"aerosettle:inspection:order:"
    f"{TAG}:{GENESIS}:{owner}"
)

order_pda = ad.find_program_address(
    [
        b"work_order",
        ad.b58decode(config_pda, 32),
        ad.b58decode(owner, 32),
        order_id,
    ],
    PROGRAM_ID,
)

agent_id = sha256(
    f"aerosettle:bootstrap:agent:v1:"
    f"{GENESIS}:{owner}:drone-a"
)

agent_pda = ad.find_program_address(
    [
        b"agent",
        ad.b58decode(config_pda, 32),
        agent_id,
    ],
    PROGRAM_ID,
)


def load_account(address, account_type):
    _, entry = ad.query_account(
        rpc, address, "confirmed"
    )

    return idl.decode_account(
        account_type,
        ad.parse_rpc_account(
            entry, PROGRAM_ID
        ),
    )


config = load_account(
    config_pda, "ProtocolConfig"
)

order = load_account(
    order_pda, "WorkOrderAccount"
)

agent = load_account(
    agent_pda, "AgentAccount"
)

_, clock = ad.query_account(
    rpc,
    ad.CLOCK_SYSVAR,
    "confirmed",
)

clock_bytes = ad.parse_rpc_account(
    clock, None
)

chain_now = int.from_bytes(
    clock_bytes[32:40],
    "little",
    signed=True,
)

if config["paused"]:
    raise SystemExit("Protocolo pausado")

if order.get("status") not in (
    "Claimed", "Submitted"
):
    raise SystemExit(
        "WorkOrder no está Claimed/Submitted: "
        + str(order.get("status"))
    )

if agent.get("status") != "Active":
    raise SystemExit(
        "El agente Drone A no está activo"
    )

if order.get("work_order_id") != order_id.hex():
    raise SystemExit(
        "WorkOrder ID on-chain incorrecto"
    )

if agent.get("agent_id") != agent_id.hex():
    raise SystemExit(
        "Agent ID on-chain incorrecto"
    )

for field in (
    "claimed_agent",
    "claimed_agent_account",
    "assigned_agent",
    "assigned_agent_account",
):
    if (
        field in order
        and order[field] != agent_pda
    ):
        raise SystemExit(
            f"Orden asignada a otro agente: {field}"
        )

for field in (
    "claimed_at",
    "execution_deadline",
    "evidence_requirements",
):
    if type(order.get(field)) is not int:
        raise SystemExit(
            f"Campo inválido de WorkOrder: {field}"
        )

if type(
    agent.get("next_signature_sequence")
) is not int:
    raise SystemExit(
        "Falta next_signature_sequence"
    )

signer = agent.get("signing_authority")
ad.b58decode(signer, 32)

context = {
    "program_id": PROGRAM_ID,
    "genesis": GENESIS,
    "order_tag": TAG,
    "owner": owner,
    "protocol_config": config_pda,
    "work_order": order_pda,
    "agent_account": agent_pda,
    "signing_authority": signer,
    "order_id_hex": order_id.hex(),
    "status": order["status"],
    "claimed_at": str(
        order["claimed_at"]
    ),
    "execution_deadline": str(
        order["execution_deadline"]
    ),
    "provided_evidence": str(
        order["evidence_requirements"]
    ),
    "sequence": str(
        agent["next_signature_sequence"]
    ),
    "chain_now": str(chain_now),
    "execution_receipt_hash": order.get(
        "execution_receipt_hash"
    ),
    "evidence_manifest_hash": order.get(
        "evidence_manifest_hash"
    ),
}

output = (
    ROOT
    / ".aerosettle-local"
    / f"execution-context-{TAG}.json"
)

output.parent.mkdir(
    parents=True, exist_ok=True
)

output.write_text(
    json.dumps(context, indent=2) + "\n"
)

print("Order:", context["work_order"])
print("Status:", context["status"])
print("Signer:", signer)
print("Next sequence:", context["sequence"])
print("Claimed at:", context["claimed_at"])
print("Chain now:", context["chain_now"])
print("Deadline:", context["execution_deadline"])
print("Context:", output)
