# CON-36 — Devnet WorkOrder E2E

## Baseline and reuse

This work starts from `origin/master` commit `20ad98f7e3d39a78ca3d2379b53ef503d2a23b7b`, the CON-35 merge. The Anchor program, SPL settlement contract, Localnet five-scenario runner and CON-23/34 `SplSettlementReconciler` remain unchanged. The Localnet runner already supplies IDL encoding, PDA derivation, attestation hashing, balance checks and finalized transaction retrieval. The Devnet flow will reuse those patterns with explicit approval gates and the official Devnet RPC.

## Read-only Devnet audit

The official `https://api.devnet.solana.com` RPC returned genesis `EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG`. Program `CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy` is executable. Its canonical ProgramData is `7kYZxnujXJ9sKGhG9CbDwThJECb693WvvqVFHGmNSsrr`, upgrade authority `DdHrtAxE5SwcVQUgoKRzoWatZ5yw9UdtBQnRwBizPK2D`, and deployed bytes match the exact CON-35 approved SBF SHA-256 `6cf3412c55c38e91b2ba0039aea24d58782c5db0d18759ffdab1c88788cdc3a2` (zero loader padding excluded). The approved IDL SHA-256 is `a6e436aa1c6468b4f518b742e40a2664e38dcdf7bc1419e53e1624444888e15d`.

The dedicated Devnet SPL test mint `HpfaV9oRuTN1b3ktDKvJoWqUWFZ1o9VFmhejxxqQ1vyh` is owned by legacy SPL Token Program `TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA`, has mint authority `4om6LcFXaZ2Wtbn3P2ZvvyqssXFQs1xjNmE2Fnj7mRHa`, six decimals and zero supply at this audit. It is neither USDC nor a production asset. `ProtocolConfig` PDA `C8HiYzxKjRcDFHoWSZ84smUsxnMQ7ipxPnQ96GK5qZVn` is absent. Fee payer `HRwPNBPzArvdCULMH1EFuUpxGw31CbRjyf1cGBz2zE2x` has 7,416,208,160 lamports; protocol admin `27cyzd58RswQRbSuR3cKh4xv2gWgZ7awb3tUtoT7hYLB` has zero. These balances and supply are point-in-time observations; the runner rechecks them.

## ProtocolConfig initialization plan

`initialize_protocol` initializes the singleton PDA with its own signer as authority and payer. It requires nonzero 32-byte `network_id` and `deployment_id`; it does not require the upgrade authority to sign. The planned authority is the preexisting CON-35 protocol admin, not the fee payer. The 32-byte network ID is the raw decoded Devnet genesis hash. The protocol deployment ID is the already approved CON-35 deployment fingerprint `06c7dfa7528460969a5ca1e8bd001f9c9f1f1f0df3d69fe36649e413e0b14ae6`: this is a unique deployment instance hash, independent of the Program ID, as described by `DeploymentContext`. Its use here was checked against that semantic meaning and the sealed deployment evidence; the CON-35 manifest is not modified.

The [exact public plan](../../../evidence/con36/protocol-config-plan.json) has approval ID `5dbc0681980e3fcf78ad35f1548ccf6dd0751eb3a697b6dcc0bc0a6f137c21a6`. It combines a 3,000,000-lamport transfer from fee payer to admin and the Anchor initialization in **one atomic transaction**. The 155-byte PDA rent quote is 1,437,640 lamports; the minimum zero-data system-account rent quote is 650,240 lamports. An earlier 2,000,000-lamport simulation failed with `InsufficientFundsForRent` because the admin's remaining balance was too low; that plan was discarded before publication, with no submitted transaction. The corrected plan simulated successfully with two signatures, a 10,000-lamport fee quote and 7,716 compute units. The maximum fee allowed by the plan is 20,000 lamports, giving a **maximum payer debit of 3,020,000 lamports (0.00302 test SOL)**. The transfer is internal between test wallets; after account creation, 1,562,360 lamports remain with the admin if the quoted rent is unchanged.

The admin and fee payer private keypairs are ignored by Git, stored in a `0700` directory as `0600` files, and have matching protected copies outside the repository. The runner checks both copies, bindings, pubkeys and genesis before signing. It sends nothing by default. `submit` requires the exact approval ID as both a CLI argument and `CON36_APPROVED_PROTOCOL_CONFIG_ID`, rechecks live state and simulates before transmission. CON-35 deployment and mint approvals cannot pass this gate. **Human approval for this CON-36 transaction is pending.**

Five additional test identities (creator, agent owner, device, shared-beneficiary device and verifier) were generated with [public role bindings](../../../evidence/con36/test-identities.json). Their private keypairs are ignored under `target/deploy/con36-private/`, backed up outside Git in the protected CON-36 wallet backup directory, and never printed. No wallet has yet been funded or used in a transaction. The [seven-order scenario inventory](../../../evidence/con36/scenario-plan.json) fixes distinct WorkOrder, agent and escrow PDAs, creator/operator token ATA addresses, payment models, expected exact base-unit allocations, and a duplicate-settlement target. Its `PREPARED_NOT_AUTHORIZED` status is explicit. Seven WorkOrders each need 1,000,000 test-token base units; a 100,000-unit escrow donation is reserved for the proportional scenario. Thus the later minting plan will require **7,100,000 base units (7.1 test tokens)**, subject to a separate exact approval. The inventory does not authorize minting, ATA creation, agent registration or WorkOrder transactions.

Read-only commands:

```bash
npm ci --prefix tools/bootstrap
node --test tools/integration/devnet/test_*.cjs
node tools/integration/devnet/prepare_wallets.cjs
node tools/integration/devnet/prepare_scenarios.cjs
node tools/integration/devnet/protocol_config.cjs inspect
node tools/integration/devnet/protocol_config.cjs prepare
node tools/integration/devnet/protocol_config.cjs simulate
```

After explicit approval of the exact plan ID, a human-supervised local operator may run `submit` with that ID. The subsequent `verify` command must recover the finalized signature, fee, exact transfer and initialization instructions, and on-chain ProtocolConfig fields before the evidence can be marked verified. No CI or pull request job executes `submit`.

## Outstanding gates

ProtocolConfig initialization has **not** been submitted. The test mint still has zero units, so no WorkOrder has been funded. The full eight-scenario Devnet matrix, genuine negative transactions, SPL balances, finalized signatures and slots, LIVE_RPC reconciliation, SQLite restart checks and historical RPC recovery remain pending. Each new Devnet state-changing operation needs its own exact manifest, spending bounds and human approval. No WorkOrder result or productive economic provenance is claimed from the simulation. CON-36 is **not complete**.
