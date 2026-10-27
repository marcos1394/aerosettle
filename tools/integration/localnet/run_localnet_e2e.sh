#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$repo_root"
rpc_port="${CON34_RPC_PORT:-18899}"
faucet_port="${CON34_FAUCET_PORT:-18909}"
if [[ "$faucet_port" == "$rpc_port" || "$faucet_port" == "$((rpc_port + 1))" ]]; then
  echo "Faucet must not use RPC or RPC WebSocket port" >&2
  exit 2
fi
root="$(mktemp -d "${TMPDIR:-/tmp}/aerosettle-con34.XXXXXXXX")"
chmod 700 "$root"
free_kb="$(df -Pk "$root" | awk 'NR == 2 {print $4}')"
min_free_kb=3145728
if [[ "${CON34_SCENARIOS:-}" == "full" ]]; then min_free_kb=1048576; fi
if (( free_kb < min_free_kb )); then
  echo "CON-34 needs at least ${min_free_kb} KiB free for a persistent ledger; found ${free_kb} KiB" >&2
  exit 1
fi
rpc="http://127.0.0.1:${rpc_port}"
validator_pid=""
stop_validator() {
  if [[ -n "$validator_pid" ]]; then
    kill "$validator_pid" 2>/dev/null || true
    wait "$validator_pid" 2>/dev/null || true
    validator_pid=""
  fi
}
trap stop_validator EXIT
start_validator() {
  local validator_args=(
    --ledger "$root/ledger"
    --rpc-port "$rpc_port"
    --faucet-port "$faucet_port"
    --limit-ledger-size 1000000
  )
  if [[ ! -d "$root/ledger" ]]; then
    validator_args+=(
      --ticks-per-slot 48
      --bpf-program CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy target/deploy/aerosettle.so
    )
  fi
  solana-test-validator "${validator_args[@]}" --quiet >"$root/validator.log" 2>&1 &
  validator_pid=$!
  for ((attempt=0; attempt<60; attempt++)); do
    if solana -u "$rpc" genesis-hash >/dev/null 2>&1; then return; fi
    if ! kill -0 "$validator_pid" 2>/dev/null; then
      cat "$root/validator.log" >&2
      exit 1
    fi
    sleep 1
  done
  echo "Validator did not become ready: $root/validator.log" >&2
  exit 1
}

echo "Isolated CON-34 run: $root"
start_validator
genesis_before="$(solana -u "$rpc" genesis-hash)"
CON34_RPC_URL="$rpc" node tools/integration/localnet/run_settlement.cjs execute "$root/report.json"
CON34_RPC_URL="$rpc" node tools/integration/localnet/run_settlement.cjs verify "$root/report.json"
CON34_RPC_URL="$rpc" python3 tools/integration/localnet/diagnose_rpc.py "$root/report.json" "$root/rpc-before-restart.json" "$root/ledger"
python3 -m tools.integration.localnet.verify_report "$root/report.json" "$root/economic-ledger.sqlite"
cp "$root/verified.json" "$root/verified-before-restart.json"
stop_validator
start_validator
genesis_after="$(solana -u "$rpc" genesis-hash)"
if [[ "$genesis_before" != "$genesis_after" ]]; then
  echo "Genesis changed across validator restart" >&2
  exit 1
fi
CON34_RPC_URL="$rpc" node tools/integration/localnet/run_settlement.cjs verify "$root/report.json"
CON34_RPC_URL="$rpc" python3 tools/integration/localnet/diagnose_rpc.py "$root/report.json" "$root/rpc-after-restart.json" "$root/ledger" "$root/rpc-before-restart.json"
python3 -m tools.integration.localnet.verify_report "$root/report.json" "$root/economic-ledger.sqlite"
cp "$root/verified.json" "$root/verified-after-restart.json"
if ! cmp -s "$root/verified-before-restart.json" "$root/verified-after-restart.json"; then
  echo "Evidence hashes or SQLite effect IDs changed across validator restart" >&2
  exit 1
fi
if [[ -n "${CON34_PUBLIC_REPORT_DIR:-}" ]]; then
  mkdir -p "$CON34_PUBLIC_REPORT_DIR"
  cp "$root/report.json" "$root/verified-before-restart.json" "$root/verified-after-restart.json" "$root/rpc-before-restart.json" "$root/rpc-after-restart.json" "$CON34_PUBLIC_REPORT_DIR/"
fi
echo "REAL_LOCALNET_E2E PASS: $root"
