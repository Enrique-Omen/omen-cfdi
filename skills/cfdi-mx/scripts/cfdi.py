#!/usr/bin/env python3
"""OMEN CFDI: leer, validar, consultar en el SAT, reportar y conciliar CFDI de México.

Un solo archivo, solo biblioteca estándar (Python 3.10+).
  CLI:  python3 cfdi.py <herramienta> [opciones]     -> JSON en stdout
  MCP:  python3 cfdi.py mcp                          -> servidor MCP por stdio (JSON-RPC 2.0)
Logs solo a stderr. Hecho por OMEN · https://omen-it.tech
"""
import argparse
import csv
import datetime as dt
import json
import os
import re
import sys
import unicodedata
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation
from xml.sax.saxutils import escape

VERSION = "0.1.0"
NOMBRE = "omen-cfdi"


def log(*a):
    print(f"[{NOMBRE}]", *a, file=sys.stderr, flush=True)


class ErrorUso(Exception):
    """Error que se le explica al usuario tal cual."""


# ---------------------------------------------------------------- catálogos
# Versión corta de los catálogos del Anexo 20 (catCFDI del SAT). No sustituye al catálogo completo.
TIPO = {"I": "Ingreso", "E": "Egreso", "T": "Traslado", "N": "Nómina", "P": "Pago"}
METODO = {"PUE": "Pago en una sola exhibición", "PPD": "Pago en parcialidades o diferido"}
FORMA_PAGO = {
    "01": "Efectivo", "02": "Cheque nominativo", "03": "Transferencia electrónica de fondos",
    "04": "Tarjeta de crédito", "05": "Monedero electrónico", "06": "Dinero electrónico",
    "08": "Vales de despensa", "12": "Dación en pago", "13": "Pago por subrogación",
    "14": "Pago por consignación", "15": "Condonación", "17": "Compensación", "23": "Novación",
    "24": "Confusión", "25": "Remisión de deuda", "26": "Prescripción o caducidad",
    "27": "A satisfacción del acreedor", "28": "Tarjeta de débito", "29": "Tarjeta de servicios",
    "30": "Aplicación de anticipos", "31": "Intermediario pagos", "99": "Por definir",
}
USO_CFDI = {
    "G01": "Adquisición de mercancías", "G02": "Devoluciones, descuentos o bonificaciones",
    "G03": "Gastos en general", "I01": "Construcciones",
    "I02": "Mobiliario y equipo de oficina por inversiones", "I03": "Equipo de transporte",
    "I04": "Equipo de cómputo y accesorios", "I05": "Dados, troqueles, moldes, matrices y herramental",
    "I06": "Comunicaciones telefónicas", "I07": "Comunicaciones satelitales",
    "I08": "Otra maquinaria y equipo", "D01": "Honorarios médicos, dentales y gastos hospitalarios",
    "D02": "Gastos médicos por incapacidad o discapacidad", "D03": "Gastos funerales",
    "D04": "Donativos", "D05": "Intereses reales por créditos hipotecarios (casa habitación)",
    "D06": "Aportaciones voluntarias al SAR", "D07": "Primas por seguros de gastos médicos",
    "D08": "Gastos de transportación escolar obligatoria",
    "D09": "Depósitos en cuentas para el ahorro, primas de pensiones",
    "D10": "Pagos por servicios educativos (colegiaturas)", "S01": "Sin efectos fiscales",
    "CP01": "Pagos", "CN01": "Nómina",
}
REGIMEN = {
    "601": "General de Ley Personas Morales", "603": "Personas Morales con Fines no Lucrativos",
    "605": "Sueldos y Salarios e Ingresos Asimilados a Salarios", "606": "Arrendamiento",
    "607": "Enajenación o Adquisición de Bienes", "608": "Demás ingresos",
    "610": "Residentes en el Extranjero sin Establecimiento Permanente en México",
    "611": "Ingresos por Dividendos", "612": "Personas Físicas con Actividades Empresariales y Profesionales",
    "614": "Ingresos por intereses", "615": "Ingresos por obtención de premios",
    "616": "Sin obligaciones fiscales", "620": "Sociedades Cooperativas de Producción",
    "621": "Incorporación Fiscal", "622": "Actividades Agrícolas, Ganaderas, Silvícolas y Pesqueras",
    "623": "Opcional para Grupos de Sociedades", "624": "Coordinados",
    "625": "Actividades Empresariales a través de Plataformas Tecnológicas",
    "626": "Régimen Simplificado de Confianza",
}
EXPORTACION = {"01": "No aplica", "02": "Definitiva con clave A1", "03": "Temporal",
               "04": "Definitiva con clave distinta a A1 o sin enajenación"}
OBJETO_IMP = {
    "01": "No objeto de impuesto", "02": "Sí objeto de impuesto",
    "03": "Sí objeto, no obligado al desglose", "04": "Sí objeto, no causa impuesto",
    "05": "Sí objeto, IVA crédito PODEBI", "06": "Sí objeto del IVA, no traslado IVA",
    "07": "No traslado del IVA, sí desglose IEPS", "08": "No traslado del IVA, no desglose IEPS",
}
IMPUESTO = {"001": "ISR", "002": "IVA", "003": "IEPS"}
DECIMALES_MONEDA = {"MXN": 2, "USD": 2, "EUR": 2, "CAD": 2, "GBP": 2, "XXX": 0, "JPY": 0, "CLP": 0, "KRW": 0}
RFC_GENERICOS = {"XAXX010101000": "público en general (nacional)", "XEXX010101000": "residente en el extranjero"}

# ---------------------------------------------------------------- namespaces
NS_CFDI = {"http://www.sat.gob.mx/cfd/3": "3.3", "http://www.sat.gob.mx/cfd/4": "4.0"}
NS_TFD = "http://www.sat.gob.mx/TimbreFiscalDigital"
NS_PAGOS = {"http://www.sat.gob.mx/Pagos": "1.0", "http://www.sat.gob.mx/Pagos20": "2.0"}
NS_NOMINA = "http://www.sat.gob.mx/nomina12"
NS_IMPLOCAL = "http://www.sat.gob.mx/implocal"
NS_PREFIJO = {
    NS_TFD: "tfd", "http://www.sat.gob.mx/Pagos": "pago10", "http://www.sat.gob.mx/Pagos20": "pago20",
    NS_NOMINA: "nomina12", "http://www.sat.gob.mx/CartaPorte": "cartaporte",
    "http://www.sat.gob.mx/CartaPorte20": "cartaporte20", "http://www.sat.gob.mx/CartaPorte30": "cartaporte30",
    "http://www.sat.gob.mx/CartaPorte31": "cartaporte31", NS_IMPLOCAL: "implocal",
    "http://www.sat.gob.mx/ComercioExterior11": "cce11", "http://www.sat.gob.mx/ComercioExterior20": "cce20",
    "http://www.sat.gob.mx/leyendasFiscales": "leyendasFisc", "http://www.sat.gob.mx/ine": "ine",
}

RE_RFC = re.compile(r"^[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}$")
RE_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
RE_FECHA = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")

NOTA_FIRMA = ("Esta revisión NO verifica la firma criptográfica del sello ni el certificado del emisor: "
              "eso solo lo hace el SAT. Para saber si el CFDI existe y está vigente usa cfdi_estatus_sat.")


def ln(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def ns(tag):
    return tag[1:].split("}", 1)[0] if isinstance(tag, str) and tag.startswith("{") else ""


def chs(el, nombre, espacios=None):
    """Hijos directos con nombre local `nombre` (y namespace en `espacios`, por defecto los de cfdi)."""
    if el is None:
        return []
    espacios = NS_CFDI if espacios is None else espacios
    return [c for c in el if ln(c.tag) == nombre and ns(c.tag) in espacios]


def ch(el, nombre, espacios=None):
    h = chs(el, nombre, espacios)
    return h[0] if h else None


def D(v):
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def D0(v):
    d = D(v)
    return d if d is not None else Decimal(0)


def decs(v):
    s = str(v or "")
    return len(s.split(".", 1)[1]) if "." in s else 0


def unidad_moneda(moneda):
    return Decimal(1).scaleb(-DECIMALES_MONEDA.get(moneda or "MXN", 2))


def tasa_txt(t):
    d = D(t)
    return f"{d:.6f}" if d is not None else (t or "")


# ---------------------------------------------------------------- carga
def cargar(ruta=None, xml=None):
    if ruta:
        if not os.path.isfile(ruta):
            raise ErrorUso(f"No existe el archivo: {ruta}")
        with open(ruta, "rb") as f:
            datos = f.read()
        if datos.startswith(b"\xef\xbb\xbf"):
            datos = datos[3:]
    elif xml:
        datos = re.sub(r"^\s*<\?xml[^>]*\?>", "", xml.lstrip("﻿")) if isinstance(xml, str) else xml
    else:
        raise ErrorUso("Falta `ruta` (archivo .xml) o `xml` (texto del CFDI).")
    _sin_dtd(datos)
    try:
        raiz = ET.fromstring(datos)
    except ET.ParseError as e:
        raise ErrorUso(f"El XML no se pudo leer (mal formado): {e}")
    if ln(raiz.tag) != "Comprobante" or ns(raiz.tag) not in NS_CFDI:
        raise ErrorUso("No es un CFDI: el nodo raíz debe ser cfdi:Comprobante (versión 3.3 o 4.0).")
    return raiz


# ---------------------------------------------------------------- 1. leer
def _impuesto(t, sufijo=""):
    imp = t.get("Impuesto" + sufijo)
    return {
        "base": D(t.get("Base" + sufijo)), "impuesto": imp, "impuesto_nombre": IMPUESTO.get(imp, imp),
        "tipo_factor": t.get("TipoFactor" + sufijo), "tasa_o_cuota": tasa_txt(t.get("TasaOCuota" + sufijo)) or None,
        "importe": D(t.get("Importe" + sufijo)),
    }


def _impuestos_de(el):
    imp = ch(el, "Impuestos")
    return ([_impuesto(t) for t in chs(ch(imp, "Traslados"), "Traslado")],
            [_impuesto(t) for t in chs(ch(imp, "Retenciones"), "Retencion")], imp)


def _resumen_impuestos(traslados, retenciones):
    r = {"iva_trasladado_por_tasa": {}, "ieps_trasladado_por_tasa": {}, "iva_trasladado": Decimal(0),
         "ieps_trasladado": Decimal(0), "iva_retenido": Decimal(0), "isr_retenido": Decimal(0),
         "ieps_retenido": Decimal(0)}
    for t in traslados:
        if t["importe"] is None:
            continue
        if t["impuesto"] in ("002", "003"):
            nombre = "iva" if t["impuesto"] == "002" else "ieps"
            clave = f"{t['tipo_factor']} {t['tasa_o_cuota']}" if t["tipo_factor"] != "Tasa" else t["tasa_o_cuota"]
            por = r[f"{nombre}_trasladado_por_tasa"]
            por[clave] = por.get(clave, Decimal(0)) + t["importe"]
            r[f"{nombre}_trasladado"] += t["importe"]
    for t in retenciones:
        nombre = {"001": "isr", "002": "iva", "003": "ieps"}.get(t["impuesto"])
        if nombre and t["importe"] is not None:
            r[f"{nombre}_retenido"] += t["importe"]
    return r


def _pagos(comp_el):
    a = comp_el.attrib
    espacio = {ns(comp_el.tag)}
    tot = ch(comp_el, "Totales", espacio)
    pagos = []
    for p in chs(comp_el, "Pago", espacio):
        docs = []
        for d in chs(p, "DoctoRelacionado", espacio):
            docs.append({
                "id_documento": (d.get("IdDocumento") or "").upper(), "serie": d.get("Serie"),
                "folio": d.get("Folio"), "moneda": d.get("MonedaDR"),
                "equivalencia": D(d.get("EquivalenciaDR") or d.get("TipoCambioDR")),
                "num_parcialidad": d.get("NumParcialidad"), "saldo_anterior": D(d.get("ImpSaldoAnt")),
                "pagado": D(d.get("ImpPagado")), "saldo_insoluto": D(d.get("ImpSaldoInsoluto")),
                "objeto_imp": d.get("ObjetoImpDR"),
            })
        pagos.append({
            "fecha": p.get("FechaPago"), "forma": p.get("FormaDePagoP"),
            "forma_nombre": FORMA_PAGO.get(p.get("FormaDePagoP")), "moneda": p.get("MonedaP"),
            "tipo_cambio": D(p.get("TipoCambioP")), "monto": D(p.get("Monto")),
            "num_operacion": p.get("NumOperacion"), "documentos": docs,
        })
    totales = {ln(k): D(v) for k, v in tot.attrib.items()} if tot is not None else {}
    return {"version": a.get("Version") or NS_PAGOS.get(ns(comp_el.tag)), "totales": totales, "pagos": pagos}


def leer_raiz(raiz):
    a = raiz.attrib
    em, rc = ch(raiz, "Emisor"), ch(raiz, "Receptor")
    em = em.attrib if em is not None else {}
    rc = rc.attrib if rc is not None else {}
    conceptos = []
    for c in chs(ch(raiz, "Conceptos"), "Concepto"):
        tras, ret, _ = _impuestos_de(c)
        conceptos.append({
            "clave_prod_serv": c.get("ClaveProdServ"), "no_identificacion": c.get("NoIdentificacion"),
            "cantidad": D(c.get("Cantidad")), "clave_unidad": c.get("ClaveUnidad"), "unidad": c.get("Unidad"),
            "descripcion": c.get("Descripcion"), "valor_unitario": D(c.get("ValorUnitario")),
            "importe": D(c.get("Importe")), "descuento": D(c.get("Descuento")),
            "objeto_imp": c.get("ObjetoImp"), "traslados": tras, "retenciones": ret,
        })
    tras_g, ret_g, imp_g = _impuestos_de(raiz)
    if imp_g is None:  # sin nodo global: se suma desde los conceptos
        tras_res = [t for c in conceptos for t in c["traslados"]]
        ret_res = [t for c in conceptos for t in c["retenciones"]]
    else:
        tras_res, ret_res = tras_g, ret_g
    impuestos = {
        "total_trasladados": D(imp_g.get("TotalImpuestosTrasladados")) if imp_g is not None else None,
        "total_retenidos": D(imp_g.get("TotalImpuestosRetenidos")) if imp_g is not None else None,
        "traslados": tras_g, "retenciones": ret_g, **_resumen_impuestos(tras_res, ret_res),
    }
    relacionados = []
    for r in chs(raiz, "CfdiRelacionados"):
        relacionados.append({"tipo_relacion": r.get("TipoRelacion"),
                             "uuids": [(x.get("UUID") or "").upper() for x in chs(r, "CfdiRelacionado")]})
    tfd, pagos, nomina, implocal, complementos = None, None, None, None, []
    for comp in chs(raiz, "Complemento"):
        for x in comp:
            espacio = ns(x.tag)
            complementos.append(f"{NS_PREFIJO.get(espacio, espacio or '?')}:{ln(x.tag)}")
            if espacio == NS_TFD and ln(x.tag) == "TimbreFiscalDigital":
                tfd = x.attrib
            elif espacio in NS_PAGOS and ln(x.tag) == "Pagos":
                pagos = _pagos(x)
            elif espacio == NS_NOMINA and ln(x.tag) == "Nomina":
                nomina = {k: x.get(k) for k in ("Version", "TipoNomina", "FechaPago", "FechaInicialPago",
                                                "FechaFinalPago", "NumDiasPagados", "TotalPercepciones",
                                                "TotalDeducciones", "TotalOtrosPagos") if x.get(k) is not None}
            elif espacio == NS_IMPLOCAL:
                implocal = {"total_traslados": D0(x.get("TotaldeTraslados")),
                            "total_retenciones": D0(x.get("TotaldeRetenciones"))}
    sello = a.get("Sello") or ""
    tipo = a.get("TipoDeComprobante")
    return {
        "version": a.get("Version") or NS_CFDI[ns(raiz.tag)], "tipo": tipo, "tipo_nombre": TIPO.get(tipo),
        "serie": a.get("Serie"), "folio": a.get("Folio"), "fecha": a.get("Fecha"),
        "lugar_expedicion": a.get("LugarExpedicion"),
        "uuid": (tfd.get("UUID") or "").upper() if tfd else None,
        "fecha_timbrado": tfd.get("FechaTimbrado") if tfd else None,
        "rfc_prov_certif": tfd.get("RfcProvCertif") if tfd else None,
        "emisor": {"rfc": (em.get("Rfc") or "").upper(), "nombre": em.get("Nombre"),
                   "regimen": em.get("RegimenFiscal"), "regimen_nombre": REGIMEN.get(em.get("RegimenFiscal"))},
        "receptor": {"rfc": (rc.get("Rfc") or "").upper(), "nombre": rc.get("Nombre"),
                     "uso_cfdi": rc.get("UsoCFDI"), "uso_cfdi_nombre": USO_CFDI.get(rc.get("UsoCFDI")),
                     "regimen": rc.get("RegimenFiscalReceptor"), "cp": rc.get("DomicilioFiscalReceptor"),
                     "residencia_fiscal": rc.get("ResidenciaFiscal"), "num_reg_id_trib": rc.get("NumRegIdTrib")},
        "moneda": a.get("Moneda"), "tipo_cambio": D(a.get("TipoCambio")),
        "subtotal": D(a.get("SubTotal")), "descuento": D(a.get("Descuento")), "total": D(a.get("Total")),
        "metodo_pago": a.get("MetodoPago"), "forma_pago": a.get("FormaPago"),
        "forma_pago_nombre": FORMA_PAGO.get(a.get("FormaPago")), "exportacion": a.get("Exportacion"),
        "condiciones_pago": a.get("CondicionesDePago"),
        "conceptos": conceptos, "impuestos": impuestos, "impuestos_locales": implocal,
        "cfdi_relacionados": relacionados, "complementos": complementos, "pagos": pagos, "nomina": nomina,
        "sello_ultimos8": sello[-8:] if sello else None,
    }


def cfdi_leer(ruta=None, xml=None):
    return leer_raiz(cargar(ruta, xml))


# ---------------------------------------------------------------- 2. validar
REQ = {
    "4.0": {"Comprobante": ["Version", "Fecha", "Sello", "NoCertificado", "Certificado", "SubTotal", "Moneda",
                            "Total", "TipoDeComprobante", "Exportacion", "LugarExpedicion"],
            "Emisor": ["Rfc", "Nombre", "RegimenFiscal"],
            "Receptor": ["Rfc", "Nombre", "DomicilioFiscalReceptor", "RegimenFiscalReceptor", "UsoCFDI"],
            "Concepto": ["ClaveProdServ", "Cantidad", "ClaveUnidad", "Descripcion", "ValorUnitario", "Importe",
                         "ObjetoImp"]},
    "3.3": {"Comprobante": ["Version", "Fecha", "Sello", "NoCertificado", "Certificado", "SubTotal", "Moneda",
                            "Total", "TipoDeComprobante", "LugarExpedicion"],
            "Emisor": ["Rfc", "RegimenFiscal"], "Receptor": ["Rfc", "UsoCFDI"],
            "Concepto": ["ClaveProdServ", "Cantidad", "ClaveUnidad", "Descripcion", "ValorUnitario", "Importe"]},
}


def _rfc(r, quien, rfc):
    if not rfc:
        return
    if rfc in RFC_GENERICOS:
        r("aviso", "rfc_generico", f"RFC del {quien} es genérico ({RFC_GENERICOS[rfc]}): {rfc}.")
        return
    if not RE_RFC.match(rfc):
        r("error", "rfc_formato", f"RFC del {quien} con formato inválido: {rfc} (persona moral: 12 caracteres, "
                                  "física: 13).")
        return
    try:
        dt.datetime.strptime(rfc[-9:-3], "%y%m%d")
    except ValueError:
        r("aviso", "rfc_fecha", f"RFC del {quien} {rfc}: la fecha {rfc[-9:-3]} no es válida.")


def validar_raiz(raiz):
    rev = []

    def r(nivel, codigo, mensaje):
        rev.append({"nivel": nivel, "codigo": codigo, "mensaje": mensaje})

    a = raiz.attrib
    version = a.get("Version") or ""
    if version not in REQ:
        r("error", "version", f"Versión «{version}» no reconocida (se esperaba 4.0).")
        version = NS_CFDI[ns(raiz.tag)]
    elif version == "3.3":
        r("aviso", "version_33", "CFDI 3.3: ya no se puede emitir desde abril de 2023; solo válido para comprobantes viejos.")
    if NS_CFDI[ns(raiz.tag)] != version:
        r("error", "namespace", f"El namespace es de CFDI {NS_CFDI[ns(raiz.tag)]} pero Version dice {version}.")
    req = REQ[version]
    nodos = {"Comprobante": [raiz], "Emisor": chs(raiz, "Emisor"), "Receptor": chs(raiz, "Receptor"),
             "Concepto": chs(ch(raiz, "Conceptos"), "Concepto")}
    for nodo, attrs in req.items():
        if not nodos[nodo]:
            r("error", "falta_nodo", f"Falta el nodo cfdi:{nodo}.")
        for i, el in enumerate(nodos[nodo], 1):
            falta = [x for x in attrs if not (el.get(x) or "").strip()]
            if falta:
                donde = f"{nodo} {i}" if nodo == "Concepto" else nodo
                r("error", "falta_atributo", f"{donde}: faltan atributos obligatorios {', '.join(falta)}.")

    info = leer_raiz(raiz)
    tipo, moneda = info["tipo"], info["moneda"] or ""
    u = unidad_moneda(moneda)

    # catálogos
    for valor, cat, campo in ((tipo, TIPO, "TipoDeComprobante"), (info["metodo_pago"], METODO, "MetodoPago"),
                              (info["forma_pago"], FORMA_PAGO, "FormaPago"),
                              (info["emisor"]["regimen"], REGIMEN, "RegimenFiscal del emisor"),
                              (info["receptor"]["regimen"], REGIMEN, "RegimenFiscalReceptor"),
                              (info["exportacion"], EXPORTACION, "Exportacion")):
        if valor and valor not in cat:
            r("error", "catalogo", f"{campo} «{valor}» no está en el catálogo del SAT.")
    uso = info["receptor"]["uso_cfdi"]
    if uso and uso not in USO_CFDI and not (version == "3.3" and uso == "P01"):
        r("error", "catalogo", f"UsoCFDI «{uso}» no está en el catálogo de CFDI {version}.")
    if moneda and not re.match(r"^[A-Z]{3}$", moneda):
        r("error", "moneda", f"Moneda «{moneda}» no tiene formato ISO 4217.")
    if info["fecha"] and not RE_FECHA.match(info["fecha"]):
        r("error", "fecha", f"Fecha «{info['fecha']}» no tiene el formato AAAA-MM-DDThh:mm:ss.")
    if info["lugar_expedicion"] and not re.match(r"^\d{5}$", info["lugar_expedicion"]):
        r("error", "lugar_expedicion", "LugarExpedicion debe ser un código postal de 5 dígitos.")
    cp = info["receptor"]["cp"]
    if cp is not None and not re.match(r"^\d{5}$", cp):
        r("error", "cp_receptor", f"DomicilioFiscalReceptor «{cp}» debe ser un código postal de 5 dígitos.")

    # RFC
    _rfc(r, "emisor", info["emisor"]["rfc"])
    _rfc(r, "receptor", info["receptor"]["rfc"])
    if info["emisor"]["rfc"] in RFC_GENERICOS:
        r("error", "rfc_generico_emisor", "El emisor no puede usar un RFC genérico.")
    rr = info["receptor"]["rfc"]
    if tipo == "P" and uso and uso != "CP01" and version == "4.0":
        r("error", "uso_pago", f"Complemento de pago: UsoCFDI debe ser CP01 (trae {uso}).")
    elif tipo == "N" and uso and uso != "CN01" and version == "4.0":
        r("error", "uso_nomina", f"Nómina: UsoCFDI debe ser CN01 (trae {uso}).")
    elif rr in RFC_GENERICOS and version == "4.0":
        if uso and uso != "S01":
            r("error", "generico_uso", f"Receptor genérico {rr}: UsoCFDI debe ser S01 (trae {uso}).")
        if info["receptor"]["regimen"] and info["receptor"]["regimen"] != "616":
            r("error", "generico_regimen",
              f"Receptor genérico {rr}: RegimenFiscalReceptor debe ser 616 (trae {info['receptor']['regimen']}).")
        if rr == "XAXX010101000" and cp and info["lugar_expedicion"] and cp != info["lugar_expedicion"]:
            r("error", "generico_cp", "Receptor XAXX010101000: DomicilioFiscalReceptor debe ser igual a LugarExpedicion.")

    # timbre y UUID
    if not info["uuid"]:
        r("error", "sin_timbre", "No trae TimbreFiscalDigital: no está timbrado, no es un CFDI válido ante el SAT.")
    elif not RE_UUID.match(info["uuid"]):
        r("error", "uuid_formato", f"UUID con formato inválido: {info['uuid']}.")
    if not info["sello_ultimos8"]:
        r("error", "sin_sello", "No trae Sello.")

    # moneda y tipo de cambio
    if moneda not in ("MXN", "XXX", "") and info["tipo_cambio"] is None:
        r("error", "tipo_cambio", f"Moneda {moneda}: falta TipoCambio.")
    if moneda == "MXN" and info["tipo_cambio"] not in (None, Decimal(1)):
        r("error", "tipo_cambio", "Moneda MXN: TipoCambio debe ser 1 o no ir.")

    # método y forma de pago
    mp, fp = info["metodo_pago"], info["forma_pago"]
    if tipo in ("P", "T"):
        if moneda != "XXX":
            r("error", "moneda_pt", f"Tipo {tipo}: Moneda debe ser XXX (trae {moneda}).")
        if (info["subtotal"] or 0) != 0 or (info["total"] or 0) != 0:
            r("error", "subtotal_pt", f"Tipo {tipo}: SubTotal y Total deben ser 0.")
        if mp or fp:
            r("error", "pago_pt", f"Tipo {tipo}: no lleva MetodoPago ni FormaPago.")
    else:
        if mp == "PPD" and fp and fp != "99":
            r("error", "ppd_forma", f"MetodoPago PPD con FormaPago {fp}: en PPD la forma debe ser 99 (Por definir); "
                                    "la forma real va en el complemento de pago.")
        if mp == "PUE" and fp == "99":
            r("error", "pue_forma", "MetodoPago PUE con FormaPago 99: en PUE hay que poner la forma real de pago.")
        if tipo in ("I", "E") and not mp:
            r("aviso", "sin_metodo", "No trae MetodoPago.")
        if tipo in ("I", "E") and not fp:
            r("aviso", "sin_forma", "No trae FormaPago.")

    # conceptos
    n = len(info["conceptos"])
    suma_imp, suma_desc = Decimal(0), Decimal(0)
    grupos_t, grupos_r = {}, {}
    for i, c in enumerate(info["conceptos"], 1):
        suma_imp += c["importe"] or 0
        suma_desc += c["descuento"] or 0
        oi = c["objeto_imp"]
        if oi and oi not in OBJETO_IMP:
            r("error", "catalogo", f"Concepto {i}: ObjetoImp «{oi}» no está en el catálogo.")
        tiene = bool(c["traslados"] or c["retenciones"])
        if oi == "02" and not tiene:
            r("error", "objeto_imp", f"Concepto {i}: ObjetoImp 02 (sí objeto) pero no desglosa impuestos.")
        if oi == "01" and tiene:
            r("error", "objeto_imp", f"Concepto {i}: ObjetoImp 01 (no objeto) pero trae impuestos.")
        cant, vu, imp = c["cantidad"], c["valor_unitario"], c["importe"]
        if None not in (cant, vu, imp):
            tol = Decimal("0.5") * (Decimal(1).scaleb(-decs(cant)) * vu + Decimal(1).scaleb(-decs(vu)) * cant) + u
            if abs(cant * vu - imp) > tol:
                r("aviso", "importe_concepto",
                  f"Concepto {i}: Importe {imp} ≠ Cantidad × ValorUnitario ({cant * vu:.2f}).")
        for t in c["traslados"]:
            k = (t["impuesto"], t["tipo_factor"], t["tasa_o_cuota"])
            g = grupos_t.setdefault(k, [Decimal(0), Decimal(0), 0])
            g[0] += t["base"] or 0
            g[1] += t["importe"] or 0
            g[2] += 1
            if t["tipo_factor"] == "Tasa" and None not in (t["base"], t["importe"], D(t["tasa_o_cuota"])):
                esperado = t["base"] * D(t["tasa_o_cuota"])
                if abs(esperado - t["importe"]) > max(u, Decimal("0.01")):
                    r("aviso", "traslado_concepto", f"Concepto {i}: traslado {t['impuesto_nombre']} {t['importe']} "
                                                    f"≠ Base × Tasa ({esperado:.2f}).")
        for t in c["retenciones"]:
            g = grupos_r.setdefault(t["impuesto"], [Decimal(0), 0])
            g[0] += t["importe"] or 0
            g[1] += 1
    tol_n = u * max(1, n)
    sub = info["subtotal"]
    if sub is not None and n and tipo not in ("P",) and abs(suma_imp - sub) > tol_n:
        r("error", "subtotal", f"SubTotal {sub} ≠ suma de importes de conceptos {suma_imp}.")
    desc = info["descuento"] or Decimal(0)
    if abs(suma_desc - desc) > tol_n:
        r("error", "descuento", f"Descuento {desc} ≠ suma de descuentos de conceptos {suma_desc}.")

    # impuestos globales vs conceptos
    imp = info["impuestos"]
    if version == "4.0" and (grupos_t or grupos_r) and ch(raiz, "Impuestos") is None:
        r("error", "impuestos_globales", "Los conceptos traen impuestos pero falta el nodo cfdi:Impuestos global.")
    if ch(raiz, "Impuestos") is not None:
        glob_t = {(t["impuesto"], t["tipo_factor"], t["tasa_o_cuota"]): t for t in imp["traslados"]}
        for k, (base, importe, cuenta) in grupos_t.items():
            g = glob_t.get(k)
            nombre = f"{IMPUESTO.get(k[0], k[0])} {k[1]} {k[2] or ''}".strip()
            if g is None:
                r("error", "impuestos_globales", f"Falta en Impuestos globales el traslado {nombre}.")
                continue
            if k[1] != "Exento" and g["importe"] is not None and abs(g["importe"] - importe) > u * max(1, cuenta):
                r("error", "impuestos_globales",
                  f"Traslado {nombre}: global {g['importe']} ≠ suma por concepto {importe}.")
            if g["base"] is not None and abs(g["base"] - base) > u * max(1, cuenta):
                r("aviso", "base_global", f"Traslado {nombre}: Base global {g['base']} ≠ suma por concepto {base}.")
        for k in glob_t:
            if k not in grupos_t:
                r("error", "impuestos_globales", f"Impuestos globales trae un traslado {k} que ningún concepto tiene.")
        glob_r = {}
        for t in imp["retenciones"]:
            glob_r[t["impuesto"]] = glob_r.get(t["impuesto"], Decimal(0)) + (t["importe"] or 0)
        for k, (importe, cuenta) in grupos_r.items():
            if abs(glob_r.get(k, Decimal(0)) - importe) > u * max(1, cuenta):
                r("error", "impuestos_globales", f"Retención {IMPUESTO.get(k, k)}: global {glob_r.get(k, 0)} "
                                                 f"≠ suma por concepto {importe}.")
        sum_t = sum((t["importe"] or 0) for t in imp["traslados"])
        sum_r = sum((t["importe"] or 0) for t in imp["retenciones"])
        if imp["total_trasladados"] is not None and abs(imp["total_trasladados"] - sum_t) > u:
            r("error", "total_trasladados", f"TotalImpuestosTrasladados {imp['total_trasladados']} ≠ suma {sum_t}.")
        if imp["total_retenidos"] is not None and abs(imp["total_retenidos"] - sum_r) > u:
            r("error", "total_retenidos", f"TotalImpuestosRetenidos {imp['total_retenidos']} ≠ suma {sum_r}.")

    # total
    if sub is not None and info["total"] is not None and tipo not in ("P", "T"):
        if ch(raiz, "Impuestos") is not None:
            tras = imp["total_trasladados"] or Decimal(0)
            ret = imp["total_retenidos"] or Decimal(0)
        else:
            tras = sum(g[1] for g in grupos_t.values()) if grupos_t else Decimal(0)
            ret = sum(g[0] for g in grupos_r.values()) if grupos_r else Decimal(0)
        loc = info["impuestos_locales"] or {"total_traslados": 0, "total_retenciones": 0}
        esperado = sub - desc + tras - ret + loc["total_traslados"] - loc["total_retenciones"]
        if abs(esperado - info["total"]) > tol_n:
            r("error", "total", f"Total {info['total']} ≠ SubTotal − Descuento + Trasladados − Retenidos "
                                f"= {sub} − {desc} + {tras} − {ret} = {esperado}.")

    # complemento de pagos
    if tipo == "P":
        if not info["pagos"]:
            r("error", "sin_complemento_pago", "Tipo P sin complemento de pagos (pago20:Pagos).")
        else:
            for i, p in enumerate(info["pagos"]["pagos"], 1):
                if p["forma"] == "99":
                    r("error", "pago_forma", f"Pago {i}: FormaDePagoP no puede ser 99.")
                suma = Decimal(0)
                for d in p["documentos"]:
                    if d["id_documento"] and not RE_UUID.match(d["id_documento"]):
                        r("aviso", "pago_docto", f"Pago {i}: IdDocumento {d['id_documento']} no tiene formato de UUID.")
                    if None not in (d["saldo_anterior"], d["pagado"], d["saldo_insoluto"]):
                        if abs(d["saldo_anterior"] - d["pagado"] - d["saldo_insoluto"]) > Decimal("0.01"):
                            r("error", "pago_saldo", f"Pago {i}, documento {d['id_documento']}: "
                                                     f"SaldoAnt {d['saldo_anterior']} − Pagado {d['pagado']} "
                                                     f"≠ SaldoInsoluto {d['saldo_insoluto']}.")
                        if d["saldo_insoluto"] < 0:
                            r("error", "pago_saldo", f"Pago {i}: saldo insoluto negativo en {d['id_documento']}.")
                    suma += (d["pagado"] or 0) / (d["equivalencia"] or 1)
                if p["monto"] is not None and suma - p["monto"] > Decimal("0.01") * max(1, len(p["documentos"])):
                    r("error", "pago_monto", f"Pago {i}: lo pagado a documentos ({suma:.2f}) es mayor que Monto {p['monto']}.")

    errores = sum(1 for x in rev if x["nivel"] == "error")
    return {
        "valido": errores == 0, "errores": errores, "avisos": len(rev) - errores, "revisiones": rev,
        "resumen": {"uuid": info["uuid"], "tipo": tipo, "emisor": info["emisor"]["rfc"],
                    "receptor": info["receptor"]["rfc"], "total": info["total"], "moneda": moneda},
        "firma_verificada": False, "nota_firma": NOTA_FIRMA,
    }


def cfdi_validar(ruta=None, xml=None):
    try:
        raiz = cargar(ruta, xml)
    except ErrorUso as e:
        return {"valido": False, "errores": 1, "avisos": 0,
                "revisiones": [{"nivel": "error", "codigo": "estructura", "mensaje": str(e)}],
                "firma_verificada": False, "nota_firma": NOTA_FIRMA}
    return validar_raiz(raiz)


# ---------------------------------------------------------------- 3. estatus SAT
URL_SAT = "https://consultaqr.facturaelectronica.sat.gob.mx/ConsultaCFDIService.svc"
SOAP_ACTION = "http://tempuri.org/IConsultaCFDIService/Consulta"
UA = f"OMEN-CFDI/{VERSION} (+https://omen-it.tech)"


def expresion_impresa(uuid, rfc_emisor, rfc_receptor, total, sello8=None):
    e = f"?re={rfc_emisor}&rr={rfc_receptor}&tt={total}&id={uuid}"
    return e + (f"&fe={sello8}" if sello8 else "")


def sobre_soap(expresion):
    return ('<?xml version="1.0" encoding="utf-8"?>'
            '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
            'xmlns:tem="http://tempuri.org/"><soapenv:Header/><soapenv:Body><tem:Consulta>'
            f'<tem:expresionImpresa>{escape(expresion)}</tem:expresionImpresa>'
            '</tem:Consulta></soapenv:Body></soapenv:Envelope>')


def leer_respuesta_sat(texto):
    _sin_dtd(texto)
    raiz = ET.fromstring(texto)
    campos = {}
    for el in raiz.iter():
        nombre = ln(el.tag)
        if nombre in ("CodigoEstatus", "Estado", "EsCancelable", "EstatusCancelacion", "ValidacionEFOS"):
            campos[nombre] = (el.text or "").strip()
    falla = next((el.text for el in raiz.iter() if ln(el.tag) == "faultstring"), None)
    if falla and not campos:
        raise ErrorUso(f"El SAT respondió con un error SOAP: {falla}")
    return campos


def lectura_sat(c):
    estado = c.get("Estado", "")
    partes = []
    if estado == "Vigente":
        partes.append("El SAT reporta el CFDI como VIGENTE.")
    elif estado == "Cancelado":
        partes.append("El SAT reporta el CFDI como CANCELADO: no lo uses para deducir ni acreditar.")
    elif estado:
        partes.append(f"El SAT responde «{estado}»: revisa UUID, RFC y total (o el CFDI es muy reciente).")
    if c.get("EsCancelable"):
        partes.append(f"Cancelación: {c['EsCancelable']}.")
    if c.get("EstatusCancelacion"):
        partes.append(f"Estatus de cancelación: {c['EstatusCancelacion']}.")
    # Lectura de ValidacionEFOS según https://github.com/phpcfdi/sat-estado-cfdi (README):
    # 200 o 201 = el emisor NO está en el listado de EFOS; cualquier otro valor reportado = sí está.
    efos = c.get("ValidacionEFOS")
    if efos in ("200", "201"):
        partes.append(f"ValidacionEFOS {efos}: el SAT no reporta al emisor en el listado de EFOS.")
    elif efos:
        partes.append(f"ValidacionEFOS {efos}: el SAT reporta al emisor en el listado de EFOS (operaciones "
                      "simuladas). No pagues ni deduzcas sin revisarlo con tu contador.")
    return " ".join(partes) or f"Respuesta del SAT: {c.get('CodigoEstatus', 'sin datos')}."


def cfdi_estatus_sat(ruta=None, xml=None, uuid=None, rfc_emisor=None, rfc_receptor=None, total=None,
                     sello8=None, timeout=20):
    if ruta or xml:
        raiz = cargar(ruta, xml)
        info = leer_raiz(raiz)
        uuid, rfc_emisor, rfc_receptor = info["uuid"], info["emisor"]["rfc"], info["receptor"]["rfc"]
        total, sello8 = raiz.get("Total"), info["sello_ultimos8"]
    falta = [k for k, v in (("uuid", uuid), ("rfc_emisor", rfc_emisor), ("rfc_receptor", rfc_receptor),
                            ("total", total)) if not v]
    if falta:
        raise ErrorUso(f"Faltan datos para consultar al SAT: {', '.join(falta)} (o pasa `ruta`/`xml`).")
    expresion = expresion_impresa(str(uuid).upper(), str(rfc_emisor).upper(), str(rfc_receptor).upper(),
                                  total, sello8)
    req = urllib.request.Request(URL_SAT, data=sobre_soap(expresion).encode("utf-8"), method="POST", headers={
        "Content-Type": "text/xml; charset=utf-8", "SOAPAction": f'"{SOAP_ACTION}"', "User-Agent": UA})
    log("consulta SAT", uuid)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            texto, http = resp.read(), resp.status
    except urllib.error.HTTPError as e:
        texto, http = e.read(), e.code
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return {"consultado": False, "expresion_impresa": expresion,
                "error": f"No se pudo conectar con el SAT ({e}). La consulta necesita red."}
    try:
        campos = leer_respuesta_sat(texto)
    except (ET.ParseError, ErrorUso) as e:
        return {"consultado": False, "http": http, "expresion_impresa": expresion,
                "error": f"Respuesta del SAT no legible: {e}"}
    return {"consultado": True, "http": http, "expresion_impresa": expresion, **campos,
            "lectura": lectura_sat(campos)}


# ---------------------------------------------------------------- 4. reporte
def _xmls(carpeta):
    if not carpeta or not os.path.isdir(carpeta):
        raise ErrorUso(f"No existe la carpeta: {carpeta}")
    for base, _, archivos in os.walk(carpeta):
        for a in sorted(archivos):
            if a.lower().endswith(".xml"):
                yield os.path.join(base, a)


def _cargar_carpeta(carpeta):
    leidos, fallas = [], []
    for ruta in sorted(_xmls(carpeta)):
        try:
            leidos.append((ruta, leer_raiz(cargar(ruta))))
        except ErrorUso as e:
            fallas.append({"archivo": ruta, "motivo": str(e)})
    return leidos, fallas


def _fila(ruta, c, rfc_propio):
    tc = c["tipo_cambio"] or Decimal(1)
    imp = c["impuestos"]
    iva_t, iva_r, isr_r = imp["iva_trasladado"], imp["iva_retenido"], imp["isr_retenido"]
    monto_pagos = Decimal(0)
    if c["tipo"] == "P" and c["pagos"]:
        tot = c["pagos"]["totales"]
        iva_t = sum((tot.get(k) or 0) for k in ("TotalTrasladosImpuestoIVA16", "TotalTrasladosImpuestoIVA8"))
        iva_r, isr_r = tot.get("TotalRetencionesIVA") or 0, tot.get("TotalRetencionesISR") or 0
        monto_pagos = tot.get("MontoTotalPagos") or sum(
            (p["monto"] or 0) * (p["tipo_cambio"] or 1) for p in c["pagos"]["pagos"])
        tc = Decimal(1)  # los Totales de pagos 2.0 ya vienen en MXN
    direccion = None
    if rfc_propio:
        direccion = ("emitida" if c["emisor"]["rfc"] == rfc_propio else
                     "recibida" if c["receptor"]["rfc"] == rfc_propio else "ajena")
    return {
        "archivo": ruta, "fecha": c["fecha"], "uuid": c["uuid"], "tipo": c["tipo"], "serie": c["serie"],
        "folio": c["folio"], "emisor_rfc": c["emisor"]["rfc"], "emisor_nombre": c["emisor"]["nombre"],
        "receptor_rfc": c["receptor"]["rfc"], "receptor_nombre": c["receptor"]["nombre"],
        "metodo_pago": c["metodo_pago"], "forma_pago": c["forma_pago"], "moneda": c["moneda"],
        "tipo_cambio": c["tipo_cambio"], "subtotal": c["subtotal"], "total": c["total"],
        "iva_trasladado": iva_t * tc, "iva_retenido": iva_r * tc, "isr_retenido": isr_r * tc,
        "total_mxn": (c["total"] or 0) * tc, "monto_pagos_mxn": monto_pagos, "direccion": direccion,
    }


def _suma(acc, f):
    signo = -1 if f["tipo"] == "E" else 1
    acc["cfdi"] += 1
    if f["tipo"] in ("I", "E"):
        acc["total_mxn"] += signo * f["total_mxn"]
        acc["iva_trasladado"] += signo * f["iva_trasladado"]
        acc["iva_retenido"] += signo * f["iva_retenido"]
        acc["isr_retenido"] += signo * f["isr_retenido"]
        if f["metodo_pago"] == "PUE":
            acc["iva_flujo"] += signo * f["iva_trasladado"]
    elif f["tipo"] == "P":
        acc["pagos_mxn"] += f["monto_pagos_mxn"]
        acc["iva_flujo"] += f["iva_trasladado"]
        acc["iva_retenido_pagos"] += f["iva_retenido"]
        acc["isr_retenido_pagos"] += f["isr_retenido"]


def _acc():
    return {"cfdi": 0, "total_mxn": Decimal(0), "iva_trasladado": Decimal(0), "iva_retenido": Decimal(0),
            "isr_retenido": Decimal(0), "pagos_mxn": Decimal(0), "iva_flujo": Decimal(0),
            "iva_retenido_pagos": Decimal(0), "isr_retenido_pagos": Decimal(0)}


def conciliar_ppd(leidos):
    vistos, pagos_por_doc, conocidos = set(), {}, set()
    for ruta, c in leidos:
        if c["tipo"] == "I":
            conocidos.add(c["uuid"])
        if c["tipo"] != "P" or not c["pagos"] or c["uuid"] in vistos:
            continue
        vistos.add(c["uuid"])
        for p in c["pagos"]["pagos"]:
            for d in p["documentos"]:
                pagos_por_doc.setdefault(d["id_documento"], []).append({
                    "uuid_pago": c["uuid"], "fecha": p["fecha"], "parcialidad": d["num_parcialidad"],
                    "saldo_anterior": d["saldo_anterior"], "pagado": d["pagado"],
                    "saldo_insoluto": d["saldo_insoluto"]})
    ppd, sin_pago, ya = [], [], set()
    for ruta, c in leidos:
        if c["tipo"] != "I" or c["metodo_pago"] != "PPD" or c["uuid"] in ya:
            continue
        ya.add(c["uuid"])
        pagos = sorted(pagos_por_doc.get(c["uuid"], []), key=lambda x: x["fecha"] or "")
        pagado = sum((p["pagado"] or 0) for p in pagos)
        saldo = (c["total"] or 0) - pagado
        estado = "sin complemento de pago" if not pagos else ("pagada" if saldo <= Decimal("0.01") else "parcial")
        fila = {"uuid": c["uuid"], "serie": c["serie"], "folio": c["folio"], "fecha": c["fecha"],
                "emisor": c["emisor"]["rfc"], "receptor": c["receptor"]["rfc"], "total": c["total"],
                "moneda": c["moneda"], "pagos": pagos, "pagado": pagado, "saldo": saldo, "estado": estado}
        ppd.append(fila)
        if not pagos:
            sin_pago.append({k: fila[k] for k in ("uuid", "serie", "folio", "fecha", "emisor", "receptor", "total")})
    fuera = sorted(d for d in pagos_por_doc if d not in conocidos)
    return {"ppd": ppd, "ppd_sin_complemento_de_pago": sin_pago,
            "pagos_a_documentos_fuera_de_la_carpeta": fuera}


COLUMNAS_CSV = ["fecha", "uuid", "tipo", "serie", "folio", "emisor_rfc", "emisor_nombre", "receptor_rfc",
                "receptor_nombre", "metodo_pago", "forma_pago", "moneda", "tipo_cambio", "subtotal", "total",
                "iva_trasladado", "iva_retenido", "isr_retenido", "monto_pagos_mxn", "direccion", "archivo"]


def cfdi_reporte(carpeta=None, rfc_propio=None, csv_salida=None):
    rfc_propio = (rfc_propio or "").upper().strip() or None
    leidos, fallas = _cargar_carpeta(carpeta)
    filas = sorted((_fila(r, c, rfc_propio) for r, c in leidos), key=lambda f: f["fecha"] or "")
    por_uuid = {}
    for f in filas:
        if f["uuid"]:
            por_uuid.setdefault(f["uuid"], []).append(f["archivo"])
    duplicados = [{"uuid": u, "archivos": a} for u, a in por_uuid.items() if len(a) > 1]
    dup = {d["uuid"] for d in duplicados}
    contados, por_mes, por_rfc, totales = set(), {}, {}, {}
    for f in filas:
        if f["uuid"] in dup:
            if f["uuid"] in contados:
                continue  # un UUID duplicado se suma una sola vez
            contados.add(f["uuid"])
        d = f["direccion"] or "todas"
        mes = (f["fecha"] or "?")[:7]
        _suma(por_mes.setdefault(d, {}).setdefault(mes, _acc()), f)
        _suma(totales.setdefault(d, _acc()), f)
        if d == "recibida":
            rfc, nombre = f["emisor_rfc"], f["emisor_nombre"]
        elif d == "emitida":
            rfc, nombre = f["receptor_rfc"], f["receptor_nombre"]
        else:
            rfc, nombre = f["emisor_rfc"], f["emisor_nombre"]
        acc = por_rfc.setdefault(d, {}).setdefault(rfc, {"nombre": nombre, **_acc()})
        _suma(acc, f)
    if csv_salida:
        if not str(csv_salida).lower().endswith(".csv"):
            raise ErrorUso("`csv_salida` debe terminar en .csv")
        with open(csv_salida, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=COLUMNAS_CSV, extrasaction="ignore")
            w.writeheader()
            for f in filas:
                w.writerow({k: _celda(f.get(k)) for k in COLUMNAS_CSV})
    return {
        "carpeta": carpeta, "rfc_propio": rfc_propio, "cfdi_leidos": len(filas), "no_leidos": fallas,
        "cfdi": filas, "resumen_por_mes": por_mes, "resumen_por_rfc": por_rfc, "totales": totales,
        "uuid_duplicados": duplicados, "conciliacion_ppd": conciliar_ppd(leidos), "csv_salida": csv_salida,
        "notas": ["Montos en MXN usando TipoCambio del CFDI; egresos (E) restan.",
                  "iva_trasladado = IVA facturado (I − E). iva_flujo = IVA de facturas PUE + IVA de complementos "
                  "de pago (P): es el IVA que se causa o acredita al cobrar/pagar.",
                  "Solo se lee lo que hay en la carpeta: no descarga nada del SAT."],
    }


# ---------------------------------------------------------------- 5. conciliar banco
MESES = {"ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6, "jul": 7, "ago": 8, "sep": 9, "set": 9,
         "oct": 10, "nov": 11, "dic": 12, "jan": 1, "apr": 4, "aug": 8, "dec": 12}


def _norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def leer_fecha(s):
    s = (s or "").strip()
    if not s:
        return None
    m = re.match(r"^(\d{1,2})[/\-. ]([A-Za-zÁÉÍÓÚáéíóú]{3})[A-Za-z]*[/\-. ](\d{2,4})", s)
    if m:
        mes = MESES.get(_norm(m.group(2))[:3])
        if mes:
            a = int(m.group(3))
            return dt.date(a + 2000 if a < 100 else a, mes, int(m.group(1)))
    s10 = s.split("T")[0].split(" ")[0]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y/%m/%d", "%d/%m/%y", "%d-%m-%y"):
        try:
            return dt.datetime.strptime(s10, fmt).date()
        except ValueError:
            pass
    return None


def leer_monto(s):
    s = (s or "").strip().replace("$", "").replace(" ", "").replace("MXN", "")
    if not s or s in ("-",):
        return None
    neg = s.startswith("(") and s.endswith(")") or s.startswith("-") or s.endswith("-")
    s = s.strip("()-+")
    if "," in s and "." in s and s.rfind(",") > s.rfind("."):
        s = s.replace(".", "").replace(",", ".")  # 1.234,56
    elif "," in s and "." not in s and re.match(r"^\d+,\d{2}$", s):
        s = s.replace(",", ".")  # 1234,56
    else:
        s = s.replace(",", "")
    d = D(s)
    return -d if (d is not None and neg) else d


def _columnas(encabezados):
    n = [_norm(h) for h in encabezados]

    def buscar(*claves):
        for clave in claves:
            for i, h in enumerate(n):
                if clave in h.split() or h.startswith(clave):
                    return i
        return None

    return {"fecha": buscar("fecha", "date", "dia"),
            "descripcion": buscar("descripcion", "concepto", "detalle", "referencia", "movimiento", "description"),
            "cargo": buscar("cargo", "cargos", "retiro", "retiros", "debito", "debit"),
            "abono": buscar("abono", "abonos", "deposito", "depositos", "credito", "credit"),
            "monto": buscar("monto", "importe", "cantidad", "amount")}


def leer_estado_cuenta(ruta_csv):
    if not ruta_csv or not os.path.isfile(ruta_csv):
        raise ErrorUso(f"No existe el CSV del estado de cuenta: {ruta_csv}")
    with open(ruta_csv, encoding="utf-8-sig", errors="replace", newline="") as fh:
        texto = fh.read()
    try:
        dialecto = csv.Sniffer().sniff(texto[:4096], delimiters=",;\t|")
    except csv.Error:
        dialecto = csv.excel
    filas = [f for f in csv.reader(texto.splitlines(), dialecto) if any(x.strip() for x in f)]
    inicio = next((i for i, f in enumerate(filas) if _columnas(f)["fecha"] is not None), None)
    if inicio is None:
        raise ErrorUso("No encontré una columna de fecha en el CSV (busco encabezados como Fecha, Concepto, "
                       "Cargo, Abono o Monto).")
    col = _columnas(filas[inicio])
    if col["monto"] is None and col["cargo"] is None and col["abono"] is None:
        raise ErrorUso("No encontré columnas de monto, cargo o abono en el CSV.")
    movs = []
    for num, f in enumerate(filas[inicio + 1:], inicio + 2):
        val = lambda k: f[col[k]] if col[k] is not None and col[k] < len(f) else ""
        fecha = leer_fecha(val("fecha"))
        if fecha is None:
            continue
        abono, cargo = leer_monto(val("abono")), leer_monto(val("cargo"))
        if abono:
            monto = abs(abono)
        elif cargo:
            monto = -abs(cargo)
        else:
            monto = leer_monto(val("monto"))
        if not monto:
            continue
        movs.append({"fila": num, "fecha": fecha.isoformat(), "descripcion": val("descripcion").strip(),
                     "monto": monto})
    return movs, {k: (filas[inicio][v] if v is not None else None) for k, v in col.items()}


def _candidatos(leidos, rfc_propio):
    vistos, cands = set(), []
    for ruta, c in leidos:
        if c["uuid"] in vistos:
            continue
        vistos.add(c["uuid"])
        base = {"uuid": c["uuid"], "tipo": c["tipo"], "serie": c["serie"], "folio": c["folio"],
                "emisor": c["emisor"]["rfc"], "receptor": c["receptor"]["rfc"], "archivo": ruta}
        sentido = 0
        if rfc_propio:
            sentido = 1 if c["emisor"]["rfc"] == rfc_propio else -1 if c["receptor"]["rfc"] == rfc_propio else 0
        if c["tipo"] in ("I", "E") and c["total"]:
            s = -sentido if c["tipo"] == "E" else sentido
            cands.append({**base, "fecha": (c["fecha"] or "")[:10], "monto": c["total"], "sentido": s,
                          "moneda": c["moneda"]})
        elif c["tipo"] == "P" and c["pagos"]:
            for p in c["pagos"]["pagos"]:
                if p["monto"]:
                    cands.append({**base, "fecha": (p["fecha"] or "")[:10], "monto": p["monto"], "sentido": sentido,
                                  "moneda": p["moneda"], "documentos": [d["id_documento"] for d in p["documentos"]],
                                  "refs": [r for d in p["documentos"] for r in (d["folio"], f"{d['serie'] or ''}{d['folio'] or ''}") if r]})
    return cands


def cfdi_conciliar_banco(carpeta=None, csv=None, dias=5, rfc_propio=None):
    rfc_propio = (rfc_propio or "").upper().strip() or None
    dias = int(dias if dias is not None else 5)
    leidos, fallas = _cargar_carpeta(carpeta)
    movs, columnas = leer_estado_cuenta(csv)
    cands = _candidatos(leidos, rfc_propio)
    usados, pares, sin_cfdi = set(), [], []
    for m in movs:
        fm = dt.date.fromisoformat(m["fecha"])
        desc = _norm(m["descripcion"]).upper().replace(" ", "")
        mejor = None
        for i, c in enumerate(cands):
            if i in usados or abs(abs(m["monto"]) - c["monto"]) > Decimal("0.01"):
                continue
            if c["sentido"] and (m["monto"] > 0) != (c["sentido"] > 0):
                continue
            try:
                dif = abs((fm - dt.date.fromisoformat(c["fecha"])).days)
            except ValueError:
                continue
            if dif > dias:
                continue
            pistas = []
            for rfc in (c["emisor"], c["receptor"]):
                if rfc and rfc != rfc_propio and rfc.replace("&", "") in desc:
                    pistas.append(f"RFC {rfc}")
            for ref in {c["folio"], f"{c['serie'] or ''}{c['folio'] or ''}", *c.get("refs", [])}:
                if ref and len(ref) >= 2 and re.search(rf"(?<![0-9]){re.escape(_norm(ref).upper().replace(' ', ''))}"
                                                       r"(?![0-9])", desc):
                    pistas.append(f"folio {ref}")
            if c["uuid"] and c["uuid"][:8] in desc:
                pistas.append("UUID")
            clave = (-len(pistas), dif)
            if mejor is None or clave < mejor[0]:
                mejor = (clave, i, dif, pistas)
        if mejor:
            usados.add(mejor[1])
            c = cands[mejor[1]]
            pares.append({"movimiento": m, "cfdi": {k: v for k, v in c.items() if k != "sentido"},
                          "dias_diferencia": mejor[2], "desempate": mejor[3]})
        else:
            sin_cfdi.append(m)
    sin_mov = [{k: v for k, v in c.items() if k != "sentido"} for i, c in enumerate(cands) if i not in usados]
    return {"columnas_detectadas": columnas, "movimientos": len(movs), "cfdi_candidatos": len(cands),
            "dias_tolerancia": dias, "emparejados": pares, "movimientos_sin_cfdi": sin_cfdi,
            "cfdi_sin_movimiento": sin_mov, "no_leidos": fallas,
            "notas": ["Empareja por monto exacto (±0.01) y fecha (±dias); RFC, folio o UUID en la descripción "
                      "desempatan. Facturas PPD se pagan con su complemento (P): es normal que la PPD quede "
                      "sin movimiento y su pago sí empareje.",
                      "Montos en la moneda del CFDI: si el banco es en MXN y el CFDI en USD no empareja."]}


# ---------------------------------------------------------------- herramientas
_RUTA = {"type": "string", "description": "Ruta a un archivo .xml de CFDI."}
_XML = {"type": "string", "description": "Texto completo del XML del CFDI (alternativa a `ruta`)."}
_CARPETA = {"type": "string", "description": "Carpeta con XML de CFDI (se recorre con subcarpetas)."}
_RFC_PROPIO = {"type": "string", "description": "Tu RFC, para separar emitidas y recibidas."}

HERRAMIENTAS = {
    "cfdi_leer": (cfdi_leer, "Lee un CFDI 4.0/3.3 (XML) y devuelve sus datos en JSON: emisor, receptor, conceptos, "
                             "impuestos por tasa, UUID, complementos (pagos, nómina, carta porte). "
                             "Reads a Mexican CFDI invoice XML into JSON.",
                  {"ruta": _RUTA, "xml": _XML}, []),
    "cfdi_validar": (cfdi_validar, "Revisa un CFDI: atributos obligatorios, RFC, UUID, timbre, catálogos, sumas "
                                   "(SubTotal, impuestos, Total), PPD/PUE y forma de pago, receptor genérico. Devuelve "
                                   "errores y avisos en español. NO verifica la firma del sello (usa cfdi_estatus_sat). "
                                   "Validates a CFDI's structure and math.",
                     {"ruta": _RUTA, "xml": _XML}, []),
    "cfdi_estatus_sat": (cfdi_estatus_sat, "Consulta en el servicio público del SAT si un CFDI está Vigente o "
                                           "Cancelado, si es cancelable y la validación EFOS del emisor. Necesita red. "
                                           "Acepta ruta/xml o uuid + rfc_emisor + rfc_receptor + total. "
                                           "Checks CFDI status with Mexico's SAT.",
                         {"ruta": _RUTA, "xml": _XML, "uuid": {"type": "string"},
                          "rfc_emisor": {"type": "string"}, "rfc_receptor": {"type": "string"},
                          "total": {"type": "string", "description": "Total tal como viene en el XML."},
                          "sello8": {"type": "string", "description": "Últimos 8 caracteres del Sello (opcional)."}},
                         []),
    "cfdi_reporte": (cfdi_reporte, "Reporte de una carpeta de CFDI: tabla por factura, resúmenes por mes y por RFC, "
                                   "IVA trasladado/retenido (facturado y en flujo), UUID duplicados y conciliación de "
                                   "facturas PPD contra complementos de pago. Opcional: CSV. "
                                   "Monthly VAT report and PPD vs payments reconciliation.",
                     {"carpeta": _CARPETA, "rfc_propio": _RFC_PROPIO,
                      "csv_salida": {"type": "string", "description": "Ruta donde escribir la tabla en CSV."}},
                     ["carpeta"]),
    "cfdi_conciliar_banco": (cfdi_conciliar_banco, "Concilia una carpeta de CFDI contra un estado de cuenta en CSV: "
                                                   "empareja por monto exacto y fecha cercana (RFC/folio desempatan). "
                                                   "Devuelve emparejados, movimientos sin CFDI y CFDI sin movimiento. "
                                                   "Bank statement reconciliation.",
                             {"carpeta": _CARPETA, "csv": {"type": "string", "description": "Ruta al CSV del banco."},
                              "dias": {"type": "integer", "description": "Días de tolerancia (default 5)."},
                              "rfc_propio": _RFC_PROPIO},
                             ["carpeta", "csv"]),
}


def _json_default(o):
    if isinstance(o, Decimal):
        return float(o)
    if isinstance(o, (dt.date, dt.datetime)):
        return o.isoformat()
    raise TypeError(type(o).__name__)


def _celda(v):
    """Celda de CSV segura: texto que empieza con = + - @ no se vuelve fórmula en Excel."""
    if v is None:
        return ""
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@"):
        return "'" + v
    return v


def _sin_dtd(datos):
    """Un CFDI o respuesta SOAP nunca trae DTD ni entidades: se rechazan (XXE / billion laughs)."""
    muestra = datos if isinstance(datos, str) else datos.decode("utf-8", "ignore")
    if re.search(r"<!(DOCTYPE|ENTITY)", muestra, re.I):
        raise ErrorUso("El XML trae DOCTYPE o ENTITY; un CFDI nunca los lleva. No se procesa.")


def a_json(obj, indent=None):
    return json.dumps(obj, ensure_ascii=False, default=_json_default, indent=indent)


def llamar(nombre, argumentos):
    if nombre not in HERRAMIENTAS:
        raise KeyError(nombre)
    fn, _, props, _ = HERRAMIENTAS[nombre]
    args = {k: v for k, v in (argumentos or {}).items() if k in props and v not in (None, "")}
    return fn(**args)


# ---------------------------------------------------------------- MCP stdio
def _herramientas_mcp():
    return [{"name": n, "title": n.replace("_", " ").upper().replace("CFDI ", "CFDI: "), "description": d,
             "inputSchema": {"type": "object", "properties": p, "required": r},
             "annotations": {"readOnlyHint": n != "cfdi_reporte", "destructiveHint": False,
                             "openWorldHint": n == "cfdi_estatus_sat"}}
            for n, (_, d, p, r) in HERRAMIENTAS.items()]


def manejar(msg):
    """Procesa un mensaje JSON-RPC. Devuelve la respuesta (dict) o None si es notificación."""
    if not isinstance(msg, dict):
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}}
    metodo, mid, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
    es_notificacion = "id" not in msg
    if es_notificacion:
        return None  # notifications/initialized, notifications/cancelled, etc.

    def ok(resultado):
        return {"jsonrpc": "2.0", "id": mid, "result": resultado}

    def err(codigo, mensaje):
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": codigo, "message": mensaje}}

    if metodo == "initialize":
        return ok({"protocolVersion": params.get("protocolVersion") or "2025-06-18",
                   "capabilities": {"tools": {}},
                   "serverInfo": {"name": NOMBRE, "version": VERSION},
                   "instructions": "Herramientas para CFDI de México (leer, validar, estatus SAT, reporte de IVA, "
                                   "conciliación). Todo local salvo cfdi_estatus_sat."})
    if metodo == "ping":
        return ok({})
    if metodo == "tools/list":
        return ok({"tools": _herramientas_mcp()})
    if metodo == "tools/call":
        nombre = params.get("name")
        if nombre not in HERRAMIENTAS:
            return err(-32602, f"Herramienta desconocida: {nombre}")
        try:
            res, es_error = llamar(nombre, params.get("arguments")), False
        except ErrorUso as e:
            res, es_error = {"error": str(e)}, True
        except Exception as e:  # noqa: BLE001 - se reporta al cliente, no tumba el servidor
            log("falla en", nombre, repr(e))
            res, es_error = {"error": f"Falla interna: {e!r}"}, True
        return ok({"content": [{"type": "text", "text": a_json(res)}], "isError": es_error})
    return err(-32601, f"Método no encontrado: {metodo}")


def servir_mcp():
    log(f"servidor MCP {VERSION} por stdio")
    entrada = sys.stdin.buffer
    for linea in entrada:
        linea = linea.strip()
        if not linea:
            continue
        try:
            msg = json.loads(linea)
        except json.JSONDecodeError:
            resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        else:
            resp = manejar(msg)
        if resp is not None:
            sys.stdout.write(a_json(resp) + "\n")
            sys.stdout.flush()


# ---------------------------------------------------------------- CLI
def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="cfdi.py", description="OMEN CFDI: herramientas para CFDI de México.")
    sub = ap.add_subparsers(dest="comando", required=True)
    sub.add_parser("mcp", help="Servidor MCP por stdio")
    for nombre, (_, desc, props, _) in HERRAMIENTAS.items():
        p = sub.add_parser(nombre, aliases=[nombre.replace("cfdi_", "")], help=desc.split(".")[0])
        if "ruta" in props:
            p.add_argument("ruta_pos", nargs="?", metavar="ruta", help="Archivo .xml")
        elif "carpeta" in props:
            p.add_argument("carpeta_pos", nargs="?", metavar="carpeta", help="Carpeta con XML")
        for k, v in props.items():
            p.add_argument(f"--{k}", type=int if v.get("type") == "integer" else str, help=v.get("description"))
        p.set_defaults(herramienta=nombre)
    a = ap.parse_args(argv)
    if a.comando == "mcp":
        servir_mcp()
        return 0
    args = {k: v for k, v in vars(a).items() if k in HERRAMIENTAS[a.herramienta][2]}
    if getattr(a, "ruta_pos", None) and not args.get("ruta"):
        args["ruta"] = a.ruta_pos
    if getattr(a, "carpeta_pos", None) and not args.get("carpeta"):
        args["carpeta"] = a.carpeta_pos
    if args.get("xml") == "-":
        args["xml"] = sys.stdin.read()
    try:
        res = llamar(a.herramienta, args)
    except ErrorUso as e:
        print(a_json({"error": str(e)}, indent=2))
        return 2
    print(a_json(res, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
