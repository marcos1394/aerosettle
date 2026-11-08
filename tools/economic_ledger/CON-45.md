# CON-45 — x402 economic reconciliation

## AS-IS audit and scope

Baseline: `origin/master` at merge `f7790f9e15efb0aae1e698e42d14e3896f692b1e` (CON-44 PR #27). Jira CON-45 requires idempotent, identity-scoped resource payment accounting. Jira CON-96 is the separate, pending Devnet SVM `exact` gate. CON-44 uses the official x402 V2 Python schemas and HTTP headers, but its `conatus-sandbox-exact` scheme, facilitator, and receipts are intentionally local simulations. Its `SandboxStore` is a delivery journal, not an Economic Ledger. A successful HTTP 200 or signed sandbox receipt proves neither a token transfer nor financial income.

The Economic Ledger already has `economic_movements`, double-entry `journal_entries`/`ledger_entries`, exact integer accounting, evidence lineage, and `ingestion_effects` for CON-36/37 WorkOrder settlements. `SplSettlementReconciler` validates genuine WorkOrder settlements against Solana RPC. CON-45 preserves that reconciler and all historical movements; no WorkOrder settlement is converted into a resource payment. Agent Runtime CON-42 and negotiation CON-43 authorize or propose work, but neither is a source of settled payments. Operations CON-38 supplies RPC health boundaries. The transaction SDK remains unchanged.

## Model and trust boundary

Migration `013_x402_economic_reconciliation.sql` adds versioned `x402_payments`, `x402_events`, and a reserved `x402_verified_effects` table **inside the Economic Ledger SQLite database**. Payment rows contain signed receipt bytes, receipt and payload hashes, payment/resource identities, client and provider AgentAccount, agent ID, owner, payer, recipient, CAIP-2 network, genesis, program, mint, token program, decimals, and exact base-unit amount as decimal text. Sandbox rows are constrained by SQLite to `SANDBOX_SIMULATION`, `UNVERIFIED`, `INSUFFICIENT_DATA`, and null transaction/instruction fields. Their economic effect identity is absent. There is no API to insert a verified effect in CON-45.

Events have `schema_version=1`, immutable IDs and hashes. The taxonomy includes resource request, requirements, authorization, facilitator verification, settlement attempt, receipt, duplicate, RPC check, finality, difference, and refund. Only events independently observed by this importer are written: signed receipt import, duplicate import, read-only RPC check, and reconciliation difference. The importer never reconstructs earlier stages from a receipt as though it witnessed them. Future CON-96 evidence can use the reserved taxonomy after its gate is implemented.

`X402EconomicStore.import_sandbox_receipt()` requires the independently configured facilitator Ed25519 public key. It reuses CON-44's complete receipt signature verifier and checks its pinned Devnet test mint, CAIP-2 network, genesis, program ID, exact amount, resource URL, and current client/provider identity and owner. Reads recheck the hash, signature and current identities. Owner or agent ID changes block historical access and idempotent reuse. Errors contain codes without disclosing another tenant's receipt. `BEGIN IMMEDIATE`, unique payment/receipt/requirements/payload keys, and immutable row hashes make exact retries, concurrent consumers and SQLite restarts idempotent. A changed receipt conflicts instead of replacing evidence.

## Financial effects and WorkOrder dedupe

The reserved effect identity is a digest of `(network, genesis, payment_id, transaction_signature, instruction_index, effect_type, agent_account, asset)`. `x402_verified_effects` has a matching SQLite unique key. Its allowed kinds are x402 payment, resource revenue, facilitator fee, network fee, provider payout, payer cost, refund and economic adjustment. These are **potential** categories, not assumed legs of every transaction. No record enters this table until CON-96 proves each applicable effect. Network fees are denominated in lamports, so they are never silently subtracted from token-denominated revenue. The agent view shows sandbox receivables/payables separately from realized revenue/expense and leaves realized profit `null`.

`workorder_collision()` checks both `ingestion_effects` and WorkOrder `economic_movements` under the exact network/genesis/signature/instruction scope. The demo compares the signed sandbox receipt to the seven genuine WorkOrder settlement signatures in `evidence/con36/verified-matrix.json` without copying them or creating movements. Since CON-44 has no transaction signature, it cannot share a verified SPL effect or increase the WorkOrder totals. The future CON-96 posting path must cross-check this index and use the Economic Ledger's movement idempotency before writing any effect; this path is intentionally disabled here.

## RPC inspection and provenance

`inspect_rpc()` is a read-only seam for CON-96. It accepts only the existing `SolanaRpcClient` configured for the official Devnet RPC URL. It checks genesis, signature format and status, `finalized`, transaction availability, slot, absence of errors, fee presence, transaction signature list, pre/post token balances, mint, token program, decimals, payer/recipient deltas and live token-account program ownership. A missing or pruned transaction, RPC error, confirmed-only status, failed transaction, contradictory balance or incomplete account context yields `INSUFFICIENT_DATA`. Even a plausible finalized transfer still yields `INSUFFICIENT_DATA`: CON-44's sandbox receipt cannot bind an SVM `exact` instruction, transaction signer, instruction index or fee allocation. `inspect_and_record()` stores that unsuccessful check and difference without posting a movement. No mock can produce `LIVE_RPC` or `RECONCILED` through this module.

`PENDING`, `REJECTED`, `LIVE_RPC`, `FINALIZED` and `RECONCILED` are defined in the event schema. The sandbox importer emits `SANDBOX_SIMULATION`; read-only inspection may record `PENDING` for confirmed-only RPC status, `REJECTED` for an RPC transaction error, or `INSUFFICIENT_DATA` for missing or inconsistent evidence. None changes the payment row's sandbox provenance or its zero realized amount. `LIVE_RPC`, `FINALIZED` and `RECONCILED` economic events remain disabled until CON-96. A signature alone, HTTP success, human approval, quote or AcceptIntent never changes financial provenance. Refunds and facilitator fees remain zero/unverified without separate evidence. No fabricated transaction, refund, fee, revenue or expense is written.

## Reproduce

```bash
python -m unittest discover -s tools/x402
python -m unittest discover -s tools/economic_ledger
python -m tools.economic_ledger.x402_reconciliation_demo
```

The demo generates a fresh authentic CON-44 **sandbox** receipt over localhost HTTP, verifies and imports it twice, restarts the Economic Ledger SQLite file, revalidates the full signed receipt and event history, compares the CON-36 WorkOrder signature set, and produces a difference report. `evidence/con45/demo-offline.json` is one captured run; IDs and signatures in future runs vary. Its required assertions include `SANDBOX_RECOGNIZED_REVENUE=0`, `WORKORDER_DOUBLE_COUNT=false`, `INSUFFICIENT_DATA_HANDLED=true`, and `ONCHAIN_TRANSACTIONS_SENT=0`. The workflow `con45-x402-reconciliation.yml` runs the demo and Python/JS/Rust regressions, uploads JSON evidence, and never submits Solana transactions.

## Remaining gate

CON-96 must supply an approved Devnet payment manifest, genuine x402 V2 SVM `exact` payload/receipt, finalized recoverable RPC transaction, instruction-level SPL effects, identity and fee evidence, and specific human approval before financial posting can be enabled. Until then all x402 realized income, expense, fee and refund totals remain zero, and realized profit remains unknown. Mainnet and production assets are out of scope.
