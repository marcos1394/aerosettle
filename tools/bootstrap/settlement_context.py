#!/usr/bin/env python3
"""Read-only settlement context for AeroSettle Localnet."""

from pathlib import Path
import json
import os
import re
import runpy

TAG = os.environ.get(
    "AEROSETTLE_ORDER_TAG", "claim-v2"
)

if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", TAG):
    raise SystemExit("Invalid WorkOrder tag")

verification_file = Path(
    "tools/bootstrap/verification_context.py"
)

verification_source = verification_file.read_text()

old_states = '"Claimed", "Submitted", "Verified"'
new_states = '"Claimed", "Submitted", "Verified", "Settled"'

if verification_source.count(old_states) != 1:
    raise SystemExit(
        "Estados inesperados en verification_context.py"
    )

verification_source = verification_source.replace(
    old_states,
    new_states,
    1,
)

scope = {
    "__name__": "__main__",
    "__file__": str(verification_file),
}

exec(
    compile(
        verification_source,
        str(verification_file),
        "exec",
    ),
    scope,
)

order = scope["order"]
context = dict(scope["context"])

fields = (
    "creator",
    "settlement_beneficiary",
    "token_mint",
    "total_amount",
    "payment_model",
)

missing = [
    field for field in fields
    if field not in order
]

if missing:
    raise SystemExit(
        "Faltan campos económicos: "
        + str(missing)
        + "\nCampos disponibles: "
        + str(sorted(order))
    )

for field in (
    "creator",
    "settlement_beneficiary",
    "token_mint",
):
    scope["ad"].b58decode(
        order[field], 32
    )

amount = order["total_amount"]

if type(amount) is not int or amount <= 0:
    raise SystemExit(
        "total_amount inválido"
    )

if context["status"] not in (
    "Verified", "Settled"
):
    raise SystemExit(
        "La WorkOrder no está Verified/Settled"
    )

context.update({
    field: order[field]
    for field in fields
})

context["total_amount"] = str(amount)

if context.get("verification_status") is not None:
    if context["verification_status"] != "Accepted":
        raise SystemExit(
            "VerificationStatus no es Accepted"
        )

if context.get("completion_bps") is not None:
    if context["completion_bps"] != 10000:
        raise SystemExit(
            "La ejecución no fue aceptada al 100%"
        )

if context["payment_model"] != "Fixed":
    raise SystemExit(
        "PaymentModel no es Fixed"
    )

if amount != 10_000_000:
    raise SystemExit(
        "La orden no contiene los 10 tokens esperados"
    )

if context["creator"] != context["owner"]:
    raise SystemExit(
        "El creador no coincide con el bootstrap local"
    )

output = Path(
    ".aerosettle-local/"
    f"settlement-context-{TAG}.json"
)

output.write_text(
    json.dumps(context, indent=2) + "\n"
)

print("\n=== AEROSETTLE SETTLEMENT CONTEXT ===")
print("WorkOrder:", context["work_order"])
print("Status:", context["status"])
print("Creator:", context["creator"])
print(
    "Beneficiary:",
    context["settlement_beneficiary"]
)
print("Mint:", context["token_mint"])
print("Payment model:", context["payment_model"])
print("Amount:", context["total_amount"])
print("Context:", output)
