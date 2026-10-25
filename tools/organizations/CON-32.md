# CON-32 — Organizations, Membership & Auditable RBAC

## Auditoría AS-IS

- `tools/economic_ledger/auth.py` verifica firmas Ed25519 para lectura económica de un AgentAccount; `budget_policies.py`, `spending_approvals.py` y `paper_trading/store.py` tienen dominios de mutación separados y controlan identidad, nonce e idempotencia. Sus firmas no se reutilizan aquí.
- Discovery obtiene `agent_account`, `agent_id`, `owner`, `status` y `active` desde AgentAccount; Marketplace API añade `program_id` y valida génesis mediante el proveedor RPC local. La signing authority técnica no representa al propietario.
- `tools/economic_ledger/schema.py` conserva migraciones económicas 001–011. CON-31 mantiene `paper_trading.sqlite` separado. CON-32 crea `organizations.sqlite`; no añade migraciones económicas.
- `tools/marketplace_api/server.py`, `openapi_spec.py`, el SDK TypeScript y la app React sirven como adaptadores de transporte y presentación. No se modificó ningún contrato Anchor ni acceso económico existente.

## Arquitectura y autoridad

`signatures.py` define `conatus:organization-admin:v1` para POST y `conatus:organization-read:v1` para GET. La firma de mutación incluye versión, organización, actor, acción, destinatario, rol, ámbito, método, ruta, hash canónico de todo el cuerpo, vigencia, nonce e idempotency key. La lectura firma actor, ruta y timestamp. Solo se admiten 300 segundos de vigencia temporal para credenciales de mutación y lectura. Las claves públicas y firmas se verifican con Ed25519 existente.

`rbac.py` evalúa permisos de forma pura y determinista. Los permisos se enumeran; los desconocidos son DENY. OWNER administra la organización. ADMIN tiene lectura administrativa y solo recibe operaciones de escritura mediante delegación explícita. Ningún rol incluye gasto, custodia, settlement, firma de dispositivo ni acceso económico privado. Las delegaciones tienen profundidad máxima uno: solo un permiso de un rol base vigente puede delegarse a otro miembro activo, para un recurso exacto u organización, y durante una vigencia limitada. Se comprueba el estado actual del delegador en cada evaluación.

`store.py` serializa mutaciones con `BEGIN IMMEDIATE`. Conserva únicamente un índice de identidad y eventos inmutables, reconstruye el estado de la organización desde las firmas y la cadena de hashes en cada lectura, y comprueba el hash y versión de cabecera para detectar truncamientos. Reproduce también las transiciones y permisos históricos. Los timestamps efectivos son los de confirmación local de la transacción; no se permite usar un `issued_at` atrasado para revivir un permiso revocado. El hash local no es una prueba de blockchain.

El propietario organizacional es inmutable en CON-32. Un representante distinto se declara inicialmente como `PENDING_VERIFICATION`; su wallet debe aceptar una invitación con rol `LEGAL_REPRESENTATIVE`. Tras esa aceptación el estado continúa `UNVERIFIED`: una firma no prueba facultades jurídicas. No se recopilan documentos oficiales.

## Membresía de agentes

Un administrador invita usando la proyección actual de Discovery. La invitación firmada contiene `agent_account`, `agent_id`, propietario, red, génesis, programa y hash del snapshot. La aceptación firmada por el propietario actual vincula el ID de invitación, AgentAccount y hash del snapshot. El servidor vuelve a consultar Discovery antes de confirmar. Si cambia la identidad o el propietario, falla cerrado. Las lecturas comparan de nuevo la identidad y exponen `REVIEW_REQUIRED` cuando ya no coincide, cuando el agente está suspendido/revocado o cuando vence su membresía. Un nuevo propietario requiere una nueva invitación y consentimiento; el historial previo sigue intacto. La fuente RPC y la transacción SQLite no son atómicas entre sí, por lo que toda discrepancia observada antes de commit cancela la operación, y las lecturas posteriores vuelven a comprobar.

La organización no obtiene `AgentAccount.owner`, signing authority, fondos, políticas CON-27, permisos CON-29, reservas, simulaciones CON-31, settlement ni endpoints económicos privados. La lectura pública de registro de agente solo proporciona la identidad necesaria para preparar la invitación y requiere firma de lectura organizacional.

## API y UI

- `POST /v1/organizations` crea con firma raíz.
- `POST /v1/organizations/{id}/actions` aplica acciones administrativas tipadas con versión esperada.
- `GET /v1/organizations` enumera únicamente organizaciones accesibles a la wallet firmante.
- `GET /v1/organizations/{id}` y `/{section}` restringen detalles, miembros, agentes, invitaciones, roles, delegaciones, permisos y auditoría.
- `GET /v1/organizations/agent-registration/{account}` devuelve el snapshot actual de registro necesario para el consentimiento.

La acción única evita duplicar rutas para cada transición; el servidor valida permisos actuales y el SDK conserva tipos de acción. La pantalla Web3 presenta vista general, miembros, agentes, roles, delegaciones y cronología; todas las acciones firman mensajes exclusivos de organización. Las opciones visibles se filtran con los permisos devueltos por el backend, que repite la validación al recibir la mutación. Al cambiar wallet se limpian organización, historial y errores cargados. La interfaz indica que se trata de administración off-chain sin custodia ni firma de dispositivos.

## Límites y dependencia de CON-33

No se implementan estatutos, votaciones, quórum, DAO, treasury colectiva, distribución económica, transferencias, órdenes de inversión ni autoridad legal verificada. CON-33 definirá gobernanza y reglas de participación. Una suspensión organizacional deshabilita acciones y lecturas ordinarias; solo el titular raíz puede consultar el resumen y reactivar la organización.

## Validación

`test_organizations.py` cubre firmas, lectura, invitaciones, consentimiento, revocación, roles, delegaciones, cambios de propietario, concurrencia, integridad del historial, truncamiento, reinicio e idempotencia. `test_organizations_api.py` cubre API, lectura privada, bloqueo financiero y contenido invariable de las tablas económicas. `organizations.test.mjs` compara los bytes canónicos Python/TypeScript y rechaza autoridad financiera falsa. La suite Rust verifica que el ciclo WorkOrder existente no sufrió cambios.
