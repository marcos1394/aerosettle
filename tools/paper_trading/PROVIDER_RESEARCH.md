# CON-31 — Investigación de proveedores (consulta: 24 de octubre de 2026)

La implementación se mantiene offline. Esta matriz evalúa posibles fuentes futuras y **no** aprueba una conexión comercial ni una cuenta real.

| Criterio | Alpaca | Interactive Brokers |
|---|---|---|
| API paper | Sí; entorno paper documentado | Sí mediante TWS API y cuenta paper |
| Datos simulados/históricos | Paper usa datos IEX para cuentas solo paper; acceso y licencia según plan | Paper usa condiciones de mercado simuladas; detalles de datos dependen de cuenta/suscripciones |
| Paper execution | Órdenes simuladas, no enrutadas a bolsa real; el API paper se parece al live | Cuenta paper de prueba; ejecución puede diferir del live |
| Requisito de cuenta | Registro de cuenta paper; credenciales separadas | Documentación TWS: cuenta real aprobada y fondeada para abrir paper; requisitos dependen de modalidad |
| KYC/KYB | Cuenta paper global con email según documentación; para cuenta empresarial real, beta y elegibilidad variable | Cuenta corporativa documentada; onboarding y verificación según entidad y jurisdicción |
| Elegibilidad de SAS mexicana | **No verificada** para cuenta empresarial y/o instrumentos concretos | **No verificada** para SAS mexicana y/o instrumentos concretos |
| Instrumentos | Paper documenta acciones y cripto; cada instrumento y país requiere verificación | Amplia oferta de productos; disponibilidad depende de cuenta, permisos y jurisdicción |
| Tarifas/límites | No asumir costos de mercado: paper omite impacto, latencia y algunas tarifas regulatorias | Tarifas y datos dependen de plan, mercado y cuenta; verificar antes de integrar |
| Uso comercial de datos | **No verificado**; requiere licencia/condiciones específicas | **No verificado**; requiere licencia/condiciones específicas |
| Riesgo de conexión live | Alto: documentación distingue `paper-api.alpaca.markets` de `api.alpaca.markets` y credenciales | Alto: TWS API también puede operar cuenta live según sesión/configuración |
| Adecuación a Conatus hoy | Solo investigación; no se incluye cliente ni URL | Solo investigación; no se incluye cliente ni gateway |

Fuentes oficiales: [Alpaca Paper Trading](https://docs.alpaca.markets/us/docs/paper-trading), [Alpaca Authentication](https://docs.alpaca.markets/us/v1.1/docs/authentication-1), [Alpaca business accounts beta](https://alpaca.markets/support/alpaca-business-accounts), [IBKR TWS API limitations](https://www.interactivebrokers.com/docs/tws-api/doc/notes-limitations/tws-api-limitations), [IBKR Small Business](https://www.interactivebrokers.com/en/accounts/small-business.php). La disponibilidad actual de APIs y los términos deben reconfirmarse antes de cualquier integración. La existencia de una API paper no valida elegibilidad mexicana, facultades de una persona moral, instrumento, tarifas ni uso comercial de datos.
