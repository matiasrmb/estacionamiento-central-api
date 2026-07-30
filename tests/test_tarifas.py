import unittest
import sys
import types
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

try:
    import sqlalchemy  # noqa: F401
except ModuleNotFoundError:
    sqlalchemy_stub = types.ModuleType("sqlalchemy")
    sqlalchemy_stub.text = lambda value: value

    sqlalchemy_engine_stub = types.ModuleType("sqlalchemy.engine")
    sqlalchemy_engine_stub.Connection = object

    sys.modules["sqlalchemy"] = sqlalchemy_stub
    sys.modules["sqlalchemy.engine"] = sqlalchemy_engine_stub

from app.services.tarifas import (
    calcular_minutos_fuera_modo_noche,
    calcular_monto_con_lavados,
    calcular_monto_mvp,
    calcular_montos_activos_con_lavados,
)


class _FakeResult:
    def __init__(self, row=None, rows=None):
        self._row = row
        self._rows = rows or []

    def fetchone(self):
        return self._row

    def fetchall(self):
        return self._rows

    def scalar(self):
        return self._row[0] if isinstance(self._row, tuple) else self._row


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
    def __init__(self, lavado_rows=None, lavado_totals=None, convertido_totals=None, config=None):
        self.queries = []
        self.lavado_rows = lavado_rows or []
        self.lavado_totals = lavado_totals or []
        self.convertido_totals = convertido_totals or []
        self.config = config or {"modo_cobro": "minuto", "tarifa_minima": "300", "valor_minuto": "25"}

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
            return _BatchResult(rows=list(self.config.items()))
        if "FROM subida_precios" in sql:
            return _BatchResult()
        raise AssertionError(f"Unexpected query: {sql}")


class _NightConnection(_FakeConnection):
    def __init__(self, config, wash_rows=None, subida=None):
        super().__init__(config, subida=subida)
        self.wash_rows = wash_rows or []

    def execute(self, statement, params=None):
        sql = str(statement)
        if "SELECT fecha_hora_inicio, fecha_hora_fin" in sql:
            return _BatchResult(rows=self.wash_rows)
        if "SUM(valor_lavado_snapshot)" in sql or "SUM(valor_lavado)" in sql:
            return _FakeResult((0,))
        return super().execute(statement, params)


class CalcularMontoMvpTests(unittest.TestCase):
    def test_modo_noche_cuenta_solo_extras_fuera_de_gracia(self):
        for ingreso, salida, esperado in (
            (datetime(2026, 7, 30, 19, 0), datetime(2026, 7, 31, 10, 0), {"antes": 0, "despues": 0, "total": 0}),
            (datetime(2026, 7, 30, 18, 40), datetime(2026, 7, 31, 9, 30), {"antes": 20, "despues": 0, "total": 20}),
            (datetime(2026, 7, 30, 19, 30), datetime(2026, 7, 31, 10, 20), {"antes": 0, "despues": 20, "total": 20}),
        ):
            with self.subTest(ingreso=ingreso, salida=salida):
                self.assertEqual(calcular_minutos_fuera_modo_noche(ingreso, salida), esperado)

    def test_modo_noche_sin_extras_no_aplica_tarifa_minima(self):
        conn = Mock()
        conn.execute.return_value.mappings.return_value.all.return_value = []
        conn.execute.return_value.scalar.side_effect = [0, 0]
        ingreso = datetime(2026, 7, 30, 19, 0)
        salida = datetime(2026, 7, 31, 10, 0)

        with patch("app.services.tarifas.calcular_monto_desde_minutos") as calcular:
            minutos, monto, _detalle, monto_estacionamiento, total_lavados = calcular_monto_con_lavados(
                conn, 1, ingreso, salida, modo_noche=True
            )

        self.assertEqual((minutos, monto, monto_estacionamiento, total_lavados), (0, 0, 0, 0))
        calcular.assert_not_called()

    def test_modo_noche_descuenta_solo_lavado_que_solapa_extra_previo(self):
        ingreso = datetime(2026, 7, 30, 18, 40)
        salida = datetime(2026, 7, 31, 9, 30)
        conn = _NightConnection(
            {"modo_cobro": "minuto", "tarifa_minima": "0", "valor_minuto": "1"},
            wash_rows=[{
                "fecha_hora_inicio": datetime(2026, 7, 30, 18, 45),
                "fecha_hora_fin": datetime(2026, 7, 30, 19, 15),
            }],
        )

        minutos, _monto, _detalle, _estacionamiento, _lavados = calcular_monto_con_lavados(
            conn, 1, ingreso, salida, modo_noche=True
        )

        self.assertEqual(minutos, 5)

    def test_modo_noche_salida_exacta_a_las_diez_no_tiene_extra(self):
        conn = _NightConnection({"modo_cobro": "minuto", "tarifa_minima": "0", "valor_minuto": "1"})

        minutos, monto, _detalle, estacionamiento, _lavados = calcular_monto_con_lavados(
            conn, 1, datetime(2026, 7, 30, 19, 30), datetime(2026, 7, 31, 10, 0), modo_noche=True
        )

        self.assertEqual((minutos, monto, estacionamiento), (0, 0, 0))

    def test_modo_noche_descuenta_solo_lavado_que_solapa_extra_posterior(self):
        ingreso = datetime(2026, 7, 30, 19, 30)
        salida = datetime(2026, 7, 31, 10, 20)
        conn = _NightConnection(
            {"modo_cobro": "minuto", "tarifa_minima": "0", "valor_minuto": "1"},
            wash_rows=[{
                "fecha_hora_inicio": datetime(2026, 7, 31, 9, 50),
                "fecha_hora_fin": datetime(2026, 7, 31, 10, 10),
            }],
        )

        minutos, _monto, _detalle, _estacionamiento, _lavados = calcular_monto_con_lavados(
            conn, 1, ingreso, salida, modo_noche=True
        )

        self.assertEqual(minutos, 10)

    def test_modo_noche_aplica_recargo_solo_en_intervalo_extra(self):
        ingreso = datetime(2026, 7, 30, 19, 30)
        salida = datetime(2026, 7, 31, 10, 20)
        config = {"modo_cobro": "minuto", "tarifa_minima": "0", "valor_minuto": "0"}
        conn = _NightConnection(
            config,
            subida={"hora_inicio": "09:00", "hora_fin": "10:00", "monto_adicional": 100},
        )

        _, monto, _, estacionamiento, _ = calcular_monto_con_lavados(
            conn, 1, ingreso, salida, modo_noche=True
        )
        self.assertEqual((monto, estacionamiento), (0, 0))

        conn.subida = {"hora_inicio": "10:00", "hora_fin": "10:10", "monto_adicional": 100}
        _, monto, _, estacionamiento, _ = calcular_monto_con_lavados(
            conn, 1, ingreso, salida, modo_noche=True
        )
        self.assertEqual((monto, estacionamiento), (1000, 1000))

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

    def test_minute_mode_charges_only_completed_minutes(self):
        conn = _FakeConnection(
            {"modo_cobro": "minuto", "tarifa_minima": "0", "valor_minuto": "25"}
        )
        ingreso = datetime(2026, 1, 1, 10, 0, 0)

        for segundos, minutos_esperados, monto_esperado in [
            (0, 0, 0),
            (60, 1, 0),
            (61, 1, 0),
            (120, 2, 25),
        ]:
            with self.subTest(segundos=segundos):
                minutos, monto, _ = calcular_monto_mvp(
                    conn, ingreso, ingreso + timedelta(seconds=segundos)
                )

                self.assertEqual(minutos, minutos_esperados)
                self.assertEqual(monto, monto_esperado)

    def test_quote_with_washes_uses_only_completed_minutes(self):
        ingreso = datetime(2026, 1, 1, 10, 0, 0)

        for segundos, minutos_esperados in [(0, 0), (60, 1), (61, 1), (120, 2)]:
            with self.subTest(segundos=segundos):
                conn = Mock()
                conn.execute.return_value.mappings.return_value.all.return_value = []
                conn.execute.return_value.scalar.side_effect = [0, 0]

                with patch("app.services.tarifas.calcular_monto_desde_minutos") as calcular:
                    calcular.return_value = (minutos_esperados, 0, "Modo minuto")
                    calcular_monto_con_lavados(
                        conn, 1, ingreso, ingreso + timedelta(seconds=segundos)
                    )

                self.assertEqual(calcular.call_args.args[1], minutos_esperados)

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

    def test_active_batch_quote_charges_only_completed_minutes(self):
        calculado_a = datetime(2026, 7, 1, 11, 0, 0)
        conn = _BatchConnection(
            config={"modo_cobro": "minuto", "tarifa_minima": "0", "valor_minuto": "25"}
        )
        offsets = [0, 60, 61, 120]

        cotizaciones = calcular_montos_activos_con_lavados(
            conn,
            [
                {
                    "id_ingreso": index,
                    "fecha_hora_ingreso": calculado_a - timedelta(seconds=segundos),
                }
                for index, segundos in enumerate(offsets, start=1)
            ],
            calculado_a,
        )

        self.assertEqual(
            {id_ingreso: cotizaciones[id_ingreso][:2] for id_ingreso in cotizaciones},
            {1: (0, 0), 2: (1, 0), 3: (1, 0), 4: (2, 25)},
        )

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
