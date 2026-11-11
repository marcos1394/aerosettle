"""Evaluate live npm audit output against narrowly scoped, expiring exceptions."""

from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path

from .sbom import NPM_LOCKS


ADVISORY = re.compile(r"GHSA-[a-z0-9-]+\Z")
EXCEPTION_FIELDS = frozenset({
    "advisory_id", "package", "affected_version", "patched_version", "severity",
    "exploitability", "exposure", "mitigation", "owner", "review_date",
    "resolution_status", "scopes",
})


def evaluate(root: Path, reports: dict[str, dict], exceptions: list[dict], *, today: date | None = None) -> dict:
    today = today or date.today()
    indexed = {}
    for entry in exceptions:
        if type(entry) is not dict or set(entry) != EXCEPTION_FIELDS:
            raise ValueError("Malformed dependency exception")
        if not ADVISORY.fullmatch(entry["advisory_id"]):
            raise ValueError("Invalid advisory identifier")
        if entry["resolution_status"] != "TEMPORARY_EXCEPTION" or not all(
            entry[field] for field in ("exploitability", "exposure", "mitigation", "owner")
        ):
            raise ValueError("Incomplete dependency exception")
        if date.fromisoformat(entry["review_date"]) < today:
            raise ValueError(f"Expired dependency exception: {entry['advisory_id']}")
        for scope in entry["scopes"]:
            if scope not in NPM_LOCKS:
                raise ValueError("Unknown dependency exception scope")
            key = (scope, entry["advisory_id"], entry["package"], entry["affected_version"])
            if key in indexed:
                raise ValueError("Duplicate dependency exception")
            indexed[key] = entry
    observed = []
    for scope in NPM_LOCKS:
        report = reports.get(scope)
        if type(report) is not dict or report.get("error") or type(report.get("vulnerabilities")) is not dict:
            raise ValueError(f"Live npm audit unavailable or malformed: {scope}")
        packages = json.loads((root / scope).read_text())["packages"]
        for vulnerability in report["vulnerabilities"].values():
            for finding in vulnerability.get("via", []):
                if type(finding) is not dict:
                    continue
                advisory_id = finding.get("url", "").rsplit("/", 1)[-1]
                package = finding.get("name")
                versions = {info["version"] for location, info in packages.items()
                            if location.endswith("node_modules/" + package) and "version" in info}
                if not versions:
                    raise ValueError(f"Advisory package absent from lockfile: {scope}/{package}")
                # npm can report several installed versions; an exception must bind each
                # affected version. When an unaffected nested version exists, it is ignored.
                matched = [indexed[(scope, advisory_id, package, version)] for version in versions
                           if (scope, advisory_id, package, version) in indexed]
                if not matched:
                    raise ValueError(f"Unexcepted advisory: {scope}/{advisory_id}/{package}")
                if any(item["severity"] != finding["severity"] for item in matched):
                    raise ValueError(f"Advisory severity changed: {advisory_id}")
                observed.append({"scope": scope, "advisory_id": advisory_id, "package": package,
                                 "severity": finding["severity"], "resolution_status": "TEMPORARY_EXCEPTION"})
    return {"status": "VERIFIED_WITH_EXCEPTIONS", "advisories": observed,
            "exception_count": len(observed)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--exceptions", type=Path,
                        default=Path("tools/security/dependency-exceptions.json"))
    args = parser.parse_args()
    try:
        reports = {scope: json.loads((args.report_dir / (Path(scope).parent.name + ".json")).read_text())
                   for scope in NPM_LOCKS}
        result = evaluate(args.root, reports, json.loads(args.exceptions.read_text()))
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "FAILED", "reason": str(exc)}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
