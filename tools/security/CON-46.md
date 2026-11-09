# CON-46 — Release Security, Supply Chain & Authority Controls

Base: merge CON-45 `9b0fe8e39ca0fe8f5afc67fee08d8c6600919791`. Alcance: control del proceso; **cero** despliegues, pagos, cambios de upgrade authority o claves Mainnet.

## Auditoría AS-IS y cambios

| Superficie | Antes | Cambio CON-46 / evidencia | Estado |
| --- | --- | --- | --- |
| Workflows | 14 workflows, `contents: read`; acciones por etiqueta mutable; CON-34 Localnet condicionado a su rama | Acciones fijadas a SHA oficiales verificados; gate CON-46 sin filtro de paths y con suite Localnet propia; escáner estático de permisos, secretos y comandos de despliegue | VERIFIED en archivos; CI pendiente |
| Credenciales | `.gitignore` excluye `.aerosettle-local/`, wallets, PEM, `.env`; CON-35 coteja keypair y binding | Gitleaks v8.30.1 escanea historial completo con salida redactada. Baseline de 40 hallazgos `generic-api-key` en fixtures públicos y anotaciones de tipos; nuevos hallazgos fallan. No se agregan llaves | VERIFIED para escaneo local; custodia externa NOT_ACCESSIBLE |
| Dependencias | Cargo.lock; cuatro npm lockfiles; tres requirements Python sin lock transitivo con hashes; toolchains Anchor/Solana fijadas en Anchor.toml | Dependabot semanal, SBOM CycloneDX, auditorías npm y `pip-audit` en vivo y excepciones fechadas. Vite 6.3.6→6.4.5 elimina sus advisories en lockfile de rama | PARTIAL: Python transitivo sin hashes y excepciones abiertas |
| Artefactos | CON-35 ya compara dos builds SBF/IDL equivalentes y verifica manifest Devnet | Se ejecuta en CI CON-46, se almacena manifest y hash; verificador Ed25519 independiente para bundle futuro | PENDING_APPROVAL para firma real |
| Autoridades | Fee payer, upgrade authority y administrador Devnet separados; deploy requiere id exacto | Matriz de roles; release verifier exige program, genesis, autoridad, toolchain, hashes, firma y aprobación externa | VERIFIED en pruebas; ninguna autoridad alterada |
| GitHub | Los jobs existen, pero controles administrativos no estaban probados | API: `master` responde `404 Branch not protected`; rulesets `[]` (2026-11-08) | PENDING_APPROVAL del administrador |

## Inventario y vulnerabilidades

`Cargo.lock` incluye Anchor/Solana/Agave y dependencias transitivas; `Anchor.toml` declara Anchor 1.2.0 y Solana 4.1.2. Npm: web, transaction SDK, marketplace SDK y bootstrap con lockfiles separados. Python: `requirements.txt`, `tools/deployment/requirements.txt` y `tools/economic_ledger/requirements.txt`. El SBOM registra componentes resueltos de Cargo y npm, distribuciones Python instaladas y SHA-256 de cada manifest. Es un inventario de entorno, no prueba por sí solo ausencia de CVEs.

La API de Dependabot mostró 24 alertas abiertas en `master` el 2026-11-08: 3 altas, 19 medias y 2 bajas. Diez alertas Vite corresponden al lockfile base y deben revalidarse tras merge; el lockfile de la rama ya usa 6.4.5 y `npm audit` local no reporta Vite. Las restantes incluyen `bigint-buffer` 1.1.5 alta (bootstrap), `stream-json` 1.9.1 y `uuid` 8.3.2 medias en la cadena Solana RPC, y `rand` 0.7.3 baja en `litesvm` de pruebas Rust. `dependency-exceptions.json` conserva advisory, versión, exposición, mitigación, dueño y revisión 2026-11-30 para los cinco advisories npm no corregidos; **no** los presenta como resueltos. La alerta `rand` queda documentada aquí porque es transitiva de `litesvm` dev-dependency; se revisará al actualizar esa cadena. Los scripts fallan si aparece un advisory npm nuevo, cambia severidad, vence la excepción o falla el endpoint de auditoría.

`pip-audit` 2.10.1 ejecutado contra `requirements.txt` no encontró vulnerabilidades conocidas el 2026-11-08 y está agregado al gate CI. La resolución puede variar porque no hay lock Python con hashes; ese resultado no garantiza que todas las instalaciones futuras sean idénticas. Dependabot proporciona cobertura Rust; no hay `cargo-audit` independiente en este PR. `cryptography` y `certifi` solo tienen mínimos en requirements, sin hashes ni lock de tránsito: prioridad de hardening posterior.

## Toolchain y reproducibilidad

CI Linux `ubuntu-24.04` x86_64: Rust/Cargo 1.89.0, Agave CLI/SBF 4.1.2 (tarball SHA-256 fijado), Anchor declarado 1.2.0, Node 24 y Python 3.12. El script `tools/deployment/compare_clean_builds.sh` produce dos builds con `CARGO_TARGET_DIR` independientes, compara `.so`, IDL y catálogo de errores byte a byte, y deja `reproducibility.json` con commit, hashes binario/IDL y Cargo.lock. La igualdad se afirma **solo dentro de ese entorno**. Los hashes macOS/Linux históricos de CON-35 difieren; no se infiere reproducibilidad entre plataformas ni identidad con ProgramData. La verificación on-chain pertenece a CON-35/36 y a un post-deploy autorizado.

## Criterios de Jira y evidencia

| Criterio | Evidencia | Estado |
| --- | --- | --- |
| CI integral y permisos mínimos | `.github/workflows/con46-release-security.yml`; `workflow_policy.py`; tests Python, JS, Rust, SBF y Localnet | PENDING CI |
| Dependencias, secretos, SBOM | Dependabot consultado, auditoría npm, Gitleaks redactado, CycloneDX y excepciones | PARTIAL por hallazgos y lock Python |
| Separación de autoridades | [Matriz](authority-matrix.md), bindings CON-35, pruebas de rechazo | VERIFIED para software; custodia NOT_ACCESSIBLE |
| Release firmado y autorización | `release.py` + tests de firma, sustitución, aprobación, Mainnet y toolchain | VERIFIED como control; firma real PENDING_APPROVAL |
| Freeze, rollback y amenazas | [Política](release-policy.md), [modelo](threat-model.md) | VERIFIED documental; simulación en tests |

## Riesgos y acciones pendientes

1. Administrador debe activar y comprobar branch protection/ruleset para los cinco jobs CON-46, revisión obligatoria y prohibición de bypass. La API mostró que **no** estaban activos.
2. Aprobar por canal independiente una clave pública de firma de releases y su custodia; `release-trust.example.json` no tiene claves. Ningún nuevo despliegue se autoriza con ella.
3. Revisar excepciones npm antes del 2026-11-30, actualizar la cadena Solana cuando exista versión compatible, y cerrar alertas Dependabot solo con evidencia de lockfile y merge.
4. Introducir lock Python con hashes y una auditoría Rust independiente en una etapa posterior; no tratar el inventario actual como cierre de esa cobertura.
5. Corroborar por RPC las identidades públicas antes de cualquier despliegue futuro y preservar evidencia finalized. No se envía transacción desde CI.

La evidencia final de tests, hashes y CI se añadirá al PR tras ejecutar los jobs. No se cierra Jira ni se hace merge en CON-46 automáticamente.
