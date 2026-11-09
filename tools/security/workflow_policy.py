"""Reject privileged or unpinned GitHub Actions paths in repository workflows."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


PINNED_ACTION = re.compile(r"^\s*-\s*uses:\s+[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@[0-9a-f]{40}\s*$", re.M)
USES = re.compile(r"^\s*-\s*uses:\s*(.+)$", re.M)
DANGEROUS = (
    re.compile(r"\bsolana\s+program\s+(?:deploy|upgrade|set-upgrade-authority)\b", re.I),
    re.compile(r"\bdeploy\s+--submit\b", re.I),
    re.compile(r"\b(?:asset_funding|protocol_config|workorder_create)\.cjs\s+submit\b", re.I),
    re.compile(r"\b(?:mainnet-beta|mainnet)\b", re.I),
)


def check_text(source: str) -> list[str]:
    errors: list[str] = []
    if re.search(r"^on:\s*\n(?:.|\n)*?^\s*pull_request_target\s*:", source, re.M):
        errors.append("pull_request_target is prohibited")
    if not re.search(r"^permissions:\s*\n\s{2}contents:\s*read\s*$", source, re.M):
        errors.append("Top-level contents: read permission required")
    for line in source.splitlines():
        if re.search(r"^\s+(?:contents|actions|checks|deployments|id-token|packages|pull-requests):\s*write\s*$", line):
            errors.append("Write or id-token permission prohibited")
        if "continue-on-error: true" in line:
            errors.append("Fail-open step prohibited")
        if "secrets." in line:
            errors.append("Workflow secrets prohibited in PR-capable workflows")
    for match in USES.finditer(source):
        if not PINNED_ACTION.fullmatch(match.group(0)):
            errors.append("Action must be pinned to a 40-character commit SHA")
    # Scan only commands and expressions, not harmless human-readable job names.
    for line in source.splitlines():
        if not ("run:" in line or line.startswith("          ") or line.startswith("            ")):
            continue
        if any(pattern.search(line) for pattern in DANGEROUS):
            errors.append("Transaction, authority, or Mainnet command in PR workflow")
    return sorted(set(errors))


def check_directory(folder: Path) -> dict[str, list[str]]:
    workflows = sorted(folder.glob("*.yml")) + sorted(folder.glob("*.yaml"))
    if not workflows:
        return {str(folder): ["No workflows found"]}
    return {str(path): errors for path in workflows if (errors := check_text(path.read_text()))}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workflows", type=Path, default=Path(".github/workflows"))
    args = parser.parse_args()
    failures = check_directory(args.workflows)
    for path, errors in failures.items():
        for error in errors:
            print(f"FAILED {path}: {error}")
    if failures:
        return 1
    print("VERIFIED: workflows use read-only permissions, pinned actions and no PR deployment path")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
