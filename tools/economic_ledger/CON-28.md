# CON-28 — Motor determinista de evaluación de gastos

## Auditoría AS-IS previa a la implementación

- CON-27 almacena una política por `agent_account` y versiones inmutables en SQLite. `BudgetPolicyStore.current()` valida `agent_account`, `agent_id`, propietario y `policy_id` derivado antes de devolverla. El evaluador utilizará esa versión y su hash, sin duplicar reglas o mutaciones de políticas.
- Discovery decodifica el `AgentAccount` on-chain. El IDL real contiene `owner` y `signing_authority`; el snapshot público aún no los exponía. CON-28 añadirá esos campos sólo cuando estén presentes y sean claves válidas. Sin propietario verificable, ninguna evaluación se autentica. La autoridad de dispositivo puede pedir una evaluación firmada, nunca autorizar un pago.
- `get_economic_summary()` calcula `available_balance` desde débitos reconciliados y créditos de `ASSET:TREASURY`. El traslado a `ASSET:RESERVED:*` ya reduce ese disponible. `total_obligations_accrued` registra pasivos no pagados; `agent_reserves` y `reserve_transactions` conservan la reserva contable. Escrow y CAPEX son magnitudes separadas. Los costos `REALIZED`, `ESTIMATED` y `ACCRUED_LIABILITY` no son intercambiables.
- Movimientos y costos tienen estado y `evidence_lineage`. Los verificadores productivos SPL y de atestación permanecen cerrados hasta CON-34; una forma válida de firma, un ID o un fixture no prueban procedencia económica. El motor productivo no considerará completa la historia diaria ni la liquidez sin una fuente auténtica de cobertura. Por ello devuelve `REQUIRE_APPROVAL` si no hay rechazo concluyente de política. El modo `SYNTHETIC_TEST` es explícito y aislado.
- `schema.py` aplica migraciones numeradas en transacciones SQLite. CON-28 añadirá sólo la migración 010 para propuestas, decisiones y compromisos administrativos; no toca migraciones 001–009 ni tablas financieras. `BEGIN IMMEDIATE` serializa evaluaciones y evita dos claims simultáneos sobre la misma capacidad.

## Precedencia y capacidad

La función pura procesa primero violaciones concluyentes de política (`DENY`), luego incertidumbre económica (`REQUIRE_APPROVAL`) y sólo después condiciones verificadas (`ALLOW`). Las razones se emiten en un orden fijo. Ningún texto libre de `purpose` o `metadata` modifica las reglas.

La ventana diaria es `[00:00:00 UTC, 00:00:00 UTC siguiente)`. Consumo realizado y claims se filtran por agente, red, génesis, programa y mint. Costos ligados a un movimiento no se suman dos veces. Un claim se cuenta sólo mientras no haya expirado y siga asociado a la versión vigente. Sin enlace comprobable con un pago ejecutado, puede superponerse temporalmente al costo contabilizado: se conserva el claim hasta su vencimiento, de forma conservadora.

El disponible contable ya excluye reservas asignadas. La capacidad segura adicional se calcula como `max(0, disponible - obligaciones_devengadas - max(0, reserva_mínima_de_política - reserva_contable) - claims_vigentes)`. No se descuenta nuevamente la reserva contable ni se suma escrow. Un `ALLOW` crea sólo un claim administrativo temporal, nunca una reserva del ledger ni una instrucción Solana. La aplicabilidad de una decisión anterior se recalcula al consultar/reintentar y se pierde por expiración, cambio de política o de identidad.

## Límite de confianza

La salida siempre declara `is_executable: false`. `ALLOW` significa elegibilidad consultiva bajo el snapshot, sin firma de transferencia ni consentimiento final. `REQUIRE_APPROVAL` no implementa un flujo de aprobación. La integración auténtica RPC/SPL y atestación sigue en CON-34. No hay ejecución de pagos ni cambios al ciclo WorkOrder.

La aplicabilidad actual exige evidencia `VERIFIED`, snapshot persistido íntegro y completo, política vigente y claim no vencido. Los `ALLOW` de `SYNTHETIC_TEST`, `HISTORICAL_FIXTURE` y `HISTORICAL_UNVERIFIED` siguen visibles en auditoría, pero siempre se consultan como no aplicables, incluso tras reiniciar SQLite. Un claim administrativo nunca certifica procedencia económica.
