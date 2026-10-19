#!/usr/bin/env python3
"""AeroSettle claim-ui mission audit. Read-only."""

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/discovery"))

import agent_discovery as d

PROGRAM = "CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy"
GENESIS = "HP9XKTusRPGC78EFDpR9xdEq6simL2vqyDdrMvn6Vacg"

TAG = "claim-ui-20261013-v1"

CREATOR = "8rPDpYsLZxNBm8Q8GKSKki8Ag6dodkasedhUT9x3Ec1D"
MINT = "HTHpns7gqLAhSBhAzqxhYdyHv9HeXkkRW6aHQfdUjL1G"

TARGET = "8Uf6qJvjigP7ApoBEA1cUBFoGEjFqE5A3qxRyAb9rW4E"
VAULT = "4bpvK9eBgU1v8mDWpv9dd6ub3Ahqb2MEZtjoZUqtqfAy"

OLD_ORDER = "EnkZQWDqF5HeFeusZ7xnj7tngVN9xASofmKvXtDLeqbx"
OLD_VAULT = "6nWoFVfJayAbJmkqWnJHfCCHCCvJMj3AGQ9iLtBEGt4k"

TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"

EXPECTED_AMOUNT = 10_000_000

def require(condition, message):
    if not condition:
        raise RuntimeError(message)

def main():
    require(
        len(sys.argv) == 2 and
        sys.argv[1] in ("Absent", "Draft", "Open", "Claimed"),
        "Uso: claim_ui_audit.py Absent|Draft|Open|Claimed"
    )

    expected = sys.argv[1]

    rpc = d.Rpc("http://127.0.0.1:8899", timeout=15)

    require(
        rpc.call("getGenesisHash", []) == GENESIS,
        "Genesis Hash incorrecto"
    )

    idl = d.Idl(json.loads(
        (ROOT / "target/idl/aerosettle.discovery.json")
        .read_text()
    ))

    require(idl.address == PROGRAM, "IDL incorrecto")

    def account(key):
        response = rpc.call(
            "getAccountInfo",
            [
                key,
                {
                    "encoding": "base64",
                    "commitment": "confirmed"
                }
            ]
        )
        return response["value"]

    config = d.find_program_address(
        [b"protocol_config"], PROGRAM
    )

    order_id = hashlib.sha256(
        f"aerosettle:inspection:order:{TAG}:{GENESIS}:{CREATOR}"
        .encode()
    ).digest()

    derived = d.find_program_address(
        [
            b"work_order",
            d.b58decode(config, 32),
            d.b58decode(CREATOR, 32),
            order_id
        ],
        PROGRAM
    )

    derived_vault = d.find_program_address(
        [
            b"escrow",
            d.b58decode(derived, 32)
        ],
        PROGRAM
    )

    require(derived == TARGET, "Target PDA mismatch")
    require(derived_vault == VAULT, "Vault PDA mismatch")

    previous = account(OLD_ORDER)

    require(previous is not None, "Old WorkOrder missing")

    old_order = idl.decode_account(
        "WorkOrderAccount",
        d.parse_rpc_account(previous, PROGRAM)
    )

    require(
        old_order["status"] == "Settled",
        "La orden anterior cambió de estado"
    )

    require(
        account(OLD_VAULT) is None,
        "El vault anterior no está cerrado"
    )

    current = account(TARGET)
    vault = account(VAULT)

    print("=== AEROSETTLE CLAIM-UI AUDIT ===")
    print("WorkOrder:", TARGET)
    print("Escrow:", VAULT)
    print("Expected:", expected)

    if expected == "Absent":
        require(current is None, "WorkOrder ya existe")
        require(vault is None, "Vault ya existe")
        print("✅ WorkOrder absent")
        print("✅ Escrow absent")
    else:
        require(current is not None, "WorkOrder missing")

        order = idl.decode_account(
            "WorkOrderAccount",
            d.parse_rpc_account(current, PROGRAM)
        )

        require(order["status"] == expected, "Unexpected status")
        require(order["creator"] == CREATOR, "Unexpected creator")
        require(order["work_order_id"] == order_id.hex(),
                "Unexpected WorkOrder ID")
        require(order["token_mint"] == MINT, "Unexpected mint")
        require(order["total_amount"] == EXPECTED_AMOUNT,
                "Unexpected amount")
        require(order["required_capabilities"] == 33,
                "Unexpected capability mask")

        print("Status:", order["status"])

        if expected == "Draft":
            require(vault is None, "Draft already funded")
            print("✅ Draft exists, no escrow")
        else:
            require(vault is not None, "Escrow missing")

            data = d.parse_rpc_account(
                vault, TOKEN_PROGRAM
            )

            require(
                len(data) >= 165 and data[108] == 1,
                "Invalid SPL Token account"
            )

            require(
                d.b58encode(data[0:32]) == MINT,
                "Escrow mint mismatch"
            )

            require(
                d.b58encode(data[32:64]) == VAULT,
                "Escrow authority mismatch"
            )

            amount = int.from_bytes(
                data[64:72], "little"
            )

            require(
                amount == EXPECTED_AMOUNT,
                "Escrow balance mismatch"
            )

            # CLAIMED-STATE ASSERTIONS
            if expected == "Claimed":
                require(
                    order["claimed_agent"] ==
                    "DcusvnYAdFFKzNDVzUkUvmgZ9fDhzszeRR5Fj8F5dMbB",
                    "Incorrect claimed agent"
                )

                require(
                    order["settlement_beneficiary"] ==
                    "8rPDpYsLZxNBm8Q8GKSKki8Ag6dodkasedhUT9x3Ec1D",
                    "Incorrect economic beneficiary"
                )

                require(
                    order["claimed_at"] > 0,
                    "Missing claimed_at timestamp"
                )

                print("✅ Drone A claimed WorkOrder")
                print("✅ Correct economic beneficiary")
                print("✅ Valid claim timestamp")

            print("Escrow base units:", amount)
            print("✅ Escrow funded")
            print("✅ Token mint and authority verified")

    print("✅ Previous settled order preserved")
    print("✅ Previous closed vault preserved")
    print("✅ Audit passed")
    print("Transactions sent: 0")

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("❌ AUDIT FAILED:", exc, file=sys.stderr)
        sys.exit(1)
