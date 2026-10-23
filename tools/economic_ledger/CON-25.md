# CON-25 — Solvency Engine

## Auditoría AS-IS

El Economic Ledger de CON-22 ya contiene movimientos, asientos dobles y saldos por `agent_account + network + genesis_hash + program_id + token_mint`. CON-23 aporta conciliación SPL finalizada con hash de evidencia y distingue `LIVE_RPC`, `HISTORICAL_FIXTURE` y `SYNTHETIC_TEST`. CON-24 aporta costos con atestación, obligaciones devengadas, reservas contables, CAPEX y resumen económico. El servidor Marketplace aplica autorización Ed25519 del propietario. Atlas alimenta las vistas de ejemplo; `ProvenanceBadge` ya distingue datos simulados. Se reutilizaron todos esos componentes. No se creó otro ledger ni reconciliador.

La referencia `master` local al iniciar estaba obsoleta. El `master` remoto sí contiene CON-21 a CON-24 por el merge de CON-24 (`6f23989`). La rama CON-25 se alinea con ese commit antes de publicar.

## Motor y metodología

`solvency.py` lee el ledger sin consultar RPC ni alterar asientos. Cada resultado pertenece a una identidad monetaria completa. Las ventanas usan segundos Unix UTC `[window_start, window_end)`. Los ingresos se ubican por `observed_at`, los costos por `incurred_at`; `economic_period` solo es una etiqueta. La evaluación usa el estado de verificación visible al calcularla, incluso si la conciliación ocurrió después del evento económico.

Se suman ingresos `INCOME` conciliados con evidencia de reconciliación. El gasto operativo cuenta costos `REALIZED` atestados, conciliados y respaldados por un movimiento vigente. Se excluyen provisionales, reversados, estimaciones, depreciación no monetaria, reservas y CAPEX. Las obligaciones devengadas se muestran aparte; no entran de nuevo al OPEX cuando se pagan como costo realizado. El ratio es ingresos verificados / OPEX verificado. El margen operativo es `(ingresos - OPEX) / ingresos`, el excedente operativo es la diferencia exacta en unidades base. Los cocientes se truncan a ocho decimales; no se redondean montos antes de dividir.

Para afirmar cobertura completa, **ambos lados** requieren una atestación independiente para la misma ventana y contexto monetario. `record_coverage` es un punto de ingestión interno que exige un verificador externo; no existe endpoint público que cree coberturas. El ledger actual no trae una prueba de exhaustividad para una ventana arbitraria. Hasta integrar un verificador real de cobertura, los datos existentes producen `INSUFFICIENT_DATA`, aunque los importes individuales estén conciliados. Esto evita convertir ausencia de registros en cero comprobado.

Los estados son `VALID`, `INSUFFICIENT_DATA`, `UNDEFINED_RATIO`, `STALE_DATA`, `MIXED_ASSET_CONTEXT` y `ERROR`. Los fallos de integridad al calcular un contexto producen `ERROR` sin importes ni ratio; si falla el acceso a la base antes de identificar contextos, la API devuelve un error HTTP. `VALID` exige ambas coberturas y valores elegibles; denominador cero da `UNDEFINED_RATIO`. En la ventana actual, evidencia más antigua que siete días da `STALE_DATA`. Una petición consolidada entre identidades distintas da `MIXED_ASSET_CONTEXT` sin ratio. Clasificación configurable: `<1` AT_RISK, `[1,1.6)` STABLE, `>=1.6` THRIVING; cualquier ratio inválido es UNDETERMINED.

La liquidez disponible reutiliza el saldo conservador de tesorería de CON-24: débitos conciliados menos todos los créditos. Esto contempla reservas, pagos, transferencias y CAPEX, sin tratar ingresos provisionales como caja. El capital líquido elegible resta obligaciones devengadas. El runway divide ese capital entre OPEX monetario diario realizado; con gasto cero queda indefinido. Las reservas son segregaciones contables off-chain, no tokens bloqueados. El patrimonio verificado permanece `null` porque el modelo actual no verifica de forma uniforme el valor de todos los activos y pasivos; se expone separado el valor contable provisional.

`006_agent_solvency_assessments.sql` almacena solo atestaciones de cobertura y snapshots de resultados. Cada snapshot conserva período, versiones, hash de entradas y referencias consultables. `GET /solvency` calcula y guarda un snapshot idempotente; `/history` lee los snapshots. No se duplican asientos ni se mueve capital.

## Ejemplos con verificadores de prueba

| Ingresos | OPEX | Cobertura | Estado | Ratio | Clase |
|---:|---:|---|---|---:|---|
| 100 | 50 | Ambas partes atestadas | VALID | 2.00000000 | THRIVING |
| 50 | 100 | Ambas partes atestadas | VALID | 0.50000000 | AT_RISK |
| 100 | 0 | Ambas partes atestadas | UNDEFINED_RATIO | — | UNDETERMINED |
| 100 | 50 | Sin atestación de cobertura | INSUFFICIENT_DATA | — | UNDETERMINED |

USDC y EURC, o dos redes/génesis/programas, se evalúan por separado. No hay conversión FX ni ratio de flota verificado. Economy, Fleet y perfiles Atlas siguen mostrando una simulación explícita; el perfil real consulta la API con firma del propietario.

## Evidencia y límites

Las pruebas automáticas usan `IsolatedTestReconcilerVerifier`, `IsolatedTestAttestationVerifier` y un verificador de cobertura de fixture. **No son liquidaciones verificadas contra una blockchain viva.** `provenance` distingue esos resultados como `TEST_VERIFIER_FIXTURE`. La integración E2E contra Solana, la fuente productiva de atestaciones de cobertura, la liquidación contable de obligaciones previamente devengadas y la valoración verificable de activos fijos quedan pendientes. Por eso no se afirma patrimonio verificado ni rentabilidad futura.
