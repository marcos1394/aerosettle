# CON-53 — Frontend Localnet / Devnet

## Estado y alcance

Base: merge CON-46 `54b6a3b51cb4e6be2f0b80e044b8e1b0d20717db`. La app tiene dos builds explícitos. `LOCALNET` conserva las rutas existentes de desarrollo. `DEVNET` carga una entrada separada de solo lectura; no monta wallet adapters, SDK de transacciones, navegación financiera ni fixtures Localnet. `MAINNET` no tiene manifest ni build admitido.

No se enviaron transacciones ni se cambió el programa, mint, fondos o autoridades. La beta pública no está disponible.

## Inventario AS-IS

| Superficie | Origen anterior | Clase | Decisión CON-53 |
| --- | --- | --- | --- |
| `config.ts`, `Providers.tsx`, `NetworkProvider.tsx`, `api.ts` | RPC y genesis Localnet fijos, conexión de wallet, API en el origen web | Lectura / conexión | Se preserva Localnet; `verifyNetwork()` comprueba manifest, IDL, programa, mint y API. El árbol se reinicia al cambiar cuenta. |
| Agentes, misiones, dashboard, historial, settlement | API Localnet y snapshots con procedencia variada | Lectura / simulación | Permanecen solo en build Localnet. Devnet muestra estado vacío hasta que exista API verificable. |
| Creación, funding, claim, firmas | IDL y evidencia Localnet; `signTransaction` en componentes y SDK | Escritura económica de desarrollo | No se importan en el build Devnet. El escáner de artefactos falla si aparecen rutas de firma o envío. |
| `localnet-idl.json`, `localnet-evidence.json` | Fixtures de validador Localnet | Fixture | Nunca se presentan en Devnet. |
| Vite proxy `127.0.0.1:8899` | Uso local | Desarrollo | Se mantiene únicamente para Localnet. Devnet llama exclusivamente al RPC oficial fijado. |

## Matriz de entornos

| Campo | Localnet | Devnet | Mainnet |
| --- | --- | --- | --- |
| Genesis | `HP9XKTusRPGC78EFDpR9xdEq6simL2vqyDdrMvn6Vacg` | `EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG` | Deshabilitado |
| Programa | `CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy` | mismo Program ID, validado por genesis | Deshabilitado |
| Mint | `HTHpns7gqLAhSBhAzqxhYdyHv9HeXkkRW6aHQfdUjL1G` | `HpfaV9oRuTN1b3ktDKvJoWqUWFZ1o9VFmhejxxqQ1vyh`, token de prueba | Deshabilitado |
| API | Proxy local `127.0.0.1:5173` | `API_NOT_CONFIGURED` | Deshabilitado |
| Wallet y transacciones | Desarrollo Localnet | Deshabilitadas | Deshabilitadas |
| Procedencia | `LOCALNET_FIXTURE` | `LIVE_DEVNET_READ_ONLY` solo tras comprobación RPC | `UNVERIFIABLE` |

Los manifests de `src/config/environments.ts` tienen schema estricto, versión 1 y SHA-256 canónico. `src/config/trust.ts` fija las identidades aprobadas por separado: CON-35 para programa, IDL, ProgramData y upgrade authority; CON-35/36 para mint de prueba, autoridad, Token Program y seis decimales. La IDL distribuida se comprueba byte a byte contra su hash antes de consultar RPC. Los hashes aprobados son:

- Localnet manifest: `22e026a55a0b0e0f30ef5f1530fcfe4eb18386657cf4fdbf4ef0393308800f9b`.
- Devnet manifest: `db8d0bf22b0e9102d9464d9f35c6732a8e0e9e444fe459ead4a75a1fc8469592`.
- Localnet IDL: `73d2f8b0e5184229deae81d08ba5742765f4bc2ba21f325d0da223f765fa5c98`.
- Devnet IDL: `a6e436aa1c6468b4f518b742e40a2664e38dcdf7bc1419e53e1624444888e15d`.

Estos pins viven en el mismo bundle y **no son una firma independiente**. CON-97 debe aprobar una clave de release distribuida por canal controlado antes de afirmar autenticidad productiva del manifest. El hash protege contra cambios accidentales y mezclas internas; no protege contra un actor que reemplace todo el bundle.

## Verificación y estados

`verifyEnvironment()` consulta `getGenesisHash` y `getAccountInfo` con commitment `finalized`. Exige programa ejecutable bajo BPF Upgradeable Loader, ProgramData y upgrade authority aprobados en Devnet, mint SPL inicializado de 82 bytes bajo Token Program aprobado, autoridad y decimales exactos. No hay cambio automático de RPC ni fallback entre redes. La API Localnet se valida mediante health y metadata de catálogo frente a genesis y Program ID. Devnet no tiene endpoint API aprobado; por eso el estado correcto tras RPC válido es `DEGRADED_READ_ONLY` / `API_NOT_CONFIGURED`, nunca `VERIFIED`. Errores de identidad dan `NETWORK_MISMATCH` o `MANIFEST_INVALID`; RPC caído o incompleto da `UNAVAILABLE`. El indicador visible muestra red, activos de prueba, procedencia y capacidades deshabilitadas, con detalles desplegables.

El build Devnet no contiene métodos de firma o envío. `capabilities.ts` rechaza programáticamente esas capacidades. En Localnet, el cambio de wallet reinicia el árbol de rutas y sus cachés; `VerificationSession` aborta consultas anteriores y descarta respuestas fuera de orden. Devnet no tiene wallet ni selector de red en esta fase; cada nueva verificación invalida la anterior.

## Builds, tests y evidencia

```bash
npm ci --prefix apps/marketplace-web
npm test --prefix apps/marketplace-web
npm run typecheck --prefix apps/marketplace-web
npm run build:localnet --prefix apps/marketplace-web
npm run build:devnet --prefix apps/marketplace-web
node --experimental-strip-types apps/marketplace-web/scripts/verify-build.mjs localnet
node --experimental-strip-types apps/marketplace-web/scripts/verify-build.mjs devnet
node apps/marketplace-web/scripts/combine-evidence.mjs
```

`verify-build.mjs` comprueba el grafo de entrada, hashes y ausencia de funciones de wallet/firma en el artefacto Devnet; `combine-evidence.mjs` produce JSON solo tras verificar ambos builds. El workflow `.github/workflows/con53-multienvironment-web.yml` ejecuta esto, los SDKs, TypeScript, pruebas adversariales, `tools/security` y la política CON-46; no accede a secretos ni envía transacciones. El workflow CON-46 existente sigue ejecutando regresiones Python, Rust, SBF y Localnet en cada PR a `master`.

Observación RPC real y de solo lectura: [evidence/con53/devnet-rpc-read-only.json](../../evidence/con53/devnet-rpc-read-only.json), obtenida con `scripts/verify-live-devnet.mjs`. El resultado fue `DEGRADED_READ_ONLY` con identidad RPC válida y API ausente; no se presenta como servicio Devnet completo. Los artefactos de build tienen hashes propios por plataforma y no prueban reproducibilidad binaria entre macOS y Linux.

Las pruebas cubren manifest e IDL alterados, red desconocida/Mainnet, genesis equivocado, programa no ejecutable, owner y mint erróneos, decimales y autoridad incorrectos, API de otro clúster, RPC caído o incompleto, intentos de firma en Devnet y respuestas fuera de orden. El aislamiento del build impide reutilizar estado Localnet en Devnet.

## Dependencias pendientes

- CON-54: conexión real de wallets.
- CON-55 y CON-59: catálogo y API/indexación Devnet verificables.
- CON-56 y CON-69: WorkOrders y pasarela de transacciones web.
- CON-58: staging público.
- CON-97: firma aprobada y gate administrativo de manifests/releases.

Hasta entonces, Devnet permanece en preview de lectura RPC y `API_NOT_CONFIGURED`. No hacer merge automático ni cerrar Jira desde esta implementación.
