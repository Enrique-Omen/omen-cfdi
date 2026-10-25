---
name: cfdi-mx
description: Trabaja con CFDI de México (facturas electrónicas XML del SAT). Úsala cuando el usuario tenga facturas XML CFDI 4.0/3.3, quiera revisar o validar una factura, saber si está vigente o cancelada en el SAT, revisar si un proveedor está en la lista de EFOS, sacar el reporte de IVA del mes, conciliar facturas PPD contra complementos de pago, o conciliar facturas contra un estado de cuenta del banco. Use for Mexican CFDI invoices, SAT status, VAT (IVA) and reconciliation.
---

# CFDI de México (OMEN CFDI)

Seis herramientas. Con el plugin instalado están como herramientas MCP (`cfdi_leer`, `cfdi_validar`, `cfdi_estatus_sat`, `cfdi_estatus_sat_carpeta` para consultar al SAT toda una carpeta de una vez, `cfdi_reporte`, `cfdi_conciliar_banco`). Sin MCP (por ejemplo en claude.ai con la skill subida) funcionan igual por línea de comandos, con salida JSON:

```bash
python3 scripts/cfdi.py cfdi_leer factura.xml
python3 scripts/cfdi.py cfdi_validar factura.xml
python3 scripts/cfdi.py cfdi_estatus_sat factura.xml
python3 scripts/cfdi.py cfdi_estatus_sat --uuid <UUID> --rfc_emisor <RFC> --rfc_receptor <RFC> --total 1160.00
python3 scripts/cfdi.py cfdi_reporte carpeta/ --rfc_propio <TU_RFC> --csv_salida reporte.csv
python3 scripts/cfdi.py cfdi_conciliar_banco carpeta/ --csv estado_cuenta.csv --rfc_propio <TU_RFC> --dias 5
```

(También sirven los nombres cortos: `leer`, `validar`, `estatus_sat`, `reporte`, `conciliar_banco`.) Todo corre local con Python 3.10+ sin instalar nada. Solo `cfdi_estatus_sat` y `cfdi_estatus_sat_carpeta` salen a internet (servicio público del SAT): necesita red; si no hay, dilo y sigue con lo local.

## Reglas al contestar
- Habla en español claro, sin jerga. Montos con $ y dos decimales.
- Distingue **error** (el CFDI está mal o no sirve fiscalmente) de **aviso** (revisar).
- `cfdi_validar` NO verifica la firma criptográfica del sello. Si importa que sea auténtico, consulta `cfdi_estatus_sat`.
- No eres contador: en EFOS, cancelaciones o deducibilidad dudosa, recomienda confirmarlo con su contador.

## Flujos

### 1. Revisar las facturas del mes
1. `cfdi_reporte` sobre la carpeta, con `rfc_propio` si el usuario te lo da (separa emitidas y recibidas).
2. Muestra: cuántas hay, total por mes, IVA trasladado y retenido, UUID duplicados y archivos que no se pudieron leer.
3. Para las que se vean raras (montos altos, proveedores nuevos), corre `cfdi_validar` y resume solo los errores.

### 2. Validar antes de pagarle a un proveedor
1. `cfdi_validar` de la factura: si hay errores, explícalos y sugiere pedir una corrección.
2. `cfdi_estatus_sat`: debe decir **Vigente**. Si dice Cancelado o No Encontrado, no se paga hasta aclararlo.
3. Revisa `ValidacionEFOS`: si el emisor aparece en el listado de EFOS, alerta claro.
4. Comprueba que el receptor sea el RFC del usuario y que el UsoCFDI y el método de pago (PUE/PPD) cuadren con lo pactado. Si es PPD, recuerda que al pagar se necesita un complemento de pago.

### 3. Checar estatus y EFOS en el SAT
`cfdi_estatus_sat` con `ruta` o `xml`, o con los datos sueltos (uuid, rfc_emisor, rfc_receptor, total tal como viene en el XML). Reporta Estado, EsCancelable, EstatusCancelacion, ValidacionEFOS y la `lectura`. «No Encontrado» suele ser un dato mal escrito o un CFDI de minutos de antigüedad.

### 4. Conciliar PPD vs pagos
1. `cfdi_reporte` sobre una carpeta con facturas y complementos de pago (tipo P).
2. Usa `conciliacion_ppd`: por cada PPD, pagos, pagado y saldo; y la lista `ppd_sin_complemento_de_pago` (facturas cobradas o pagadas que pueden necesitar su complemento).
3. Con un estado de cuenta en CSV, usa `cfdi_conciliar_banco`: emparejados, movimientos del banco sin CFDI (pide la factura) y CFDI sin movimiento.

### 5. Reporte de IVA
1. `cfdi_reporte` con `rfc_propio`.
2. Explica las dos cifras: `iva_trasladado` es el IVA facturado (ingresos menos notas de crédito); `iva_flujo` es el IVA de facturas PUE más el de complementos de pago, que es el que se causa (emitidas) o se acredita (recibidas) al cobrar o pagar.
3. IVA a cargo aproximado = `iva_flujo` emitidas − `iva_flujo` recibidas − IVA que te retuvieron tus clientes (en emitidas: `iva_retenido` de PUE + `iva_retenido_pagos`). El IVA que tú retuviste a proveedores (recibidas) no se resta: se entera aparte. Aclara que es un apoyo y la declaración la revisa su contador.
4. Si piden archivo, usa `csv_salida`.

## Límites
No timbra, no cancela, no descarga XML del SAT y no verifica la firma del sello. Los catálogos embebidos son una versión corta del Anexo 20.
