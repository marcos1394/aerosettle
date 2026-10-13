#!/usr/bin/env python3
"""Busca un keypair local del verificador. Solo lectura."""

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

EXPECTED = (
    "DmWQhuVujHrJb4jFzo62UnCT3mwnx9GFtVdo8VUu82Wu"
)

SEARCH_ROOTS = [
    ROOT,
    Path.home() / ".config/solana",
]

EXCLUDED_DIRS = {
    ".git",
    "node_modules",
    "target",
    "dist",
    "build",
    ".next",
    ".venv",
    "__pycache__",
    ".aerosettle-local-ledger-v0",
    ".coldguard-tests",
}

SUFFIXES = {
    ".json",
    ".keypair",
}

matches = []
checked = 0

print("=== AEROSETTLE VERIFIER KEY SEARCH ===")
print("Expected verifier:", EXPECTED)

for root in SEARCH_ROOTS:
    if not root.is_dir():
        continue

    for directory, dirs, files in os.walk(
        root, followlinks=False
    ):
        dirs[:] = [
            name for name in dirs
            if name not in EXCLUDED_DIRS
        ]

        for filename in files:
            path = Path(directory) / filename

            if path.is_symlink():
                continue

            if path.suffix not in SUFFIXES:
                continue

            try:
                if path.stat().st_size > 8192:
                    continue

                secret = json.loads(
                    path.read_text()
                )

                if not (
                    isinstance(secret, list)
                    and len(secret) == 64
                    and all(
                        isinstance(n, int)
                        and 0 <= n <= 255
                        for n in secret
                    )
                ):
                    continue

                checked += 1

                result = subprocess.run(
                    [
                        "solana-keygen",
                        "pubkey",
                        str(path),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )

                if result.returncode != 0:
                    continue

                public_key = result.stdout.strip()

                if public_key == EXPECTED:
                    matches.append(str(path))
                    print("\n✅ MATCH FOUND")
                    print("Keypair file:", path)
                    print("Public key:", public_key)

            except (
                OSError,
                ValueError,
                TypeError,
                subprocess.TimeoutExpired,
            ):
                continue

print("\nKeypairs inspected:", checked)
print("Matches:", len(matches))

if matches:
    print("✅ Tenemos una wallet candidata")
else:
    print(
        "⚠️ Ninguna wallet coincidente "
        "en los directorios revisados"
    )

print("Private keys printed: 0")
print("Transactions sent: 0")
