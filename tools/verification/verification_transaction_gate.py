#!/usr/bin/env python3
"""Read-only verifier preflight for AeroSettle Localnet."""

import base64
import json
import os
import struct
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

sys.path.insert(
    0, str(ROOT / "tools/execution")
)

import submission_gate as sg

ORDER = os.environ.get(
    "AEROSETTLE_WORK_ORDER",
    "EnkZQWDqF5HeFeusZ7xnj7tngVN9xASofmKvXtDLeqbx"
)

VERIFIER = (
    "DmWQhuVujHrJb4jFzo62UnCT3mwnx9GFtVdo8VUu82Wu"
)

KEY = (
    ROOT /
    ".aerosettle-local/bootstrap/keys/"
    "demo-verifier-e1f798efbb1d.json"
)

OUTPUT = (
    ROOT /
    ".aerosettle-local/verification-transaction-gate.json"
)


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    require(
        sg.rpc("getGenesisHash") == sg.GENESIS,
        "Genesis Hash distinto"
    )

    require(KEY.is_file(), "Falta el keypair del verificador")

    pubkey = subprocess.check_output(
        ["solana-keygen", "pubkey", str(KEY)],
        text=True
    ).strip()

    require(
        pubkey == VERIFIER,
        "El keypair no corresponde al verifier registrado"
    )

    raw_idl = json.loads(
        (ROOT / "target/idl/aerosettle.discovery.json").read_text()
    )

    require(
        raw_idl.get("address") == sg.PROGRAM,
        "IDL de programa equivocado"
    )

    idl = sg.d.Idl(raw_idl)
    raw = sg.get_account(ORDER)

    require(
        raw["owner"] == sg.PROGRAM,
        "WorkOrder owner incorrecto"
    )

    order = idl.decode_account(
        "WorkOrderAccount",
        sg.d.parse_rpc_account(raw, sg.PROGRAM)
    )

    require(
        order["status"] == "Submitted",
        f"La orden no está Submitted: {order['status']}"
    )

    require(
        order["verifier"] == VERIFIER,
        "Verificador on-chain no coincide"
    )

    require(
        order["verification_status"] is None,
        "Orden previamente verificada"
    )

    clock = sg.get_account(sg.CLOCK)

    blob = base64.b64decode(
        clock["data"][0],
        validate=True
    )

    require(
        len(blob) >= 40,
        "Clock sysvar inválido"
    )

    now = struct.unpack_from("<q", blob, 32)[0]
    wall = int(time.time())
    ended = int(order["execution_ended_at"])
    deadline = int(order["verification_deadline"])

    require(
        ended <= now,
        "Reloj chain anterior al fin de ejecución"
    )

    require(
        now <= deadline,
        "Plazo de verificación vencido según Clock on-chain"
    )

    for field in [
        "execution_receipt_hash",
        "evidence_manifest_hash",
        "work_order_id",
    ]:
        value = order[field]

        require(
            isinstance(value, str)
            and len(value) == 64
            and len(bytes.fromhex(value)) == 32,
            f"Campo {field} inválido"
        )

    require(
        int(order["provided_evidence"]) > 0,
        "Sin evidencia"
    )

    ixs = [
        ix for ix in raw_idl["instructions"]
        if ix["name"] == "verify_execution"
    ]

    require(
        len(ixs) == 1,
        "verify_execution ausente o duplicada"
    )

    expected = [
        ("protocol_config", False, False),
        ("work_order", False, True),
        ("verifier", True, False),
    ]

    accounts = ixs[0]["accounts"]

    require(
        len(accounts) == len(expected),
        "AccountMetas inesperadas"
    )

    for acct, (name, signer, writable) in zip(
        accounts, expected
    ):
        require(
            acct["name"] == name
            and bool(acct.get("signer")) == signer
            and bool(acct.get("writable")) == writable,
            f"AccountMeta no coincide: {name}"
        )

    report = {
        "schema": "aerosettle.verify-gate.v1",
        "network": "localnet",
        "genesis": sg.GENESIS,
        "program_id": sg.PROGRAM,
        "work_order": ORDER,
        "protocol_config": order["protocol_config"],
        "verifier": VERIFIER,
        "keypair_file": str(KEY),
        "protocol_version": int(order["protocol_version"]),
        "work_order_id": order["work_order_id"],
        "execution_receipt_hash":
            order["execution_receipt_hash"],
        "evidence_manifest_hash":
            order["evidence_manifest_hash"],
        "execution_ended_at": ended,
        "verification_deadline": deadline,
        "chain_now": now,
        "wall_now": wall,
        "clock_skew_seconds": now - wall,
        "status": order["status"],
        "provided_evidence": int(
            order["provided_evidence"]
        ),
        "transactions_sent": 0,
    }

    OUTPUT.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    OUTPUT.write_text(
        json.dumps(report, indent=2) + "\n"
    )

    print("=== AEROSETTLE VERIFY TRANSACTION GATE ===")

    for field in [
        "work_order",
        "status",
        "verifier",
        "protocol_version",
        "execution_ended_at",
        "verification_deadline",
        "chain_now",
        "wall_now",
        "clock_skew_seconds",
    ]:
        print(f"{field}: {report[field]}")

    print("Local verifier keypair: MATCH")
    print("Chain verification window: OPEN")
    print("Report:", OUTPUT)
    print("Transactions sent: 0")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(
            "❌ VERIFY GATE:",
            exc,
            file=sys.stderr
        )
        sys.exit(1)
