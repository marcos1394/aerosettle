# CON-25 — Solvency Engine

## Auditoría AS-IS

El Economic Ledger de CON-22 ya contiene movimientos, asientos dobles y saldos por `agent_account + network + genesis_hash + program_id + token_mint`. CON-23 aporta conciliación SPL finalizada con hash de evidencia y distingue `LIVE_RPC`, `HISTORICAL_FIXTURE` y `SYNTHETIC_TEST`. CON-24 aporta costos con atestación, obligaciones devengadas, reservas contables, CAPEX y resumen económico. El servidor Marketplace aplica autorización Ed25519 del propietario. Atlas alimenta las vistas de ejemplo; `ProvenanceBadge` ya distingue datos simulados. Se reutilizaron todos esos componentes. No se creó otro ledger ni reconciliador.

La referencia `master` local al iniciar estaba obsoleta. El `master` remoto sí contiene CON-21 a CON-24 por el merge de CON-24 (`6f23989`). La rama CON-25 se alinea con ese commit antes de publicar.

## Motor y metodología

`solvency.py` lee el ledger sin consultar RPC ni alterar asientos. Cada resultado pertenece a una identidad monetaria completa. Las ventanas usan segundos Unix UTC `[window_start, window_end)`. Los ingresos se ubican por `observed_at`, los costos por `incurred_at`; `economic_period` solo es una etiqueta. La evaluación usa el estado de verificación visible al calcularla, incluso si la conciliación ocurrió después del evento económico.

Se suman ingresos `INCOME` conciliados con evidencia de reconciliación. El gasto operativo cuenta costos `REALIZED` atestados, conciliados y respaldados por un movimiento vigente. Se excluyen provisionales, reversados, estimaciones, depreciación no monetaria, reservas y CAPEX. Las obligaciones devengadas se muestran aparte; no entran de nuevo al OPEX cuando se pagan como costo realizado. El ratio es ingresos verificados / OPEX verificado. El margen operativo es `(ingresos - OPEX) / ingresos`, el excedente operativo es la diferencia exacta en unidades base. Los cocientes se truncan a ocho decimales; no se redondean montos antes de dividir.

Para afirmar cobertura completa, **ambos lados** requieren una atestación independiente para la misma ventana y contexto monetario vinculada a un **canonical data digest**. `record_coverage` es un punto de ingestión interno que exige un `CoverageVerifier` (no admite callables arbitrarios). El ledger no trae una prueba de exhaustividad para una ventana arbitraria. Hasta integrar un verificador real de cobertura, los datos existentes producen `INSUFFICIENT_DATA`, aunque los importes individuales estén conciliados. Esto evita convertir ausencia de registros en cero comprobado.

## Hardening de Cobertura y Procedencia

### 1. Snapshots inmutables y Data Digest canónico
`calculate_side_data_digest()` genera un digest SHA-256 canónico y determinista (`conatus-solvency-data-digest-v1`) sobre todos los registros económicos relevantes (tanto elegibles como excluidos: provisionales, estimados, no verificados, devengos y reversiones) dentro de `[window_start, window_end)`.
- Si se agrega un nuevo gasto o ingreso posterior a la atestación, si un ingreso provisional se concilia tardíamente, si ocurre una reversión o si se altera un hash de evidencia, el digest recalculado en `assess_agent()` difiere del almacenado en `solvency_coverage`.
- Ante cualquier discrepancia de digest o digest faltante, la evaluación arroja inmediatamente `INSUFFICIENT_DATA` (nunca `VALID`).
- Las coberturas con cero eventos tienen un digest canónico reproducible sobre una lista vacía; cualquier movimiento posterior invalida dicha cobertura.
- Los snapshots guardados en `agent_solvency_assessments` son inmutables (`INSERT OR IGNORE`) y nunca se sobrescriben.

### 2. Frontera de confianza y Verificación Criptográfica Productiva (Gate 1 & Gate 2)
- **Verificación Criptográfica Ed25519 Estándar y Mantenida**: Reemplazo de operaciones manuales sobre curvas elípticas en código de producción por la biblioteca estándar `cryptography.hazmat.primitives.asymmetric.ed25519` (RFC 8032). `ProductionCoverageVerifier` exige una clave pública Ed25519 confiable registrada para cada autoridad habilitada. Decodifica y verifica matemáticamente la firma Ed25519 contra los bytes serializados de `canonical_coverage_message()`. Cero operaciones manuales sobre curvas en producción.
- **Vinculación Canónica y Separación de Dominio**: El mensaje firmado vincula deterministamente `"domain": "conatus:solvency-coverage-attestation:v1"`, agente, contexto monetario (`network`, `genesis_hash`, `program_id`, `token_mint`), ventana UTC `[window_start, window_end)`, lado (`REVENUE`/`OPEX`), `data_digest`, `evidence_hash`, `verifier_id`, `provenance_type` y `expires_at`.
- **Caducidad y Política de Revocación**: Las coberturas expiran matemáticamente si `now > expires_at` o por TTL configurable. Las autoridades pueden ser revocadas explícitamente (`revoke_authority`); cualquier cobertura asociada a una autoridad revocada o expirada falla cerrado.
- **Revalidación y Selección Multicandidato**: Durante `assess_agent()`, no se asume validez de coberturas por el mero hecho de residir en la base de datos. Se revalidan criptográficamente contra el verificador activo. Ante múltiples registros para una misma ventana, se itera y selecciona únicamente una cobertura auténtica, no expirada, no revocada y con digest coincidente, sin depender ciegamente del orden temporal de inserción.
- **Fail-Closed y Protección contra Promoción Sintética**: `ProductionCoverageVerifier` rechaza tajantemente `SYNTHETIC_TEST` e `HISTORICAL_FIXTURE`. Cerrar y reabrir la base SQLite sin inyectar verificadores de prueba activa por defecto el verificador productivo sin claves confiables, retornando `INSUFFICIENT_DATA` ante cualquier intento de simular verificación productiva.

### 3. Procedencia persistente y linaje de evidencia inmutable
La procedencia nunca depende de clases Python en memoria ni se infiere ciegamente de `provenance_source=ONCHAIN_VERIFIED`:
- **Taxonomía Canónica de 5 Niveles**: Se distingue explícitamente `LIVE_RPC`, `EXTERNAL_ATTESTED`, `HISTORICAL_FIXTURE`, `SYNTHETIC_TEST` e `HISTORICAL_UNVERIFIED`.
- Cada movimiento y cada costo almacena de forma inmutable su `evidence_lineage` en columnas dedicadas (`economic_movements.evidence_lineage` y `agent_costs.evidence_lineage`) y dentro de `metadata_json`.
- En modo productivo, una evaluación falla cerrado a `INSUFFICIENT_DATA` si cualquiera de sus ingresos o costos subyacentes tiene linaje sintético (`SYNTHETIC_TEST`), de fixture (`HISTORICAL_FIXTURE`), o no verificado (`HISTORICAL_UNVERIFIED`). Ni siquiera una firma Ed25519 válida sobre la cobertura puede promover fixtures económicos a evidencia productiva.
- En modo de prueba explícito (`IsolatedTestCoverageVerifier`), las evaluaciones matemáticas son admisibles pero preservan de forma estricta e inmutable `provenance = "SYNTHETIC_TEST"`.
- Con verificadores productivos auténticos (`ProductionReconciliationVerifier` y `ProductionAttestationVerifier`), los registros adquieren `LIVE_RPC` y `EXTERNAL_ATTESTED`, alcanzando la procedencia plena `LIVE_RPC_AND_EXTERNAL_ATTESTED`.
- `agent_solvency_assessments` almacena `provenance_type` en columna dedicada y dentro de `result_json`.

### 4. Migraciones 007 y 008
- `007_solvency_coverage_digest_and_provenance.sql`: añade incrementalmente `data_digest`, `provenance_type`, `authority_pubkey` y `signature` a `solvency_coverage`, y `provenance_type` a `agent_solvency_assessments`. Los registros históricos sin digest verificable quedan como `HISTORICAL_UNVERIFIED`.
- `008_evidence_lineage_and_authentic_provenance.sql`: añade la columna inmutable `evidence_lineage TEXT NOT NULL DEFAULT 'HISTORICAL_UNVERIFIED'` a `economic_movements` y `agent_costs`, backfilleando linajes históricos desde `metadata_json`.

## Ejemplos con verificadores de prueba

| Ingresos | OPEX | Cobertura | Estado | Ratio | Clase |
|---:|---:|---|---|---:|---|
| 100 | 50 | Ambas partes atestadas con digest válido | VALID | 2.00000000 | THRIVING |
| 50 | 100 | Ambas partes atestadas con digest válido | VALID | 0.50000000 | AT_RISK |
| 100 | 0 | Ambas partes atestadas con digest válido | UNDEFINED_RATIO | — | UNDETERMINED |
| 100 | 50 | Sin atestación o con digest mismatch | INSUFFICIENT_DATA | — | UNDETERMINED |

USDC y EURC, o dos redes/génesis/programas, se evalúan por separado. No hay conversión FX ni ratio de flota verificado. Economy, Fleet y perfiles Atlas siguen mostrando una simulación explícita; el perfil real consulta la API con firma del propietario.

## Evidencia y límites

Las pruebas automáticas usan `IsolatedTestReconcilerVerifier`, `IsolatedTestAttestationVerifier` y `IsolatedTestCoverageVerifier`. **No son liquidaciones verificadas contra una blockchain viva.** `provenance` distingue de forma persistente esos resultados como `SYNTHETIC_TEST` (o `HISTORICAL_FIXTURE`). La integración E2E contra Solana, la fuente productiva de atestaciones de cobertura, la liquidación contable de obligaciones previamente devengadas y la valoración verificable de activos fijos quedan pendientes. Por eso no se afirma patrimonio verificado ni rentabilidad futura.
