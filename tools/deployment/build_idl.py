"""Generate the Anchor IDL without changing the deployed error ABI.

Anchor 1.2 rejects a program with more than one ``#[error_code]`` enum while
assembling the IDL.  The program has three such enums, each starting at 6000.
This tool consumes Anchor's own compiled IDL print output, retains its program
definition, and writes the ambiguous error codes to a namespaced sidecar.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROGRAM = ROOT / "programs" / "aerosettle"


def _sections(output: str, name: str) -> list[str]:
    pattern = re.compile(
        rf"^--- IDL begin {re.escape(name)} ---\n(.*?)^--- IDL end {re.escape(name)} ---$",
        re.MULTILINE | re.DOTALL,
    )
    return [match.group(1) for match in pattern.finditer(output)]


def generate(output: str) -> tuple[dict, dict]:
    program_sections = _sections(output, "program")
    address_sections = _sections(output, "address")
    error_sections = _sections(output, "errors")
    if len(program_sections) != 1 or len(address_sections) != 1 or len(error_sections) != 3:
        raise ValueError("Unexpected Anchor IDL print structure")
    idl = json.loads(program_sections[0])
    idl["address"] = json.loads(json.loads(address_sections[0].strip()))
    if idl["address"] != "CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy":
        raise ValueError("Anchor program ID changed")
    errors = [json.loads(section) for section in error_sections]
    if any(not isinstance(group, list) or not group for group in errors):
        raise ValueError("Invalid Anchor error definition")
    # Anchor's numeric error codes overlap across the three existing enums.
    # Publishing them in one flat IDL would imply a false unique mapping.
    idl["errors"] = []
    names = {"Unauthorized": "ErrorCode", "InvalidNetworkId": "IdentityError", "InvalidWorkOrderId": "WorkOrderError"}
    catalog = {"status": "AMBIGUOUS_NUMERIC_CODES", "error_groups": {}}
    for group in errors:
        name = names.get(group[0].get("name"))
        if not name or name in catalog["error_groups"]:
            raise ValueError("Unexpected Anchor error group")
        catalog["error_groups"][name] = group
    return idl, catalog


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--idl", type=Path, required=True)
    parser.add_argument("--error-catalog", type=Path, required=True)
    parser.add_argument("--raw-output", type=Path, help="Use captured Anchor output for diagnosis")
    args = parser.parse_args()
    if args.raw_output:
        output = args.raw_output.read_text()
    else:
        result = subprocess.run(
            ["cargo", "test", "__anchor_private_print_idl", "--features", "idl-build", "--", "--show-output", "--quiet"],
            cwd=PROGRAM, text=True, capture_output=True, check=False,
            env={**__import__("os").environ, "ANCHOR_IDL_BUILD_RESOLUTION": "FALSE"},
        )
        if result.returncode:
            raise SystemExit("Anchor IDL compile failed: " + result.stderr[-4000:])
        output = result.stdout
    idl, catalog = generate(output)
    args.idl.parent.mkdir(parents=True, exist_ok=True)
    args.error_catalog.parent.mkdir(parents=True, exist_ok=True)
    args.idl.write_text(json.dumps(idl, indent=2, sort_keys=True) + "\n")
    args.error_catalog.write_text(json.dumps(catalog, indent=2, sort_keys=True) + "\n")
    print(f"Generated Anchor IDL: {args.idl}")


if __name__ == "__main__":
    main()
