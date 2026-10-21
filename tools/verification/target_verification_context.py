#!/usr/bin/env python3
"""AeroSettle target WorkOrder context — read-only."""

import base64
import json
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

sys.path.insert(0, str(ROOT / "tools/execution"))
import submission_gate as gate

TARGET = (
    "EnkZQWDqF5HeFeusZ7xnj7tngVN9xASofmKvXtDLeqbx"
)

EXPECTED_VERIFIER = (
    "DmWQhuVujHrJb4jFzo62UnCT3mwnx9GFtVdo8VUu82Wu"
)

def require(condition, message):
    if not condition:
        raise RuntimeError(message)

def load(idl, address, account_type):
    raw = gate.get_account(address)

    require(
        raw["owner"] == gate.PROGRAM,
        f"Owner incorrecto: {address}"
    )

    return idl.decode_account(
        account_type,
        gate.d.parse_rpc_account(raw, gate.PROGRAM)
    )

def main():
    require(
        gate.rpc("getGenesisHash") == gate.GENESIS,
        "Genesis incorrecto"
    )

    raw_idl = json.loads(
        (
            ROOT / "target/idl/aerosettle.discovery.json"
        ).read_text()
    )

    require(
        raw_idl["address"] == gate.PROGRAM,
        "IDL incompatible"
    )

    idl = gate.d.Idl(raw_idl)

    config_pda = gate.d.find_program_address(
        [b"protocol_config"], gate.PROGRAM
    )

    config = load(idl, config_pda, "ProtocolConfig")
    order = load(idl, TARGET, "WorkOrderAccount")

    require(
        not config["paused"],
        "Protocolo pausado"
    )

    require(
        order["protocol_config"] == config_pda,
        "ProtocolConfig incorrecto"
    )

    require(
        order["verifier"] == EXPECTED_VERIFIER,
        "Verifier incorrecto"
    )

    require(
        order["claimed_agent"] == gate.AGENT,
        "Agente inesperado"
    )

    order_id = bytes.fromhex(
        order["work_order_id"]
    )

    require(
        len(order_id) == 32,
        "WorkOrder ID inválido"
    )

    derived = gate.d.find_program_address(
        [
            b"work_order",
            gate.d.b58decode(config_pda, 32),
            gate.d.b58decode(order["creator"], 32),
            order_id,
        ],
        gate.PROGRAM
    )

    require(
        derived == TARGET,
        "WorkOrder PDA no coincide"
    )

    status = order["status"]

    require(
        status in ("Submitted", "Verified"),
        f"Estado incompatible: {status}"
    )

    raw_clock = gate.get_account(gate.CLOCK)

    clock = base64.b64decode(
        raw_clock["data"][0],
        validate=True
    )

    require(
        len(clock) >= 40,
        "Clock Sysvar inválido"
    )

    chain_now = struct.unpack_from(
        "<q", clock, 32
    )[0]

    ended = int(order["execution_ended_at"])
    deadline = int(order["verification_deadline"])

    if status == "Submitted":
        require(
            ended <= chain_now <= deadline,
            "Ventana de verificación cerrada"
        )

        require(
            order["verification_status"] is None,
            "Ya existe una decisión del verifier"
        )

    owner = subprocess.check_output(
        [
            "solana-keygen",
            "pubkey",
            str(
                Path.home() / ".config/solana/id.json"
            ),
        ],
        text=True
    ).strip()

    context = {
        "schema": "aerosettle.target-verification.v1",
        "genesis": gate.GENESIS,
        "program_id": gate.PROGRAM,
        "owner": owner,
        "creator": order["creator"],
        "protocol_config": config_pda,
        "work_order": TARGET,
        "order_id_hex": order["work_order_id"],
        "status": status,
        "verifier": order["verifier"],
        "submitted_at": str(order["submitted_at"]),
        "execution_ended_at": str(ended),
        "verification_deadline": str(deadline),
        "chain_now": str(chain_now),
        "execution_receipt_hash":
            order["execution_receipt_hash"],
        "evidence_manifest_hash":
            order["evidence_manifest_hash"],
        "verification_attestation_hash":
            order["verification_attestation_hash"],
        "verification_status":
            order["verification_status"],
        "completion_bps": order["completion_bps"],
        "verified_at": str(order["verified_at"]),
        "escrow_vault": order["escrow_vault"],
        "token_program": order["token_program"],
        "token_mint": order["token_mint"],
        "total_amount": str(order["total_amount"]),
    }

    output = (
        ROOT / ".aerosettle-local"
        / f"verification-context-target-{TARGET}.json"
    )

    output.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    output.write_text(
        json.dumps(context, indent=2) + "\n"
    )

    print("=== AEROSETTLE TARGET CONTEXT ===")
    print("WorkOrder:", TARGET)
    print("Status:", status)
    print("PDA verified: True")
    print("Verifier:", context["verifier"])
    print("Chain now:", chain_now)
    print("Deadline:", deadline)
    print("Escrow:", context["escrow_vault"])
    print("Total base units:", context["total_amount"])
    print("Transactions sent: 0")

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("TARGET CONTEXT ERROR:", exc, file=sys.stderr)
        sys.exit(1)
