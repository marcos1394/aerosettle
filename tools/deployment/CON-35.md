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

## Dedicated SPL test mint — VERIFIED on Devnet

The independent [prepared plan](../../evidence/con35/test-mint.json) and [VERIFIED mint manifest](../../evidence/con35/test-mint-verified.json) identify a newly generated `DEVNET_TEST_TOKEN` mint, distinct from real USDC and Localnet assets. It uses the official Devnet RPC/genesis, legacy SPL Token Program `TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA`, mint `HpfaV9oRuTN1b3ktDKvJoWqUWFZ1o9VFmhejxxqQ1vyh`, dedicated mint authority `4om6LcFXaZ2Wtbn3P2ZvvyqssXFQs1xjNmE2Fnj7mRHa`, six decimals and test fee payer `HRwPNBPzArvdCULMH1EFuUpxGw31CbRjyf1cGBz2zE2x`. The separately approved creation ID was `8044d0f4fea6cb5c87014c08a80867b509596fd8b69c22afcd66544b557ec5d5`.

The mint and authority keypairs are in ignored `target/deploy/con35-private/` (directory `0700`, files `0600`) and have matching copies outside Git in the private CON-35 backup directory. No keypair bytes or seed phrase are in the public manifests. The pre-submission read-only preflight confirmed genesis, the mint account's absence, payer balance **7,417,284,960 lamports**, and rent quote **1,066,800 lamports** for an 82-byte mint, plus a 50,000-lamport fee reserve.

After explicit human approval of that exact creation ID, the [mint tool](test_mint.py) sent **one** `spl-token create-token` transaction to Devnet. The CLI reported success but did not expose a signature in the JSON shape the initial parser expected. No creation retry was sent. Read-only `getSignaturesForAddress` recovered the actual finalized signature `59AT8MuBjXnvZBe6qmnLA47UrbBR9QbT2dt6AC6zLUMGsmJULUNqFFPgiZSWAhRJqjok23UHW5QTR9eqkNWv8igb` in slot **516582820**. `getSignatureStatuses`, `getTransaction` and `getAccountInfo` then verified the successful System `createAccount` and SPL Token `initializeMint`/`initializeMint2` instructions and on-chain mint state: owner is the legacy SPL Token Program, account size 82 bytes, mint authority matches, six decimals, zero supply and no freeze authority. The sealed `VERIFIED` manifest records the actual signature, slot, owner and genesis. See the [official mint account specification](https://solana.com/docs/tokens/basics/create-mint).

Read-only verification, safe to repeat:

```bash
python3 tools/deployment/test_mint.py verify \
  --manifest evidence/con35/test-mint.json \
  --signature 59AT8MuBjXnvZBe6qmnLA47UrbBR9QbT2dt6AC6zLUMGsmJULUNqFFPgiZSWAhRJqjok23UHW5QTR9eqkNWv8igb \
  --output evidence/con35/test-mint-verified.json
python3 -m unittest discover -s tools/deployment -v
```

The creation command required matching keypairs, distinct roles, an absent mint, sufficient test SOL, and all of `--submit`, `--approval <creation_id>` and `CON35_APPROVED_TEST_MINT_ID=<creation_id>`. The approval was specific to this mint; the earlier deployment approval did not authorize it. For audit, the exact command executed from the repository root was:

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

The CLI output parser now has a bounded read-only RPC recovery path: after one successful submission it searches the mint address, validates candidate signatures against the full creation transaction and mint account, and never resubmits. The prepared plan remains immutable. This test mint has no minted units, token accounts or protocol accounts, and the Economic Ledger was not written. Network, owner, authority, decimal, transaction and manifest mismatches fail closed. The deployment manifest and Deployment ID did not change; the program was not redeployed.

## Existing controls and regressions

`devnet.py preflight`, `inspect`, `verify-artifacts`, `post-deploy-verification` and `prepare-rollback` remain available. Deployment still requires separate human approval of the immutable deployment ID; `prepare-rollback` produces a plan for a separately authorized upgrade, never an automatic rollback. Wallet roles and genesis-bound bindings remain distinct and outside Git. `request-test-funds` is limited to 2 Devnet SOL per request and a 10 SOL resulting wallet balance. No Mainnet RPC, real USDC, production income or production payment execution is involved.

The unchanged CON-34 Localnet runner previously passed `full`, `zero`, `proportional`, `invalid_shared` and `valid_shared`, with Anchor `SettlementInvalidCreatorRefund` for the invalid shared destination; finalized transactions remained retrievable after validator restart and SQLite reconciliation kept the same `LIVE_RPC` effect IDs. [Regression CI](https://github.com/marcos1394/aerosettle/actions/runs/40623908619) passed Python, JavaScript and Rust. The new mint tests cover read-only preflight and negative cases for wrong network, owner, authority, decimals, incomplete or unrelated transaction evidence and missing creation approval. PR #18 remains open without merge; CON-36 has not started.
