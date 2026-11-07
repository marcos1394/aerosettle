# CON-43 — Signed Agent-to-Agent RFQ and Quote Negotiation

## Auditoría de la base

La rama parte de `origin/master` en `250aa216811a9447f7589d0564887a78eae2f2c1`, que fusionó CON-42. `tools/a2a/cards.py` publica tarjetas de discovery y las marca expresamente sin autoridad financiera. `tools/a2a/task_server.py` implementa tareas JSON-RPC de CON-41 y correlación de WorkOrders offline; no es un transporte de negociación. `tools/agent_runtime/runtime.py` consulta CON-27/28 y mantiene `ALLOW` como asesoría sin pago. CON-27 es `BudgetPolicyStore.current`, CON-28 es `SpendingProposal` más `evaluate_spending_proposal`; CON-29 retiene las aprobaciones humanas. CON-38 aporta logs estructurados. Anchor y los SDKs de transacciones no son importados ni modificados por este módulo.

## Contrato y confianza

`models.py` exige el esquema exacto `conatus.agent-negotiation.v1` para `RFQ`, `Quote`, `Counteroffer`, `AcceptIntent` y `RejectIntent`. El precio total se expresa como string decimal entero positivo de unidades base u64, con `token_mint` y `token_decimals` explícitos. La cantidad es un entero de servicios; no es cantidad de tokens. `terms_hash` cubre mint, decimales, importe, cantidad, servicio, SLA y fecha de entrega. `canonical.py` usa RFC 8785 y firma todo el mensaje, incluido tipo, identidad, contexto, nonce, expiración y hash del padre, con dominio `CONATUS-AGENT-NEGOTIATION-v1`. Se verifica Ed25519 contra el owner o signing authority vigente del AgentAccount suministrado por una fuente independiente.

La confianza de producción requiere `TrustedContext.verified_devnet()`, que reutiliza los pins de CON-39/35, valida manifiesto, IDL, programa y mint de prueba mediante JSON-RPC real; `IdentityVerifier` exige además una función `refresh_context` que repita esa comprobación en cada mensaje. El proveedor de AgentAccount debe entregar proyecciones actuales y autenticadas, con tenant y organización verificados. Sin esta fuente completa, la integración productiva falla cerrada. La demo usa `OFFLINE_FIXTURE` de manera explícita. `VERIFIED_IDENTITY` indica que se verificó identidad, no que ocurrió una transacción económica. `SIGNED_MESSAGE` solo indica una firma válida sobre el mensaje. `LIVE_RPC` no se asigna a la negociación, pues no hay movimiento on-chain. Las condiciones no verificables se rechazan con `UNVERIFIABLE` o un código de confianza; nunca se promocionan por el mero reinicio de SQLite.

Una Agent Card puede ayudar al descubrimiento, pero no sustituye la proyección actual de AgentAccount ni confiere autorización. El adaptador `a2a_adapter.py` coloca el mensaje firmado en un `a2a.types.Message` versión 1.0 con media type propio. No anuncia el binding read-only de CON-39 como transporte de tareas ni crea un endpoint público. La interoperabilidad probada es **offline**, entre solicitante Python y proveedor Node.js. La semilla Node `0x02` es fixture pública de prueba.

## Máquina de estados y límites

El primer mensaje `RFQ` crea `RFQ_SENT`. Cotizaciones de proveedores invitados pasan a `QUOTING`; una `Counteroffer` enlazada y con ronda incremental pasa a `COUNTEROFFER_PENDING`. `AcceptIntent` del solicitante produce `INTENT_ACCEPTED` y una propuesta exclusivamente off-chain. `RejectIntent` produce `INTENT_REJECTED`; si referencia la RFQ original, cancela y produce `CANCELED`. `EXPIRED` se calcula al consultar una sesión activa vencida, sin alterar su historial. Mensajes inválidos no producen estado `FAILED`: se rechazan y registran como denegaciones, preservando el estado previamente firmado.

Los límites por defecto son 4 proveedores, 3 rondas, 3600 segundos totales, 900 segundos de vigencia por oferta, 1,000,000,000 unidades base por oferta, desviación máxima de 2,500 bps sobre el presupuesto, 100 unidades de servicio, 20 mensajes por agente y 4 negociaciones simultáneas del solicitante. Todos son configurables con valores positivos. Una oferta superior al presupuesto puede registrarse para auditoría dentro del margen configurado, pero jamás se selecciona. Se comparan solo las ofertas vigentes más recientes de cada rama. Las restricciones duras son vigencia, cantidad, SLA, fecha de entrega y presupuesto. Entre elegibles, gana menor precio total, fecha más temprana, cuenta del proveedor y `message_id` en ese orden. Ningún LLM decide la elegibilidad. Los controles de identidad y CON-27/28 se comprueban después de la comparación, antes de persistir `AcceptIntent`.

`DENY` de CON-28 bloquea la intención. `REQUIRE_APPROVAL` genera `PENDING_HUMAN_APPROVAL`; `ALLOW` genera `ELIGIBLE_INTENT_ONLY`. Ambos resultados conservan `requires_independent_authorization=true`, `is_onchain=false`, `escrow_created=false`, `funds_transferred=false` y `settlement_verified=false`. Este módulo no crea claims de CON-28, aprobaciones CON-29, movimientos contables, escrow ni instrucciones Anchor.

## Persistencia y auditoría

`NegotiationStore` usa transacciones `BEGIN IMMEDIATE`, unicidad global de `message_id`, de `idempotency_key` por agente y de nonce por agente/contexto monetario. Cada versión incluye hash del mensaje, estado, selección, hash de la propuesta y hash del evento anterior. Las lecturas comprueban la cadena completa y verifican otra vez todas las firmas e identidades vigentes. La lectura del historial exige prueba Ed25519 reciente del owner solicitante. Una clave idempotente solo devuelve el mensaje exacto después de validar identidad e integridad, incluso si el mensaje ya expiró; el reintento se marca histórico y no aplicable. Una edición directa de sesión, propuesta o mensaje que no actualice toda la cadena se detecta. `HASH_CHAIN_ONLY` describe honestamente la garantía: un administrador con acceso de escritura a toda la base puede recomputar hashes; la firma Ed25519 protege los mensajes originales, mientras que una atestación externa del estado y la propuesta no está implementada.

Los logs CON-38 contienen correlación, tipo y código de autorización sin claves, JWT ni descripción del servicio. La entrada descriptiva rechaza instrucciones comunes de prompt injection; ningún texto libre del proveedor se interpreta como comando o política.

## Reproducción

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tools/negotiation
python -m tools.negotiation.demo > con43-demo.json
```

`evidence/con43/demo-offline.json` registra el resultado observado: cuatro mensajes, firmas verificadas, propuesta off-chain, revisión humana pendiente, reinicio SQLite e idempotencia correctos, sin movimientos financieros. El workflow `.github/workflows/con43-agent-negotiation.yml` repite la demo, verifica sus indicadores, publica un artefacto JSON y ejecuta regresiones Python, JavaScript y Rust. No envía transacciones Solana.

## Límites pendientes

No hay servidor público de negociación ni transporte interoperable desplegado. La demostración no acredita E2E financiero Devnet. `TrustedContext.verified_devnet()` dispone de validación read-only, pero publicar un servicio productivo exige conectar una fuente autenticada y fresca de AgentAccount, tenant y organización, más controles de acceso al endpoint. Una propuesta histórica nunca equivale a autorización de gasto actual; CON-29 y Anchor siguen como puertas independientes. El ciclo WorkOrder create→fund→claim→submit→verify→settle conserva sus contratos y pruebas existentes.
