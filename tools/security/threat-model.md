# CON-46 — Modelo de amenazas

Escala: impacto `alto/medio`, probabilidad `media/baja` en el contexto actual Devnet y servicios aún controlados. `MITIGATED` exige control y prueba; `PARTIAL` indica riesgo residual. No equivale a una auditoría externa.

| Escenario | Impacto / probabilidad | Control y evidencia | Estado |
| --- | --- | --- | --- |
| Compromiso de wallet | Alto / media | Roles de fee payer, upgrade y administrador distintos; binding de keypairs en CON-35; freeze y rotación documentada. Custodia externa sin prueba en este repo. | PARTIAL |
| Agent Card A2A maliciosa | Medio / media | Validación de schema, firma, identidad y procedencia, binding limitado a lectura; pruebas adversariales CON-39. | MITIGATED dentro del alcance de lectura |
| Suplantación de herramienta MCP | Alto / media | Autenticación, RBAC, allowlist de herramientas y respuestas de solo lectura CON-40. | PARTIAL para clientes externos |
| Ejecución de herramienta no autorizada | Alto / media | Denegación de mutaciones MCP, autorización por principal y tests de alcance. | MITIGATED para superficie implementada |
| Recibo x402 falso | Alto / media | Verificación de firma, transacción y reconciliación exacta CON-44/45; no promover recibos sin evidencia. | PARTIAL ante facilitador comprometido |
| Suplantación de facilitador | Alto / media | Identidad del facilitador vinculada a recibo y allowlist; pruebas negativas x402. Rotación externa pendiente. | PARTIAL |
| RPC spoofing | Alto / media | Genesis, Program ID, finalized, ProgramData y hashes cotejados; fuentes RPC independientes requeridas para incidentes. | PARTIAL si fuente única comprometida |
| IDL alterada | Alto / media | Hash IDL en manifiesto y comparación con ABI aprobada; pruebas de sustitución. | MITIGATED para release gate |
| Sustitución de destino SPL | Alto / media | Cuentas y mint verificados por contrato y reconciliador; Localnet/Devnet CON-34/36 incluyen destino inválido. | MITIGATED en settlement probado |
| Replay o doble settlement | Alto / media | Idempotencia y unicidad de firma/efecto económico CON-23/37/45; reinicio SQLite probado. | PARTIAL fuera de escenarios probados |
| Prompt injection | Medio / media | Salidas A2A/MCP como datos no confiables; no conceder autoridad financiera por texto. | PARTIAL; evaluación operativa pendiente |
| SSRF | Medio / media | Validación de URL y destinos de discovery CON-39; pruebas adversariales. | MITIGATED en rutas conocidas |
| Dependencia maliciosa | Alto / media | Lockfiles, acciones fijadas por SHA, checksums de binarios, SBOM, auditoría npm, Gitleaks, Dependabot. Python no tiene lock transitivo con hashes. | PARTIAL |
| Escalada de privilegios GitHub Actions | Alto / baja | `contents: read`, SHA de acciones, prohibición `pull_request_target`, secretos y deploy en workflows PR; test estático CON-46. Ruleset aún sin verificar. | PARTIAL |
| Compromiso de upgrade authority | Alto / media | Autoridad separada; manifest firmado y aprobación independiente requeridos para nuevo release; no hay clave de release aprobada aún. | PARTIAL |
| Acceso entre tenants | Alto / media | Identidad de agente, owner y política cotejadas en ledger/API; pruebas negativas CON-27/29/32. | PARTIAL ante integraciones nuevas |

La clasificación se basa en el código y pruebas del repositorio, la evidencia pública Devnet de CON-35/36 y el inventario Dependabot consultado el 2026-11-08. Una recomendación documental se marca `PARTIAL`; los controles administrativos y la custodia de claves requieren verificación externa.
