# Privacidad · OMEN CFDI

- Todo se procesa en tu equipo. OMEN no recibe, guarda ni ve tus facturas, estados de cuenta ni reportes.
- Lo único que sale a internet es `cfdi_estatus_sat` (y `cfdi_estatus_sat_carpeta`, que lo repite por cada XML de una carpeta), y solo cuando tú (o Claude por tu pedido) lo usas: envía al servicio público del SAT (`consultaqr.facturaelectronica.sat.gob.mx`) el RFC emisor, el RFC receptor, el total, el UUID y los últimos 8 caracteres del sello. Nada más.
- No hay telemetría, analítica ni cuentas.
- Conservación: el plugin no guarda nada propio. Solo escribe un archivo si tú le das una ruta `csv_salida` en `cfdi_reporte`; ese CSV queda en tu equipo hasta que tú lo borres. OMEN no conserva ningún dato.
- Público: es para contadores y dueños de negocio; no está dirigido a menores de 18 años.
- El modelo de Claude ve lo que las herramientas devuelven; eso se rige por los términos de tu cuenta de Claude.

Contacto: contacto@omen-it.tech

## Privacy (English)
Everything runs locally. Only `cfdi_estatus_sat` and `cfdi_estatus_sat_carpeta` (one query per XML) contact Mexico's SAT public service, sending issuer and receiver RFC, total, UUID and the last 8 characters of the seal. No telemetry. The plugin keeps no data of its own; it writes a file only when you pass `csv_salida` to `cfdi_reporte`, and that CSV stays on your machine until you delete it. Not intended for anyone under 18. Contact: contacto@omen-it.tech
