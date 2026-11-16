# CON-59 — Devnet RPC gateway and read-only index

## Status (2026-11-16)

| Gate | State | Evidence |
| --- | --- | --- |
| GATEWAY_IMPLEMENTED | Yes | `gateway.py`; GET-only, fixed routes, method/parameter allowlist, response limits, CORS |
| INDEXER_IMPLEMENTED | Yes | Reuses `tools/discovery/agent_discovery.py` and approved CON-35 IDL; seven agents and seven WorkOrders in live probe |
| LIVE_RPC_VERIFIED | Yes, at the recorded slots | `evidence/con59/live-read.json`; official public Devnet RPC, finalized reads |
| STAGING_API_DEPLOYED | No | No host for this Python process has been approved; no Cloudflare Function or paid service enabled |
| BROWSER_API_VERIFIED | No | Staging correctly remains `API_NOT_CONFIGURED` |
| READY_FOR_CON55 | API contract ready; publication gate open | Catalog must wait for an independently deployed and verified API |

This is a **read-only advisory index**. It cannot authorize settlement, spending, WorkOrder transitions, or any financial action. The seven observed accounts are Devnet test data, never a Mainnet or production balance. No Solana transaction was sent.

## Architecture and identity

The local HTTP server binds only to loopback. `Index` creates a bounded scan from one RPC provider at a time. It checks the approved genesis, the executable Program account, its ProgramData address, upgrade authority and deployed SBF binary hash, the SPL test mint owner/decimals/authority, and the ProtocolConfig program, admin, network ID and deployment ID. The full identity is checked again after account indexing with a minimum finalized context slot. The IDL bytes are pinned to the CON-35 SHA-256 and their address must match the independent Program ID. The existing discovery decoder validates Anchor discriminators, complete Borsh layouts, account owner, PDAs, protocol link, agent identity and WorkOrder identity. CON-59 additionally rejects missing agent authorities and WorkOrders with an unapproved mint or token program.

Only `finalized` account reads enter the index. Slots from all account queries are retained as `slot_min`/`slot_max`; **they are not an atomic snapshot**. `observed_slot` is a later finalized `getSlot`. Each response carries network, genesis, program, mint, IDL hash, commitment, provider, index/verification timestamps, and `advisory_only=true`, `is_financial_authority=false`.

The HTTP routes are `/health`, `/ready`, `/v1/network`, `/v1/program`, `/v1/agents`, `/v1/agents/:pubkey`, `/v1/workorders`, and `/v1/workorders/:pubkey`. No transaction history route is published: account references alone do not prove complete finalized history, and the official public RPC can prune history. There is no generic JSON-RPC endpoint. All non-GET methods fail. Filters are limited to `status`; page size is 1–50 and defaults to 20. Signed cursors from `tools/marketplace_api/cursor_pagination.py` bind to network, genesis, program, IDL, provider, slot, resource and filter. A new slot invalidates the cursor. Account lists are sorted by stable account pubkey. Missing accounts return 404; unavailable RPC returns 503 with `UNVERIFIABLE` provenance. `GET /health` is process liveness; `/ready` independently rechecks index availability and returns 503 if unverified.

The in-memory cache lasts at most 10 seconds. Every cache hit requires the same finalized slot and genesis from the same provider; a changed slot forces a scan. The cache has a content digest and a pinned context. Tampering fails closed. A cached response is `CACHED_VERIFIED`, never `LIVE_RPC`; a fresh scan is `INDEXED_FROM_RPC`. Stale data is **not served** on provider failure. An old record may still be historically interesting but cannot be described as current from this gateway.

## Providers and operating limits

Primary: `https://api.devnet.solana.com`. Secondary: optional, **not configured**; current mode is `SINGLE_PROVIDER_MODE`, so no high-availability claim. A secondary must be explicitly provisioned by an operator with an exact approved HTTPS hostname and public DNS addresses. Browser clients cannot select endpoints or methods. Redirects, private/local DNS answers, URL credentials, query strings and non-HTTPS endpoints are rejected. The transport accepts only `getGenesisHash`, `getAccountInfo`, `getProgramAccounts`, and `getSlot`, with fixed read-only parameters. Responses are capped at 2 MB and scans at 500 accounts per type. RPC timeout is at most 10 seconds. Each provider has a 120-call/minute local budget, two scan attempts with short jitter, a 3-failure circuit breaker and a 30-second half-open probe. The HTTP gateway permits 20 reads/minute per client and at most eight concurrent in-flight requests; it never trusts `X-Forwarded-For` in its loopback server. These in-memory limits are **per process**, so an external deployment needs a separately approved edge rate limit and trusted proxy policy.

An identity mismatch or contradictory slot fails the entire operation; it does not silently switch to another provider. Transient failures may fail over to the optional provider, which must pass the same complete identity checks. The cursor cannot cross providers. No account data from different providers is merged.

The service reuses CON-38 structured logs. It emits method-independent HTTP result, network, program, provider, resource, slot, cache state, request trace and duration without RPC bodies, URLs, tokens or wallet keys. `Gateway.stats()` supplies 60-second request rate, cache ratio, request rejection counts, scan/error/retry/failover counters, circuit state and scan latency p50/p95/p99. `Index.alert_codes()` flags network mismatch, unavailable scans, open circuits and high p95; a deployment operator must wire those alerts into the approved CON-38 channel. There is no public metrics route. Indexing lag is observable as `observed_slot - slot_max` in the probe evidence.

## Hosting and cost boundary

Cloudflare's [Workers Free limits](https://developers.cloudflare.com/workers/platform/limits/) currently list 100,000 requests/day, 10 ms CPU per invocation, 128 MB memory, 50 external subrequests and six simultaneous outgoing connections. [Pages Functions count against the Workers quota](https://developers.cloudflare.com/pages/functions/pricing/). A complete Anchor account scan and Python Borsh decode cannot be assumed to fit 10 ms CPU, and the current gateway is a Python process rather than a Pages Function. CON-59 therefore does not publish it to the existing Pages Free project or add KV, D1, R2, a paid plan, a temporary-credit service, or credentials. A future approved host may run the loopback process behind an authenticated reverse proxy and external rate limit, or a separately reviewed lightweight BFF can consume an offline verified index. Neither is claimed deployed here.

The CON-53/58 web manifest remains pinned to `api_endpoint=API_NOT_CONFIGURED`. The site continues direct, read-only RPC identity diagnostics and shows web/RPC/API states separately. No catalog or economic panel is enabled based on this unhosted API. Before any staging integration, approve a concrete HTTPS API destination, update the trusted manifest/release workflow, deploy, verify browser CORS and independent identity, then record the deployment evidence. No automatic deployment runs from a PR.

## Reproduce and evidence

```bash
python3 -m pip install -r requirements.txt
python3 -m unittest tools.integration.devnet.test_gateway
python3 -m tools.integration.devnet.probe --offline-load
python3 -m tools.integration.devnet.probe --live  # explicit, bounded, read-only Devnet RPC
```

The offline load in `evidence/con59/offline-load.json` used 40 requests, eight threads and a deterministic fixture: zero errors, one scan and 39 cache hits. Timing and memory measurements are machine-specific and do not predict cloud performance. The live proof in `evidence/con59/live-read.json` records seven agents, seven WorkOrders, finalized context slots, approved binary/IDL hashes and a SHA-256 of the response; it contains no wallet secret or account payload. A later run can differ as Devnet advances. Both evidence files are generated by `probe.py` with no Solana write method.

The CI workflow `.github/workflows/con59-devnet-rpc-indexer.yml` performs offline unit/adversarial tests, load probe, CON-38/46 and Economic Ledger regressions, SDK/web tests and Devnet build validation. CI does not query live RPC or deploy. Security tests cover genesis/program/mint/authority/IDL changes, inconsistent slots, cache poisoning, primary/secondary outage, circuit/rate limits, SSRF, RPC method injection, oversize responses, invalid cursors, CORS and non-GET rejection.

## Known limits

- Official public RPC may rate-limit `getProgramAccounts`, omit old transactions or return a response above the 2 MB cap. The gateway reports unavailability rather than incomplete results as complete history.
- Multiple finalized calls are not an atomic cross-account view. No transaction history API or financial total is inferred from the index.
- Secondary RPC, external hosting, browser integration and durable indexing remain unconfigured. Persistent storage requires a separate plan/cost and security review.
- Read-only public account fields are exposed. Tenant-private data is outside this API; it must never be added without authentication and authorization design.
