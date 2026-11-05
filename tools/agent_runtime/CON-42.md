# CON-42 — Policy-Governed Autonomous Agent Runtime

## Auditoría AS-IS y autoridad

Base: `origin/master` con merge CON-41 `d49a713a6941ec449ff111e9e36838d676290c9e`.
CON-27 guarda versiones inmutables de política por AgentAccount, `agent_id`, propietario y contexto monetario. CON-28 tiene el evaluador puro `evaluate_spending_proposal` y `SpendingDecisionStore.evaluate`, que registra evaluaciones y claims administrativos, nunca pagos. CON-29 exige firmas Ed25519 del propietario para abrir, aprobar, rechazar o revocar una revisión. Su `get()` comprueba la cadena de hashes, firmas, identidad y aplicabilidad actual. CON-40 expone únicamente herramientas MCP de lectura; CON-39/41 no conceden autoridad económica por medio de una Agent Card o tarea A2A. CON-38 aporta métricas y logs estructurados.

## Arquitectura y flujo

`models.py` valida planes y estados. `planner.py` define `Planner`, `DeterministicPlanner` y una interfaz `LLMPlanner` sin proveedor. `tool_registry.py` publica una allowlist cerrada y llama a los handlers reales de CON-40; `quote_task` devuelve solo una estimación offline. `policy_gate.py` conserva políticas de autonomía versionadas y exige un token Ed25519 de administración para modificar controles. `runtime.py` verifica identidad y política antes de **cada** llamada, espera con timeout, resume observaciones como datos inertes y solicita una evaluación CON-28. `audit.py` persiste runs y eventos encadenados. `observations.py` detecta patrones de inyección y nunca pasa texto externo al planificador.

Estados persistidos: `CREATED → PLANNING → POLICY_CHECK → EXECUTING_TOOL → OBSERVING → POLICY_CHECK`, repetidos por paso, hasta `AWAITING_APPROVAL`, `DENIED`, `FAILED` o `CANCELED`. El runtime no tiene una transición de pago. Una cancelación solo detiene el run local, nunca una transacción ni WorkOrder on-chain.

Las dos credenciales son distintas: `conatus-agent-runtime` para ejecución y `conatus-agent-runtime-admin` con scope `runtime:admin` para políticas, revocación y suspensión. El kill switch global requiere `runtime:globaladmin`; cancelar requiere `runtime:cancel`. El planificador no ve esos tokens. El `agent_supplier` debe consultar la identidad actual de una fuente confiable; la demo usa una copia de fixture. El caller de producción debe proteger la API de construcción del runtime y el almacenamiento SQLite con controles del sistema operativo.

## Herramientas y política

El registry admite búsqueda de agentes, lectura de Agent Cards, estado del protocolo, WorkOrders y evidencia autorizada a través de CON-40, más una cotización informativa offline. Cada `ToolSpec` declara proveedor, protocolo, scopes, riesgo, tipo de agente, timeout, cuota, esquemas y `read_only=True`. Se rechazan herramientas desconocidas, URL/rutas en argumentos, `wallet_sign`, `transfer`, `fund_workorder`, `claim_workorder`, `verify_workorder`, `settle_workorder`, `refund`, `change_beneficiary`, `change_budget_policy`, `upgrade_program` y `export_private_key`, aunque aparezcan en una salida LLM. La autorización MCP conserva su aislamiento de owner, tenant y organización por recurso.

La política comprueba versión/hash actual, expiración, scopes, herramientas, cuotas de pasos/llamadas/cómputo, riesgo, entorno y kill switches antes de cada llamada y al terminarla. Una revocación durante un handler descarta su respuesta. `max_compute_units` cuenta operaciones autorizadas; no mide CPU. El límite LLM usa `tokens_used` declarado por el adaptador; hasta tener medición confiable del proveedor, se configura `max_llm_tokens=0` por defecto y no se habilita LLM en despliegue productivo. El planificador determinista de la demo no consume tokens.

## Integración económica y matriz

El payload de propuesta se analiza con `SpendingProposal.parse`, se compara con la política CON-27 actual y se evalúa con el motor CON-28. Si un propietario aporta una **firma externa válida** para la evaluación, se llama a `SpendingDecisionStore.evaluate` y queda la evaluación persistida. Sin firma, solo se utiliza el evaluador puro con snapshots reales del ledger y el resultado se etiqueta `CON28_ADVISORY_UNPERSISTED`. El runtime jamás fabrica la firma. Una referencia CON-29, si se proporciona, se lee mediante `SpendingApprovalStore.get` para comprobar firmas, cadena, identidad, contexto, vigencia y decisión; el runtime no crea ni aprueba una revisión por sí mismo.

| CON-28 | Resultado del runtime | Efecto económico |
| --- | --- | --- |
| `DENY` | `DENIED` | Ninguno |
| `REQUIRE_APPROVAL` | `AWAITING_APPROVAL`, `approval_request_id` | Ninguno; propietario debe usar CON-29 |
| `ALLOW` | `AWAITING_APPROVAL` | Ninguno; ALLOW tampoco firma ni liquida |

La demo usa fixture de política y claves **de prueba** fuera del runtime, un token de acceso de vida corta, y una evaluación firmada externamente. Obtiene `REQUIRE_APPROVAL` porque el ledger no tiene evidencia económica productiva. No se abre una aprobación CON-29 automáticamente. La política monetaria, balances y fórmulas existentes no se modifican.

## Auditoría, amenazas y aislamiento

El runtime guarda `run_id`, identidad, hash HMAC del objetivo y solicitud, versión/hash de política, plan, paso, estado, y eventos con `previous_event_hash` y `event_hash`. Los argumentos y observaciones se guardan como HMAC, no como texto bruto. El verificador revisa orden, cadena, estado final, resultado y plan tras reinicios. Por defecto la etiqueta es `HASH_CHAIN_ONLY`: una cadena hash **no** es firma. Un firmante externo incluido en `approved_attestors` puede enviar una firma Ed25519 real sobre los bytes del hash del evento; `attest()` verifica y conserva esa prueba separada. El verificador marca entonces ese evento `SIGNED`. Sin firmante aprobado, falla cerrado.

Observaciones MCP, Agent Cards y cotizaciones son datos no confiables. El runtime retiene únicamente hash, procedencia e indicador de inyección; el LLM no recibe el texto de la herramienta para modificar política, scopes o propietario. El fixture de Agent Card contiene una inyección intencional y las pruebas confirman que no altera la secuencia. Un resultado `OFFLINE_FIXTURE` no se promueve a `LIVE_RPC`. Las claves privadas, tokens y headers firmados no se registran en eventos.

Los límites de URL, tamaño de respuesta, tiempo y concurrencia son controles **lógicos dentro del proceso**, no una sandbox de sistema operativo. Los adaptadores confiables CON-40/CON-39 mantienen su política de red y SSRF. Un despliegue que agregue herramientas externas debe ejecutarlas en un proceso/contenedor aislado con permisos de archivo y red mínimos. No existe shell ni evaluación de Python generado por LLM.

## Reproducción y evidencia

```bash
python -m unittest discover -s tools/agent_runtime
python -m tools.agent_runtime.demo
```

`evidence/con42/demo-offline.json` contiene los booleanos exigidos, hash final de auditoría, procedencia, resultado CON-28 e indicador de que no cambiaron tablas financieras. La demo no usa Devnet ni envía transacciones. `.github/workflows/con42-agent-runtime.yml` ejecuta pruebas adversariales, demo, regresiones económicas, A2A, MCP, operaciones, descubrimiento, deployment, organizaciones, gobernanza, Marketplace, SDK/web y Rust; publica el JSON como artefacto.

Validación inicial del commit `fe6e3e84cca1e53df58b303647b9be4794439a21`: [workflow CON-42, run 41963870905](https://github.com/marcos1394/aerosettle/actions/runs/41963870905), jobs Python, JavaScript y Rust `success`; [artefacto de demo offline](https://github.com/marcos1394/aerosettle/actions/runs/41963870905/artifacts/13385964917). Localmente pasaron 20 pruebas CON-42, 208 Economic Ledger, 27 A2A, 13 MCP, 19 Operations, 24 Discovery, 20 Deployment, 14 Organizations, 16 Governance, 3 Devnet read-only, 13 Funding, 5 Mission, 65 Marketplace API, 10 Transaction SDK, 36 Marketplace SDK, 43 web, build web y `cargo test --workspace --offline`. `git diff --check` quedó limpio.

## Límites pendientes

No hay ejecución financiera autónoma, adapter Devnet productivo, cotización de mercado ni LLM proveedor configurado. La aprobación humana se **prepara y detiene** en CON-42; la firma y mutación real siguen exclusivamente en CON-29. No se afirma E2E financiero Devnet ni se concede a una Agent Card, token MCP o tarea A2A autoridad para fondos.
