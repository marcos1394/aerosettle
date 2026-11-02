# CON-37 — Reliable Devnet SPL ingestion

## AS-IS and scope

The baseline is `origin/master` merge `5f53bc2571acc39c5bc98ffde2a7097376710364`, which includes CON-36's seven real Devnet settlements. `SplSettlementReconciler` already checks finalized JSON-RPC transactions, the Anchor settlement discriminator and accounts, WorkOrder and AgentAccount identity, actual SPL account owners and mints, inner `TransferChecked` instructions, pre/post integer balances, payout/refund conservation, frozen beneficiary and evidence hash. `EconomicLedger` already provides an SQLite unique idempotency key and authentic `RECONCILED` promotion. CON-36's `verify_matrix.py` recovers the fixed historical fixture, but did not discover arbitrary new signatures, paginate or retain a consumer cursor. This consumer adds those missing operations and keeps the reconciler as the accounting authority.

The only accepted network is `solana:devnet`, genesis `EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG`, program `CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy`, and approved six-decimal test mint `HpfaV9oRuTN1b3ktDKvJoWqUWFZ1o9VFmhejxxqQ1vyh`. Before ingesting, the consumer re-reads genesis, Program/ProgramData, upgrade authority, SBF bytes, mint owner, mint authority, decimals and its finalized creation evidence using the official RPC. The approved CON-35 artifact is compared byte-for-byte to deployed program data. A mock or alternate RPC client cannot be labeled `LIVE_RPC` by the consumer.

Only explicitly provided WorkOrder addresses and a bounded slot interval are scanned. The consumer uses no signing or transaction-submission API. Devnet test tokens are never classified as production revenue; tax, market value, operating cost and solvency are outside this ingestion.

## Discovery and recovery

`getSignaturesForAddress` is paginated newest-first with a finite page and signature cap. Each scope is one WorkOrder, network, genesis, program, mint and slot interval, hashed to `scope_id`. Discovery must reach the prior checkpoint signature or the lower slot bound. It rejects duplicate or unordered pages, missing checkpoints and incomplete pagination. A second head query detects a new signature arriving during pagination; the entire scan is retried later. These checks prevent a partial page from advancing the cursor.

After complete discovery, observations are staged as `DISCOVERED`. Processing runs oldest-first. Each signature must have `getSignatureStatuses` reporting `finalized`, a matching `getTransaction(finalized)` slot and signature, and matching error status. Failed on-chain transactions are `UNVERIFIABLE` with no movement. Successful transactions without the approved settlement discriminator are `FINALIZED` but create no economic effect. Exactly one settlement instruction is allowed; its index is bound to the receipt. The signature is confirmed in `getBlock`. The existing reconciler then verifies all Anchor/SPL economics and promotes exactly one operator movement. It may not fall back to `confirmed` because the consumer has already required `finalized` and checks the receipt commitment again.

If status is premature, the observation remains `PENDING_FINALITY`. Missing or pruned transaction history is `INSUFFICIENT_DATA`. Mismatched or malformed evidence is `UNVERIFIABLE` with an audit incident. In all three cases the checkpoint does **not** pass that signature. Bounded RPC retries cover 429 and transient 5xx with exponential backoff and jitter; persistent errors leave the scope `INCOMPLETE` or `GAP` for a later `resume`. A failed transaction is permanently observed and the cursor may advance because it cannot represent a successful settlement.

The persistent migration `012_devnet_ingestion.sql` adds:

- `ingestion_checkpoints`: exact scope identity, version, latest processed signature/slot, last successful sync and `READY`/`INCOMPLETE`/`GAP` status.
- `ingestion_observations`: one status and attempt count per scope/signature.
- `ingestion_effects`: unique `(network, genesis, signature, instruction_index, effect_kind, destination, mint)` with immutable amount, identity and evidence hash.
- `ingestion_incidents`: append-only differences and RPC gaps.

Each verified settlement has two auditable effects: operator payout and creator refund. The operator effect retains the CON-23/34/36 `effect_id` and references the existing reconciled movement; the refund has its own destination-bound effect ID and no new Ledger movement. This records shared destinations as separate contractual allocations without double counting the token account's balance. Zero allocations remain explicit. The Ledger's movement remains the single operator payout/adjustment, so seven CON-36 settlements produce seven movements and fourteen effects. No automatic balancing or compensating movements are created.

Ledger reconciliation commits before the observation/effect/checkpoint transaction. A crash between them is safe: restart discovers the unchanged checkpoint, the existing Ledger idempotency key returns the same movement, and the unique effect key is checked for identical amount, owner, WorkOrder and hash. Two workers may replay the same page; SQLite uniqueness and `BEGIN IMMEDIATE` serialize effect insertion. A conflicting identity or hash raises an incident and stops cursor advancement. `backfill` and `reconcile` deliberately replay the bounded interval; `resume` starts after the last committed signature. The official public RPC is paced across workers in one process; 429 and transient 5xx still use bounded retries with jitter.

## CLI

The default SQLite path is `target/con37/devnet-ledger.sqlite`, ignored by Git. Every command requires one or more explicit `--work-order` values and `--from-slot`; `--to-slot`, `--page-size`, `--max-pages` and `--max-signatures` set further bounds. `inspect` only reads RPC and never creates a database. `report` opens an existing SQLite database read-only. `backfill`, `reconcile` and `resume` write only to that local SQLite file.

```bash
python3 -m tools.economic_ledger.devnet_ingestion inspect \
  --work-order 2M2gMx8n5jDJ7ivKnLRxGVJepBAUst74vDuYZid4xRPr \
  --from-slot 516889000 --to-slot 517616000 --max-pages 2

python3 -m tools.economic_ledger.devnet_ingestion backfill \
  --work-order 2M2gMx8n5jDJ7ivKnLRxGVJepBAUst74vDuYZid4xRPr \
  --from-slot 516889000 --to-slot 517616000 --max-pages 2

python3 -m tools.economic_ledger.devnet_ingestion resume \
  --work-order 2M2gMx8n5jDJ7ivKnLRxGVJepBAUst74vDuYZid4xRPr \
  --from-slot 516889000 --to-slot 517616000 --max-pages 2
```

The CLI report contains scope, checkpoint, every observation/effect and incident, plus per-run counters for discovery, finality, reconciliation, duplicates, RPC errors, gaps and differences. When the RPC supplies a block timestamp, observations record the elapsed time since that block; this is an approximation of finalization-to-ingestion lag because JSON-RPC does not provide a separate finalization timestamp. The report exposes its maximum. It includes no private keys or test-wallet secrets.

## Historical CON-36 gate

`verify_ingestion.py` reads the seven WorkOrder addresses from the public CON-36 inventory rather than hardcoding their signatures in the generic consumer. It ingests them from real RPC, compares slots, `effect_id`, evidence hashes, payouts and refunds to the CON-36 receipt evidence, replays immediately, runs two concurrent resume workers, closes/reopens SQLite, resumes, and rereads all seven historical signatures. An offline concurrent writer test exercises the unique economic effect constraint directly. The live gate requires exactly seven `RECONCILED` movements, fourteen effects and unchanged hashes after every replay. The public result is `evidence/con37/verified-ingestion.json`; CI recomputes it into runner-local SQLite and uploads a fresh JSON artifact. CI does not submit transactions.

The public Devnet RPC may throttle requests or prune older history. The bounded retry and incomplete checkpoint state make this visible as an audit gap; they do not manufacture evidence or advance the cursor. Scanning the whole program without a WorkOrder scope, ingesting arbitrary tokens, real operating costs and production finance remain outside CON-37.

The local read-only RPC gate recovered these seven historical settlements from the approved CON-36 WorkOrders and compared each receipt to the committed CON-36 evidence. Amounts are integer base units of the six-decimal Devnet test mint. No unexplained economic difference was recorded:

| CON-36 case | Finalized slot | Operator payout | Creator refund | Difference |
| --- | ---: | ---: | ---: | --- |
| E2E-01-full | 516890572 | 1,000,000 | 0 | None |
| E2E-02-zero | 516890840 | 0 | 1,000,000 | None |
| E2E-03-proportional | 516891051 | 600,000 | 500,000 | None |
| E2E-04-invalid-shared | 516891303 | 600,000 | 400,000 | None |
| E2E-05-valid-shared | 516891488 | 600,000 | 400,000 | None |
| E2E-06-invalid-mint | 516891707 | 1,000,000 | 0 | None |
| E2E-07-wrong-beneficiary | 517615528 | 1,000,000 | 0 | None |

The fresh SQLite run yielded seven `RECONCILED` movements, fourteen unique effects and 46 transaction observations. Immediate replay, two concurrent resume workers, SQLite restart and a full RPC reread left those counts unchanged. A deliberate earlier public-RPC 429 exhausted its bounded retries, recorded an incident and kept the checkpoint behind the failed signature; pacing was added before repeating the full gate successfully. This demonstrates fail-closed behavior under provider throttling, while leaving public RPC availability as an operational dependency. The CON-37 workflow recomputes the stable receipt fields and uploads a fresh evidence artifact.
