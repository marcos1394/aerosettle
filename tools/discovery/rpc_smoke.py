import base64
import json
import os
import urllib.request
from pathlib import Path

RPC = os.environ.get(
    "AEROSETTLE_RPC",
    "http://127.0.0.1:8899",
)

IDL_PATH = Path(
    "target/idl/aerosettle.discovery.json"
)

EXPECTED_ID = (
    "CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy"
)

idl = json.loads(IDL_PATH.read_text())
program_id = idl["address"]

if program_id != EXPECTED_ID:
    raise SystemExit("Program ID incorrecto")


def rpc(method, params):
    payload = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params,
    }).encode()

    req = urllib.request.Request(
        RPC,
        data=payload,
        headers={
            "Content-Type": "application/json"
        },
    )

    with urllib.request.urlopen(
        req,
        timeout=20,
    ) as response:
        result = json.load(response)

    if "error" in result:
        raise RuntimeError(result["error"])

    return result["result"]


program = rpc(
    "getAccountInfo",
    [
        program_id,
        {"encoding": "base64"},
    ],
)["value"]

if not program or not program.get("executable"):
    raise SystemExit(
        "AeroSettle todavía no está desplegado"
    )

print("✅ AeroSettle executable")
print("RPC:", RPC)
print("Program ID:", program_id)

accounts = rpc(
    "getProgramAccounts",
    [
        program_id,
        {
            "encoding": "base64",
            "commitment": "confirmed",
            "dataSlice": {
                "offset": 0,
                "length": 8,
            },
        },
    ],
)

snapshot = {}

for name in (
    "ProtocolConfig",
    "AgentAccount",
    "WorkOrderAccount",
):
    matching_schema = [
        entry
        for entry in idl["accounts"]
        if entry["name"].split("::")[-1] == name
    ]

    if len(matching_schema) != 1:
        raise RuntimeError(
            f"Esquema inválido: {name}"
        )

    discriminator = bytes(
        matching_schema[0]["discriminator"]
    )

    matched = []

    for entry in accounts:
        encoded = entry["account"]["data"][0]
        data = base64.b64decode(encoded)

        if data == discriminator:
            matched.append(entry["pubkey"])

    snapshot[name] = matched
    print(f"{name}: {len(matched)} cuenta(s)")

output = Path(
    ".aerosettle-local/rpc-smoke.json"
)

output.parent.mkdir(
    parents=True,
    exist_ok=True,
)

output.write_text(
    json.dumps(
        {
            "rpc": RPC,
            "program_id": program_id,
            "accounts": snapshot,
        },
        indent=2,
    ) + "\n"
)

print("✅ RPC Smoke Test completado")
print("Snapshot:", output)
