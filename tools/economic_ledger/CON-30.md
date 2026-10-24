# CON-30 — Excedente potencial y continuidad operativa

## Auditoría AS-IS y matriz de fuentes

| Concepto | Fuente autorizada | Efecto contable | Tratamiento CON-30 |
|---|---|---|---|
| Tesorería | `ledger_entries` de `ASSET:TREASURY`, a través de `EconomicLedger.get_economic_summary()` | Activo líquido contable | Saldo inicial; no es prueba RPC de titularidad |
| Reserva existente | `agent_reserves` y asientos `ASSET:RESERVED:*` | Ya salió de tesorería al asignarse | Mostrar por separado; no descontar el saldo reservado de nuevo |
| Pasivo devengado | Saldo neto de `LIABILITY:ACCRUED_EXPENSES` en el General Ledger | Crédito pendiente, neto de débitos/reversiones registrados | Descontar una sola vez si se puede demostrar independencia del gasto pagado |
| Gasto realizado | `agent_costs`, `economic_movements` y crédito a tesorería o reserva | Ya redujo el activo correspondiente | Solo fuente de burn observado; no deducir otra vez como gasto histórico |
| Estimación de costo | `agent_costs` con `ESTIMATED` | No mueve tesorería | No tratar como efectivo pagado ni burn observado |
| Claim administrativo | `spending_budget_claims` de CON-28 | No financiero | Retener solo claims actuales de idéntica identidad/política/contexto; si hay posible solapamiento con costos, no publicar cifra |
| Aprobación humana | `spending_approvals` y sus eventos de CON-29 | No financiero | Puede invalidar un claim al revocarse; nunca se suma como segundo compromiso |
| Mínimo de reserva | Regla por mint de la política CON-27 | No segrega físicamente | Descontar únicamente la brecha no cubierta por reserva elegible |
| Escrow, fondos de clientes y otra wallet | Protocolo Solana, fuera de `ASSET:TREASURY` | Propiedad separada | Excluidos; no se importan balances RPC como tesorería |
| CAPEX | Activo distinto de tesorería | Ya acreditó tesorería al adquirirse | Excluido; no se suma como efectivo |
| Ingreso provisional | `economic_movements` provisional | No aporta débito conciliado a tesorería disponible | Excluido |

CON-24 calcula `available_balance` como **máximo de cero y débitos conciliados menos todos los créditos** del asiento `ASSET:TREASURY`, en la partición exacta de agente, red, génesis, programa y mint. Su `investible_surplus` histórico solo resta costos devengados a ese saldo; continúa por compatibilidad y no representa la evaluación de continuidad CON-30. CON-25 calcula solvencia y cobertura de ventanas UTC: el adaptador consulta su evaluación exacta de 30 días y conserva como contexto el Conatus Ratio, Operating Margin, Runway, estado y procedencia. Solo usa una cobertura completa de CON-25 para afirmar cobertura del burn; `VALID` no demuestra por sí mismo propiedad ni liquidez libre. CON-27 aporta política e identidad; CON-28 aporta claims consultivos; CON-29 aporta consentimiento revocable. Ninguno ejecuta una inversión.

## Metodología `conatus:investible-surplus:v1`

El motor puro `assess_investible_surplus()` recibe snapshots explícitos y un tiempo inyectado. Usa enteros de unidades base y cadenas decimales; no usa SQLite, reloj, RPC, floats ni IA. La salida incluye hash del snapshot de entrada, hash de resultado, referencias y deducciones explicadas. Con iguales entradas devuelve el mismo resultado.

El cálculo, cuando todos los componentes y sus relaciones están conocidos, es:

```text
max(0, tesorería contable
       − pasivo devengado pendiente no pagado
       − brecha de reserva mínima elegible
       − claims administrativos actuales independientes
       − buffer adicional de continuidad
       − haircut de escenario
       − otras restricciones independientes)
```

Reservas contables existentes ya segregadas de `ASSET:TREASURY` se muestran, pero su deducción aplicada es cero. Solo reservas `OPERATIONAL_CONTINUITY` satisfacen inicialmente el mínimo de política; otras finalidades siguen restringidas. Si el objetivo mínimo y el buffer son del mismo propósito, el motor puede netearlos únicamente con relación `SAME_PURPOSE` explícita; si son independientes, usa `INDEPENDENT`. Una relación desconocida impide publicar una cifra. Obligaciones y claims también deben demostrar independencia de pagos y costos. La mera existencia de un `decision=ALLOW` o `approval_status=APPROVED` nunca agrega capital ni movimiento.

El burn es costo realizado y conciliado en una ventana observada de 30 días, excluyendo estimaciones, reversos y depreciación. Sin cobertura completa de la ventana ni un supuesto explícito de estimación, el adaptador devuelve `INSUFFICIENT_DATA`; no divide un registro aislado entre 30 días como si los días faltantes fueran cero. Cero observado sin cobertura completa es **desconocido**, no cero auténtico. El buffer de continuidad es `ceil(OPEX observada × horizonte × multiplicador_bps / (días observados × 10000))`. El haircut positivo de tesorería se redondea hacia arriba como deducción conservadora, incluso si el saldo es una sola unidad base; los multiplicadores de gasto también se redondean hacia arriba. BASE usa 10000 bps y 0 haircut; CONSERVATIVE 12500 y 500; STRESS 15000 y 1500. Los parámetros son hipótesis demostrativas, no pronósticos ni tasas empíricas. Horizontes: 7, 30 y 90 días. No hay FX ni rendimientos proyectados.

El fixture matemático de aceptación mantiene deducciones **independientes**: tesorería 1000, obligación 200, brecha de reserva 150, claim 100 y buffer adicional 250. Produce estimación 300, con `verified_investible_surplus_base_units_str=null` y procedencia `SYNTHETIC_TEST`.

## Confianza, procedencia y límites

- `VERIFIED`: solamente cuando capital y titularidad, restricciones y cobertura tienen prueba auténtica, completa y fresca, con procedencia productiva. El adaptador actual **nunca afirma esta condición**: no dispone de CON-34.
- `ESTIMATED`: hay entradas y reglas de no solapamiento suficientes para una proyección aritmética, pero no prueba productiva completa. Nunca es capital confirmado.
- `INSUFFICIENT_DATA`: falta tesorería, observación temporal, burn o prueba de independencia entre categorías; ambas cantidades de excedente son `null`.
- `STALE_DATA`: la observación supera 24 horas; ambas cantidades de excedente son `null`.
- Contexto mixto o identidad histórica incompatible: error explícito, sin agregar activos, owners, redes, génesis o programas.

La capa de lectura usa la política actual, el General Ledger, costos, reservas y claims de la misma partición. Rechaza registros de esa partición con otra identidad de agente/owner; no usa balance de wallet externa, escrow ni ingreso provisional. Una revocación o rechazo de CON-29 excluye su claim administrativo solamente después de validar con `SpendingApprovalStore` la firma Ed25519, cadena de hashes, identidad, contexto económico y secuencia de transiciones de todo el historial. Un evento inválido o incompleto produce conflicto de integridad y no libera capacidad. Los claims sintéticos nunca se presentan como gasto realizado o evidencia productiva. Cuando un claim y un costo realizado pueden corresponder al mismo propósito sin vínculo verificable, o un pasivo puede solaparse con burn/pago, devuelve `INSUFFICIENT_DATA` en lugar de sumar descuentos dudosos. Incluso con tesorería contable positiva, la evaluación puede ser `INSUFFICIENT_DATA` si faltan cobertura de burn y continuidad o prueba de independencia entre categorías. Un supuesto explícito puede permitir `ESTIMATED`, etiquetado como estimación consultiva y con `verified_investible_surplus_base_units_str=null`; el adaptador no emite `VERIFIED` sin infraestructura auténtica de CON-34.

No se creó la migración 012: las evaluaciones son reproducibles y consultivas, y no existe todavía un snapshot productivo de titularidad y cobertura que amerite promoverse a histórico persistido. El `assessment_hash` permite auditar una respuesta capturada externamente, pero no es prueba on-chain. No existe endpoint de historial CON-30. Las consultas no escriben en tablas contables, propuestas, claims ni aprobaciones. La API solo expone GET privado para evaluación de un contexto exacto y metodología; SDK e interfaz no ofrecen órdenes ni transferencias.

CON-34 debe aportar evidencia RPC/SPL y cobertura auténtica de costos e ingresos, vínculos de liquidación de claims con pagos, titularidad económica y snapshot temporal atómico antes de habilitar un importe productivo confirmado. Las lecturas cruzadas actuales no son un snapshot atómico entre fuentes; por ello la respuesta sigue siendo consultiva y `is_executable=false`.
