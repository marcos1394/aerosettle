# CON-31 — Laboratorio de simulación aislado

## Auditoría AS-IS y reutilización

Revisado el 24 de octubre de 2026 sobre `origin/master` en `0f98a4f` (merge de CON-30). `EconomicLedger` y `schema.py` mantienen el libro contable y las migraciones 001–011; no se agregaron tablas paper a ese migrador. `solvency.py` y `investible_surplus.py` conservan las fuentes y límites de CON-25/CON-30. `BudgetPolicyStore` aporta identidad y contexto de política actual; CON-28 y CON-29 conservan sus claims y consentimientos, sin ser consumidos como autorización financiera. `server.py` aporta autenticación de lectura Ed25519 y validación del AgentAccount; el POST paper usa un dominio de firma separado. `openapi_spec.py`, Marketplace SDK y los paneles de agente son las extensiones de presentación. Atlas sigue siendo un origen visual simulado y no entra al motor. No se tocaron contratos Anchor ni settlement.

## Fronteras y arquitectura

1. `simulator.py` es cálculo puro: enteros exactos, sin reloj, I/O, SQLite ni RPC. El precio es una fracción racional; compra redondea costos hacia arriba, venta redondea ingresos hacia abajo. Un fill parcial usa búsqueda binaria para no exceder efectivo ficticio ni límites de riesgo.
2. `providers.py` define interfaces **solo de lectura** para instrumentos, cotización, liquidez y costos. `DeterministicFixtureProvider` devuelve dos instrumentos spot con el mismo símbolo pero IDs y mercados distintos. Cada snapshot está marcado `FIXTURE` y `OFFLINE_FIXTURE`. `LocalPaperExecutionAdapter.simulate_fill()` invoca únicamente el motor puro. No existe método de órdenes reales, URL configurable, credencial de broker ni adaptador HTTP. `NETWORK_ENABLED=False`.
3. `store.py` usa `paper_trading.sqlite`, físicamente distinto del Economic Ledger. Persiste solicitud, snapshot de mercado y resultado con hashes e historial inmutable. El POST exige firma Ed25519 del propietario actual sobre `conatus:paper-simulation:v1`, cuerpo completo, presupuesto, escenario, ruta, timestamp, nonce e idempotency key. Lectura e idempotencia exigen identidad exacta. La política vigente se usa solo para validar contexto, nunca para transferir o reservar fondos.
4. La API, el SDK y `PaperTradingLab` exhiben exclusivamente datos paper; el SDK rechaza respuestas que anuncien ejecución, capital real o procedencia productiva. La UI muestra el presupuesto ficticio aparte de la economía CON-30 y usa wallet solo para firmar la solicitud paper, no una transacción.

## Metodología

`paper_budget_base_units_str` y `funding_source` son explícitos. Actualmente solo se habilita `MANUAL_PAPER_ALLOCATION`. `CON30_HYPOTHETICAL_SCENARIO` queda reservado hasta poder vincular y verificar una evaluación concreta; se rechaza para no atribuir una procedencia inexistente. No se lee automáticamente `available_balance`, `estimated_investible_surplus`, `ALLOW` ni `APPROVED` para generar el presupuesto. Toda respuesta devuelve `is_paper=true`, `is_executable=false`, `real_capital_authorized=false`.

El fixture spot usa precio de 100 o 105 unidades base de la divisa cotizada por unidad ficticia, fee de 100 bps, spread de 0 bps, slippage de 50 bps y profundidad de 1000 unidades ficticias. Estos valores **no son precios de mercado**. Una compra de 10 unidades en ALPHA contra presupuesto ficticio de 1000 cuesta 1015 y se reduce explícitamente a 9 unidades por 914, con 86 remanentes, si se permite fill parcial; con fill completo requerido se rechaza. BASE, DOWNSIDE y STRESS aplican shocks deterministas declarados, sin inferir probabilidades ni rendimientos esperados. Los costos de salida también se descuentan de manera conservadora.

Reinversión productiva compara preservar liquidez, hardware y reemplazo a partir de CAPEX, OPEX, mantenimiento, vida útil, utilización y capacidad declarados. Un cambio en capacidad no se convierte en ingreso. El plazo de recuperación es `INSUFFICIENT_ASSUMPTIONS` si no se proporciona beneficio monetario mensual explícito. No se registra depreciación como salida de efectivo. No hay FX automático: la moneda de cotización, el mint de tesorería paper y la moneda de alternativas deben coincidir. Un mint localnet no hereda valor de un token productivo.

## Limitaciones

- No se conectan servicios externos. Los fixtures se datan al instante explícito de la simulación y su procedencia siempre es `FIXTURE`; la frescura es interna al escenario, no una cotización externa.
- No hay trading real, liquidez exigible, custodia, wallet de firma financiera, promesa de rendimiento ni recomendación personalizada.
- El portafolio de cada run es un snapshot ficticio inicial, no una secuencia de órdenes reales o una posición transferible. El historial es auditable y siempre paper.
- La UI incluye supuestos ilustrativos visibles y editables. Ausencia de un supuesto de beneficio deja payback indeterminado.
- CON-34 y revisiones jurídicas, regulatorias, de seguridad, custodia y elegibilidad comercial son requisitos separados para considerar cualquier integración productiva.

## Evidencia de aislamiento

Las pruebas comparan hashes de **contenido completo**, no solo conteos, de `economic_movements`, `journal_entries`, `ledger_entries`, `agent_costs`, `agent_reserves`, `reserve_transactions`, `spending_proposals`, `spending_decisions`, `spending_budget_claims`, `spending_approvals` y `spending_approval_events` antes y después de un run. Se prueban firma alterada, identidad cambiada, nonces, diez reintentos concurrentes, reinicio SQLite, precisión u64, stale quote, presupuesto, prohibición de short/leverage, fixtures sin credenciales y variable de broker live ignorada.
