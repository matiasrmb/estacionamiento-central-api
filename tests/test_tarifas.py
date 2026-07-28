import unittest
import sys
import types
from datetime import datetime, timedelta

try:
    import sqlalchemy  # noqa: F401
except ModuleNotFoundError:
    sqlalchemy_stub = types.ModuleType("sqlalchemy")
    sqlalchemy_stub.text = lambda value: value

    sqlalchemy_engine_stub = types.ModuleType("sqlalchemy.engine")
    sqlalchemy_engine_stub.Connection = object

    sys.modules["sqlalchemy"] = sqlalchemy_stub
    sys.modules["sqlalchemy.engine"] = sqlalchemy_engine_stub

from app.services.tarifas import calcular_monto_mvp, calcular_montos_activos_con_lavados


class _FakeResult:
    def __init__(self, row=None, rows=None):
        self._row = row
        self._rows = rows or []

    def fetchone(self):
        return self._row

    def fetchall(self):
        return self._rows


class _FakeConnection:
    def __init__(self, config, tramos=None, subida=None):
        self.config = config
        self.tramos = tramos or []
        self.subida = subida

    def execute(self, statement, params=None):
        sql = str(statement)

        if "FROM tarifas_personalizadas" in sql:
            rows = [
                (tramo["minuto_inicio"], tramo["minuto_fin"], tramo["valor"])
                for tramo in self.tramos
            ]
            return _FakeResult(rows=rows)

        if "FROM subida_precios" in sql:
            if self.subida is None:
                return _FakeResult()
            return _FakeResult(
                (
                    self.subida["hora_inicio"],
                    self.subida["hora_fin"],
                    self.subida["monto_adicional"],
                )
            )

        if "FROM configuracion" in sql:
            if params is None:
                return _FakeResult(rows=list(self.config.items()))

            clave = params["c"]
            value = self.config.get(clave)
            if value is None:
                return _FakeResult()
            return _FakeResult((value,))

        raise AssertionError(f"Unexpected query: {sql}")


class _BatchResult(_FakeResult):
    def mappings(self):
        return self

    def all(self):
        return self._rows


class _BatchConnection:
    def __init__(self, lavado_rows=None, lavado_totals=None, convertido_totals=None):
        self.queries = []
        self.lavado_rows = lavado_rows or []
        self.lavado_totals = lavado_totals or []
        self.convertido_totals = convertido_totals or []

    def execute(self, statement, params=None):
        sql = str(statement)
        self.queries.append(sql)
        if "fecha_hora_inicio, fecha_hora_fin" in sql:
            return _BatchResult(rows=self.lavado_rows)
        if "SUM(valor_lavado)" in sql:
            return _BatchResult(rows=self.lavado_totals)
        if "SUM(valor_lavado_snapshot)" in sql:
            return _BatchResult(rows=self.convertido_totals)
        if "FROM configuracion" in sql:
            return _BatchResult(rows=[("modo_cobro", "minuto"), ("tarifa_minima", "300"), ("valor_minuto", "25")])
        if "FROM subida_precios" in sql:
            return _BatchResult()
        raise AssertionError(f"Unexpected query: {sql}")


class CalcularMontoMvpTests(unittest.TestCase):
    def test_uses_desktop_tarifa_hora_when_legacy_key_is_missing(self):
        conn = _FakeConnection({"modo_cobro": "desconocido", "tarifa_minima": "300", "tarifa_hora": "1300"})
        ingreso = datetime(2026, 1, 1, 10, 0, 0)
        salida = ingreso + timedelta(minutes=61)

        minutos, monto, detalle = calcular_monto_mvp(conn, ingreso, salida)

        self.assertEqual(minutos, 61)
        self.assertEqual(monto, 1600)
        self.assertEqual(detalle, "MVP: mínima + 1h extra")

    def test_preserves_legacy_tarifa_por_hora_precedence_when_present(self):
        conn = _FakeConnection(
            {
                "modo_cobro": "desconocido",
                "tarifa_minima": "300",
                "tarifa_por_hora": "600",
                "tarifa_hora": "1300",
            }
        )
        ingreso = datetime(2026, 1, 1, 10, 0, 0)
        salida = ingreso + timedelta(minutes=121)

        minutos, monto, detalle = calcular_monto_mvp(conn, ingreso, salida)

        self.assertEqual(minutos, 121)
        self.assertEqual(monto, 1500)
        self.assertEqual(detalle, "MVP: mínima + 2h extra")

    def test_matches_desktop_minute_mode(self):
        conn = _FakeConnection(
            {"modo_cobro": "minuto", "tarifa_minima": "300", "valor_minuto": "25"}
        )
        ingreso = datetime(2026, 1, 1, 10, 0, 0)
        salida = ingreso + timedelta(minutes=10)

        minutos, monto, detalle = calcular_monto_mvp(conn, ingreso, salida)

        self.assertEqual(minutos, 10)
        self.assertEqual(monto, 525)
        self.assertEqual(detalle, "Modo minuto")

    def test_matches_desktop_auto_mode(self):
        conn = _FakeConnection({"modo_cobro": "auto", "tarifa_minima": "300"})
        ingreso = datetime(2026, 1, 1, 10, 0, 0)
        salida = ingreso + timedelta(minutes=61)

        minutos, monto, detalle = calcular_monto_mvp(conn, ingreso, salida)

        self.assertEqual(minutos, 61)
        self.assertEqual(monto, 600)
        self.assertEqual(detalle, "Modo auto")

    def test_matches_desktop_custom_mode_cycles_tramos(self):
        conn = _FakeConnection(
            {"modo_cobro": "personalizado", "tarifa_minima": "300"},
            tramos=[
                {"minuto_inicio": 0, "minuto_fin": 30, "valor": 300},
                {"minuto_inicio": 31, "minuto_fin": 60, "valor": 600},
            ],
        )
        ingreso = datetime(2026, 1, 1, 10, 0, 0)
        salida = ingreso + timedelta(minutes=61)

        minutos, monto, detalle = calcular_monto_mvp(conn, ingreso, salida)

        self.assertEqual(minutos, 61)
        self.assertEqual(monto, 900)
        self.assertEqual(detalle, "Modo personalizado - tramo 0-30 min (+1 ciclo(s) completo(s))")

    def test_matches_desktop_minute_mode_with_subida(self):
        conn = _FakeConnection(
            {"modo_cobro": "minuto", "tarifa_minima": "300", "valor_minuto": "25"},
            subida={"hora_inicio": "10:00", "hora_fin": "10:10", "monto_adicional": 100},
        )
        ingreso = datetime(2026, 1, 1, 10, 0, 0)
        salida = ingreso + timedelta(minutes=11)

        minutos, monto, detalle = calcular_monto_mvp(conn, ingreso, salida)

        self.assertEqual(minutos, 11)
        self.assertEqual(monto, 1550)
        self.assertEqual(detalle, "Modo minuto")

    def test_active_batch_quote_uses_fixed_aggregate_and_tariff_queries(self):
        conn = _BatchConnection()
        calculado_a = datetime(2026, 7, 1, 11, 0)

        cotizaciones = calcular_montos_activos_con_lavados(
            conn,
            [
                {"id_ingreso": 1, "fecha_hora_ingreso": datetime(2026, 7, 1, 10, 0)},
                {"id_ingreso": 2, "fecha_hora_ingreso": datetime(2026, 7, 1, 10, 15)},
                {"id_ingreso": 3, "fecha_hora_ingreso": datetime(2026, 7, 1, 10, 30)},
            ],
            calculado_a,
        )

        self.assertEqual(set(cotizaciones), {1, 2, 3})
        self.assertEqual(len(conn.queries), 5)
        self.assertEqual(sum("FROM lavados" in query for query in conn.queries), 2)
        self.assertEqual(sum("FROM operaciones_servicio" in query for query in conn.queries), 1)
        self.assertEqual(sum("FROM configuracion" in query for query in conn.queries), 1)

    def test_active_batch_quote_caps_active_wash_at_calculation_time(self):
        calculado_a = datetime(2026, 7, 1, 11, 0)
        conn = _BatchConnection(
            lavado_rows=[{
                "id_ingreso": 1,
                "fecha_hora_inicio": datetime(2026, 7, 1, 10, 30),
                "fecha_hora_fin": datetime(2026, 7, 1, 11, 30),
            }]
        )

        cotizaciones = calcular_montos_activos_con_lavados(
            conn,
            [{"id_ingreso": 1, "fecha_hora_ingreso": datetime(2026, 7, 1, 10, 0)}],
            calculado_a,
        )

        minutos, monto, detalle, monto_estacionamiento, total_lavados = cotizaciones[1]
        self.assertEqual(minutos, 30)
        self.assertEqual(monto_estacionamiento, 1025)
        self.assertEqual(monto, 1025)
        self.assertEqual(total_lavados, 0)
        self.assertIn("descuenta 30 min de lavado", detalle)

    def test_active_batch_quote_includes_converted_solo_lavado_once(self):
        calculado_a = datetime(2026, 7, 1, 11, 0)
        conn = _BatchConnection(
            convertido_totals=[{"id_ingreso_generado": 1, "total": 9000}]
        )

        cotizaciones = calcular_montos_activos_con_lavados(
            conn,
            [{"id_ingreso": 1, "fecha_hora_ingreso": datetime(2026, 7, 1, 10, 0)}],
            calculado_a,
        )

        minutos, monto, detalle, monto_estacionamiento, total_lavados = cotizaciones[1]
        self.assertEqual(minutos, 60)
        self.assertEqual(monto_estacionamiento, 1775)
        self.assertEqual(total_lavados, 9000)
        self.assertEqual(monto, 10775)
        self.assertIn("lavados $9000", detalle)
        self.assertIn("incluye solo lavado convertido $9000", detalle)


if __name__ == "__main__":
    unittest.main()
