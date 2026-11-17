# CON-59 — Devnet RPC gateway and read-only index

## Status (2026-11-17)

| Gate | State | Evidence |
| --- | --- | --- |
| GATEWAY_IMPLEMENTED | Yes | `gateway.py`; GET-only, fixed routes, method/parameter allowlist, response limits, CORS |
| INDEXER_IMPLEMENTED | Yes | Reuses `tools/discovery/agent_discovery.py` and approved CON-35 IDL; seven agents and seven WorkOrders in live probe |
| LIVE_RPC_VERIFIED | Yes, at the recorded slots | `evidence/con59/live-read.json`; official public Devnet RPC, finalized reads |
| PAGES_FREE_BFF_PREPARED | Yes | Pages advanced-mode Function, only `/api/*` invocation routes, release-bound 24-hour snapshot; local Wrangler preview verified |
| STAGING_API_DEPLOYED | No | New release and exact destination require separate human approval |
| BROWSER_API_VERIFIED | No | Public browser QA waits for deployment |
| READY_FOR_CON55 | No | Public API and rollback gates remain open |

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

Cloudflare's [Workers Free limits](https://developers.cloudflare.com/workers/platform/limits/) list 100,000 requests/day, 10 ms CPU per invocation, 128 MB memory, 50 external subrequests and six simultaneous outgoing connections. [Pages Functions count against that quota](https://developers.cloudflare.com/pages/functions/pricing/). The account owner previously confirmed that account `54cb929430c4a02b90d6ea3ce356d0d9` uses Free; the billing API was not available to independently recheck the plan. No card, paid service, KV, D1, R2 or external database is used. The Python scan stays operator-side and is **never executed per HTTP request**. Cloudflare [supports `_worker.js` in Direct Upload](https://developers.cloudflare.com/pages/get-started/direct-upload/) and `_routes.json` restricts Function invocations to `/api/*`; static asset requests do not consume Function requests.

`snapshot.py` runs one complete finalized RPC identity/Anchor scan against the approved official Devnet endpoint, then exports public agent and WorkOrder account records with genesis, program, IDL and binary hashes, deployment ID, test mint, token owner/authority/decimals, slot range, provider, generated/expiry times, counts and non-atomic provenance. The release packager embeds those bytes in `_worker.js` and pins SHA-256 in both Worker code and release manifest. This hash detects alteration and binds release bytes; **it is not a signature by an independent oracle**. The trusted Cloudflare project and verified CON-46/58 release process are the publication trust boundary. The Worker checks identity and digest, then responds from the immutable snapshot. It does not claim `LIVE_RPC`; API responses say `RELEASE_BOUND_RPC_SNAPSHOT`. At 24 hours, every data and readiness route returns HTTP 503 with `INSUFFICIENT_DATA`; only `/api/health` remains live. Refresh requires a new verified snapshot, new release ID and explicit destination approval. There is no automatic refresh or hidden RPC fallback.

The Pages API exposes GET only: `/api/health`, `/api/ready`, `/api/v1/network`, `/api/v1/program`, `/api/v1/agents`, `/api/v1/agents/:pubkey`, `/api/v1/workorders`, `/api/v1/workorders/:pubkey`. List pages are bounded at 50, stable by account pubkey, with snapshot-bound cursors and optional status filters. There is no generic RPC proxy, transaction route, wallet, signing, payment, Mainnet or financial authority. The browser independently verifies approved live RPC genesis/program/mint, then binds the API readiness and both list responses to one pinned snapshot digest, genesis, program, IDL, binary and mint. The UI exposes `WEB_AVAILABLE`, `RPC_VERIFIED`, `API_VERIFIED`, `INDEX_FRESH`, `INDEX_STALE`, `API_UNAVAILABLE` and `DEGRADED_READ_ONLY`; `READY_FOR_TRANSACTIONS=false` always. A snapshot error never falls back to a Localnet fixture.

The Free Pages project uses `*.pages.dev`, which is not a zone controlled by this account for a custom WAF per-client rate rule. The Worker has bounded work and the Free daily quota, but **no durable global per-client rate limiter**. Python's loopback per-client limiter is not represented as an edge control. The API never performs upstream RPC reads, so public requests cannot drain the RPC provider. Per-client abuse protection and alert routing remain operational limitations; no high-availability provider failover is claimed for the published snapshot. Snapshot expiry is an intentional degraded mode.

### Release and deployment gate

Build the Devnet frontend, run `verify-build.mjs devnet`, export a fresh snapshot with `python3 -m tools.integration.devnet.snapshot <temporary-snapshot.json>`, then run `node --experimental-strip-types apps/marketplace-web/scripts/con59-package.mjs <dist-devnet> <temporary-snapshot.json>`. Remove the temporary JSON from the upload directory. `con58-release.mjs prepare` and `verify` bind the source commit, manifest, IDL, bundle, snapshot hash, expiry and every file to one release ID. `con58-pages-deploy.mjs preflight` checks the existing account/project/subdomain with Wrangler credentials without deploying. The `deploy` operation additionally requires `CON58_APPROVED_DESTINATION=<account>/<project>/<exact-release-id>`. Only an explicit human approval for that ID and destination permits publication. Verify real HTTPS/API/browser after upload and retain the previous healthy deployment for rollback. No Cloudflare or Solana write has occurred for the new CON-59 release at this status date.

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
- Secondary RPC and durable indexing remain unconfigured. The Pages Function and browser integration are implemented but public QA waits for approved deployment. A snapshot is only a 24-hour release artifact, not continuously refreshed storage.
- Read-only public account fields are exposed. Tenant-private data is outside this API; it must never be added without authentication and authorization design.
