# CON-29 — Auditoría y consentimiento humano de gastos

## Auditoría AS-IS previa

- CON-28 conserva una sola propuesta en `spending_proposals` y una decisión inmutable en `spending_decisions`. El payload canónico, `proposal_hash`, `decision_json` y `economic_snapshot_hash` permiten vincular el consentimiento al contenido exacto sin crear una segunda propuesta ni recalcular el resultado.
- Discovery proyecta `owner` y `signing_authority` del `AgentAccount` on-chain. La primera clave es la única que puede administrar consentimiento; la segunda sólo puede solicitar evaluaciones CON-28. Una lectura o mutación falla si la identidad actual no coincide con `agent_account`, `agent_id` y propietario registrados.
- `BudgetPolicyStore.current()` valida identidad y devuelve versión/hash vigente. CON-29 coteja la referencia de la decisión con esa política para abrir o aprobar, y mantiene el historial cuando la política cambia.
- El ledger conserva resumen, costos, reservas y linaje económico. `SpendingDecisionStore._applicable()` comprueba procedencia `VERIFIED`, integridad/completitud del snapshot, política y claim vigente. CON-29 lo reutiliza para informar elegibilidad; el consentimiento no convierte `REQUIRE_APPROVAL` o `SYNTHETIC_TEST` en solvencia verificada.
- Las consultas privadas existentes usan desafío Ed25519 ligado al AgentAccount. Las mutaciones de política usan firma del owner. CON-29 emplea un dominio nuevo y liga firma, cuerpo, ruta, acción y referencias económicas. El historial queda en eventos append-only con cadena de hashes.
- La verificación RPC/SPL y la cobertura económica productiva siguen pendientes de CON-34. Una aprobación es off-chain y siempre `is_executable=false`; no escribe movimientos, reservas ni claims.

## Modelo y límites

Una revisión por decisión comienza `PENDING_REVIEW`. Un evento `APPROVE` o `REJECT` la cierra; sólo `APPROVED` admite `REVOKE`. `EXPIRED` se deriva de la hora sin cambiar el evento. El estado histórico y la elegibilidad económica son campos distintos. Aun con consentimiento vigente, una decisión `REQUIRE_APPROVAL` o sintética tiene `NOT_EXECUTION_ELIGIBLE`.

La mutación usa `BEGIN IMMEDIATE`; propuesta, decisión y política se vuelven a comprobar dentro de esa transacción. La clave idempotente y nonce son únicos. Los eventos y la revisión base no se editan ni borran. La revocación posterior al vencimiento sigue permitida para dejar constancia administrativa.

## Implementación y resultado

La migración 011 añade una revisión inmutable por decisión y eventos `OPEN`, `APPROVE`, `REJECT` y `REVOKE`. Cada evento conserva firma Ed25519, mensaje y cuerpo canónicos, hash del mensaje, hash del evento y vínculo con el hash anterior. La lectura verifica firma, cuerpo y cadena. `EXPIRED` se deriva de la hora; no reescribe el histórico.

El servidor comprueba el owner actual en Discovery, la firma de cada mutación, el contenido persistido de CON-28 y la política vigente. El SDK reproduce los mismos bytes de desafío que Python. Agent Detail ofrece una revisión privada del owner y explica que el consentimiento no verifica fondos ni ejecuta pagos. Los seis grupos de tablas financieras y `spending_budget_claims` permanecen intactos por acciones de consentimiento.

`APPROVED` describe consentimiento humano. `financial_eligibility` sólo indica si una evaluación `ALLOW` productiva sigue aplicable bajo las reglas CON-28; `is_executable` siempre es `false`. Con la infraestructura económica actual, las evaluaciones productivas siguen sin prueba suficiente y no generan elegibilidad de ejecución. La integración Solana RPC/SPL y la transferencia administrativa de políticas permanecen fuera de CON-29.
