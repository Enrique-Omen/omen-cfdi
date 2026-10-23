"""Pruebas de OMEN CFDI. Correr desde la raíz del plugin:  python3 -m unittest discover -s tests -v
La consulta real al SAT solo corre con OMEN_CFDI_RED=1 (necesita red)."""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

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
        self.assertEqual(nombres, {"cfdi_leer", "cfdi_validar", "cfdi_estatus_sat", "cfdi_reporte",
                                   "cfdi_conciliar_banco"})
        r3 = resp[3]["result"]
        self.assertFalse(r3["isError"])
        self.assertFalse(json.loads(r3["content"][0]["text"])["valido"])
        self.assertTrue(resp[4]["result"]["isError"])
        self.assertEqual(resp[5]["result"], {})
        self.assertEqual(resp[6]["error"]["code"], -32601)
        self.assertIn("servidor MCP", out.stderr)


if __name__ == "__main__":
    unittest.main()
