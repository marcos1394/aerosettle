"""Deterministic CycloneDX inventory from resolved local dependency state."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import re
import tomllib
from pathlib import Path


NPM_LOCKS = (
    "apps/marketplace-web/package-lock.json",
    "packages/marketplace-sdk/package-lock.json",
    "packages/transaction-sdk/package-lock.json",
    "tools/bootstrap/package-lock.json",
)
PYTHON_REQUIREMENTS = ("requirements.txt", "tools/deployment/requirements.txt",
                       "tools/economic_ledger/requirements.txt")
LOCKS = ("Cargo.lock", *NPM_LOCKS, *PYTHON_REQUIREMENTS, "Anchor.toml")
REQUIREMENT = re.compile(r"^([A-Za-z0-9_.-]+)")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def component(kind: str, name: str, version: str, scope: str) -> dict:
    ref = f"pkg:{kind}/{name}@{version}"
    return {"type": "library", "bom-ref": f"{scope}:{ref}", "name": name,
            "version": version, "purl": ref, "properties": [{"name": "conatus:scope", "value": scope}]}


def generate(root: Path) -> dict:
    root = root.resolve()
    for lock in LOCKS:
        if not (root / lock).is_file():
            raise ValueError(f"Missing dependency manifest: {lock}")
    items: dict[str, dict] = {}
    cargo = tomllib.loads((root / "Cargo.lock").read_text())
    for package in cargo.get("package", []):
        entry = component("cargo", package["name"], package["version"], "rust")
        items[entry["bom-ref"]] = entry
    if not any(x["properties"][0]["value"] == "rust" for x in items.values()):
        raise ValueError("Cargo dependency inventory empty")
    for lock in NPM_LOCKS:
        data = json.loads((root / lock).read_text())
        if type(data.get("packages")) is not dict or not data["packages"]:
            raise ValueError(f"Unsupported or empty npm lockfile: {lock}")
        for location, package in data["packages"].items():
            name = package.get("name") or (location.split("node_modules/")[-1] if location else data.get("name"))
            version = package.get("version")
            if not name or not version:
                continue
            entry = component("npm", name, version, lock)
            items[entry["bom-ref"]] = entry
    required: set[str] = set()
    for file in PYTHON_REQUIREMENTS:
        for line in (root / file).read_text().splitlines():
            match = REQUIREMENT.match(line.strip())
            if match and not line.lstrip().startswith("#"):
                required.add(match.group(1).lower().replace("_", "-"))
    installed = {d.metadata["Name"].lower().replace("_", "-"): d.version
                 for d in importlib.metadata.distributions() if d.metadata.get("Name")}
    missing = sorted(required - installed.keys())
    if missing:
        raise ValueError("Missing installed Python requirements: " + ", ".join(missing))
    for name, version in installed.items():
        entry = component("pypi", name, version, "python")
        items[entry["bom-ref"]] = entry
    if not any(x["properties"][0]["value"] == "python" for x in items.values()):
        raise ValueError("Python dependency inventory empty")
    return {
        "bomFormat": "CycloneDX", "specVersion": "1.5", "version": 1,
        "metadata": {
            "component": {"type": "application", "name": "conatus", "version": "CON-46"},
            "properties": [{"name": "conatus:manifest-sha256:" + file, "value": sha(root / file)}
                           for file in LOCKS],
        },
        "components": [items[key] for key in sorted(items)],
    }


def validate(bom: dict) -> None:
    if bom.get("bomFormat") != "CycloneDX" or bom.get("specVersion") != "1.5":
        raise ValueError("Invalid SBOM format")
    entries = bom.get("components")
    if type(entries) is not list or not entries:
        raise ValueError("Empty SBOM")
    refs = [x.get("bom-ref") for x in entries if type(x) is dict]
    if len(refs) != len(entries) or len(set(refs)) != len(refs):
        raise ValueError("Duplicate or invalid SBOM components")
    scopes = {p.get("value") for x in entries for p in x.get("properties", [])
              if p.get("name") == "conatus:scope"}
    if not {"rust", "python", *NPM_LOCKS}.issubset(scopes):
        raise ValueError("SBOM omits a required ecosystem")
    properties = bom.get("metadata", {}).get("properties", [])
    recorded = {x.get("name"): x.get("value") for x in properties}
    if any("conatus:manifest-sha256:" + x not in recorded for x in LOCKS):
        raise ValueError("SBOM omits a dependency manifest hash")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        bom = generate(args.root)
        validate(bom)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(bom, sort_keys=True, separators=(",", ":")) + "\n")
    except (ValueError, OSError, KeyError, json.JSONDecodeError) as exc:
        print(f"SBOM FAILED: {exc}")
        return 1
    print(f"SBOM VERIFIED: {len(bom['components'])} components; sha256={sha(args.output)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
