# CON-39 — A2A Agent Cards y descubrimiento seguro

## Auditoría y criterio de aceptación

Base: `origin/master` después de CON-38 (`181b148644ae51bde548c481493c8f4cb7f07655`). Jira: [CON-39](https://quhealthy-team.atlassian.net/browse/CON-39). La historia exige tarjetas A2A conformes, publicación por `/.well-known/agent-card.json`, catálogo y cliente externos, procedencia comprobable, negociación, controles SSRF, demo con SDK independiente, observabilidad y CI; prohíbe ejecutar tareas, crear WorkOrders y transferir fondos.

El repositorio ya tenía `AgentAccount` on-chain, validación PDA/IDL y lectura RPC en `tools/discovery/agent_discovery.py`, capacidades como máscara de 16 bits en Anchor, API de marketplace y RBAC organizacional. Ninguno constituye una identidad A2A ni una autorización financiera. CON-39 conserva esos modelos y añade únicamente tarjetas firmadas y un catálogo SQLite independiente. No hay migraciones del ledger, cambios Anchor, operaciones SPL ni claves privadas en el catálogo.

## Versión y compatibilidad

Se fija [A2A spec v1.0.1](https://github.com/a2aproject/A2A/releases/tag/v1.0.1), versión de protocolo `1.0`, y el modelo `AgentCard` generado por `a2a-sdk==1.3.0`. `google.protobuf.json_format.ParseDict(..., ignore_unknown_fields=False)` y `MessageToDict` validan el esquema antes de firmar, aceptar o publicar. Se fijan `rfc8785==0.1.4` para JCS y Ed25519 para JWS, de acuerdo con [la especificación oficial](https://a2a-protocol.org/latest/specification/). Las entradas desconocidas se rechazan; no se mezclan campos de A2A 0.3.

Las tarjetas anuncian una **interfaz personalizada de descubrimiento**, `https://github.com/marcos1394/aerosettle/a2a/bindings/read-only-card/v1`, con `protocolVersion=1.0`. Su URL es `https://<dominio>/a2a/cards/<card_id>`, separada del recurso de bootstrap `/.well-known/agent-card.json`. La semántica completa de este binding v1 es **solo `GET` de esa tarjeta firmada en JSON**; `POST` devuelve 405 y no existen `message/send`, tareas, streaming, cancelación ni operaciones de pago. `GET /a2a/cards/<card_id>/verify` es una extensión administrativa del catálogo, no una operación A2A. El SDK A2A oficial con transportes estándar, sin registrar este binding, rechaza la tarjeta con `no compatible transports found`; nuestra negociación lo representa como `UNSUPPORTED_TRANSPORT`. No se anuncia soporte para tareas HTTP+JSON, JSON-RPC o gRPC. La negociación devuelve `is_executable=false`, incluso cuando una skill coincide. La tarjeta no declara requisitos de seguridad para tareas, porque no existe una tarea que autenticar; la publicación requiere el vínculo firmado y la lectura pública requiere validación de procedencia.

## Identidades, procedencia y publicación

Los campos de identidad son separados: `agentId` (ID Conatus), `agentAccount` (PDA), `ownerPubkey` (propietario), `signingAuthority`, `organizationId` opcional, `publisherId`/`publisherKey` (publicador A2A) y `endpointDomain`. `network`, `genesisHash` y `programId` fijan el contexto de Solana. El propietario firma un payload JCS con dominio `CONATUS-A2A-OWNER-BINDING-v1`, versión, vigencia máxima de 24 horas, interfaz, skills y todos esos campos. El publicador firma la tarjeta completa con JWS EdDSA: cabecera protegida `alg`, `typ`, `kid` y firma sobre `base64url(header).base64url(JCS(card-sin-signatures))`. Se rechazan `jku`, algoritmos distintos, claves sin anclaje y firmas alteradas. La posesión del dominio **no** demuestra control de wallet; la firma del propietario es la prueba de asociación.

`generate_card()` construye skills únicamente desde bits habilitados de un AgentAccount activo. Las descripciones de skills son fijas para evitar promesas de ejecución o capacidades inventadas. `DiscoveryIdentitySource` usa el descubrimiento IDL/PDA existente con compromiso `finalized` y rechaza `ProtocolConfig` pausado. Su ancla **no proviene del IDL suministrado por CLI**: `tools/a2a/trust.py` fija de manera independiente el Program ID `CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy`, red `solana:devnet`, genesis `EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG`, RPC oficial, IDL versión/spec `0.1.0`, IDL SHA-256 `a6e436aa1c6468b4f518b742e40a2664e38dcdf7bc1419e53e1624444888e15d` y deployment ID `06c7dfa7528460969a5ca1e8bd001f9c9f1f1f0df3d69fe36649e413e0b14ae6`. Contrasta el [manifiesto CON-35 VERIFIED](../../evidence/con35/devnet-deployment.json) con su hash de archivo fijado `a47cf814f12e9f9e39ca5881b66ff4f9e96adb32ddbbcf867f877c5205154e58`, el [IDL aprobado](../../evidence/con35/artifacts/aerosettle-idl.json) byte a byte y `tools/deployment/devnet.json`. Un IDL estructuralmente compatible de otro programa, otro RPC, versión o archivo modificado falla antes de hacer consultas de discovery.

Antes y después del discovery se revalidan los archivos de confianza, el genesis RPC y, reutilizando `tools/deployment/devnet.py`, el Program Account/ProgramData del loader: dirección canónica `7kYZxnujXJ9sKGhG9CbDwThJECb693WvvqVFHGmNSsrr`, upgrade authority `DdHrtAxE5SwcVQUgoKRzoWatZ5yw9UdtBQnRwBizPK2D` y slot de despliegue `516258865`. El snapshot resultante debe informar el Program ID aprobado, PDA de ProtocolConfig aprobado y compromiso `finalized`; `discover()` valida además owner de cuentas, PDA, IDL y vínculos de AgentAccount. Un upgrade cambia el slot y exige una nueva revisión y política de confianza aprobada. Las fixtures offline usan un `identity_source` explícito de pruebas y **no** pueden configurarse mediante la CLI productiva. No se presenta una fixture como identidad Devnet real.

`CardCatalog.publish()` verifica esquema, firma del propietario, firma del publicador, contexto on-chain actual y organización mediante un verificador independiente, cuando se declara. Sin callback organizacional, una tarjeta con `organizationId` falla cerrada. Cada lectura (`get`, búsqueda, endpoint conocido y `verify`) vuelve a consultar la identidad actual; un cambio de propietario, signing authority, capacidades, estado o red oculta la tarjeta. Versiones posteriores deben ser monotónicas. La rotación de clave del publicador requiere una **nueva firma del propietario** que vincule la nueva clave. Revocación requiere firma Ed25519 del propietario actual sobre `CONATUS-A2A-REVOKE-v1`, card ID, versión y propietario; la tarjeta se vuelve invisible. Tarjetas expiradas y versiones anteriores no se sirven. El historial solo conserva metadatos y hashes, no se ofrece como autoridad actual.

Servicio de lectura: `GET /.well-known/agent-card.json`, `GET /a2a/cards`, `GET /a2a/cards/{card_id}` y `GET /a2a/cards/{card_id}/verify`. Búsqueda: `skill`, `category`, `modality`, `capability`, `version`, `agent_id`, `organization_id`. `POST` devuelve 405. El servicio Python escucha por defecto en loopback; para publicación externa se necesita proxy HTTPS, DNS y operación de claves fuera de este PR.

Ejemplo de ejecución, usando un archivo **previamente firmado**; la CLI carga por defecto el IDL y la política Devnet aprobados, y rechaza otros RPC/IDL:

```sh
python -m tools.a2a.cli publish --db /secure/cards.sqlite \
  --card /secure/owner-and-publisher-signed-card.json
python -m tools.a2a.cli serve --db /secure/cards.sqlite
```

La extensión `conatus-identity/v1` dentro de `capabilities.extensions[].params` incluye `cardId`, `cardVersion`, `agentAccount`, `agentId`, `ownerPubkey`, `signingAuthority`, `publisherId`, `publisherKey`, `endpointDomain`, `network`, `genesisHash`, `programId`, `issuedAt`, `expiresAt`, `capabilityMask`, `organizationId`, `discoveryOnly` y `ownerSignature`. Ejemplo abreviado de la interfaz:

```json
{
  "name": "Conatus Discovery Agent",
  "description": "Registered capabilities for discovery.",
  "supportedInterfaces": [{"url": "https://agent.example.org/a2a/cards/<signed-card-id>", "protocolBinding": "https://github.com/marcos1394/aerosettle/a2a/bindings/read-only-card/v1", "protocolVersion": "1.0"}],
  "version": "1.0.0",
  "capabilities": {"streaming": false, "pushNotifications": false, "extensions": [{"uri": "https://github.com/marcos1394/aerosettle/a2a/extensions/conatus-identity/v1", "required": false, "params": {"...": "see fields above"}}]},
  "defaultInputModes": ["application/json"],
  "defaultOutputModes": ["application/json"],
  "skills": [{"id": "conatus.aerial_mobility", "name": "Aerial Mobility", "description": "Registered Conatus capability for discovery only.", "tags": ["aerial_mobility", "conatus"]}],
  "signatures": [{"protected": "<base64url-protected-header>", "signature": "<base64url-ed25519-signature>"}]
}
```

## Cliente externo y aislamiento

`A2ADiscoveryClient` requiere una allowlist local de `TrustAnchor(domain, publisher_id, public_key, expires_at, revoked)`. No aprende claves de la tarjeta ni sigue URLs de JWKS. Solo consulta HTTPS en el path conocido, valida que **todas** las respuestas DNS sean IP públicas, repite la resolución y fija la IP elegida en el socket; TLS valida el hostname original con SNI. Rechaza redirecciones (límite cero), puertos no estándar, IP locales/privadas, content types no JSON, documentos mayores a 64 KiB, JSON duplicado o malformado, profundidad excesiva y firmas no ancladas. No hay caché de tarjetas externas. Si la tarjeta afirma identidad Conatus, exige además un `DiscoveryIdentitySource` independiente; la ausencia de fuente falla cerrada. El timeout por defecto es 5 s.

Los estados de negociación son `SUPPORTED`, `UNSUPPORTED_VERSION`, `UNSUPPORTED_TRANSPORT`, `UNSUPPORTED_MODALITY`, `UNTRUSTED_CARD` y `EXPIRED_CARD`; verificación también emite `INVALID_SIGNATURE` e `INVALID_IDENTITY`. El cliente jamás invoca skills o instrucciones incluidas en la tarjeta. Ninguna tarjeta autoriza firmar transacciones, reclamar WorkOrders, modificar beneficiarios o gastar fondos.

## Demo, observabilidad y pruebas

`python -m tools.a2a.demo_interop` levanta un servidor local de fixture con claves efímeras. Recupera por HTTP local la tarjeta que sería servida mediante HTTPS en operación, la parsea con el `AgentCard` del SDK oficial independiente, comprueba firma y vínculo, selecciona el binding de descubrimiento, hace `GET` en el recurso seleccionado y enumera skills. `ClientFactory()` del SDK oficial sin binding personalizado rechaza la creación de cliente de tareas; `POST` en el binding devuelve 405. La demo informa `standard_client_status=UNSUPPORTED_TRANSPORT`, `binding_get_verified=true`, `binding_post_status=405`, `is_executable=false`, `is_financial_authority=false` y `funds_transferred=false`. **No prueba publicación real en Devnet ni un ejecutor A2A externo**.

`tools/a2a/test_a2a.py` cubre schema, firmas, alteraciones, suplantación, propietario y signing authority cambiados, capacidades y skills falsas, expiración, rotación, revocación, persistencia SQLite, aislamiento entre agentes, organización, versiones, modalidades, SSRF, DNS rebinding, redirecciones, tamaño, JSON, JWKS e inyección en descripciones. Los casos nuevos rechazan IDL alterada, programa alternativo Anchor en el mismo genesis, manifiesto cambiado, RPC ajeno, ProgramData/upgrade authority inesperados, y comprueban `UNSUPPORTED_TRANSPORT` con `ClientFactory` oficial. CON-38 recibe métricas bajo scope `a2a` (`a2a_cards_published`, `a2a_cards_validated`, `a2a_cards_rejected`, `a2a_invalid_signatures`, `a2a_discovery_errors`, `a2a_unsupported_versions`, `a2a_ssrf_blocked`, `a2a_resolution_ms`) y logs allowlisted con IDs, resultado y duración, sin secretos ni saldos. El workflow `con39-a2a-agent-cards.yml` ejecuta demo, tests, regresiones Python CON-34–38, suites JS, build web y Rust, sin fondos ni claves reales.

Riesgos operativos pendientes: provisionar DNS/TLS y claves con rotación segura, añadir un verificador organizacional concreto cuando se publiquen organizaciones, y definir un servicio A2A de tareas en una historia futura. Hasta entonces la publicación externa real requiere tarjeta firmada, evidencia RPC actual y endpoint HTTPS operativo; este PR no publica una tarjeta Devnet ni declara compatibilidad con transportes estándar de tareas. Un upgrade verificado del programa/IDL requiere un nuevo manifiesto y cambio revisado de las constantes fijadas; nunca se acepta automáticamente desde un IDL o endpoint suministrado.
