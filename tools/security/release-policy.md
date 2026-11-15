# CON-46 — Política de release y recuperación

## Estados independientes

`BUILD_OK` significa compilación exitosa; `REPRODUCIBLE` exige dos builds equivalentes con hashes iguales; `SIGNED` exige Ed25519 de una clave de release aprobada; `DEPLOYED_MATCH` compara el binario con ProgramData; `RPC_VERIFIED` exige red, genesis, firma finalized, slot, programa y autoridad observados. Ningún estado implica automáticamente el siguiente.

## Camino autorizado

1. Partir de un commit revisado y lockfiles fijados. Ejecutar el gate CON-46, inventario SBOM, auditorías, tests y dos builds SBF/IDL en el mismo entorno Linux fijado. Guardar SHA-256 de `.so`, IDL y SBOM. El hash macOS puede diferir: no se afirma identidad binaria entre plataformas.
2. Crear un manifiesto JSON con exactamente `repository`, `commit_sha`, `program_id`, `network`, `genesis_hash`, `artifact_sha256`, `idl_sha256`, `toolchain_versions`, `sbom_sha256`, `approval_identifier`, `upgrade_authority_pubkey`, `created_at`. `approval_identifier` es SHA-256 de JSON canónico de los demás campos. La firma Ed25519 cubre el JSON canónico completo, incluido el identificador.
3. El revisor recibe por canal independiente el manifiesto, binario, IDL y SBOM. Verifica los hashes y compara una política de confianza protegida fuera del PR. Una política que venga del mismo PR no sirve como autoridad. `release-trust.example.json` contiene **cero** claves aprobadas y no habilita releases.
4. El aprobador humano autoriza el `approval_identifier` exacto y la autoridad exacta. El comando de solo lectura `python -m tools.security.release --manifest ... --signature ... --trusted-policy ... --artifact ... --idl ... --sbom ... --approved-identifier ...` debe devolver `VERIFIED`. No envía transacciones.
5. Un despliegue futuro requiere procedimiento independiente con firmas y wallets específicas, y debe ejecutar preflight, control de ProgramData y JSON-RPC finalized según CON-35. El workflow CON-46 no puede desplegar ni cambiar autoridades. Mainnet está bloqueado en el verificador aun si el manifest o una variable de entorno lo solicita; CON-47 y CON-73–76 decidirán el gate final.

La firma no se crea en CI ni se almacena en el repositorio. Actualmente no hay clave pública de release aprobada en la política de ejemplo ni un release CON-46 firmado: **PENDING_APPROVAL** para cualquier despliegue nuevo. Esto evita presentar un checksum como una firma.

## Freeze y respuesta

| Evento | Acción inmediata | Evidencia antes de levantar freeze |
| --- | --- | --- |
| Build o dependencia comprometida | Congelar promociones; aislar artefacto y commit; identificar lockfile y advisory | Nuevo build doble, SBOM, escaneo y firma bajo nueva aprobación |
| Secreto filtrado o wallet comprometida | Suspender operaciones del rol afectado; preservar logs redactados; plan de rotación | Confirmación de revocación/rotación por dueño, nueva identidad pública y prueba RPC |
| Despliegue equivocado o upgrade fallido | Detener nuevos releases y operaciones dependientes; capturar ProgramData y firma | Binario de recuperación aprobado, authority vigente, plan de upgrade y verificación finalized |
| IDL incompatible | Congelar clientes que dependan de ABI nueva | Hash IDL reconstruido, tests de compatibilidad y aprobación |
| RPC alterado | Deshabilitar ingestión productiva hasta comparar genesis, firmas y datos con RPC independiente | Evidencia consistente de dos fuentes y reconciliación repetida |
| Facilitador x402 o MCP/A2A comprometido | Suspender credenciales y políticas afectadas, revocar tokens y detener pagos automáticos | Identidad y firma renovadas, replay tests, trazas auditadas |
| Pérdida de upgrade authority | Congelar upgrades; no intentar usar otra wallet | Procedimiento de gobernanza aprobado o plan de migración a nuevo programa |

Un rollback Solana exige un **nuevo upgrade autorizado** con binario anterior revisado y nuevo manifiesto. `git revert` no modifica ProgramData. Esta historia simula los rechazos mediante tests; no ejecuta upgrades, rotaciones ni transferencias.

## Protección administrativa pendiente

Configurar en GitHub un ruleset sobre `master` con revisión humana, branch actualizada, prohibición de bypass y checks obligatorios de `CON-46 release security gate` (cinco jobs), además de los controles de auditoría del repositorio. Verificar la configuración real y registrar capturas/API antes de marcarla `VERIFIED`. La presencia de un workflow en Git no demuestra que branch protection esté activa. La clave de release y la aprobación deben provenir de canales separados del PR.
