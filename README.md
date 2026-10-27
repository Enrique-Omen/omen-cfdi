# OMEN CFDI

Revisa tus facturas del mes con Claude. Le das la carpeta de XML y te dice cuáles traen errores, cuáles ya no están vigentes en el SAT, si algún proveedor está en la lista de EFOS, cuánto IVA te toca y qué pagos no cuadran con tu banco.

Instálalo en Claude Code con 2 comandos:

```
/plugin marketplace add Enrique-Omen/omen-cfdi
/plugin install omen-cfdi@omen-cfdi
```

Y pregúntale, por ejemplo: «Valida las facturas de la carpeta `facturas/octubre` y dime cuáles tienen errores y por qué.»

Necesitas Python 3.10 o más nuevo; no instala nada más. En Windows, si `python3` no existe, instala Python desde python.org o cambia `python3` por `py` en `.mcp.json`. Todo corre en tu computadora; solo la consulta de vigencia va al SAT.

## Qué hace

| Herramienta | Para qué |
|---|---|
| `cfdi_leer` | CFDI 4.0 y 3.3 a JSON: emisor, receptor, conceptos, impuestos por tasa, UUID, relacionados, complementos: pagos 1.0/2.0 y nómina 1.2 con detalle; carta porte y otros solo se identifican. |
| `cfdi_validar` | Errores y avisos en español: atributos obligatorios, RFC, UUID, timbre, catálogos, sumas (SubTotal, impuestos, Total), PUE/PPD vs forma de pago, P/T con moneda XXX, receptor genérico, saldos del complemento de pago. |
| `cfdi_estatus_sat` | Consulta pública del SAT: Vigente/Cancelado, si es cancelable, estatus de cancelación y validación EFOS. |
| `cfdi_estatus_sat_carpeta` | Estatus SAT de todos los XML de una carpeta (hasta `max_cfdi`, 200 por defecto), uno por uno, con conteo de vigentes, cancelados y no encontrados. |
| `cfdi_reporte` | Carpeta completa: tabla por CFDI, resumen por mes y por RFC (emitidas/recibidas), IVA trasladado/retenido (facturado y en flujo), UUID duplicados, PPD con su pagado y saldo, «PPD sin complemento de pago». CSV opcional. |
| `cfdi_conciliar_banco` | Carpeta + CSV del banco: empareja por monto exacto y fecha cercana; RFC o folio en la descripción desempatan. |

## Ejemplos

- «Valida las facturas de la carpeta `facturas/octubre` y dime cuáles tienen errores y por qué.»
- «¿Esta factura de mi proveedor está vigente en el SAT y el proveedor aparece en la lista de EFOS? `proveedor/F-88.xml`»
- «Con mi RFC EKU9003173C9, dame el IVA trasladado y retenido de octubre, las facturas PPD sin complemento de pago y concilia contra `banco/octubre.csv`.»

## Probarlo desde una copia local

`claude --plugin-dir ./omen-cfdi`

## Usar en claude.ai (sin MCP)

Comprime la carpeta `skills/cfdi-mx/` en un zip y súbela en Ajustes → Skills → Subir skill. Claude correrá `python3 scripts/cfdi.py <herramienta> ...` en su entorno de código. La consulta al SAT necesita que ese entorno tenga salida a internet.

## Línea de comandos

```bash
python3 skills/cfdi-mx/scripts/cfdi.py validar factura.xml
python3 skills/cfdi-mx/scripts/cfdi.py estatus_sat factura.xml
python3 skills/cfdi-mx/scripts/cfdi.py reporte facturas/ --rfc_propio TU_RFC --csv_salida iva.csv
python3 skills/cfdi-mx/scripts/cfdi.py conciliar_banco facturas/ --csv banco.csv --dias 5
python3 skills/cfdi-mx/scripts/cfdi.py mcp      # servidor MCP por stdio
```

Pruebas: `python3 -m unittest discover -s tests -v` (la consulta en vivo al SAT: `OMEN_CFDI_RED=1`). Los XML de `tests/` son sintéticos.

## Privacidad

Todo corre en tu equipo. Solo `cfdi_estatus_sat` y `cfdi_estatus_sat_carpeta` salen a la red y envían al SAT: RFC emisor, RFC receptor, total, UUID y los últimos 8 caracteres del sello. Sin telemetría. Ver [PRIVACY.md](PRIVACY.md).

## Límites

- No timbra ni cancela CFDI.
- No verifica la firma criptográfica del sello ni el certificado (eso lo hace el SAT: usa `cfdi_estatus_sat`).
- No descarga XML del SAT (descarga masiva): trabaja con los XML que ya tienes.
- Con Pagos 1.0 (sin nodo Totales) el IVA en flujo de esos complementos sale en 0.
- Catálogos embebidos en versión corta; no reemplaza la revisión de tu contador.
- Probado con facturas sintéticas: la consulta al SAT responde en vivo, pero todavía no se probó con un CFDI real vigente.

## Detalles técnicos

Es un plugin para Claude (Claude Code y Cowork) con un servidor MCP y una Agent Skill.

Si tu cliente MCP lo soporta, `cfdi_reporte` y `cfdi_conciliar_banco` te preguntan tu RFC (con los más frecuentes de la carpeta como opciones) cuando no lo das; si no, siguen sin separar emitidas y recibidas. `cfdi_estatus_sat_carpeta` corre como Task (MCP 2025-11-25): el cliente recibe un `taskId`, consulta el avance con `tasks/get`, cancela con `tasks/cancel` y recoge el resultado con `tasks/result`; sin soporte de Tasks, responde en la misma llamada. Claude Code (2.1.293, medido el 25-oct-2026) sí muestra el formulario del RFC, pero no pide Tasks: ahí responde en la misma llamada, y con 200 XML puede tardar minutos. Si no contestas el formulario en 2 minutos, el reporte sigue sin separar emitidas de recibidas.

---

## English

OMEN CFDI is a Claude plugin (MCP server + Agent Skill) for Mexican electronic invoices (CFDI 4.0/3.3): parse XML to JSON, validate structure and math with Spanish explanations, check SAT status and EFOS listing, monthly VAT report, and reconcile PPD invoices against payment complements and bank statements. Pure Python standard library; everything is local except the SAT status query (sends RFCs, total, UUID and the last 8 characters of the seal). Install with `/plugin marketplace add <repo>` and `/plugin install omen-cfdi@omen-cfdi`. It does not stamp, cancel, download from SAT, or verify the seal signature.

---

Hecho por OMEN · [omen-it.tech](https://omen-it.tech) · contacto@omen-it.tech
