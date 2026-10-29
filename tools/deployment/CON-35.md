# CON-35 — Devnet deployment and SPL test asset

## Verified deployment

CON-34's [Localnet E2E](https://github.com/marcos1394/aerosettle/actions/runs/40456131320) and [regressions](https://github.com/marcos1394/aerosettle/actions/runs/40456131307) passed before this Devnet work. This branch leaves Anchor contracts, SPL settlement, accounting, SDKs, web RPC defaults and the WorkOrder lifecycle unchanged. `ProtocolConfig` remains `UNINITIALIZED` on Devnet; a Devnet WorkOrder E2E cycle is not claimed and belongs to CON-36.

The deployment is **VERIFIED**. The immutable [public evidence record](../../evidence/con35/devnet-deployment.json), [exact approved SBF and IDL](../../evidence/con35/artifacts/), [preparation workflow](https://github.com/marcos1394/aerosettle/actions/runs/40804645272) and [read-only post-deploy workflow](https://github.com/marcos1394/aerosettle/actions/runs/40804645230) establish:

| Field | Verified Devnet value |
| --- | --- |
| Genesis | `EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG` |
| Program ID | `CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy` |
| Deployment ID | `06c7dfa7528460969a5ca1e8bd001f9c9f1f1f0df3d69fe36649e413e0b14ae6` |
| Finalized transaction | `3FdinSa8F8VBsP3a1fM6so64K9X7QBUbR5Ay7z6Zv32mXQJx27SWhGddPK67pnLN5KBEYTkX25DsQgZWLdWfVDEA` |
| Slot | `516258865` |
| ProgramData | `7kYZxnujXJ9sKGhG9CbDwThJECb693WvvqVFHGmNSsrr` |
| Upgrade authority | `DdHrtAxE5SwcVQUgoKRzoWatZ5yw9UdtBQnRwBizPK2D` |
| Approved SBF SHA-256 | `6cf3412c55c38e91b2ba0039aea24d58782c5db0d18759ffdab1c88788cdc3a2` |
| IDL SHA-256 | `a6e436aa1c6468b4f518b742e40a2664e38dcdf7bc1419e53e1624444888e15d` |

The post-deploy check queried the official Devnet JSON-RPC at `finalized`, recovered the actual transaction and signature status, checked the loader instruction and slot, executable Program and canonical ProgramData accounts, upgrade authority and exact approved ELF bytes (allowing only zero loader padding), and emitted `VERIFIED`. Neither workflow sends a deploy transaction. The first deployment attempt created a Buffer but hit RPC write retries; the same approved buffer was resumed over TPU and consumed in the finalized deploy. No second program deployment or upgrade followed.

## Build provenance and platform hashes

The deployed SBF came from two isolated **macOS** builds at source commit `b95c7bfd7c760558a0a7b87ee25b0a4b67aa6f14`, byte-identical to one another. The public SBF above is that exact approved artifact. The **Linux** preparation workflow passed two isolated Linux builds but produced SBF SHA-256 `584ca1c7024673baf0cb716573fe62dc13e5301dc3973fd6c18cecc1726cb451`; its run at head `43c248fbcf1295a1a600457952b5ff1470b1c2ea` produced the same IDL SHA-256 `a6e436aa1c6468b4f518b742e40a2664e38dcdf7bc1419e53e1624444888e15d`. That head differs from the deployed source commit only in evidence and workflows. Each platform's two-build comparison passed. **Binary reproducibility across macOS and Linux is not established or claimed.** The Linux artifact and its deployment ID are not the approved on-chain binary or deployment ID. The post-deploy workflow restores the exact public approved SBF and verifies it against Devnet.

`build_idl.py` invokes the compiled Anchor IDL printer because Anchor CLI 1.2.0's `anchor idl build` fails on overlapping error definitions (`ErrorCode`, `IdentityError`, `WorkOrderError`). Its account/instruction/type ABI matches the CON-34 IDL; errors remain in a separate catalog. `compare_clean_builds.sh` compares two clean SBF/IDL outputs within one platform, records source and Cargo.lock hashes, and copies the SBF to the Rust integration test layout. A single `devnet.py build` output is `NOT_COMPARED` and cannot pass the deploy gate.

The deployment manifest is sealed and binds the exact artifact hashes, genesis, program ID, public roles and deployment ID. It is never edited to add a mint. `tools/deployment/devnet.json` intentionally retains `test_mint_* = null` because changing those fields would change the approved deployment ID. Test asset evidence has its **own** manifest and creation ID.

## Dedicated SPL test mint — prepared, awaiting approval

The [independent test mint manifest](../../evidence/con35/test-mint.json) identifies a newly generated `DEVNET_TEST_TOKEN` mint, distinct from real USDC and Localnet assets. It records the official Devnet RPC/genesis, legacy SPL Token Program `TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA`, planned mint `HpfaV9oRuTN1b3ktDKvJoWqUWFZ1o9VFmhejxxqQ1vyh`, separate mint authority `4om6LcFXaZ2Wtbn3P2ZvvyqssXFQs1xjNmE2Fnj7mRHa`, six decimals, test fee payer `HRwPNBPzArvdCULMH1EFuUpxGw31CbRjyf1cGBz2zE2x`, and creation ID `8044d0f4fea6cb5c87014c08a80867b509596fd8b69c22afcd66544b557ec5d5`.

The mint and authority keypairs are in ignored `target/deploy/con35-private/` (directory `0700`, files `0600`) and have copies outside Git in the existing private CON-35 backup directory. No keypair bytes or seed phrase are in the public manifest. A real read-only Devnet preflight on 2026-10-29 confirmed genesis, the mint account's absence, payer balance **7,417,284,960 lamports**, and rent quote **1,066,800 lamports** for an 82-byte mint, plus a 50,000-lamport fee reserve. Refresh these values at submission. The manifest's `creation_signature` and `creation_slot` are deliberately `null`, status `PREPARED`. **The mint does not yet exist on Devnet; Jira criterion 3 remains open until creation and verification.**

The [mint tool](test_mint.py) uses only the fixed official Devnet RPC and checks genesis before any state change. It requires matching local keypairs, distinct roles, an absent mint, sufficient test SOL, and all of `--submit`, `--approval <creation_id>` and `CON35_APPROVED_TEST_MINT_ID=<creation_id>`. This approval is specific to mint creation; the earlier deployment approval does not authorize it. Its one transaction creates an 82-byte account owned by the legacy SPL Token Program and initializes the mint with six decimals, dedicated authority, no freeze authority and zero supply. No token units are minted, no token accounts or protocol accounts are created, and the Economic Ledger is untouched. See the [official mint account specification](https://solana.com/docs/tokens/basics/create-mint).

Read-only checks, safe now:

```bash
python3 tools/deployment/test_mint.py preflight
python3 -m unittest discover -s tools/deployment -v
```

**Only after a human explicitly approves the exact creation ID above**, run this from the repository root with the backed-up local wallets. This command sends a Devnet transaction:

```bash
CON35_APPROVED_TEST_MINT_ID=8044d0f4fea6cb5c87014c08a80867b509596fd8b69c22afcd66544b557ec5d5 \
python3 tools/deployment/test_mint.py create \
  --manifest evidence/con35/test-mint.json \
  --mint-keypair target/deploy/con35-private/test-mint.json \
  --authority-keypair target/deploy/con35-private/test-mint-authority.json \
  --payer-keypair target/deploy/con35-private/fee-payer.json \
  --submit --approval 8044d0f4fea6cb5c87014c08a80867b509596fd8b69c22afcd66544b557ec5d5 \
  --output evidence/con35/test-mint-verified.json
```

The command prints the submitted signature for recovery if finality polling fails. It writes the independent `VERIFIED` manifest only after real JSON-RPC confirms the signature and slot at `finalized`, `getTransaction` contains successful System `createAccount` and SPL Token `initializeMint`/`initializeMint2` instructions for the approved mint, and `getAccountInfo` returns the expected owner, initialized 82-byte layout, authority, decimals, zero supply and no freeze authority. A read-only recovery command is `python3 tools/deployment/test_mint.py verify --signature <actual-signature> --output evidence/con35/test-mint-verified.json`. The verified manifest will record the **actual** finalized signature and slot; publish it in this PR and rerun CI. Network, owner, authority, decimal, transaction and manifest mismatches fail closed. Do not change the deployment manifest or redeploy the program.

## Existing controls and regressions

`devnet.py preflight`, `inspect`, `verify-artifacts`, `post-deploy-verification` and `prepare-rollback` remain available. Deployment still requires separate human approval of the immutable deployment ID; `prepare-rollback` produces a plan for a separately authorized upgrade, never an automatic rollback. Wallet roles and genesis-bound bindings remain distinct and outside Git. `request-test-funds` is limited to 2 Devnet SOL per request and a 10 SOL resulting wallet balance. No Mainnet RPC, real USDC, production income or production payment execution is involved.

The unchanged CON-34 Localnet runner previously passed `full`, `zero`, `proportional`, `invalid_shared` and `valid_shared`, with Anchor `SettlementInvalidCreatorRefund` for the invalid shared destination; finalized transactions remained retrievable after validator restart and SQLite reconciliation kept the same `LIVE_RPC` effect IDs. [Regression CI](https://github.com/marcos1394/aerosettle/actions/runs/40623908619) passed Python, JavaScript and Rust. The new mint tests cover read-only preflight and negative cases for wrong network, owner, authority, decimals, incomplete or unrelated transaction evidence and missing creation approval. PR #18 remains open without merge; CON-36 has not started.
