# CON-27 — Agent Budget Policy Management

## Auditoría AS-IS

- `EconomicLedger` ya conserva movimientos, asientos de partida doble, costos, reservas contables y conciliaciones. `agent_reserves` y `reserve_transactions` son la fuente de reserva real; `get_economic_summary()` es la fuente del disponible y las obligaciones. La política no llama a ningún mutador contable.
- Marketplace Discovery aporta `AgentAccount` con `agent_account`, `agent_id` y `owner`. La API consulta el snapshot actual para autorizar al propietario. No existe un administrador delegado comprobable.
- CON-26 ya usa desafíos Ed25519 para lecturas privadas. Ese desafío no firma el contenido de una mutación; CON-27 incorpora el dominio `conatus:budget-policy-mutation:v1` con cuenta, propietario, método, ruta, SHA-256 del JSON canónico, timestamp, nonce, idempotency key y versión esperada.
- `schema.py` aplica migraciones SQLite numeradas y atómicas; la migración 009 agrega exclusivamente tablas de política. El lector de migraciones admite sentencias `CREATE TRIGGER` completas.
- Sólo cambian rutas restringidas de Marketplace API, su OpenAPI, métodos tipados del SDK y un panel en Agent Detail. La ingestión económica general sigue sin métodos de escritura.

## Modelo y garantías

Existe una política por `agent_account`, vinculada al propietario y a la identidad del agente que se observaron al crearla. Las versiones son monotónicas y conservan estado, reglas por mint, destinatarios, vigencia, autor, motivo, acción, hash y claves de idempotencia. Las reglas monetarias son cadenas decimales u64 exactas; no hay conversión entre mints. SQLite impide modificar o borrar versiones, reglas y destinatarios históricos. Sólo cambia el puntero `current_version` de la tabla principal.

Las mutaciones se validan y se guardan con `BEGIN IMMEDIATE`, control de versión esperada, nonce único e idempotencia estricta. Una firma válida del propietario actual es obligatoria. La API vuelve a consultar el registro del agente antes de escribir y rechaza un cambio de propietario o de identidad. Si la propiedad cambia después de existir la política, el acceso y las mutaciones se cierran hasta que exista un procedimiento de transferencia de titularidad verificable.

`DRAFT` puede activarse; `ACTIVE` puede pausarse; `PAUSED` puede reactivarse; `REVOKED` es final. `EXPIRED` se calcula por tiempo y nunca se presenta como vigente. Una política vencida puede editarse como nuevo borrador; su activación requiere una fecha futura. No hay autorización implícita si faltan reglas activas o destinatarios.

La comparación de reservas presenta por mint el mínimo configurado, la reserva contable existente, la brecha y los valores disponibles y de obligaciones cuando el ledger tiene un resumen. El objetivo de reserva **no asigna fondos**, y la comparación no trata escrow ni tokens on-chain como capital libre.

## Límite de CON-27

Este módulo administra configuración off-chain. No decide `ALLOW`, `DENY` ni `REQUIRE_APPROVAL`, no aplica presupuestos a WorkOrders, no bloquea tokens y no ejecuta pagos. CON-28 deberá evaluar propuestas económicas contra una versión y hash de política concretos, el propietario vigente y el ledger del mismo contexto monetario. Los destinatarios por activo y la delegación administrativa requieren diseño y verificación posteriores.
