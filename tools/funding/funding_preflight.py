#!/usr/bin/env python3
"""
AeroSettle - EPIC 3.4.3
Funding SPL Preflight (Localnet).

Read-only auditor de WorkOrders, cuentas SPL y escrow.

Requiere:
  tools/discovery/agent_discovery.py
  target/idl/aerosettle.discovery.json
  programas Rust de AeroSettle

No firma, transmite, acuña ni transfiere tokens.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys

from pathlib import Path
from typing import Any


PROGRAM = (
    "CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy"
)

GENESIS = (
    "HP9XKTusRPGC78EFDpR9xdEq6simL2vqyDdrMvn6Vacg"
)

MINT = (
    "HTHpns7gqLAhSBhAzqxhYdyHv9HeXkkRW6aHQfdUjL1G"
)

TOKEN_PROGRAM = (
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
)

SYSTEM_PROGRAM = "11111111111111111111111111111111"


EXPECTED_ACCOUNTS = [
    ("protocol_config", False, False),
    ("work_order", False, True),
    ("creator", True, True),
    ("mint", False, False),
    ("creator_token_account", False, True),
    ("escrow_vault", False, True),
    ("token_program", False, False),
    ("system_program", False, False),
]


def get_decoder(root: Path):
    discovery = root / "tools" / "discovery"

    if not (
        discovery / "agent_discovery.py"
    ).exists():
        raise RuntimeError(
            "Falta tools/discovery/agent_discovery.py "
            "del EPIC 3.2"
        )

    sys.path.insert(0, str(discovery))

    import agent_discovery as d

    return d


def rust_account_audit(root: Path) -> dict[str, Any]:
    """
    Compara el orden de cuentas con la estructura
    FundWorkOrder declarada en el programa Rust.
    """

    src = root / "programs" / "aerosettle" / "src"

    if not src.exists():
        raise RuntimeError(
            "No se encuentra programs/aerosettle/src"
        )

    matches = []

    pattern = (
        r"pub\s+struct\s+FundWorkOrder\b"
        r"[^\{]*\{(.*?)^\s*\}"
    )

    for file in src.rglob("*.rs"):
        contents = file.read_text()

        result = re.search(
            pattern,
            contents,
            re.S | re.M,
        )

        if result:
            matches.append(
                (file, result.group(1))
            )

    if len(matches) != 1:
        raise RuntimeError(
            "Se esperaba una definición FundWorkOrder "
            f"en Rust; encontradas: {len(matches)}"
        )

    file, body = matches[0]

    actual = re.findall(
        r"\bpub\s+([a-z_]+)\s*:",
        body,
    )

    expected = [
        name for name, _, _ in EXPECTED_ACCOUNTS
    ]

    if actual != expected:
        raise RuntimeError(
            "Cuentas Rust diferentes.\n"
            f"Actual: {actual}\n"
            f"Esperado: {expected}"
        )

    return {
        "source_file": str(
            file.relative_to(root)
        ),
        "accounts_in_rust_order": actual,
    }


def read_escrow_seed(root: Path) -> bytes:
    """
    Obtiene ESCROW_VAULT_SEED del código real Rust.
    No presupone que la semilla sea 'escrow'.
    """

    src = root / "programs" / "aerosettle" / "src"

    matches = set()

    pattern = (
        r"\bESCROW_VAULT_SEED\s*:"
        r"[^=;\n]*=\s*b\"([a-zA-Z0-9_-]+)\""
    )

    for file in src.rglob("*.rs"):
        contents = file.read_text()

        for match in re.finditer(
            pattern,
            contents,
        ):
            matches.add(
                match.group(1).encode("ascii")
            )

    if len(matches) != 1:
        raise RuntimeError(
            "ESCROW_VAULT_SEED no verificable "
            f"unívocamente: {len(matches)} valores"
        )

    seed = matches.pop()

    if len(seed) > 32:
        raise RuntimeError(
            "ESCROW_VAULT_SEED demasiado largo"
        )

    return seed


def choose_source(
    accounts: list[dict],
    wallet: str,
    mint: str,
    minimum: int,
):
    """
    Selecciona una cuenta SPL válida perteneciente
    a la wallet, inicializada y no congelada.
    """

    candidates = []

    for record in accounts:

        account = record.get("account", {})

        if account.get("owner") != TOKEN_PROGRAM:
            continue

        parsed = (
            account.get("data", {})
            .get("parsed", {})
        )

        if parsed.get("type") != "account":
            continue

        info = parsed.get("info", {})

        if info.get("owner") != wallet:
            continue

        if info.get("mint") != mint:
            continue

        if info.get("state") != "initialized":
            continue

        if info.get("delegate") is not None:
            continue

        try:
            amount = int(
                info["tokenAmount"]["amount"]
            )
        except (
            KeyError,
            TypeError,
            ValueError,
        ):
            continue

        if amount < 0:
            continue

        candidates.append(
            (amount, record["pubkey"])
        )

    candidates.sort(
        key=lambda item: (
            -item[0],
            item[1],
        )
    )

    eligible = next(
        (
            (amount, key)
            for amount, key in candidates
            if amount >= minimum
        ),
        None,
    )

    return eligible, candidates


def read_mint(d, rpc, mint: str):
    """
    Verifica mint SPL Token clásico.
    Formato Mint: 82 bytes.
    """

    _, info = d.query_account(
        rpc,
        mint,
        "confirmed",
    )

    raw = d.parse_rpc_account(
        info,
        TOKEN_PROGRAM,
    )

    if len(raw) != 82 or raw[45] != 1:
        raise RuntimeError(
            "Mint no inicializado o no SPL Token classic"
        )

    decimals = raw[44]

    supply = int.from_bytes(
        raw[36:44],
        "little",
    )

    if decimals != 6:
        raise RuntimeError(
            "Se esperaban 6 decimales, "
            f"encontrados {decimals}"
        )

    return decimals, supply


def check_idl_discriminator(raw_idl: dict):
    """
    Calcula el discriminador Anchor y compara
    cualquier definición disponible en el IDL.
    """

    discriminator = hashlib.sha256(
        b"global:fund_work_order"
    ).digest()[:8]

    for ix in raw_idl.get(
        "instructions", []
    ):

        name = str(
            ix.get("name", "")
        ).replace("_", "").lower()

        if name != "fundworkorder":
            continue

        declared = ix.get("discriminator")

        if declared is not None:
            if bytes(declared) != discriminator:
                raise RuntimeError(
                    "Discriminador IDL diferente "
                    "al discriminador Anchor"
                )

        if ix.get("args"):
            raise RuntimeError(
                "FundWorkOrder no debe tener "
                "argumentos en esta versión"
            )

        if ix.get("accounts"):

            actual = [
                a["name"]
                .replace("_", "")
                .lower()
                for a in ix["accounts"]
            ]

            expected = [
                name.replace("_", "").lower()
                for name, _, _ in EXPECTED_ACCOUNTS
            ]

            if actual != expected:
                raise RuntimeError(
                    "El orden de cuentas entre "
                    "IDL y Rust es diferente"
                )

    return discriminator



def extract_settlement_terms(
    order: dict,
    idl: Any,
) -> tuple[dict, str]:
    """
    Extrae token_mint y total_amount únicamente
    mediante tipos comprobados del IDL Anchor.

    Admite:
      - Struct financiera anidada y tipada
      - Campos planos explícitos y tipados

    Cualquier ambigüedad bloquea el Funding.
    """

    def key(name: str) -> str:
        return "".join(
            c.lower()
            for c in name
            if c.isalnum()
        )

    def is_financial_schema(fields: Any) -> bool:
        if (
            not isinstance(fields, list)
            or not all(
                isinstance(f, dict)
                for f in fields
            )
        ):
            return False

        mapping = {
            key(f.get("name", "")): f.get("type")
            for f in fields
        }

        if len(mapping) != len(fields):
            raise RuntimeError(
                "Campos IDL ambiguos"
            )

        return (
            mapping.get("tokenmint")
            in ("pubkey", "publicKey")
            and mapping.get("totalamount") == "u64"
        )

    def unique_field(
        data: dict,
        name: str,
    ) -> Any:
        matches = [
            value
            for field, value in data.items()
            if key(field) == key(name)
        ]

        if len(matches) != 1:
            raise RuntimeError(
                f"Campo financiero ausente o ambiguo: {name}"
            )

        return matches[0]

    schema = idl.types.get(
        "WorkOrderAccount",
        {},
    )

    if schema.get("kind") != "struct":
        raise RuntimeError(
            "IDL WorkOrderAccount inválido"
        )

    fields = schema.get("fields", [])

    candidates = []

    for field in fields:
        field_type = field.get("type")

        if (
            not isinstance(field_type, dict)
            or "defined" not in field_type
        ):
            continue

        definition = field_type["defined"]

        defined_name = (
            definition
            if isinstance(definition, str)
            else definition.get("name")
        )

        matches = [
            (name, body)
            for name, body in idl.types.items()
            if key(name) == key(defined_name)
        ]

        if len(matches) != 1:
            raise RuntimeError(
                "Tipo IDL definido ausente "
                f"o ambiguo: {defined_name}"
            )

        name, body = matches[0]

        if (
            body.get("kind") == "struct"
            and is_financial_schema(
                body.get("fields")
            )
        ):
            candidates.append(
                (field["name"], name)
            )

    if len(candidates) > 1:
        raise RuntimeError(
            "Múltiples estructuras financieras "
            "compatibles. Funding bloqueado."
        )

    if len(candidates) == 1:
        field_name, type_name = candidates[0]

        settlement = unique_field(
            order,
            field_name,
        )

        if not isinstance(settlement, dict):
            raise RuntimeError(
                "La estructura financiera "
                "no se decodificó correctamente"
            )

        source = (
            f"WorkOrderAccount.{field_name}"
            f" ({type_name})"
        )

    elif is_financial_schema(fields):
        settlement = order
        source = (
            "WorkOrderAccount "
            "(campos financieros planos)"
        )

    else:
        raise RuntimeError(
            "El IDL no declara inequívocamente "
            "token_mint(pubkey) y total_amount(u64). "
            "No se puede autorizar Funding."
        )

    mint = unique_field(
        settlement,
        "token_mint",
    )

    amount = unique_field(
        settlement,
        "total_amount",
    )

    if (
        not isinstance(mint, str)
        or not isinstance(amount, int)
        or isinstance(amount, bool)
    ):
        raise RuntimeError(
            "Tipos financieros decodificados inválidos"
        )

    return {
        "token_mint": mint,
        "total_amount": amount,
    }, source


def audit(args):
    """
    Auditoría principal.

    Returns:
      (report, ready_for_funding)
    """

    root = Path(__file__).resolve().parents[2]

    d = get_decoder(root)

    d.b58decode(args.wallet, 32)

    rust = rust_account_audit(root)

    raw_idl = json.loads(
        (root / args.idl).read_text()
    )

    idl = d.Idl(raw_idl)

    if idl.address != PROGRAM:
        raise RuntimeError(
            "Program ID diferente al esperado"
        )

    discriminator = check_idl_discriminator(
        raw_idl
    )

    rpc = d.Rpc(args.rpc_url)

    chain_genesis = rpc.call(
        "getGenesisHash", []
    )

    if chain_genesis != GENESIS:
        raise RuntimeError(
            "RPC conectado a otra blockchain. "
            "Funding bloqueado."
        )

    report: dict[str, Any] = {
        "schema_version":
            "aerosettle.funding_preflight.v1",
        "network": "Localnet ONLY",
        "rpc_url": args.rpc_url,
        "genesis": GENESIS,
        "program_id": PROGRAM,
        "wallet": args.wallet,
        "mint": MINT,
        "rust_account_audit": rust,
        "write_operations_performed": 0,
        "ready_for_funding": False,
        "instruction_name": "fund_work_order",
        "instruction_data_hex":
            discriminator.hex(),
        "notes": [],
    }

    # Verificar el programa desplegado.

    _, program_info = d.query_account(
        rpc,
        PROGRAM,
        "confirmed",
    )

    if (
        program_info is None
        or not program_info.get("executable")
    ):
        raise RuntimeError(
            "AeroSettle no está desplegado "
            "o no es ejecutable"
        )

    # Discovery obtiene WorkOrders y ProtocolConfig.

    snapshot = d.discover(
        rpc,
        idl,
        "confirmed",
    )

    if snapshot["protocol_paused"]:
        raise RuntimeError(
            "ProtocolConfig está pausado"
        )

    drafts = [
        order
        for order in snapshot["work_orders"]
        if (
            order["creator"] == args.wallet
            and order["status"] == "Draft"
        )
    ]

    report["drafts_for_wallet"] = [
        order["work_order_account"]
        for order in drafts
    ]

    # Elegir una única WorkOrder.

    if args.work_order:

        selected = next(
            (
                order
                for order in drafts
                if order["work_order_account"]
                == args.work_order
            ),
            None,
        )

        if selected is None:
            report["notes"].append(
                "La WorkOrder no existe, "
                "no es Draft o no pertenece a Phantom"
            )

            return report, False

    else:

        if len(drafts) != 1:
            report["notes"].append(
                f"Se encontraron {len(drafts)} "
                "WorkOrders Draft. "
                "Selecciona una mediante --work-order"
            )

            return report, False

        selected = drafts[0]

    work_order = selected[
        "work_order_account"
    ]

    # Decodificar la WorkOrder directamente.

    _, order_info = d.query_account(
        rpc,
        work_order,
        "confirmed",
    )

    order = idl.decode_account(
        "WorkOrderAccount",
        d.parse_rpc_account(
            order_info,
            PROGRAM,
        ),
    )

    if (
        order.get("creator") != args.wallet
        or order.get("status") != "Draft"
    ):
        raise RuntimeError(
            "Estado o creador de WorkOrder inválidos"
        )

    if (
        order.get("protocol_config")
        != snapshot["protocol_config"]
    ):
        raise RuntimeError(
            "WorkOrder pertenece a otro protocolo"
        )

    settlement, settlement_source = (
        extract_settlement_terms(order, idl)
    )

    report["settlement_idl_source"] = (
        settlement_source
    )

    if settlement.get("token_mint") != MINT:
        raise RuntimeError(
            "La WorkOrder utiliza otro token mint"
        )

    total = settlement.get(
        "total_amount"
    )

    if (
        not isinstance(total, int)
        or not (0 < total < 2**64)
    ):
        raise RuntimeError(
            "Monto total inválido"
        )

    if (
        order.get("execution_deadline", 0)
        <= snapshot["now_unix"]
    ):
        raise RuntimeError(
            "Execution deadline vencida"
        )

    if (
        order.get("verification_deadline", 0)
        <= order["execution_deadline"]
    ):
        raise RuntimeError(
            "Verification deadline inválida"
        )

    # Verificar mint y cuentas SPL.

    _, supply = read_mint(
        d,
        rpc,
        MINT,
    )

    token_accounts = rpc.call(
        "getTokenAccountsByOwner",
        [
            args.wallet,
            {"mint": MINT},
            {
                "encoding": "jsonParsed",
                "commitment": "confirmed",
            },
        ],
    )["value"]

    selected_source, candidates = choose_source(
        token_accounts,
        args.wallet,
        MINT,
        total,
    )

    # Obtener la semilla directamente desde Rust.

    escrow_seed = read_escrow_seed(root)

    escrow = d.find_program_address(
        [
            escrow_seed,
            d.b58decode(
                work_order,
                32,
            ),
        ],
        PROGRAM,
    )

    _, vault_info = d.query_account(
        rpc,
        escrow,
        "confirmed",
    )

    if vault_info is not None:
        raise RuntimeError(
            "Escrow Vault ya existe para "
            "esta WorkOrder Draft"
        )

    # Verificar SOL disponible.

    lamports = rpc.call(
        "getBalance",
        [
            args.wallet,
            {"commitment": "confirmed"},
        ],
    )["value"]

    report.update({
        "work_order": work_order,
        "protocol_config":
            snapshot["protocol_config"],
        "order_status": order["status"],
        "amount_base_units": str(total),
        "amount_tokens": (
            f"{total // 1_000_000}."
            f"{total % 1_000_000:06d}"
        ),
        "mint_supply_base_units":
            str(supply),
        "mint_decimals": 6,
        "escrow_vault": escrow,
        "escrow_seed_utf8":
            escrow_seed.decode("ascii"),
        "escrow_exists": False,
        "creator_sol_lamports":
            str(lamports),
        "creator_token_accounts": [
            {
                "address": key,
                "amount_base_units": str(amount),
            }
            for amount, key in candidates
        ],
        "creator_token_account": (
            selected_source[1]
            if selected_source
            else None
        ),
        "execution_deadline":
            order["execution_deadline"],
        "verification_deadline":
            order["verification_deadline"],
        "chain_now_unix":
            snapshot["now_unix"],
        "account_metas": [],
    })

    if selected_source is None:
        report["notes"].append(
            "Saldo SPL insuficiente "
            "en Phantom"
        )

    if lamports < 10_000_000:
        report["notes"].append(
            "Saldo SOL inferior a 0.01 SOL"
        )

    # Preparar cuentas para el Funding Builder.

    by_name = {
        "protocol_config":
            snapshot["protocol_config"],
        "work_order": work_order,
        "creator": args.wallet,
        "mint": MINT,
        "creator_token_account": (
            selected_source[1]
            if selected_source
            else None
        ),
        "escrow_vault": escrow,
        "token_program": TOKEN_PROGRAM,
        "system_program": SYSTEM_PROGRAM,
    }

    report["account_metas"] = [
        {
            "name": name,
            "pubkey": by_name[name],
            "is_signer": signer,
            "is_writable": writable,
        }
        for name, signer, writable
        in EXPECTED_ACCOUNTS
    ]

    ready = (
        selected_source is not None
        and lamports >= 10_000_000
    )

    report["ready_for_funding"] = ready

    report["notes"].append(
        "Snapshot sólo lectura. "
        "Revalidar y simular antes de firmar."
    )

    return report, ready


def main() -> int:

    parser = argparse.ArgumentParser(
        description=__doc__
    )

    parser.add_argument(
        "--wallet",
        required=True,
        help="Dirección pública Phantom",
    )

    parser.add_argument(
        "--work-order",
        help="PDA específica de WorkOrder Draft",
    )

    parser.add_argument(
        "--rpc-url",
        default="http://127.0.0.1:8899",
    )

    parser.add_argument(
        "--idl",
        default="target/idl/aerosettle.discovery.json",
    )

    parser.add_argument(
        "--output",
        default=".aerosettle-local/funding-preflight.json",
    )

    args = parser.parse_args()

    root = Path(__file__).resolve().parents[2]

    try:
        report, ready = audit(args)

    except Exception as exc:
        print(
            f"❌ PREFLIGHT FAIL-CLOSED: {exc}",
            file=sys.stderr,
        )
        return 1

    destination = root / args.output

    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    destination.write_text(
        json.dumps(
            report,
            indent=2,
            ensure_ascii=False,
        ) + "\n"
    )

    print(
        "=== AEROSETTLE FUNDING PREFLIGHT ==="
    )

    print(
        "Program:",
        report["program_id"],
    )

    print(
        "Wallet:",
        report["wallet"],
    )

    print(
        "WorkOrder:",
        report.get(
            "work_order",
            "(pendiente)",
        ),
    )

    print(
        "Order status:",
        report.get(
            "order_status",
            "(no disponible)",
        ),
    )

    print(
        "Amount:",
        report.get(
            "amount_tokens",
            "(no disponible)",
        ),
    )

    print(
        "Source:",
        report.get(
            "creator_token_account",
            "(sin saldo suficiente)",
        ),
    )

    print(
        "Escrow PDA:",
        report.get(
            "escrow_vault",
            "(no disponible)",
        ),
    )

    print(
        "Ready for simulated funding:",
        "YES" if ready else "NO",
    )

    for note in report["notes"]:
        print(" -", note)

    print(
        "Report:",
        destination,
    )

    print(
        "Read-only: 0 transactions sent"
    )

    return 0 if ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
