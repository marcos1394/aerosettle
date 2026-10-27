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

Dos corridas previas produjeron transacciones finalizadas y conciliaciones `RECONCILED`, pero `getTransaction` devolvió `null` tras reiniciar su ledger. Esos intentos quedan como evidencia histórica fallida. El análisis posterior identificó agotamiento de disco y pérdida del bloque de la firma en RocksDB; los resultados posteriores se describen abajo. Los directorios temporales de pruebas fallidas se retiraron para liberar espacio sin modificar historiales contables.

La IDL de referencia está en `tools/integration/localnet/aerosettle-idl.json`. `anchor idl build` se intentó con Anchor CLI 1.2.0 y falló con `Multiple error definitions are not allowed`; la snapshot se validó contra discriminadores y orden de cuentas, y el runner vuelve a comprobar discriminadores al construir instrucciones. La IDL no cambia layouts por el atributo `dup`. La generación directa de la IDL sigue pendiente de resolver en la toolchain, sin alterar definiciones de errores ajenas a CON-34.

## Diagnóstico de persistencia RPC (revisión del PR #17)

Se revisaron [los comentarios técnicos del PR #17](https://github.com/marcos1394/aerosettle/pull/17#issuecomment-6429442871) y Jira CON-34 antes de modificar el runner. [Agave 4.1.2 habilita](https://github.com/anza-xyz/agave/blob/v4.1.2/validator/src/bin/solana-test-validator.rs#L459-L466) `enable_rpc_transaction_history` y metadatos extendidos en `solana-test-validator`; la falta de un flag de CLI no era la causa. El [validador de prueba crea snapshots completos cada 100 slots](https://github.com/anza-xyz/agave/blob/v4.1.2/test-validator/src/lib.rs#L1062-L1076), pero un snapshot conserva el estado bancario, no sustituye el historial de bloques y sus índices RocksDB.

En el ledger fallido, el log de Agave mostró `No space left on device` al añadir shreds a RocksDB; después `TransactionStatusService is stopping because: blockstore operation failed`. El análisis offline con `agave-ledger-tool blockstore bounds` mostró solo los slots 2930–2993, mientras la firma de liquidación había quedado finalizada en el slot 2906. La columna `transaction_status` aún tenía entradas, pero el bloque de la firma ya estaba fuera del rango disponible. Eso explica el `getTransaction: null` con el mismo genesis: el disco lleno interrumpió la escritura del historial y el bloque necesario ya no era recuperable. No se atribuye este resultado a un supuesto defecto de configuración del RPC ni se trata un snapshot como prueba de historial.

Una corrida aislada y limpia con Agave 4.1.2 confirmó la hipótesis: la firma `3cjbJhZEJQ6EGpaVb8gTa1fR7V7WdxQ12GzgXcVeZLF4AN1RJfogu4yzsUiCA1yVUYxR1kqZBmNw6G79dvyhyWsU`, finalizada en el slot 305, siguió disponible tras reiniciar exactamente el mismo ledger y genesis `5gSJSykN16MSn2Z4TYEZEiki1utd35ViNuXoEZGmZJko`. JSON-RPC devolvió `getSignatureStatuses(..., searchTransactionHistory=true)` como `finalized`, `getTransaction` en el slot 305, `getBlock` con la firma, el WorkOrder del programa y los balances SPL 0/10000000/0. `getFirstAvailableBlock` y `minimumLedgerSlot` fueron 0, y había 2.19 GB libres en el momento de la consulta. Esta prueba demuestra persistencia para **un** caso; la matriz completa y CI se registran por separado.

El runner ahora evita una expansión de array vacío que abortaba el segundo arranque en Bash 3.2, verifica espacio antes de iniciar, usa 48 ticks por slot para reducir crecimiento del ledger sin omitir finalización ni RPC, y guarda diagnósticos de `getTransaction`, status histórico, bloque, cuenta y balances antes y después. Exige igualdad de blockhash, hash SHA-256 de datos del WorkOrder, balances, hashes de evidencia y effect IDs de SQLite al reiniciar. Si falta un dato, el gate falla. El workflow de Actions acepta `pull_request` para ejecutarse desde la rama del PR, ya que `workflow_dispatch` de un archivo aún ausente en la rama principal no aparece en la interfaz de GitHub.

La matriz completa de cinco escenarios se ejecutó en un nuevo ledger Agave 4.1.2 (genesis `8JVVKuF7P7GfdWNaUMnfWwc6gL5ZYRVomajjEPwRvFyE`). Las liquidaciones total, cero, proporcional y compartida válida finalizaron en los slots 304, 569, 834 y 1297; el destino compartido con identidades distintas devolvió `SettlementInvalidCreatorRefund` sin liberar el escrow. Después del primer reinicio, los cuatro `getTransaction`, `getSignatureStatuses(searchTransactionHistory=true)` y `getBlock` dieron las firmas y slots esperados. Se reconstruyeron cuatro recibos `LIVE_RPC` y se conciliaron en SQLite. Tras un segundo reinicio del **mismo** ledger y genesis, la comparación JSON-RPC dio cero errores: mismos blockhashes, hashes de datos de WorkOrder y balances SPL. Los cuatro hashes de evidencia y effect IDs persistieron idénticos (`cmp verified-before-restart.json verified-after-restart.json` = 0); los reintentos inmediatos, concurrentes y tras reapertura de SQLite no duplicaron movimientos. El blockstore offline conservaba los slots 0–1392, con 1441 entradas en `transaction_status` y 4474 en `address_signatures`; el slot finalizado más reciente antes/después fue 1326/1398. Había 3.89/3.85 GB libres durante las consultas. La edición del runner durante la ejecución interrumpió el encadenamiento automático tras escribir el reporte; las verificaciones y dos reinicios se ejecutaron manualmente sobre ese mismo ledger. El workflow CI ejecutará la versión estable completa del runner.

Además, el runner final se ejecutó sin intervención con `CON34_SCENARIOS=full`: firma finalizada `21PXuFACZitQdrg2uXJn8HNzmR2hmRHwcbeZubQzGzdnBNvsDQfZNsTjhXakeQNH9kYEahF9W8ECd8ytsy9Tnvbq` en slot 306; RPC, conciliación `LIVE_RPC`, reapertura SQLite y comparación antes/después del reinicio pasaron. Esto comprueba el flujo automático del script; la matriz completa local se verificó sobre su ledger independiente como se describe arriba.

## Matriz de aceptación

| Prueba | Nivel | Resultado |
|---|---|---|
| SD-01..07 owner y montos, incluido excedente | UNIT y SIMULATED_ONCHAIN | PASS, con SBF recompilado |
| Owner distinto o mint incorrecto | SIMULATED_ONCHAIN | PASS (rechazo Anchor) |
| Payout total, cero y proporcional | REAL_LOCALNET_E2E | PASS: slots 304, 569, 834; balances SPL exactos |
| Destino compartido inválido/válido | REAL_LOCALNET_E2E | PASS: `SettlementInvalidCreatorRefund` sin drenaje; válido finalizado slot 1297 |
| Reconstrucción Python desde JSON-RPC | REAL_LOCALNET_E2E | PASS: cuatro recibos `LIVE_RPC`, hashes y montos coincidentes |
| Idempotencia y reapertura SQLite | REAL_LOCALNET_E2E | PASS: cuatro effect IDs estables, reintentos inmediatos y concurrentes |
| Firmas recuperables tras reinicio del validador | REAL_LOCALNET_E2E | PASS local: cuatro `getTransaction`, status histórico, bloques, cuentas y balances, mismo genesis |
| GitHub Actions | CI | PENDING: workflow habilitado en el PR; falta ejecución remota satisfactoria |

Las suites locales pasaron: Economic Ledger 190, Marketplace API 65, Funding 13, Discovery 24, Organizations 14, Governance 16, Mission 5, Paper Trading 9, Transaction SDK 10, Marketplace SDK 36, Marketplace Web 43, build web y Rust workspace offline. No se usaron Mainnet, Devnet ni fondos reales. CON-34 no está completamente aprobada hasta obtener un run satisfactorio del workflow Localnet E2E en GitHub Actions.
