#!/usr/bin/env python3
"""AeroSettle Verification Readiness - read only."""

import base64
import hashlib
import json
import os
import struct
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/execution"))

import submission_gate as gate

ORDER = os.environ.get(
    "AEROSETTLE_WORK_ORDER",
    "EnkZQWDqF5HeFeusZ7xnj7tngVN9xASofmKvXtDLeqbx"
)

PROGRAM = gate.PROGRAM

WALLETS = {
    "Solana CLI Owner":
        Path.home() / ".config/solana/id.json",
    "Localnet Dev Creator":
        ROOT / ".aerosettle-local/dev-signer-wallet.json",
    "Drone A Device":
        ROOT / ".aerosettle-local/drone-a-device.json",
}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def local_time(timestamp):
    return datetime.fromtimestamp(
        int(timestamp),
        ZoneInfo("America/Mazatlan")
    ).isoformat()


def public_key(path):
    if not path.is_file():
        return None

    result = subprocess.run(
        ["solana-keygen", "pubkey", str(path)],
        capture_output=True,
        text=True,
        check=True
    )

    return result.stdout.strip()


def chain_clock():
    account = gate.get_account(gate.CLOCK)

    raw = base64.b64decode(
        account["data"][0],
        validate=True
    )

    require(len(raw) >= 40, "Clock sysvar inválido")

    return struct.unpack_from("<q", raw, 32)[0]


def main():
    require(
        gate.rpc("getGenesisHash") == gate.GENESIS,
        "Genesis incorrecto"
    )

    idl_raw = json.loads(
        (
            ROOT / "target/idl/aerosettle.discovery.json"
        ).read_text()
    )

    require(
        idl_raw.get("address") == PROGRAM,
        "Program ID incompatible"
    )

    idl = gate.d.Idl(idl_raw)

    account = gate.get_account(ORDER)

    require(
        account["owner"] == PROGRAM,
        "WorkOrder no pertenece al programa"
    )

    order = idl.decode_account(
        "WorkOrderAccount",
        gate.d.parse_rpc_account(account, PROGRAM)
    )

    require(
        order.get("status") == "Submitted",
        "Se esperaba WorkOrder Submitted"
    )

    verifier = order.get("verifier")

    require(
        isinstance(verifier, str) and verifier,
        "Verifier no identificado"
    )

    now = chain_clock()
    wall_now = int(time.time())
    deadline = int(order["verification_deadline"])
    execution_end = int(order["execution_ended_at"])

    can_verify_now = (
        execution_end <= now <= deadline
    )

    wallets = {
        name: public_key(path)
        for name, path in WALLETS.items()
    }

    matching_wallets = [
        name for name, key in wallets.items()
        if key == verifier
    ]

    instructions = [
        ix for ix in idl_raw["instructions"]
        if ix["name"] == "verify_execution"
    ]

    require(
        len(instructions) == 1,
        "verify_execution no es única"
    )

    ix = instructions[0]

    expected_accounts = [
        ("protocol_config", False, False),
        ("work_order", False, True),
        ("verifier", True, False),
    ]

    require(
        len(ix["accounts"]) == 3,
        "Número de cuentas incorrecto"
    )

    for actual, expected in zip(
        ix["accounts"],
        expected_accounts
    ):
        name, signer, writable = expected

        require(
            actual["name"] == name
            and bool(actual.get("signer")) == signer
            and bool(actual.get("writable")) == writable,
            "AccountMeta incorrecta: " + name
        )

    discriminator = hashlib.sha256(
        b"global:verify_execution"
    ).digest()[:8]

    require(
        bytes(ix["discriminator"]) == discriminator,
        "Discriminador Anchor incorrecto"
    )

    require(
        len(ix["args"]) == 1,
        "Número de argumentos incorrecto"
    )

    type_name = ix["args"][0]["type"]["defined"]["name"]

    types = [
        typ for typ in idl_raw.get("types", [])
        if typ["name"] == type_name
        or typ["name"].split("::")[-1]
            == type_name.split("::")[-1]
    ]

    require(
        len(types) == 1,
        "No se pudo resolver VerifyExecutionArgs"
    )

    fields = types[0]["type"]["fields"]

    require(
        len(fields) == 4,
        "VerifyExecutionArgs: campos inesperados"
    )

    expected_fields = [
        "verification_attestation_hash",
        "status",
        "completion_bps",
        "verified_at",
    ]

    require(
        [f["name"] for f in fields] == expected_fields,
        "Orden Borsh de verificación incorrecto"
    )

    print("=== AEROSETTLE VERIFICATION READINESS ===")
    print("Genesis: OK")
    print("WorkOrder:", ORDER)
    print("Status:", order["status"])

    print("\n=== AUTHORIZATION ===")
    print("Verifier on-chain:", verifier)

    for name, key in wallets.items():
        print(name + ":", key or "NOT FOUND")

    print(
        "Matching local wallets:",
        matching_wallets or "NONE"
    )

    print("\n=== TEMPORAL CONSTRAINTS ===")
    print("Chain now:", local_time(now))
    print("Mac time:", local_time(wall_now))
    print("Execution ended:", local_time(execution_end))
    print("Verification deadline:", local_time(deadline))
    print("Clock difference seconds:", now - wall_now)
    print("Conservative window open:", can_verify_now)

    print("\n=== EXECUTION COMMITMENTS ===")
    for key in [
        "execution_receipt_hash",
        "evidence_manifest_hash",
        "provided_evidence",
        "execution_sequence",
        "settlement_beneficiary",
        "verification_status",
        "completion_bps",
    ]:
        print(key + ":", order.get(key))

    print("\n=== VERIFICATION IDL ===")
    print("Discriminator:", list(discriminator))
    print("Type:", types[0]["name"])

    for index, field in enumerate(fields, 1):
        print(
            str(index) + ".",
            field["name"],
            "=>",
            field["type"]
        )

    report = {
        "schema_version":
            "aerosettle.verification.readiness.v1",
        "mode": "read-only",
        "work_order": ORDER,
        "program": PROGRAM,
        "verifier": verifier,
        "matching_local_wallets": matching_wallets,
        "chain_now": now,
        "wall_now": wall_now,
        "execution_ended_at": execution_end,
        "verification_deadline": deadline,
        "conservative_window_open": can_verify_now,
        "fields": fields,
        "transactions_sent": 0,
    }

    output = (
        ROOT /
        ".aerosettle-local/verification-readiness.json"
    )

    output.parent.mkdir(
        parents=True, exist_ok=True
    )

    output.write_text(
        json.dumps(
            report,
            indent=2,
            ensure_ascii=False
        ) + "\n"
    )

    print("\nReport:", output)

    if not can_verify_now:
        print(
            "⚠️ Verificación bloqueada por el auditor: "
            "revisar plazos y reloj"
        )
    elif not matching_wallets:
        print(
            "⚠️ Falta identificar la clave autorizada "
            "del verificador"
        )
    else:
        print("✅ Identidad y ventana preliminar válidas")

    if abs(now - wall_now) > 300:
        print(
            "⚠️ El reloj de Localnet difiere más "
            "de 5 minutos del reloj del Mac"
        )

    print("Read-only: 0 transactions")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(
            "❌ VERIFICATION READINESS:",
            exc,
            file=sys.stderr
        )
        sys.exit(1)
