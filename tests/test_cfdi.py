"""Pruebas de OMEN CFDI. Correr desde la raíz del plugin:  python3 -m unittest discover -s tests -v
La consulta real al SAT solo corre con OMEN_CFDI_RED=1 (necesita red)."""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

AQUI = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(AQUI, "..", "skills", "cfdi-mx", "scripts", "cfdi.py")
XML = os.path.join(AQUI, "xml")
CSV_BANCO = os.path.join(AQUI, "estado_cuenta.csv")
RFC = "EKU9003173C9"

spec = importlib.util.spec_from_file_location("cfdi", SCRIPT)
cfdi = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cfdi)


def x(nombre):
    return os.path.join(XML, nombre)


def codigos(res):
    return {r["codigo"] for r in res["revisiones"] if r["nivel"] == "error"}


class Leer(unittest.TestCase):
    def test_ingreso_pue(self):
        c = cfdi.cfdi_leer(ruta=x("ingreso-pue.xml"))
        self.assertEqual((c["version"], c["tipo"], c["serie"], c["folio"]), ("4.0", "I", "F", "101"))
        self.assertEqual(c["uuid"], "11111111-1111-4111-8111-111111111111")
        self.assertEqual(c["emisor"]["rfc"], RFC)
        self.assertEqual(c["receptor"]["cp"], "76028")
        self.assertEqual(len(c["conceptos"]), 2)
        self.assertEqual(c["conceptos"][0]["traslados"][0]["impuesto_nombre"], "IVA")
        self.assertEqual(float(c["impuestos"]["iva_trasladado_por_tasa"]["0.160000"]), 2000.0)
        self.assertEqual(float(c["total"]), 14500.0)
        self.assertEqual(c["sello_ultimos8"], "ZWJhcw==")
        self.assertIn("tfd:TimbreFiscalDigital", c["complementos"])

    def test_pago20(self):
        c = cfdi.cfdi_leer(ruta=x("pago-parcial.xml"))
        self.assertEqual(c["pagos"]["version"], "2.0")
        d = c["pagos"]["pagos"][0]["documentos"][0]
        self.assertEqual(d["id_documento"], "22222222-2222-4222-8222-222222222222")
        self.assertEqual((float(d["saldo_anterior"]), float(d["pagado"]), float(d["saldo_insoluto"])),
                         (58000.0, 23200.0, 34800.0))

    def test_relacionados_y_texto(self):
        with open(x("egreso.xml"), encoding="utf-8") as f:
            c = cfdi.cfdi_leer(xml=f.read())
        self.assertEqual(c["cfdi_relacionados"][0]["tipo_relacion"], "01")
        self.assertEqual(c["cfdi_relacionados"][0]["uuids"], ["11111111-1111-4111-8111-111111111111"])

    def test_cartaporte(self):
        c = cfdi.cfdi_leer(ruta=x("extra/cfdi-ejemplo-traslado-cartaporte.xml"))
        self.assertIn("cartaporte31:CartaPorte", c["complementos"])

    def test_no_es_cfdi(self):
        with self.assertRaises(cfdi.ErrorUso):
            cfdi.cfdi_leer(xml="<hola/>")


class Seguridad(unittest.TestCase):
    def test_rechaza_doctype(self):
        with self.assertRaises(cfdi.ErrorUso):
            cfdi.cfdi_leer(xml='<!DOCTYPE a [<!ENTITY x "y">]><a>&x;</a>')

    def test_csv_sin_formulas_y_solo_csv(self):
        self.assertEqual(cfdi._celda("=HYPERLINK(1)"), "'=HYPERLINK(1)")
        self.assertEqual(cfdi._celda(12), 12)
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(cfdi.ErrorUso):
                cfdi.cfdi_reporte(carpeta=XML, csv_salida=os.path.join(d, "x.sh"))


class Validar(unittest.TestCase):
    def test_buenos(self):
        for n in ("ingreso-pue.xml", "ingreso-ppd.xml", "pago-parcial.xml", "egreso.xml", "gasto-recibido.xml",
                  "extra/cfdi-ejemplo-traslado-cartaporte.xml"):
            res = cfdi.cfdi_validar(ruta=x(n))
            self.assertTrue(res["valido"], f"{n}: {res['revisiones']}")
            self.assertFalse(res["firma_verificada"])
            self.assertIn("NO verifica la firma", res["nota_firma"])

    def test_con_errores(self):
        res = cfdi.cfdi_validar(ruta=x("con-errores.xml"))
        self.assertFalse(res["valido"])
        self.assertTrue({"total", "ppd_forma", "generico_uso", "generico_regimen"} <= codigos(res), codigos(res))

    def test_demo_ppd_forma(self):
        self.assertEqual(codigos(cfdi.cfdi_validar(ruta=x("extra/cfdi-ejemplo-ingreso-ppd.xml"))), {"ppd_forma"})

    def test_estructura(self):
        with open(x("ingreso-pue.xml"), encoding="utf-8") as f:
            t = f.read()
        roto = (t.replace('Rfc="XOJI740919U48"', 'Rfc="XOJI74"').replace(' Exportacion="01"', "")
                 .replace('SubTotal="12500.00"', 'SubTotal="12000.00"').replace('MetodoPago="PUE"', 'MetodoPago="PUE" ')
                 .replace('FormaPago="03"', 'FormaPago="99"').replace("11111111-1111-4111-8111-111111111111", "malo"))
        cods = codigos(cfdi.cfdi_validar(xml=roto))
        self.assertTrue({"rfc_formato", "falta_atributo", "subtotal", "pue_forma", "uuid_formato"} <= cods, cods)
        self.assertFalse(cfdi.cfdi_validar(xml="<roto")["valido"])

    def test_pago_xxx(self):
        with open(x("pago-parcial.xml"), encoding="utf-8") as f:
            t = f.read().replace('Moneda="XXX"', 'Moneda="MXN"').replace('ImpSaldoInsoluto="34800.00"',
                                                                        'ImpSaldoInsoluto="30000.00"')
        self.assertTrue({"moneda_pt", "pago_saldo"} <= codigos(cfdi.cfdi_validar(xml=t)))


class EstatusSAT(unittest.TestCase):
    def test_expresion_y_sobre(self):
        e = cfdi.expresion_impresa("AAA", "EKU9003173C9", "XOJI740919U48", "14500.00", "ZWJhcw==")
        self.assertEqual(e, "?re=EKU9003173C9&rr=XOJI740919U48&tt=14500.00&id=AAA&fe=ZWJhcw==")
        self.assertIn("&amp;rr=", cfdi.sobre_soap(e))

    def test_respuesta_real_guardada(self):
        # Respuesta real del SAT capturada el 2026-10-22 para un UUID sintético.
        with open(os.path.join(AQUI, "fixtures", "sat-no-encontrado.soap"), "rb") as f:
            c = cfdi.leer_respuesta_sat(f.read())
        self.assertEqual(c["Estado"], "No Encontrado")
        self.assertTrue(c["CodigoEstatus"].startswith("N - 602"))

    def test_lectura(self):
        txt = cfdi.lectura_sat({"Estado": "Vigente", "EsCancelable": "Cancelable sin aceptación",
                                "ValidacionEFOS": "200"})
        self.assertIn("VIGENTE", txt)
        self.assertIn("no reporta", txt)
        self.assertIn("listado de EFOS", cfdi.lectura_sat({"Estado": "Vigente", "ValidacionEFOS": "100"}))

    def test_faltan_datos(self):
        with self.assertRaises(cfdi.ErrorUso):
            cfdi.cfdi_estatus_sat(uuid="x")

    @unittest.skipUnless(os.environ.get("OMEN_CFDI_RED") == "1", "consulta real al SAT: OMEN_CFDI_RED=1")
    def test_sat_en_vivo(self):
        res = cfdi.cfdi_estatus_sat(ruta=x("ingreso-pue.xml"))
        self.assertTrue(res["consultado"], res)
        self.assertEqual(res["Estado"], "No Encontrado")


class Reporte(unittest.TestCase):
    def test_reporte(self):
        with tempfile.TemporaryDirectory() as tmp:
            salida = os.path.join(tmp, "r.csv")
            r = cfdi.cfdi_reporte(carpeta=XML, rfc_propio=RFC, csv_salida=salida)
            self.assertEqual(r["cfdi_leidos"], 8)
            self.assertEqual(r["no_leidos"], [])
            em = r["totales"]["emitida"]
            self.assertEqual(float(em["iva_trasladado"]), 17520.0)  # 2000+8000+160+7520−160
            self.assertEqual(float(em["iva_flujo"]), 5040.0)  # PUE 2000 − egreso 160 + pago 3200
            self.assertEqual(float(r["totales"]["recibida"]["iva_trasladado"]), 480.0)
            self.assertIn("2026-09", r["resumen_por_mes"]["emitida"])
            self.assertIn("AAA010101AAA", r["resumen_por_rfc"]["recibida"])
            ppd = {p["uuid"]: p for p in r["conciliacion_ppd"]["ppd"]}
            a200 = ppd["22222222-2222-4222-8222-222222222222"]
            self.assertEqual((a200["estado"], float(a200["pagado"]), float(a200["saldo"])), ("parcial", 23200.0, 34800.0))
            sin = {p["uuid"] for p in r["conciliacion_ppd"]["ppd_sin_complemento_de_pago"]}
            self.assertIn("00000000-0000-4000-8000-0000000E1042", sin)
            with open(salida, encoding="utf-8-sig") as f:
                self.assertEqual(len(f.read().strip().splitlines()), 9)

    def test_duplicados(self):
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copy(x("ingreso-pue.xml"), os.path.join(tmp, "a.xml"))
            os.makedirs(os.path.join(tmp, "sub"))
            shutil.copy(x("ingreso-pue.xml"), os.path.join(tmp, "sub", "b.XML"))
            with open(os.path.join(tmp, "roto.xml"), "w") as f:
                f.write("<no")
            r = cfdi.cfdi_reporte(carpeta=tmp)
            self.assertEqual(len(r["uuid_duplicados"]), 1)
            self.assertEqual(len(r["no_leidos"]), 1)
            self.assertEqual(r["totales"]["todas"]["cfdi"], 1)  # el duplicado se suma una vez


class ConciliarBanco(unittest.TestCase):
    def test_conciliar(self):
        r = cfdi.cfdi_conciliar_banco(carpeta=XML, csv=CSV_BANCO, rfc_propio=RFC)
        pares = {p["movimiento"]["fila"]: p["cfdi"]["uuid"][:8] for p in r["emparejados"]}
        self.assertEqual(pares, {2: "11111111", 3: "55555555", 4: "33333333"})
        self.assertEqual([m["descripcion"] for m in r["movimientos_sin_cfdi"]], ["COMISION MANEJO DE CUENTA"])
        self.assertIn("22222222-2222-4222-8222-222222222222", {c["uuid"] for c in r["cfdi_sin_movimiento"]})

    def test_formatos(self):
        self.assertEqual(str(cfdi.leer_fecha("15/OCT/2026")), "2026-10-15")
        self.assertEqual(str(cfdi.leer_fecha("2026-10-15")), "2026-10-15")
        self.assertEqual(float(cfdi.leer_monto("$1,234.50")), 1234.5)
        self.assertEqual(float(cfdi.leer_monto("1.234,50")), 1234.5)
        self.assertEqual(float(cfdi.leer_monto("(250.00)")), -250.0)

    def test_csv_con_monto_y_punto_y_coma(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "b.csv")
            with open(p, "w", encoding="utf-8") as f:
                f.write("Banco Ejemplo;;\nFecha;Concepto;Importe\n11-sep-2026;DEP XOJI740919U48;14500,00\n")
            r = cfdi.cfdi_conciliar_banco(carpeta=XML, csv=p)
            self.assertEqual(len(r["emparejados"]), 1)


class CLIyMCP(unittest.TestCase):
    def test_cli(self):
        out = subprocess.run([sys.executable, SCRIPT, "validar", x("con-errores.xml")], capture_output=True,
                             text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertFalse(json.loads(out.stdout)["valido"])

    def test_mcp_stdio(self):
        msgs = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "cfdi_validar", "arguments": {"ruta": x("con-errores.xml")}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
             "params": {"name": "cfdi_leer", "arguments": {"ruta": "/no/existe.xml"}}},
            {"jsonrpc": "2.0", "id": 5, "method": "ping"},
            {"jsonrpc": "2.0", "id": 6, "method": "resources/list"},
        ]
        entrada = "".join(json.dumps(m) + "\n" for m in msgs)
        out = subprocess.run([sys.executable, SCRIPT, "mcp"], input=entrada, capture_output=True, text=True,
                             timeout=30)
        resp = {r["id"]: r for r in map(json.loads, out.stdout.strip().splitlines())}
        self.assertEqual(sorted(resp), [1, 2, 3, 4, 5, 6])  # la notificación no responde
        self.assertEqual(resp[1]["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual(resp[1]["result"]["serverInfo"]["name"], "omen-cfdi")
        nombres = {t["name"] for t in resp[2]["result"]["tools"]}
        self.assertEqual(nombres, {"cfdi_leer", "cfdi_validar", "cfdi_estatus_sat", "cfdi_estatus_sat_carpeta",
                                   "cfdi_reporte", "cfdi_conciliar_banco"})
        r3 = resp[3]["result"]
        self.assertFalse(r3["isError"])
        self.assertFalse(json.loads(r3["content"][0]["text"])["valido"])
        self.assertTrue(resp[4]["result"]["isError"])
        self.assertEqual(resp[5]["result"], {})
        self.assertEqual(resp[6]["error"]["code"], -32601)
        self.assertIn("servidor MCP", out.stderr)


def sat_falso(ruta=None, **_):
    """Respuesta del SAT sin red: ingreso-pue vigente, egreso cancelado, el resto No Encontrado (fixture real)."""
    base = os.path.basename(ruta)
    if base == "con-errores.xml":
        raise cfdi.ErrorUso("XML ilegible de mentiras")
    if base in ("ingreso-pue.xml", "egreso.xml"):
        campos = {"Estado": "Vigente" if base == "ingreso-pue.xml" else "Cancelado",
                  "EsCancelable": "Cancelable sin aceptación", "EstatusCancelacion": ""}
    else:
        with open(os.path.join(AQUI, "fixtures", "sat-no-encontrado.soap"), "rb") as f:
            campos = cfdi.leer_respuesta_sat(f.read())
    info = cfdi.leer_raiz(cfdi.cargar(ruta))
    return {"consultado": True, "http": 200, "expresion_impresa": f"?re=A&rr=B&tt=1&id={info['uuid']}", **campos}


class EstatusCarpeta(unittest.TestCase):
    def test_conteos(self):
        with mock.patch.object(cfdi, "cfdi_estatus_sat", sat_falso):
            r = cfdi.cfdi_estatus_sat_carpeta(XML)
        self.assertEqual((r["consultados"], r["vigentes"], r["cancelados"], r["no_encontrados"]), (7, 1, 1, 5))
        self.assertEqual([e["archivo"] for e in r["errores"]], [x("con-errores.xml")])
        self.assertIn("ilegible", r["errores"][0]["motivo"])
        pue = next(f for f in r["cfdi"] if f["archivo"] == x("ingreso-pue.xml"))
        self.assertEqual((pue["uuid"], pue["estado"], pue["error"]),
                         ("11111111-1111-4111-8111-111111111111", "Vigente", None))

    def test_tope_progreso_y_cancelacion(self):
        avance = []
        with mock.patch.object(cfdi, "cfdi_estatus_sat", sat_falso):
            r = cfdi.cfdi_estatus_sat_carpeta(XML, max_cfdi=3, progreso=lambda k, n: avance.append((k, n)))
            self.assertEqual((len(r["cfdi"]), r["omitidos"], avance), (3, 5, [(1, 3), (2, 3), (3, 3)]))
            llamadas = iter([False, True])
            r = cfdi.cfdi_estatus_sat_carpeta(XML, cancelado=lambda: next(llamadas))
        self.assertEqual(len(r["cfdi"]), 1)

    def test_red_caida_va_a_errores(self):
        caida = {"consultado": False, "expresion_impresa": "?id=U", "error": "No se pudo conectar con el SAT"}
        with mock.patch.object(cfdi, "cfdi_estatus_sat", lambda ruta=None: caida):
            r = cfdi.cfdi_estatus_sat_carpeta(XML, max_cfdi=1)
        self.assertEqual((r["consultados"], len(r["errores"])), (0, 1))


# Servidor MCP real como subproceso; con `falso` el SAT se simula (demora = segundos por XML).
DRIVER = """
import importlib.util, sys, time
spec = importlib.util.spec_from_file_location("cfdi", sys.argv[1])
cfdi = importlib.util.module_from_spec(spec); spec.loader.exec_module(cfdi)
sys.path.insert(0, sys.argv[2]); import test_cfdi; test_cfdi.cfdi = cfdi  # mismas clases de error
def sat(ruta=None, **k):
    time.sleep(float(sys.argv[3]))
    return test_cfdi.sat_falso(ruta=ruta)
cfdi.cfdi_estatus_sat = sat
sys.stdout.reconfigure(encoding="utf-8")  # como main(); sin esto Windows escribe cp1252
cfdi.servir_mcp()
"""


class Cliente:
    def __init__(self, capacidades, falso=None):
        orden = [sys.executable, "-c", DRIVER, SCRIPT, AQUI, str(falso)] if falso is not None else \
            [sys.executable, SCRIPT, "mcp"]
        self.p = subprocess.Popen(orden, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                  text=True, encoding="utf-8")
        self.cortafuegos = threading.Timer(60, self.p.kill)  # si algo se cuelga, la prueba falla en vez de colgarse
        self.cortafuegos.start()
        self.vistos = []
        self.pedir(1, "initialize", {"protocolVersion": "2025-11-25", "capabilities": capacidades,
                                     "clientInfo": {"name": "t", "version": "1"}})
        self.enviar({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def enviar(self, msg):
        self.p.stdin.write(json.dumps(msg) + "\n")
        self.p.stdin.flush()

    def leer(self):
        msg = json.loads(self.p.stdout.readline())
        self.vistos.append(msg)
        return msg

    def leer_hasta(self, id_):
        while True:
            msg = self.leer()
            if msg.get("id") == id_ and "method" not in msg:
                return msg

    def pedir(self, id_, metodo, params=None):
        self.enviar({"jsonrpc": "2.0", "id": id_, "method": metodo, "params": params or {}})
        return self.leer_hasta(id_)

    def cerrar(self):
        self.p.stdin.close()
        self.p.stdout.read()  # drena: en Windows el tubo es chico y el servidor se quedaría escribiendo
        self.p.wait(timeout=10)
        self.cortafuegos.cancel()
        self.p.stdout.close()


def llamada(id_, nombre, args, **extra):
    return {"jsonrpc": "2.0", "id": id_, "method": "tools/call",
            "params": {"name": nombre, "arguments": args, **extra}}


def cuerpo(resp):
    return json.loads(resp["result"]["content"][0]["text"])


class Elicitation(unittest.TestCase):
    def cliente(self, caps):
        c = Cliente(caps)
        self.addCleanup(c.cerrar)
        return c

    def test_pregunta_el_rfc_con_ping_y_cola(self):
        c = self.cliente({"elicitation": {}})
        c.enviar(llamada(2, "cfdi_reporte", {"carpeta": XML}))
        pet = c.leer()
        self.assertEqual((pet["method"], pet["id"], pet["params"]["mode"]), ("elicitation/create", "omen-1", "form"))
        opciones = pet["params"]["requestedSchema"]["properties"]["rfc"]["oneOf"]
        self.assertLessEqual(len(opciones), 6)
        self.assertEqual(opciones[0]["const"], RFC)  # el más frecuente primero
        self.assertTrue(opciones[0]["title"].startswith(RFC + " — "))
        self.assertNotIn("XAXX010101000", [o["const"] for o in opciones])
        self.assertIn("cancela y escríbelo en el chat", pet["params"]["requestedSchema"]["properties"]["rfc"]["description"])
        c.enviar({"jsonrpc": "2.0", "id": 90, "method": "ping"})  # se contesta mientras espera
        c.enviar({"jsonrpc": "2.0", "id": 91, "method": "tools/list"})  # se encola
        self.assertEqual(c.leer(), {"jsonrpc": "2.0", "id": 90, "result": {}})
        c.enviar({"jsonrpc": "2.0", "id": "omen-1", "result": {"action": "accept", "content": {"rfc": RFC}}})
        r = cuerpo(c.leer())
        self.assertEqual((r["rfc_propio"], r["rfc_propio_origen"]), (RFC, "preguntado"))
        self.assertEqual({f["direccion"] for f in r["cfdi"]} - {"ajena"}, {"emitida", "recibida"})
        self.assertIn("formulario (elicitation) que mostró tu cliente MCP", r["notas"][0])
        self.assertEqual(len(c.leer()["result"]["tools"]), 6)  # lo encolado se atiende después, en orden

    def test_conciliar_banco_tambien_pregunta(self):
        c = self.cliente({"elicitation": {}})
        c.enviar(llamada(2, "cfdi_conciliar_banco", {"carpeta": XML, "csv": CSV_BANCO}))
        self.assertEqual(c.leer()["method"], "elicitation/create")
        c.enviar({"jsonrpc": "2.0", "id": "omen-1", "result": {"action": "accept", "content": {"rfc": RFC}}})
        self.assertEqual(cuerpo(c.leer())["rfc_propio_origen"], "preguntado")

    def test_sin_capability_no_pregunta(self):
        c = self.cliente({})
        r = cuerpo(c.pedir(2, "tools/call", {"name": "cfdi_reporte", "arguments": {"carpeta": XML}}))
        self.assertEqual((r["rfc_propio"], r["rfc_propio_origen"]), (None, None))
        self.assertNotIn("elicitation/create", [m.get("method") for m in c.vistos])

    def test_cliente_solo_url_no_pregunta(self):
        c = self.cliente({"elicitation": {"url": {}}})
        r = cuerpo(c.pedir(2, "tools/call", {"name": "cfdi_reporte", "arguments": {"carpeta": XML}}))
        self.assertIsNone(r["rfc_propio_origen"])
        self.assertNotIn("elicitation/create", [m.get("method") for m in c.vistos])

    def test_cliente_con_form_explicito_si_pregunta(self):
        c = self.cliente({"elicitation": {"form": {}, "url": {}}})
        c.enviar(llamada(2, "cfdi_reporte", {"carpeta": XML}))
        self.assertEqual(c.leer()["method"], "elicitation/create")

    def test_con_argumento_no_pregunta(self):
        c = self.cliente({"elicitation": {}})
        r = cuerpo(c.pedir(2, "tools/call", {"name": "cfdi_reporte", "arguments": {"carpeta": XML, "rfc_propio": RFC}}))
        self.assertEqual(r["rfc_propio_origen"], "argumento")
        self.assertNotIn("elicitation/create", [m.get("method") for m in c.vistos])

    def test_decline_y_error_siguen_sin_rfc(self):
        c = self.cliente({"elicitation": {}})
        c.enviar(llamada(2, "cfdi_reporte", {"carpeta": XML}))
        c.leer()
        c.enviar({"jsonrpc": "2.0", "id": "omen-1", "result": {"action": "decline"}})
        r = cuerpo(c.leer())
        self.assertEqual((r["rfc_propio"], r["rfc_propio_origen"]), (None, None))
        c.enviar(llamada(3, "cfdi_reporte", {"carpeta": XML}))
        self.assertEqual(c.leer()["id"], "omen-2")
        c.enviar({"jsonrpc": "2.0", "id": "omen-2", "error": {"code": -32601, "message": "no"}})
        self.assertIsNone(cuerpo(c.leer())["rfc_propio_origen"])


class Tasks(unittest.TestCase):
    def cliente(self, demora):
        c = Cliente({}, falso=demora)
        self.addCleanup(c.cerrar)
        return c

    def test_initialize_y_tools_list(self):
        c = self.cliente(0)
        caps = c.vistos[0]["result"]["capabilities"]
        self.assertEqual(caps["tasks"], {"list": {}, "cancel": {}, "requests": {"tools": {"call": {}}}})
        self.assertEqual(c.vistos[0]["result"]["protocolVersion"], "2025-11-25")
        herr = {t["name"]: t for t in c.pedir(2, "tools/list")["result"]["tools"]}
        self.assertEqual({n for n, t in herr.items() if "execution" in t}, {"cfdi_estatus_sat_carpeta"})
        self.assertEqual(herr["cfdi_estatus_sat_carpeta"]["execution"], {"taskSupport": "optional"})
        self.assertTrue(herr["cfdi_estatus_sat_carpeta"]["annotations"]["openWorldHint"])

    def test_llamada_sincrona(self):
        c = self.cliente(0)
        r = cuerpo(c.pedir(2, "tools/call", {"name": "cfdi_estatus_sat_carpeta", "arguments": {"carpeta": XML}}))
        self.assertEqual((r["consultados"], r["vigentes"], r["cancelados"]), (7, 1, 1))

    def test_ciclo_completo(self):
        c = self.cliente(0.2)  # 8 XML x 0.2 s: tasks/result tiene que esperar sin congelar el servidor
        creada = c.pedir(2, "tools/call", {"name": "cfdi_estatus_sat_carpeta", "arguments": {"carpeta": XML},
                                           "task": {"ttl": 60000}})["result"]["task"]
        self.assertEqual((creada["status"], creada["ttl"], creada["pollInterval"]), ("working", 60000, 2000))
        self.assertEqual(creada["statusMessage"], "Consultando 0 de 8")
        self.assertTrue(creada["createdAt"].endswith("Z"))
        tid = creada["taskId"]
        c.enviar({"jsonrpc": "2.0", "id": 3, "method": "tasks/result", "params": {"taskId": tid}})
        self.assertEqual(c.pedir(4, "ping")["result"], {})  # el servidor sigue vivo mientras tasks/result espera
        self.assertNotIn(3, [m.get("id") for m in c.vistos])
        self.assertIn("Consultando", c.pedir(5, "tasks/get", {"taskId": tid})["result"]["statusMessage"])
        res = c.leer_hasta(3)["result"]
        self.assertFalse(res["isError"])
        self.assertEqual(json.loads(res["content"][0]["text"])["consultados"], 7)
        self.assertEqual(res["_meta"], {"io.modelcontextprotocol/related-task": {"taskId": tid}})
        fin = c.pedir(6, "tasks/get", {"taskId": tid})["result"]
        self.assertEqual(fin["status"], "completed")
        self.assertIn(("notifications/tasks/status", "completed"),
                      [(m.get("method"), m["params"]["status"]) for m in c.vistos if "params" in m and "status" in m["params"]])
        self.assertEqual([t["taskId"] for t in c.pedir(7, "tasks/list")["result"]["tasks"]], [tid])
        e = c.pedir(8, "tasks/cancel", {"taskId": tid})["error"]
        self.assertEqual(e["code"], -32602)

    def test_cancelar_una_en_curso(self):
        c = self.cliente(0.3)
        tid = c.pedir(2, "tools/call", {"name": "cfdi_estatus_sat_carpeta", "arguments": {"carpeta": XML},
                                        "task": {}})["result"]["task"]["taskId"]
        self.assertEqual(c.pedir(3, "tasks/cancel", {"taskId": tid})["result"]["status"], "cancelled")
        self.assertEqual(c.pedir(4, "tasks/result", {"taskId": tid})["error"]["code"], -32602)
        self.assertEqual(c.pedir(5, "tasks/get", {"taskId": tid})["result"]["status"], "cancelled")

    def test_fallida_y_desconocida(self):
        c = self.cliente(0)
        tid = c.pedir(2, "tools/call", {"name": "cfdi_estatus_sat_carpeta", "arguments": {"carpeta": "/no/existe"},
                                        "task": {}})["result"]["task"]["taskId"]
        res = c.pedir(3, "tasks/result", {"taskId": tid})["result"]
        self.assertTrue(res["isError"])
        t = c.pedir(4, "tasks/get", {"taskId": tid})["result"]
        self.assertEqual(t["status"], "failed")
        self.assertIn("No existe la carpeta", t["statusMessage"])
        for i, m in enumerate(("tasks/get", "tasks/result", "tasks/cancel"), 5):
            self.assertEqual(c.pedir(i, m, {"taskId": "no-existe"})["error"]["code"], -32602)

    def test_task_en_herramienta_sin_soporte_da_error(self):
        c = self.cliente(0)
        r = c.pedir(2, "tools/call", {"name": "cfdi_validar", "arguments": {"ruta": x("ingreso-pue.xml")}, "task": {}})
        self.assertEqual((r["error"]["code"], r["error"]["message"]), (-32601, "Esta herramienta no corre como Task"))

    def test_tareas_vencidas_se_olvidan(self):
        c = self.cliente(0)
        args = {"name": "cfdi_estatus_sat_carpeta", "arguments": {"carpeta": XML, "max_cfdi": 1}}
        viejo = c.pedir(2, "tools/call", {**args, "task": {"ttl": 1}})["result"]["task"]["taskId"]
        c.pedir(3, "tasks/result", {"taskId": viejo})  # ya terminó
        time.sleep(1.1)
        nuevo = c.pedir(4, "tools/call", {**args, "task": {}})["result"]["task"]["taskId"]
        self.assertEqual([t["taskId"] for t in c.pedir(5, "tasks/list")["result"]["tasks"]], [nuevo])
        self.assertEqual(c.pedir(6, "tasks/get", {"taskId": viejo})["error"]["code"], -32602)

    def test_version_de_protocolo(self):
        c = self.cliente(0)
        for pedida, esperada in (("2024-11-05", "2024-11-05"), ("2025-03-26", "2025-03-26"),
                                 ("2026-07-28", "2025-11-25")):
            r = c.pedir(2, "initialize", {"protocolVersion": pedida, "capabilities": {}})
            self.assertEqual(r["result"]["protocolVersion"], esperada)


if __name__ == "__main__":
    unittest.main()
