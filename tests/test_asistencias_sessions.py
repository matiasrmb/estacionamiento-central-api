import unittest
from datetime import datetime

from app.db.schema_ensure import _ensure_asistencias_schema_on_connection
from app.repositories.asistencias_repo import _calcular_totales_turno, _cerrar_asistencias_activas


class AsistenciasSessionSchemaTests(unittest.TestCase):
    def test_runtime_schema_adds_device_and_session_columns(self):
        class FakeConn:
            def __init__(self):
                self.statements = []

            def execute(self, statement, params=None):
                self.statements.append(str(statement))

        conn = FakeConn()
        _ensure_asistencias_schema_on_connection(conn)

        sql = "\n".join(conn.statements)
        self.assertIn("device_id VARCHAR(128) NULL", sql)
        self.assertIn("session_id VARCHAR(64) NULL", sql)
        self.assertIn("idx_asistencias_sesion_activa", sql)

    def test_migration_declares_device_scoped_attendance(self):
        from pathlib import Path

        migration = Path(__file__).resolve().parents[1].joinpath(
            "app", "db", "migrations", "007_asistencias_por_sesion.sql"
        ).read_text(encoding="utf-8")
        self.assertIn("device_id VARCHAR(128) NULL", migration)
        self.assertIn("session_id VARCHAR(64) NULL", migration)


class AsistenciasSessionRepositoryTests(unittest.TestCase):
    def test_closing_one_session_filters_by_session_id(self):
        class Result:
            def __init__(self, rows):
                self.rows = rows

            def mappings(self):
                return self

            def all(self):
                return self.rows

            def first(self):
                return self.rows[0] if self.rows else None

        class FakeConn:
            def __init__(self):
                self.calls = []

            def execute(self, statement, params=None):
                sql = str(statement)
                self.calls.append((sql, params))
                if "SELECT id_asistencia" in sql:
                    return Result([{"id_asistencia": 8, "hora_inicio": datetime(2026, 1, 1, 9)}])
                return Result([{"cantidad": 0, "total": 0}])

        conn = FakeConn()
        _cerrar_asistencias_activas(
            conn,
            "operador",
            datetime(2026, 1, 1, 10),
            session_id="mobile-session",
        )

        select_sql, select_params = conn.calls[0]
        self.assertIn("AND session_id = :session_id", select_sql)
        self.assertEqual(select_params["session_id"], "mobile-session")
        updates = [sql for sql, _ in conn.calls if "UPDATE asistencias" in sql]
        self.assertEqual(len(updates), 1)

    def test_overlapping_sessions_assign_movements_to_the_oldest_active_attendance(self):
        class Result:
            def __init__(self, row):
                self.row = row

            def mappings(self):
                return self

            def first(self):
                return self.row

        class FakeConn:
            def __init__(self):
                self.calls = []

            def execute(self, statement, params=None):
                self.calls.append((str(statement), params))
                if params["id_asistencia"] == 10 and "FROM ingresos i" in str(statement):
                    return Result({"cantidad": 1, "total": 1200})
                return Result({"cantidad": 0, "total": 0})

        conn = FakeConn()
        first = _calcular_totales_turno(
            conn, "operador", 10, datetime(2026, 1, 1, 9), datetime(2026, 1, 1, 11)
        )
        second = _calcular_totales_turno(
            conn, "operador", 11, datetime(2026, 1, 1, 10), datetime(2026, 1, 1, 11)
        )

        self.assertEqual(first, {"cantidad": 1, "total": 1200})
        self.assertEqual(second, {"cantidad": 0, "total": 0})
        for sql, params in conn.calls:
            self.assertIn("NOT EXISTS", sql)
            self.assertIn("anterior.id_asistencia < :id_asistencia", sql)
            self.assertEqual(params["usuario"], "operador")

    def test_closed_attendance_excludes_movements_at_its_logout_boundary(self):
        class Result:
            def mappings(self):
                return self

            def first(self):
                return {"cantidad": 0, "total": 0}

        class FakeConn:
            def __init__(self):
                self.calls = []

            def execute(self, statement, params=None):
                self.calls.append((str(statement), params))
                return Result()

        conn = FakeConn()
        _calcular_totales_turno(
            conn, "operador", 10, datetime(2026, 1, 1, 9), datetime(2026, 1, 1, 10), "session-a"
        )

        for sql, _ in conn.calls:
            self.assertNotIn("BETWEEN :inicio AND :fin", sql)
            if "FROM ingresos i" in sql:
                self.assertIn("i.fecha_hora_salida >= :inicio", sql)
            elif "FROM usos_bano" in sql:
                self.assertIn("b.fecha_hora >= :inicio", sql)
                self.assertIn("b.fecha_hora < :fin", sql)
            elif "FROM pagos_mensuales" in sql:
                self.assertIn("p.fecha_pago >= :inicio", sql)
                self.assertIn("p.fecha_pago < :fin", sql)
            elif "FROM cobros_noches" in sql:
                self.assertIn("n.fecha_hora_pago >= :inicio", sql)
                self.assertIn("n.fecha_hora_pago < :fin", sql)
            else:
                self.assertIn("o.fecha_hora_fin >= :inicio", sql)
                self.assertIn("o.fecha_hora_fin < :fin", sql)

    def test_legacy_attendance_yields_to_active_sessionized_attendance(self):
        class Result:
            def mappings(self):
                return self

            def first(self):
                return {"cantidad": 0, "total": 0}

        class FakeConn:
            def __init__(self):
                self.calls = []

            def execute(self, statement, params=None):
                self.calls.append((str(statement), params))
                return Result()

        conn = FakeConn()
        _calcular_totales_turno(
            conn, "operador", 11, datetime(2026, 1, 1, 10), datetime(2026, 1, 1, 11), "session-b"
        )

        for sql, params in conn.calls:
            self.assertIn(":session_id IS NOT NULL", sql)
            self.assertIn("anterior.session_id IS NOT NULL", sql)
            self.assertIn("sessionizada.session_id IS NOT NULL", sql)
            self.assertEqual(params["session_id"], "session-b")

    def test_single_session_keeps_all_of_its_movements(self):
        class Result:
            def __init__(self, row):
                self.row = row

            def mappings(self):
                return self

            def first(self):
                return self.row

        class FakeConn:
            def execute(self, statement, params=None):
                if "FROM ingresos i" in str(statement):
                    return Result({"cantidad": 2, "total": 2000})
                if "FROM usos_bano" in str(statement):
                    return Result({"cantidad": 1, "total": 300})
                return Result({"cantidad": 0, "total": 0})

        totals = _calcular_totales_turno(
            FakeConn(), "operador", 10, datetime(2026, 1, 1, 9), datetime(2026, 1, 1, 10)
        )

        self.assertEqual(totals, {"cantidad": 3, "total": 2300})

    def test_second_sequential_session_includes_its_paid_vehicle_exit(self):
        class Result:
            def __init__(self, row):
                self.row = row

            def mappings(self):
                return self

            def first(self):
                return self.row

        class FakeConn:
            def __init__(self):
                self.calls = []

            def execute(self, statement, params=None):
                sql = str(statement)
                self.calls.append((sql, params))
                if "FROM ingresos i" in sql and params["id_asistencia"] == 11:
                    return Result({"cantidad": 1, "total": 1200})
                return Result({"cantidad": 0, "total": 0})

        conn = FakeConn()
        first = _calcular_totales_turno(
            conn, "operador", 10, datetime(2026, 1, 1, 9), datetime(2026, 1, 1, 10), "session-a"
        )
        second = _calcular_totales_turno(
            conn, "operador", 11, datetime(2026, 1, 1, 10), datetime(2026, 1, 1, 11), "session-b"
        )

        self.assertEqual(first, {"cantidad": 0, "total": 0})
        self.assertEqual(second, {"cantidad": 1, "total": 1200})
        exit_queries = [call for call in conn.calls if "FROM ingresos i" in call[0]]
        self.assertEqual(exit_queries[1][1]["session_id"], "session-b")
        self.assertIn("i.usuario = :usuario", exit_queries[1][0])


if __name__ == "__main__":
    unittest.main()
