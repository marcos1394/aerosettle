#!/usr/bin/env python3
"""AeroSettle target settlement context. Read-only."""

import base64
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/execution"))

import submission_gate as gate

TARGET = "EnkZQWDqF5HeFeusZ7xnj7tngVN9xASofmKvXtDLeqbx"

EXPECTED_CREATOR = (
    "9aA2jeb1Cds7m4VMhYRpGCv9UJzdREZBZAVEYmBxAzeZ"
)

EXPECTED_VERIFIER = (
    "DmWQhuVujHrJb4jFzo62UnCT3mwnx9GFtVdo8VUu82Wu"
)

EXPECTED_ATTESTATION = (
    "9ef2d74bf906992ba3c752405a47a9b5bd591b16284ce87b5d174132b77ab523"
)

TOKEN_PROGRAM = (
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
)

AMOUNT = 10_000_000

def require(condition, message):
    if not condition:
        raise RuntimeError(message)

def decode_data(account):
    return base64.b64decode(
        account["data"][0],
        validate=True
    )

def main():
    require(
        gate.rpc("getGenesisHash") == gate.GENESIS,
        "Genesis Hash incorrecto"
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

    raw = gate.get_account(TARGET)

    require(
        raw["owner"] == gate.PROGRAM,
        "WorkOrder owner incorrecto"
    )

    order = idl.decode_account(
        "WorkOrderAccount",
        gate.d.parse_rpc_account(raw, gate.PROGRAM)
    )

    require(
        order["status"] in ("Verified", "Settled"),
        "WorkOrder no está Verified/Settled"
    )

    require(
        order["creator"] == EXPECTED_CREATOR,
        "Creator incorrecto"
    )

    require(
        order["verifier"] == EXPECTED_VERIFIER,
        "Verifier incorrecto"
    )

    require(
        order["verification_status"] == "Accepted",
        "VerificationStatus no es Accepted"
    )

    require(
        order["completion_bps"] == 10000,
        "Completion no es 100%"
    )

    require(
        order["verification_attestation_hash"]
        == EXPECTED_ATTESTATION,
        "Attestation Hash incompatible"
    )

    require(
        order["payment_model"] in (
            "Fixed", "Proportional"
        ),
        "PaymentModel incompatible"
    )

    require(
        order["total_amount"] == AMOUNT,
        "Monto económico inesperado"
    )

    require(
        order["token_program"] == TOKEN_PROGRAM,
        "Token Program no soportado"
    )

    config = gate.d.find_program_address(
        [b"protocol_config"],
        gate.PROGRAM
    )

    require(
        order["protocol_config"] == config,
        "ProtocolConfig incorrecto"
    )

    derived_order = gate.d.find_program_address(
        [
            b"work_order",
            gate.d.b58decode(config, 32),
            gate.d.b58decode(order["creator"], 32),
            bytes.fromhex(order["work_order_id"])
        ],
        gate.PROGRAM
    )

    require(
        derived_order == TARGET,
        "WorkOrder PDA incorrecta"
    )

    vault = gate.d.find_program_address(
        [
            b"escrow",
            gate.d.b58decode(TARGET, 32)
        ],
        gate.PROGRAM
    )

    require(
        order["escrow_vault"] == vault,
        "Escrow PDA incorrecta"
    )

    mint_raw = gate.get_account(order["token_mint"])

    require(
        mint_raw["owner"] == TOKEN_PROGRAM,
        "Mint owner incompatible"
    )

    mint_data = decode_data(mint_raw)

    require(
        len(mint_data) >= 82
        and mint_data[45] == 1,
        "Mint SPL no inicializado"
    )

    decimals = mint_data[44]

    vault_raw = gate.rpc(
        "getAccountInfo",
        [
            vault,
            {
                "encoding": "base64",
                "commitment": "confirmed",
            },
        ],
    )["value"]

    vault_closed = vault_raw is None

    if vault_closed:
        require(
            order["status"] == "Settled",
            "Vault ausente antes del settlement"
        )
        vault_amount = 0
    else:
        require(
            vault_raw["owner"] == TOKEN_PROGRAM,
            "Vault no pertenece a SPL Token"
        )

        data = decode_data(vault_raw)

        require(
            len(data) >= 165 and data[108] == 1,
            "Vault SPL inválido"
        )

        require(
            gate.d.b58encode(data[0:32])
            == order["token_mint"],
            "Vault mint incorrecto"
        )

        require(
            gate.d.b58encode(data[32:64]) == vault,
            "Vault authority incorrecta"
        )

        vault_amount = int.from_bytes(
            data[64:72], "little"
        )

    expected_vault = (
        AMOUNT if order["status"] == "Verified"
        else 0
    )

    require(
        vault_amount == expected_vault,
        "Saldo del escrow incompatible"
    )

    beneficiary = order["settlement_beneficiary"]

    require(
        beneficiary != gate.d.b58encode(bytes(32)),
        "Beneficiario no configurado"
    )

    fee_payer = subprocess.check_output(
        [
            "solana-keygen",
            "pubkey",
            str(Path.home() / ".config/solana/id.json")
        ],
        text=True
    ).strip()

    context = {
        "schema": "aerosettle.target-settlement.v1",
        "genesis": gate.GENESIS,
        "program_id": gate.PROGRAM,
        "owner": fee_payer,
        "creator": order["creator"],
        "protocol_config": config,
        "work_order": TARGET,
        "status": order["status"],
        "settlement_beneficiary": beneficiary,
        "payment_model": order["payment_model"],
        "verification_status": order["verification_status"],
        "completion_bps": order["completion_bps"],
        "verification_attestation_hash":
            order["verification_attestation_hash"],
        "token_mint": order["token_mint"],
        "token_program": order["token_program"],
        "total_amount": str(AMOUNT),
        "escrow_vault": vault,
        "vault_amount": str(vault_amount),
        "vault_closed": vault_closed,
        "mint_decimals": decimals,
    }

    output = (
        ROOT / ".aerosettle-local"
        / "settlement-context-target-submitted.json"
    )

    output.parent.mkdir(
        parents=True, exist_ok=True
    )

    output.write_text(
        json.dumps(context, indent=2) + "\n"
    )

    print("=" * 64)
    print("AEROSETTLE — TARGET SETTLEMENT PREFLIGHT")
    print("=" * 64)
    print("WorkOrder:", TARGET)
    print("Status:", order["status"])
    print("Creator:", order["creator"])
    print("Beneficiary:", beneficiary)
    print("Fee payer:", fee_payer)
    print("Payment model:", order["payment_model"])
    print("Verification:", order["verification_status"])
    print("Completion BPS:", order["completion_bps"])
    print("Mint:", order["token_mint"])
    print("Decimals:", decimals)
    print("Escrow:", vault)
    print("Vault balance:", vault_amount)
    print("Vault closed:", vault_closed)
    print("Expected payout:", AMOUNT)
    print("Expected refund:", 0)
    print("Transactions sent: 0")
    print("=" * 64)

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(
            "❌ SETTLEMENT PREFLIGHT:",
            exc,
            file=sys.stderr
        )
        sys.exit(1)
