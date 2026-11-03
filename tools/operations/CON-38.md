# CON-38 — Devnet observability and incident operations

## AS-IS and boundary

Baseline: `origin/master` merge `0ef8b07a107457ca9b857990e48d9b88ed074861` (CON-37). CON-35 provides the approved Devnet program, upgrade authority, SBF, mint and creation evidence. CON-36 provides the initialized ProtocolConfig and seven real WorkOrder settlements. CON-37 already has finalized JSON-RPC verification, bounded retries with jitter, a durable cursor, immutable economic effect keys, incident records and seven replayed `LIVE_RPC` receipts. It emits per-signature JSON but previously lacked a process-level operational state, provider breaker, alert rules, readiness and runbooks. Those existing reconciliation and checkpoint rules are reused unchanged. No Anchor, payment, trading or on-chain write path is added.

The operational SQLite database is independent of the Economic Ledger. Metrics read the Ledger using SQLite `mode=ro`; the collector does not open a write connection to it. The only network calls are JSON-RPC reads against the official Devnet URL. This is a Devnet trial, not a Mainnet availability statement.

## Architecture and persistence

```text
SolanaRpcClient (existing transport, optional observer and guard)
  → ProviderController (bounded requests, concurrency, retry budget, breaker)
  → RpcObserver / CON-37 ingestion journal (samples)
  → OperationalStore (separate SQLite, migration 001)
  → Health + Readiness / Alert evaluator / JSON reports
```

`observability_samples` stores timestamped values and explicit `OBSERVED`, `ESTIMATED` or `INSUFFICIENT_DATA` quality. `alert_rules` stores configurable thresholds; `alert_instances` deduplicates by rule and scope, preserving first/last seen, severity, state, count and evidence hash; `incident_events` is an append-only transition history; `provider_health` persists `OPEN`, `HALF_OPEN`, `CLOSED`, failure count, cooldown, half-open probe lease and the request window. `operational_schema_migrations` tracks version 001. Startup checks SQLite integrity, foreign keys and schema. WAL and `BEGIN IMMEDIATE` serialize concurrent writers. Sample retention defaults to seven days with a bounded 1,000-row deletion per CLI run; alerts and incident history are retained.

The optional RPC observer captures logical call duration (including retries), requests, HTTP 429/5xx attempts, timeouts, retries and final failures. The transport still caps attempts at six; the configured retry budget is two retries. The provider controller enforces at most 120 logical calls/minute, two concurrent calls per process, three consecutive final failures before opening, and a 30-second cooldown. These limits are configurable in `tools/operations/devnet.json`. A half-open probe is leased in SQLite; a crash does not leave the breaker permanently stuck. A successful probe closes it; a failed probe reopens it. The policy prevents a new RPC call while open. Telemetry observer failures cannot change an RPC result, while an unavailable policy store fails the guarded call closed.

The provider is bound to the approved `solana:devnet` genesis and official public URL. Changing the RPC provider requires explicit configuration and validation work; no automatic failover is implemented. The CLI does not include transaction submission or keypair handling.

## Metrics and trust

The RPC window reports request count, p50/p95/p99 call latency, final failure fraction, 429, 5xx, timeout, retry, circuit and rate rejections. Percentiles are computed only from captured calls. Before five calls, rate and latency alert inputs remain `INSUFFICIENT_DATA`. The endpoint availability fraction is only for calls observed by this process and window, not a Devnet uptime claim.

The Economic Ledger collector reads observed signature counts, finalized, failed, pending-finality, Anchor error codes, reconciled movements, distinct effects, source incidents, gaps, economic differences, known backlog and checkpoint status. A failed, finalized transaction is terminal and is excluded from the retry backlog. Only scopes listed in `active_scope_ids` are eligible for a checkpoint-stall alert; the default empty list intentionally avoids treating historical CON-36 backfills as a live stream. An absent active scope yields `INSUFFICIENT_DATA`. The derived replay and duplicate-attempt counts are `ESTIMATED`, because CON-37's attempt counter includes the initial discovery stage. The duplicate-effect count checks logical effect keys independently of the database's uniqueness constraint. Reconciliation-error and duplicate-effect anomalies have critical rules. Historical recovery duration is `INSUFFICIENT_DATA` because CON-37 does not retain a first-failure timestamp. The block-to-ingest p95 is also `ESTIMATED`: Solana JSON-RPC exposes block time, not a separate finalization timestamp. Old historical replays must not be presented as current indexing latency. Undiscovered signatures are not included in known backlog. Operational open incidents are counted separately from CON-37's append-only source incidents, which have no resolution state.

Security probes compare genesis, Program/ProgramData owner and canonical address, SBF bytes, upgrade authority, approved six-decimal SPL test mint, ProtocolConfig immutable fields and pause state. The public fee-payer test wallet balance is read with `getBalance`; 50 million lamports is the default warning threshold. A validation mismatch is `OBSERVED`; an RPC outage is `INSUFFICIENT_DATA`. Readiness fails closed in either case. No balances are labeled production treasury.

The CON-37 ingestion log now includes timestamp, severity, component, operation, deterministic correlation ID, per-process trace ID, network, genesis, program, WorkOrder, signature, slot, checkpoint ID, duration, status and error category. The correlation ID is SHA-256 over the public scope and signature. Source incidents in the operational report carry the same ID. Operational JSON logs accept only allowlisted fields and characters; RPC request bodies, URLs, keypairs, seed phrases and signed transactions are never logged.

## Health, readiness and exit codes

`health` is process liveness: `HEALTHY` and exit 0 without contacting RPC or opening SQLite. `readiness` separately checks operational SQLite, provider state, Devnet identity, program/mint/ProtocolConfig, test wallet, read-only Economic Ledger schema/integrity and its checkpoints. `HEALTHY` means these checks match and the circuit is closed (exit 0). `DEGRADED` means the read-only component can operate but the test wallet is below its warning threshold (exit 1). `NOT_READY` means an identity, RPC, ledger, checkpoint or circuit check prevents trusted operation (exit 2). `UNHEALTHY` means the local operational state is unusable (exit 2). Missing data never becomes a successful readiness response.

No always-on service is deployed by this PR. The CLI is invoked by an operator or CI; scheduling it is a separate operational choice. `inspect` probes the chain and can write only operational samples. `metrics`, `alerts`, `incidents` and `report` read local ledgers and may update only the isolated operational database. `alerts` evaluates rules but does not notify Slack, email or payment services.

```bash
python3 -m tools.operations.cli health
python3 -m tools.operations.cli inspect --db target/con38/operations.sqlite
python3 -m tools.operations.cli readiness --db target/con38/operations.sqlite \
  --ledger-db target/con37/devnet-ledger.sqlite
python3 -m tools.operations.cli metrics --window-seconds 300
python3 -m tools.operations.cli alerts
python3 -m tools.operations.cli incidents
python3 -m tools.operations.cli report --output target/con38/report.json
```

The JSON config may adjust limits, thresholds, sample retention and explicit active scope IDs. It cannot change the approved network/program/mint/official URL without a code review; invalid configuration exits 2. Do not place credentials or private RPC query strings in this file.

## Alert rules and incident workflow

Default rules cover error fraction over 5%, three 429 attempts in five minutes, RPC p95 above 2 seconds, known backlog age above 5 minutes, stopped configured checkpoints, RPC gaps, economic differences, low test-wallet balance, unexpected genesis, program, ProgramData, upgrade authority, mint or ProtocolConfig. Levels are `WARNING` or `CRITICAL`. Only the latest `OBSERVED` sample in a rule window can trigger or resolve an alert; a newer unavailable sample does not reuse stale success or failure. Re-evaluating the same sample is idempotent. Resolution appends a distinct audit event. Detection and external notification are deliberately separate.

### INC-01 — Persistent RPC 429 (WARNING)

Detection: 429 count or error fraction exceeds its rule. Containment: stop or reduce polling, preserve the cursor and let bounded backoff/circuit breaker open. Diagnosis: compare request window, retries, provider state and RPC status. Recovery: after cooldown, allow one half-open read probe and verify genesis. Closure: successful probe, bounded 429 count, no ingestion gap. A provider change requires an approved endpoint and genesis check; there is no automatic failover.

### INC-02 — Wrong genesis or program (CRITICAL)

Detection: identity probe mismatch or unavailable evidence. Containment: readiness `NOT_READY`; do not resume ingestion. Diagnosis: compare approved CON-35 config with RPC genesis, program owner and ProgramData address. Recovery: restore the approved endpoint or investigate Devnet reset; do not relabel another network. Closure: all identity probes match and the operator reviews affected history.

### INC-03 — Historical RPC gap (WARNING)

Detection: CON-37 incident or unrecoverable finalized signature. Containment: keep checkpoint behind the missing signature and retain the evidence hash. Diagnosis: inspect `getSignatureStatuses`, `getTransaction`, `getBlock` and provider retention. Recovery: controlled manual review of a historical provider with the same genesis; never invent a transaction. Closure: finalized evidence recovered and replay is idempotent, or gap remains explicitly unresolved.

### INC-04 — Upgrade authority or ProgramData changed (CRITICAL)

Detection: authority or SBF mismatch against CON-35. Containment: readiness `NOT_READY`, preserve approved manifest and on-chain account data. Diagnosis: inspect ProgramData, deployment slot and authority against the approved public evidence. Recovery: human review of a new deployment process; this CLI never upgrades. Closure: an approved manifest and verified binary/authority agree again.

### INC-05 — Economic difference (CRITICAL)

Detection: CON-37 incident for amount, owner, destination or evidence hash conflict. Containment: stop promotion at the disputed signature, preserve checkpoint and both hashes. Diagnosis: rerun read-only settlement verification and compare integer SPL balances, instructions, WorkOrder and ledger effect key. Recovery: resolve source evidence or a separately reviewed accounting correction. Closure: no unexplained difference and repeat replay does not create a new movement. No automatic compensating transfer is allowed.

### INC-06 — SQLite locked or corrupt (CRITICAL)

Detection: transaction timeout, integrity check or migration failure. Containment: stop operational writes; Economic Ledger remains separate. Diagnosis: inspect filesystem capacity, WAL files, lock owner, `PRAGMA quick_check` and migration version. Recovery: restore a validated backup into a new path, rerun migrations and compare incident history. Closure: integrity/foreign-key checks pass, alerts and breaker state are coherent. Do not delete the economic database.

### INC-07 — Devnet reset or instability (CRITICAL)

Detection: genesis mismatch, missing program/mint or repeated finality gaps. Containment: suspend readiness and preserve local evidence/checkpoints. Diagnosis: compare CON-35/36/37 signed receipts and current genesis/accounts. Recovery: rebuild only through separately approved Devnet procedures; historical unavailable evidence remains explicitly insufficient. Closure: new approved identity and reproducible read-only verification. Do not copy Devnet evidence into Mainnet claims.

### INC-08 — Repeated WorkOrder error (WARNING)

Detection: rising finalized failed transactions or repeated `ANCHOR_<number>` classifications. Containment: stop automated polling of the affected scope; preserve signatures and slots. Diagnosis: inspect finalized transaction logs, Anchor error code, WorkOrder state and authorities. Recovery: correct the caller or workflow with separate review; no transaction is sent by this module. Closure: failure rate falls and subsequent verified settlements reconcile once.

## Trial SLOs and evidence

Proposed 1-hour windows require at least 20 real samples: readiness success ≥99%, observed RPC p95 <2 seconds, recoverable near-real-time indexing p95 <5 minutes, zero duplicated economic movements, and critical alert creation within 60 seconds of an observed breach. The report uses `TARGET` values, `OBSERVED` only when measured from enough samples, and `INSUFFICIENT_DATA` otherwise. Block-to-ingest age from CON-37 historical backfills is only an estimate and does not satisfy the indexing SLO. CI run frequency alone does not establish a production SLO.

The local read-only probe on 2026-11-02 verified genesis, ProgramData/SBF, authority, test mint, ProtocolConfig and test-wallet balance from official Devnet JSON-RPC. Readiness against the locally replayed seven-settlement CON-37 database returned `HEALTHY`; a fresh alert evaluation opened no incidents. This is one point-in-time Devnet observation; its RPC p50/p95/p99 values are captured in the ignored local operational DB and should not be extrapolated to uptime. CI repeats a fresh read-only identity probe, tests negative readiness when the Economic Ledger is absent, rebuilds the seven-settlement historical ledger from public finalized Devnet receipts, checks positive readiness and no spurious alerts, and publishes its JSON outputs. The inherited CON-34–37 workflows continue to check Rust, SDK/web and historical settlement replay.
