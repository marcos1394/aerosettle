# CON-34 — Anchor SPL parity and Localnet evidence

## AS-IS and reproduced blocker

Baseline `21adbc631be147b41782ec70716d47bfc202ffa9` includes CON-23 and CON-33. The Rust settlement tests execute a compiled SBF program in LiteSVM (`SIMULATED_ONCHAIN`); `test_spl_reconciler.py` uses `MockRpcClient` (`UNIT`, `SYNTHETIC_TEST`). Neither is evidence of a finalized validator transaction. The old shared-destination fixtures used distinct creator and beneficiary keys, while `SettleWorkOrder` checks both SPL owners. The reconciler also accepted the shared zero-payout case when only one owner matched. The original fixtures remain as rejection cases.

After fixing the mock fixtures to use a canonical WorkOrder PDA and equal creator/beneficiary, a new LiteSVM test still failed with Anchor `ConstraintDuplicateMutableAccount (2040)` before entering settlement. Anchor 1.2 rejects two mutable `Account<TokenAccount>` fields with the same key by default. This is a contract-level blocker to the required valid shared-destination scenarios; changing Python or test fixtures cannot resolve it. The required minimal contract change is isolated in a separate commit and guarded by the two existing owner constraints. No payout formula, authority or economic identity changes are needed.

## Evidence levels

| Level | Meaning |
|---|---|
| `UNIT` | Deterministic calculation or mock RPC, never `LIVE_RPC`. |
| `SIMULATED_ONCHAIN` | Compiled SBF execution in LiteSVM, without a validator or JSON-RPC finality. |
| `REAL_LOCALNET_E2E` | Signed transaction finalized by a persistent local validator and independently recovered through JSON-RPC. |

The historical localnet fixtures are not promoted to `LIVE_RPC` without current RPC recovery on the same genesis. The Localnet test runner uses fresh, isolated test keys and a test mint; its report never contains private keys. Pending E2E requirements must be reported as `PENDING`, not passed by mock or LiteSVM results.
