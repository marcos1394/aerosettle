# CON-41 — A2A task lifecycle and offline WorkOrder correlation

## Audit and trust boundary

Baseline: `origin/master` at CON-40 merge `057210bde87f3e8a293884e84302bcfb290ccfb0`. CON-39 publishes signed Agent Cards only through its custom `read-only-card/v1` binding. That URL remains discovery-only and never advertises tasks. CON-40 serves seven MCP read-only tools and validates Ed25519 access tokens; its tokens are audience-bound and do **not** authorize this A2A service. CON-18/21 discovery can read current AgentAccounts and WorkOrders; CON-23/34 settlement reconciliation requires finalized JSON-RPC. CON-35–37 supply verified deployment and ingestion evidence. None of these existing sources gives a task permission to claim, fund, verify, settle or refund an on-chain WorkOrder. The Anchor program retains the `create → fund → claim → submit → verify → settle` authority and balances. This change does not touch Anchor, the Economic Ledger, SPL accounts or transaction SDK.

The initial implementation deliberately uses `tools/a2a/fixtures/task-workorders.json`, labeled `OFFLINE_FIXTURE`. `OfflineWorkOrders` rejects `LIVE_RPC` labels and fixture `Settled` states. A live private task binding is **not** enabled: it would require independent current owner/tenant/organization evidence, verified AgentAccount authority and finalized RPC reconciliation. A stored signature alone is insufficient. This separation prevents an offline task from appearing as a Devnet WorkOrder E2E result.

## Protocol and interfaces

CON-39 pins [A2A v1.0.1](https://github.com/a2aproject/A2A/releases/tag/v1.0.1), wire protocol `1.0`, and `a2a-sdk==1.3.0`. The official SDK's `create_jsonrpc_routes()` serves the standard `JSONRPC` binding at `POST /a2a/task-rpc`; its generated protobuf models drive `SendMessage`, `GetTask`, `ListTasks` and `CancelTask`. `GET /a2a/task-card.json` is a **separate, local offline task card** with that implemented URL, Bearer security scheme, streaming=false, pushNotifications=false and a `conatus-task/v1` extension saying `evidenceSource=OFFLINE_FIXTURE` and `isFinancialAuthority=false`. It does not replace or modify the signed CON-39 discovery card. The official Python SDK's `ClientFactory` negotiates this binding; a Node.js client independently sends A2A 1.0 JSON-RPC. The existing discovery binding remains `UNSUPPORTED_TRANSPORT` to standard task clients.

`SendStreamingMessage`, subscription, extended card and push-notification methods return standard A2A `UnsupportedOperationError`. This service does not accept or deliver callbacks; therefore callback SSRF, forged callback and duplicate delivery cannot alter a task. A request to configure a callback is tested and rejected. A future push implementation requires an independently reviewed URL allowlist, DNS pinning, TLS, signed delivery, retry outbox and receiver idempotency before `pushNotifications` can be advertised. No endpoint is given arbitrary client URLs or executes message content.

## Persistent model and states

`TaskLedger` uses its own SQLite database with `a2a_tasks`, `a2a_messages`, `a2a_artifacts`, `a2a_events`, `a2a_idempotency` and cursor metadata. The immutable binding contains task/context IDs, requester, executor, owner, signing authority, tenant, organization, AgentAccount/agent ID, WorkOrder PDA, network, genesis, program and `OFFLINE_FIXTURE` provenance. The WorkOrder PDA is unique. `BEGIN IMMEDIATE`, SQLite uniqueness and per-request validation prevent concurrent duplicate links. The fixture is reread on every task lookup, retry, update, cancellation and listing; changed owner, signer, agent identity, network, genesis or program hides old history. A repeated idempotency key returns the existing task only after that current identity check. Reusing a key with different input fails. The funded escrow fixture uses the actual Anchor WorkOrder status `Open` (funding transitions `Draft` to `Open`), with a separate fixture-only `escrow_funded=true` assertion; it does not invent a `Funded` WorkOrder state.

Task events are append-only and hash-chained. Every returned task verifies the chain, message hashes and artifact SHA-256/size. Each artifact records ID, media type, hash, size, producer, provenance and creation time. Only bounded text messages and bounded `text/plain`, `application/json` or `image/png` artifacts are accepted. The bounds are eight messages (2 KiB each) and two artifacts (8 KiB each) per task; list pages contain at most two tasks and at most two history messages each. URL parts and unknown media types are rejected. Agent text, including instruction-like text, remains untrusted data. Replies include a current **fixture** WorkOrder status and its status at link time, plus `settlement_verified=false` and `is_financial_authority=false`. A completed A2A task never promotes a WorkOrder to `Settled`.

The official A2A states are used directly:

| Coordination event | A2A state | Effect on WorkOrder |
| --- | --- | --- |
| Request accepted | `SUBMITTED` | None |
| Executor starts or resumes | `WORKING` | None |
| Partial artifact or more input needed | `INPUT_REQUIRED` | None |
| Human authorization pending | `AUTH_REQUIRED` | None; no economic approval granted |
| Work delivered | `COMPLETED` | None; `Settled` remains unverified |
| Execution error or deadline | `FAILED` | None |
| Declined request | `REJECTED` | None |
| Cancel before start | `CANCELED` | None |
| Cancel during work | `WORKING` with `cancel_requested=true`, then executor confirms `CANCELED` | No refund or escrow mutation |

The task deadline is at most 24 hours after creation. A read after expiry records a `TIMEOUT` event and returns `FAILED`; expired updates fail. Terminal transitions cannot be reopened. Pagination uses HMAC cursors bound to subject, client, tenant, organization, scopes, page size and the task snapshot; the secret persists in SQLite across restart. The result set is capped. The event history is available to the same currently authorized identities for audit.

## Authorization matrix

The HTTP launcher binds **loopback only**. Every task operation requires an Ed25519 JWT from a separately configured issuer with exact `iss`, A2A `aud`/`resource`, subject, client, tenant, organization, scopes, `iat`, `exp` (at most 15 minutes) and non-revoked `jti`. Host/Origin and duplicate-header protections are reused from CON-40. A valid MCP token fails the A2A audience check. The issuer, not the Agent Card, grants scopes.

| Operation | Required scope and identity |
| --- | --- |
| New task / requester message | `tasks:write`; subject equals current WorkOrder owner/requester and tenant/organization match |
| Task get / list | `tasks:read`; subject equals current requester or executor; matching tenant/organization |
| Executor state / artifact | `tasks:execute`; subject equals current AgentAccount signing authority/executor |
| Cancel | `tasks:cancel`; subject equals current requester/owner |
| Financial or unknown method | No route; rejected |

Authorization is repeated for each operation and resource, including idempotent retries and historical access. Cross-tenant, cross-organization and wrong-owner reads return a generic not-found error. Local rate limits apply per client, operation and resource. `BodyLimit` bounds request size. Neither the Agent Card nor the A2A token gives transaction-signing, claim, beneficiary change, escrow, verify, settlement, policy, wallet or upgrade authority. No code path imports a transaction submitter or writes an economic table.

## Observability and demo

Task transitions use the CON-38 allowlisted structured log format with task/WorkOrder IDs, requester, executor, state change, authorization result, evidence source and correlation ID. Optional `--operations-db` persists aggregate CON-38 samples; telemetry failure cannot change task authorization. `metrics_snapshot()` reports local created, active, completed, failed and canceled counts without task contents or balances. Logs exclude tokens, artifact bodies and private message text.

Run the reproducible offline demo (Python 3.12+, Node.js 24):

```sh
python -m pip install -r requirements.txt
python -m unittest discover -s tools/a2a
python -m tools.a2a.demo_task_lifecycle > con41-demo.json
```

The official Python SDK requester fetches and negotiates the separate task card, creates and replays a task, and gets its final state. An independent Node.js process acts as executor through A2A JSON-RPC, publishes progress and a partial JSON artifact, exits, and a new Node process resumes. The server closes/reopens the same SQLite database between phases. A second offline WorkOrder is canceled before execution through the official SDK. The demo checks tenant/scope denial, artifact SHA-256 and completion without settlement. Its output explicitly sets `A2A_TASK_E2E_VERIFIED=true`, `DEVNET_WORKORDER_E2E_VERIFIED=false`, `OFFLINE_FIXTURE=true`, `settlement_verified=false`, `funds_transferred=false`. It uses ephemeral issuer keys and no wallets or Solana transaction submission. CI uploads sanitized JSON only.

`.github/workflows/con41-a2a-workorders.yml` runs protocol and adversarial tests, the heterogenous demo, CON-34–40 Python regressions, JavaScript SDK/web suites, web build and Rust workspace tests. The new tests cover issuer/audience/scope, owner/signer, tenant/organization, changed network/program/agent, idempotency and concurrency, restart, cursor tampering, deadline, cancel with funded fixture, callbacks rejected, prompt injection as data, URL parts, false LIVE_RPC/Settled, hash-chain and artifact tampering, and direct financial method rejection.

## Deployment limits

The task card is an **offline local fixture card**, not a published Devnet Agent Card. No external HTTPS endpoint, OAuth authorization server, managed owner/tenant/organization WorkOrder binding, callback delivery, streaming, or finalized RPC settlement observation is claimed. `Settled` can only be reported in a later live adapter after a current finalized RPC verification and independent access binding. A2A tasks remain a coordination layer and cannot release escrow or complete the Anchor lifecycle.
