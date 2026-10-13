# AeroSettle — EPIC 3.2: Solana Agent & WorkOrder Discovery

Read-only Solana JSON-RPC indexer, implemented with Python 3.11 standard library. No network is used by the unit tests. No private keys or transactions are used. The app reads the **current `target/idl/aerosettle.json`** to decode Borsh account data; no fixed layout offsets are assumed beyond the Anchor discriminator.

## Install

```bash
cd "$HOME/Projects/aerosettle"
unzip -n "$HOME/Downloads/aerosettle-epic-3.2-discovery.zip" -d "$HOME/Downloads"
python3.11 "$HOME/Downloads/aerosettle-epic-3.2-discovery/install.py"
```

Installs **only** `tools/discovery/{agent_discovery.py,test_agent_discovery.py,README.md}`. Safe against overwrite; you can remove those files to uninstall. Does not edit smart-contract code or Cargo dependencies.

## Validate — offline

```bash
python3.11 -m unittest discover -s tools/discovery -p 'test_*.py' -v
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
python3.11 tools/discovery/agent_discovery.py --check-idl
```

`--check-idl` requires your up-to-date generated IDL. If it's missing, build with your established `anchor build --arch v0`. It does **not** require an RPC connection.

## Scan a deployed and initialized program

```bash
python3.11 tools/discovery/agent_discovery.py \
  --rpc-url http://127.0.0.1:8899 \
  --idl target/idl/aerosettle.json \
  --commitment confirmed \
  --output ./aerosettle-discovery-local.json

python3.11 -m json.tool ./aerosettle-discovery-local.json | head -100
```

**Important:** LiteSVM's test fixtures run in memory and **are not written to your RPC validator**. A local RPC has no on-chain accounts until you run a validator, deploy AeroSettle, initialize `ProtocolConfig` and register agents/create WorkOrders there. If `ProtocolConfig` is missing, the CLI returns an informative error rather than inventing data. External RPC providers may limit `getProgramAccounts`; if that happens use a capable RPC endpoint or an indexer provider.

Do not deploy this unreviewed development protocol to mainnet. Never paste a private wallet key in CLI parameters.

## What is validated

- `getAccountInfo` of the deterministic ProtocolConfig PDA; `getProgramAccounts` twice, filtered by **IDL-provided Anchor discriminators** (agents and work orders).
- Account ownership by **exact program ID**, non-executable status, correct discriminator, IDL-driven complete Borsh decode, declared protocol config, and reconstructed Agent/WorkOrder **PDA seeds + bump**.
- Chain time from **Clock sysvar**, not laptop clock, used for shortlist expiration.
- Advisory shortlist: protocol unpaused, order `Open` and before deadline, agent active and matching required capability bitmask; deterministic ordering.
- `schema_version`, `program_id`, `protocol_config`, `rpc_context_slots` for audit/debugging. Multiple RPC reads **do not form an atomic blockchain snapshot**; state can change between requests.

## Integration contract

`agents[]` has `agent_account`, `agent_id` (**64 hex chars**), `protocol_config`, `capabilities` (**u64 JSON integer**), `active`, `status`.

`work_orders[]` has `work_order_account`, `work_order_id`, `creator`, `protocol_config`, `required_capabilities`, `execution_deadline`, `is_open`, `status`.

`eligible_agents_by_order` lists matching **agent pubkeys** per open order. This is a *Python advisory projection following the same eligibility rules as the EPIC 3.1 Rust engine*, **not yet a direct Rust library invocation**. EPIC 3.3 will consume the validated snapshot and call the existing `marketplace::discover_eligible_agents` Rust implementation from the service/API. Ensure any JavaScript consumer uses `BigInt` for u64 fields beyond 2^53-1.

`claim_work_order` stays the authority for matching/authorization; RPC could be stale or untrustworthy. A selection must never bypass on-chain checks.

## Current limitations and planned improvements

- A full scan may exceed free RPC provider limits. Later use pagination/indexer rather than assuming `getProgramAccounts` scales indefinitely.
- Missing or incompatible IDL account fields trigger fail-closed errors. Rebuild IDL after account layout changes.
- `minContextSlot` prevents reading older state for later requests but **does not guarantee atomic snapshot consistency**.
- No geolocation, availability, reputation, bids, distance or price-based ranking. Deterministic order is not a recommendation score.
- EPIC 3.3: connect snapshot to Rust matching + Marketplace API, with integration tests and event/reorg handling.
