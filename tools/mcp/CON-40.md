# CON-40 — Secure MCP read-only boundary

## Existing components and trust boundary

CON-39 `CardCatalog` validates a published Agent Card signature against the current AgentAccount and approved CON-35 Devnet program identity. CON-18/21 discovery decodes current AgentAccounts and WorkOrders from the approved IDL; CON-39 pins its hash, program ID, genesis and ProgramData independently. CON-23/34 `SplSettlementReconciler` checks finalized SPL settlement through actual Solana RPC. The Marketplace API already projects WorkOrder states but its HTTP authorization is route-specific. Organization RBAC is tied to signed organization reads. CON-38 supplies allowlisted structured logs. The SDK packages have no MCP authority. This server reuses readers and does not invoke economic mutations, transaction signing or wallet functions.

The deployment has **two explicit modes**. `--fixture` loads only `OFFLINE_FIXTURE` data and cannot claim verified settlement. Without a fixture, `DevnetBackend` rechecks the pinned CON-35 identity, live genesis and ProgramData before and after finalized discovery. The optional `--catalog` connects the existing `CardCatalog` and `DiscoveryIdentitySource`. Current Devnet WorkOrders have no tenant/organization/consent binding in the on-chain account. The optional `--access-index` is a separately administered, access-controlled JSON file with pinned network/genesis/program and per-WorkOrder `owner`, `tenant_id`, `organization_id` and optional `settlement_signature`. Every indexed owner must equal the live on-chain creator; every settlement signature must be verified by the existing reconciler before any `LIVE_RPC` response. Without this index, private WorkOrder and evidence queries fail closed. The included HTTP launcher binds loopback only. No external productive endpoint or OAuth authorization server is deployed by this PR.

## Protocol and transport

The pinned official Python SDK is `mcp==2.3.0`, supporting the current stable protocol revision **2026-07-28**. The [current protocol specification](https://modelcontextprotocol.io/specification/2026-07-28/basic/versioning) uses per-request metadata and `server/discover`; it has no initialization handshake. The demo uses `server/discover` followed by `tools/list` and `tools/call`. SDK legacy clients can use the `2025-11-25` `initialize` handshake. Streamable HTTP is stateless with a 64 KiB request body limit; stdio supports anonymous public reads and rejects private reads. SDK controls HTTP framing, JSON-RPC errors, cancellation and structured tool results. No resources or prompts are registered.

Run local demo:

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tools/mcp
python -m tools.mcp.demo_interop > con40-demo.json
python -m tools.mcp.server --transport stdio --fixture tools/mcp/fixtures/offline.json
```

The demo uses the official MCP client over in-process Streamable HTTP, and tests use the official stdio client in a child process. Its sanitized [report](../../evidence/con40/demo-offline.json) marks `MCP_PROTOCOL_VERIFIED=true`, `AUTHORIZATION_VERIFIED=true`, `OFFLINE_FIXTURE=true`, `LIVE_DEVNET_READ_ONLY=false`. A separate read-only live Devnet smoke retrieved a finalized snapshot with seven agents and seven WorkOrders under the pinned genesis/program; it had zero private access bindings and did not call a private tool or send a transaction.

## Tools and output

The allowlist has exactly seven read-only tools: `conatus_search_agents`, `conatus_get_agent`, `conatus_get_agent_card`, `conatus_search_workorders`, `conatus_get_workorder`, `conatus_get_settlement_evidence`, `conatus_get_protocol_status`. All declare JSON input and output schemas generated from typed Python signatures and Pydantic response models; tool annotations mark them read-only. Public tools expose only the approved agent identity/capability fields, catalog-verified cards in Devnet and pause/identity status. Offline cards are clearly labeled as fixtures, never as verified signatures. Private tools require `workorders:read` or `evidence:read`. Pages are capped at 20 entries. A keyed cursor binds tool, resource, query, page size, current result digest, subject, client, tenant, organization and scopes. Altered, cross-client or stale cursors fail. Tool errors expose stable categories rather than internal exceptions.

WorkOrder outputs include current state (`Draft`, `Open`, `Claimed`, `Submitted`, `Verified`, `Settled`), network, genesis, program, PDA, commitment and verification status. The evidence tool returns only a scoped record. In fixture mode it remains `OFFLINE_FIXTURE`/`UNVERIFIED`, with no fabricated signature or finalized slot. In live mode the reconciler must validate a finalized transaction and exact WorkOrder before any `LIVE_RPC` label can appear. Historical data is not represented as current state.

## Authentication and resource authorization

The local HTTP resource server accepts an optional Bearer JWT signed with a separately configured Ed25519 issuer public key. It validates the signature, exact `iss`, `aud` and RFC 8707 `resource`, `sub`, `client_id`, `tenant_id`, `organization_id`, `scope`, `iat`, `exp`, `jti`, maximum 15 minute lifetime and a revocation set. An invalid supplied token is rejected even for public calls. The issuer alone grants scopes; an Agent Card cannot grant MCP authority. The server does not issue access tokens.

Each private call checks scope, current resource visibility, owner subject, tenant and organization. Missing resource metadata fails closed. Cross-tenant, cross-organization and wrong owner requests return `RESOURCE_NOT_FOUND`, avoiding disclosure. The search tool filters before pagination. A token for another audience or resource never authorizes a call. Stateless HTTP avoids transport session identity reuse; stdio is anonymous.

The local launcher intentionally requires loopback, pinned issuer/public key and exact Host. Origin is rejected unless allowlisted; no Origin is allowed for server-to-server calls. Duplicate Host, Origin or Authorization headers are rejected. No tool accepts a client URL or performs client-directed HTTP, preventing SSRF and DNS rebinding through arguments. Agent descriptions are returned as untrusted data. The result cap is 64 KiB; query and identifier patterns are bounded. Limits are per signed client/tool/resource or anonymous IP/tool/resource per minute. This process-local limiter is appropriate for local development; a shared gateway limiter, OAuth 2.1 authorization-server integration, DPoP/token replay defense and managed revocation are required before external deployment.

The only registered operations are the allowlist. Direct `tools/call` attempts for `wallet_sign`, `transfer`, `settle_workorder`, `fund_workorder`, `claim_workorder`, `change_beneficiary`, `upgrade_program`, `change_policy` and `export_private_key` fail as unknown tools. There is no database write path or Solana transaction path.

## Observability, testing and limits

Per-call JSON events carry timestamp, correlation/trace IDs, client/principal IDs, tool, scope, resource type, allow/deny, duration and error category. Tokens and private response bodies are excluded. In-process counters cover invocations, denied access, latency sum, rate limits, transport errors, cross-tenant blocks, unknown tools and evidence errors. `--operations-db` optionally records those counters through CON-38 `OperationalStore`; telemetry failures never affect authorization. `metrics_snapshot()` is also available locally; no metrics HTTP endpoint is exposed. The tests cover SDK discovery, schemas, HTTP/stdio, public/private separation, token signature/expiry/issuer/audience/revocation, scope, owner, tenant, organization, cursor binding, rate limits including identifier rotation, Host/Origin, prompt injection as data, SSRF input, synthetic evidence mislabeling and forbidden direct calls. `.github/workflows/con40-secure-mcp.yml` runs these and CON-34–39 Python, JS/web and Rust regressions without wallets, signatures or Devnet transactions, and uploads a sanitized demo JSON artifact.

Remaining deployment work: populate and audit a protected tenant/organization/consent access index for live Devnet WorkOrders, configure an OAuth 2.1 issuer and shared rate/revocation infrastructure, add TLS and a production gateway, and perform an externally hosted security review. This PR does not claim productive remote access or financial authority.
