# CON-44 — Agent-to-Agent x402 V2 Sandbox Payments

## Auditoría AS-IS y dependencias

Esta rama parte de `origin/master` en `0f928e45e263b3f445fbc42552550ba99a4e031f`, merge de CON-43. CON-27 ya ofrece políticas versionadas y segregadas por AgentAccount; CON-28 ofrece decisiones deterministas y un ledger sin permisos generales de escritura; CON-29 ofrece firmas Ed25519 y cadena de auditoría para consentimientos humanos. CON-42 es un runtime asesor sin credenciales económicas. CON-43 produce una intención de negociación off-chain, que no se convierte aquí en pago. CON-35 aporta el mint SPL de prueba verificado y el genesis Devnet. CON-39 aporta los pins independientes del programa y genesis. CON-40 mantiene MCP de solo lectura. Los componentes de WorkOrder, SDK de transacciones y Anchor no se modifican.

Los riesgos principales eran confundir un `ALLOW` administrativo con permiso de pago, reutilizar un recibo de otra API, anunciar `exact` SVM real sin liquidarlo, aceptar un facilitador no confiable, y promover una simulación a `LIVE_RPC`. El módulo nuevo mantiene otra base SQLite y nunca escribe en el ledger de movimientos ni construye instrucciones Solana.

## Protocolo, SDK y semántica

Se fijó la [especificación x402 V2](https://github.com/x402-foundation/x402/blob/main/specs/x402-specification-v2.md) y el SDK Python oficial `x402==2.27.0` (modelos `PaymentRequired`, `PaymentPayload`, `VerifyResponse`, `SettleResponse`, `SupportedResponse` y codificadores/decodificadores HTTP). La versión se verificó en PyPI el 7 de noviembre de 2026. El repositorio oficial publicaba `@x402/core` y `@x402/svm` 2.30.0 en npm, pero no se instala `@x402/svm` en este gate: sus esquemas `exact` verdaderos forman o liquidan autorizaciones Solana y esta historia prohíbe ambas operaciones. No se declara soporte para `exact` real.

El flujo usa los tres encabezados V2 oficiales, con objetos base64 serializados por el SDK: `PAYMENT-REQUIRED`, `PAYMENT-SIGNATURE` y `PAYMENT-RESPONSE`. `X-PAYMENT` y `X-PAYMENT-RESPONSE` son rechazados. `GET /supported`, `POST /verify` y `POST /settle` usan los modelos V2. El esquema declarado es **`conatus-sandbox-exact`**, una implementación aislada de simulación dentro de la extensibilidad de x402 V2; el campo `extra.simulationOnly=true` impide presentarla como esquema SPL `exact` interoperable de producción. Un cliente x402 estándar sin ese esquema debe rechazarla. El HTTP V2 sí usa los contratos del SDK oficial; la liquidación SPL real y la interoperabilidad con facilitadores `exact` quedan pendientes de otra etapa aprobada.

`/verify` no inserta estado. `/settle` inserta solamente el recibo simulado en SQLite. Su `SettleResponse.success=true` significa éxito **del settlement simulado**, con `transaction=""`, extensión `simulationOnly=true` y un recibo firmado que dice `settlement_status=SIMULATED`, `evidence_source=SANDBOX_SIMULATION`, `transaction_signature=null`, `commitment=null`. Ninguna parte lo interpreta como finalización JSON-RPC.

## Identidad, condiciones y autorización

La red en el wire es el CAIP-2 Devnet `solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1`. El genesis completo fijado es `EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG`; las políticas históricas del ledger usan `solana:devnet`, y el gate traduce explícitamente entre ambas representaciones. El mint `HpfaV9oRuTN1b3ktDKvJoWqUWFZ1o9VFmhejxxqQ1vyh` es exclusivamente **DEVNET_TEST_TOKEN**, de seis decimales bajo el programa SPL legacy. `Context.fixture()` comprueba el manifiesto CON-35 y el pin independiente, sin consultar RPC. Esta procedencia es `OFFLINE_FIXTURE`; la existencia actual del mint o balances no se afirma. No hay fallback a Mainnet.

El servidor firma el objeto `PaymentRequired` con una clave Ed25519 efímera y el cliente verifica la clave pública preconfigurada. La oferta firmada fija `payment_id`, nonce, recurso, URL, dos AgentAccounts, genesis, programa, mint, monto entero u64 en unidades base, destinatario, esquema, facilitador y caducidad. El cliente valida esas condiciones contra sus límites antes de producir un payload. El `PAYMENT-SIGNATURE` lleva un consentimiento Ed25519 separado del propietario **sobre todos esos términos** y una firma Ed25519 efímera del `SandboxSigner` sobre el payload de simulación; el facilitador verifica ambos contra la identidad vigente. El signer no implementa ninguna llamada Solana, no acepta transacciones y no se entrega al runtime CON-42. Las claves generadas en el ejemplo son efímeras; el secreto conocido de los tests CON-27 se usa solo como fixture offline.

`PaymentPolicyGate` usa `BudgetPolicyStore.current`, `SpendingDecisionStore.evaluate/get` y `SpendingApprovalStore.context/get/history` reales. La propuesta CON-28 incluye en `metadata` el hash de requisitos, recurso, URL, payment ID, red CAIP, destinatario y caducidad; la firma y cadena CON-29 autentican la revisión asociada. `DENY` bloquea. `REQUIRE_APPROVAL` exige una revisión CON-29 vigente y aprobada para seguir **solo en sandbox**. `ALLOW` sigue exigiendo el consentimiento independiente del propietario antes del signer. Ni el approval ni el payload sandbox conceden autoridad financiera productiva. Revocación, cambio de owner, política o condiciones fallan cerrados.

## Idempotencia, recibo y seguridad

`SandboxStore` mantiene settlement, delivery y recibos cliente en una base distinta del economic ledger. `BEGIN IMMEDIATE` y unicidad de `payment_id`, nonce, hash de requisitos, hash de payload y `receipt_id` evitan replay y doble registro con dos clientes concurrentes. Un reintento exacto recupera el mismo recibo; un valor distinto con la misma clave produce conflicto. El recibo incluye la identidad y URL del recurso, hash de requisitos, hash del payload, todos los términos monetarios y la firma Ed25519 del facilitador fijado. El hash del cuerpo del recurso queda en el registro de entrega. El cliente comprueba `PAYMENT-RESPONSE`, firma y términos antes de guardar el recibo. El recurso solo se entrega después de `/verify`, `/settle`, comprobación del recibo y registro idempotente de entrega.

Los únicos URLs permitidos son `http://127.0.0.1:<puerto>` con ruta exacta; no se resuelve DNS, no hay redirects, credenciales URL, query strings ni hosts internos alternativos. Solicitudes y respuestas están limitadas a 32 KiB y encabezados a 16 KiB; timeouts, 429, 5xx, 402 repetido o ausencia del recibo cierran el acceso. El cuerpo premium se trata como datos, no como instrucciones del agente. No se almacenan claves en el repositorio ni se registra el contenido de autorizaciones. El almacén local tiene hash de integridad; la firma del facilitador protege el recibo frente a edición de SQLite. La demo no publica servidor externo ni ejecuta herramientas MCP financieras.

## Reproducción y evidencia

```bash
python3.12 -m venv /tmp/con44-venv
/tmp/con44-venv/bin/python -m pip install -r requirements.txt
/tmp/con44-venv/bin/python -m unittest discover -s tools/x402
/tmp/con44-venv/bin/python -m tools.x402.demo
```

El entorno debe permitir escuchar en `127.0.0.1` para la prueba HTTP. `evidence/con44/demo-offline.json` registra una ejecución completa: 402 V2, descubrimiento, política CON-27/28/29, autorización sandbox separada, verify, settle simulado, recurso, recibo, retry, reinicio SQLite y cero movimientos contables. El workflow `.github/workflows/con44-x402-v2-sandbox.yml` repite la demo y tests adversariales, sube el JSON como artefacto y ejecuta regresiones Python, JS y Rust. Ningún step envía transacciones Solana.

## Límites y puerta Devnet

Esta fase **no** valida fondos, balances SPL, transacciones finalizadas, disponibilidad pública, pagos entre wallets reales ni un facilitador externo. Un pago Devnet posterior requiere nueva autorización humana específica, un esquema `exact` SVM genuino mediante SDK mantenido, wallet y cuentas token de prueba separadas, verificación RPC de `getTransaction`/balances y correlación con un recibo on-chain. No reutilizar el escrow WorkOrder como micropago. Jira CON-44 y el PR deben permanecer abiertos para revisión hasta que sus criterios acordados se acepten; no se hace merge automático.
