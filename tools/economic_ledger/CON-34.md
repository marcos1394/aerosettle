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

## Cambios y evidencia observada

El primer commit `03f71e7` deja reproducido el defecto, fixtures canónicos separados y el rechazo económico cuando las dos identidades difieren. El segundo commit `64d11a9` es el único cambio contractual: `dup` en `creator_refund_token_account`, con una condición explícita que exige creator igual a frozen beneficiary si los dos destinos son la misma cuenta. Las restricciones SPL owner/mint originales y los controles de conservación permanecen. Antes del cambio, LiteSVM devolvía `ConstraintDuplicateMutableAccount (2040)` incluso para una identidad igual; después de recompilar SBF, 19 tests de settlement LiteSVM pasaron, incluidos SD-01..07.

`run_settlement.cjs` creó en un validador Agave 4.1.2 separado un mint de prueba, nuevos propietarios, cinco WorkOrders y transacciones firmadas. Se observaron pagos total, cero, proporcional y destino compartido válido finalizados, y una transacción rechazada para el destino compartido inválido sin drenaje del vault. La captura original no guardó el código de error de esa última transacción; el runner actual exige explícitamente `SettlementInvalidCreatorRefund`, pero esa comprobación reforzada aún no se ha repetido en Localnet. El reporte público [observed-localnet-20261026.json](../integration/localnet/observed-localnet-20261026.json) conserva genesis `8EnNDKjPs6ptLPhNqNnbh6yBDNAMPSXT5ascmZTw2oYz`, firmas, slots, PDAs y balances. El primer pago fue reconstruido durante la ejecución por `SolanaRpcClient` con `LIVE_RPC`, `finalized`, payout 10000000, refund 0 y evidence hash `7a01839cbf36392bdebcbdb44a7dcd0df7114c8da8f44d39180a886bd3a119c5`. El SBF ejecutado tenía SHA-256 `6cf3412c55c38e91b2ba0039aea24d58782c5db0d18759ffdab1c88788cdc3a2`. El reporte se clasifica ahora como `HISTORICAL_FIXTURE` porque ese ledger aislado fue retirado tras agotar espacio; las firmas ya no son verificables en un RPC activo.

Una segunda corrida aislada produjo la firma finalizada `MnnU883mSccVrq2mca3K76QyiMjYvso9d6CvFRKv7m44nzTC6V7wqfSZUfbXgSKr84Jy5BCPVmA96WFDoB9JmzA` en slot 307 y `verify_report.py` registró `RECONCILED`, repitió la conciliación inmediatamente, lanzó dos reintentos concurrentes y reabrió SQLite sin duplicar el effect ID. Tras detener y recuperar el mismo ledger, el genesis siguió siendo `DjSeiY7HTh9pMjbuvSxaQ58JcGo1aSJmuBQsTHr3vMwh`, pero `getTransaction` devolvió `null` para esa firma. Una repetición inmediata con la firma `4P7kX4vy9gqfdCnfiZAe7D4erVHNUUjGT4eRfvrpNuqBm8RJa9dMoeyrurCFqxRMphQQSTzFFcmukG3MaeKW1Pcp` también falló la recuperación tras reinicio. Por ello **persistencia Localnet Nivel B = PENDING/FAIL**, y ningún reporte afirma que la firma sea recuperable después del reinicio. El primer intento de retención prolongada terminó además con `No space left on device` en RocksDB; se liberaron solo los directorios `/tmp` creados por esta tarea, preservando el reporte público.

La IDL de referencia está en `tools/integration/localnet/aerosettle-idl.json`. `anchor idl build` se intentó con Anchor CLI 1.2.0 y falló con `Multiple error definitions are not allowed`; la snapshot se validó contra discriminadores y orden de cuentas, y el runner vuelve a comprobar discriminadores al construir instrucciones. La IDL no cambia layouts por el atributo `dup`. La generación directa de la IDL sigue pendiente de resolver en la toolchain, sin alterar definiciones de errores ajenas a CON-34.

## Matriz de aceptación

| Prueba | Nivel | Resultado |
|---|---|---|
| SD-01..07 owner y montos, incluido excedente | UNIT y SIMULATED_ONCHAIN | PASS, con SBF recompilado |
| Owner distinto o mint incorrecto | SIMULATED_ONCHAIN | PASS (rechazo Anchor) |
| Payout total, cero y proporcional | REAL_LOCALNET_E2E durante ejecución | PASS, firmas en reporte histórico |
| Destino compartido inválido/válido | REAL_LOCALNET_E2E durante ejecución | Válido PASS; inválido rechazado sin código de error capturado, comprobación reforzada PENDING |
| Reconstrucción Python desde JSON-RPC | REAL_LOCALNET_E2E durante ejecución | PASS para payout total; matriz completa tras finalización no recuperable |
| Idempotencia y reapertura SQLite | REAL_LOCALNET_E2E durante ejecución | PASS para una transacción; mismo effect ID |
| Firma recuperable tras reinicio del validador | REAL_LOCALNET_E2E | **PENDING/FAIL**: `getTransaction` devolvió `null` |
| GitHub Actions | CI | Configurado; ejecución remota pendiente |

Las suites locales pasaron: Economic Ledger 190, Marketplace API 65, Funding 13, Discovery 24, Organizations 14, Governance 16, Mission 5, Paper Trading 9, Transaction SDK 10, Marketplace SDK 36, Marketplace Web 43, build web y Rust workspace offline. No se usaron Mainnet, Devnet ni fondos reales. CON-34 no está completamente aprobada hasta superar la recuperación de evidencia RPC tras reinicio y ejecutar el workflow Localnet en CI.
