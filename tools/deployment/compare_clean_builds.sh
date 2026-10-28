#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
scratch="$(mktemp -d "${TMPDIR:-/tmp}/con35-builds.XXXXXXXX")"
trap 'rm -rf "$scratch"' EXIT

cd "$repo_root"
lock_before="$(shasum -a 256 Cargo.lock | cut -d ' ' -f 1)"
for build in one two; do
  mkdir -p "$scratch/$build"
  CARGO_TARGET_DIR="$scratch/target-$build" \
    cargo build-sbf --manifest-path programs/aerosettle/Cargo.toml \
    --sbf-out-dir "$scratch/$build"
  test -s "$scratch/$build/aerosettle.so"
  python3 tools/deployment/build_idl.py \
    --idl "$scratch/$build/aerosettle-idl.json" \
    --error-catalog "$scratch/$build/aerosettle-error-catalog.json"
  rm -rf "$scratch/target-$build"
done

cmp "$scratch/one/aerosettle.so" "$scratch/two/aerosettle.so"
cmp "$scratch/one/aerosettle-idl.json" "$scratch/two/aerosettle-idl.json"
cmp "$scratch/one/aerosettle-error-catalog.json" "$scratch/two/aerosettle-error-catalog.json"
lock_after="$(shasum -a 256 Cargo.lock | cut -d ' ' -f 1)"
[[ "$lock_before" == "$lock_after" ]] || { echo 'Cargo.lock changed during build' >&2; exit 1; }
shasum -a 256 "$scratch/one/aerosettle.so" "$scratch/one/aerosettle-idl.json"
if [[ -n "${CON35_OUTPUT_DIR:-}" ]]; then
  mkdir -p "$CON35_OUTPUT_DIR"
  cp "$scratch/one/aerosettle.so" "$CON35_OUTPUT_DIR/aerosettle.so"
  cp "$scratch/one/aerosettle-idl.json" "$CON35_OUTPUT_DIR/aerosettle-idl.json"
  cp "$scratch/one/aerosettle-error-catalog.json" "$CON35_OUTPUT_DIR/aerosettle-error-catalog.json"
  python3 - "$CON35_OUTPUT_DIR" <<'PY'
import hashlib
import json
import subprocess
import sys
from pathlib import Path

output = Path(sys.argv[1])
def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
record = {
    'status': 'PASS',
    'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
    'cargo_lock_hash': digest(Path('Cargo.lock')),
    'binary_sha256': digest(output / 'aerosettle.so'),
    'idl_sha256': digest(output / 'aerosettle-idl.json'),
}
(output / 'reproducibility.json').write_text(json.dumps(record, sort_keys=True, indent=2) + '\n')
PY
fi
printf 'CON-35 reproducible clean builds: PASS\n'
