import unittest
from datetime import datetime
from unittest.mock import patch

from fastapi import HTTPException, status

from app.api.v1.endpoints import ingresos
from app.repositories import ingresos_repo


class ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar(self):
        return self.value


class MappingResult:
    def __init__(self, row):
        self.row = row

    def mappings(self):
        return self

    def first(self):
        return self.row

    def all(self):
        return self.row if isinstance(self.row, list) else []


class EmptyResult:
    pass


class FakeConnection:
    def __init__(self, active_row=None, vehicle_row=None, insert_id=99, print_job_id=100, print_job_error=None, config_rows=None):
        self.active_row = active_row
        self.vehicle_row = vehicle_row
        self.insert_id = insert_id
        self.print_job_id = print_job_id
        self.print_job_error = print_job_error
        self.config_rows = config_rows or []
        self.print_job_inserted = False
        self.calls = []
        self.commit_count = 0
        self.rolled_back = False

    def execute(self, statement, params=None):
        sql = str(statement)
        self.calls.append((sql, params or {}))
        if "GET_LOCK" in sql:
            return ScalarResult(1)
        if "RELEASE_LOCK" in sql:
            return ScalarResult(1)
        if "FROM ingresos i" in sql:
            return MappingResult(self.active_row)
        if "FROM vehiculos" in sql:
            return MappingResult(self.vehicle_row)
        if "FROM configuracion" in sql:
            return MappingResult(self.config_rows)
        if "INSERT INTO print_jobs" in sql:
            if self.print_job_error:
                raise self.print_job_error
            self.print_job_inserted = True
            return EmptyResult()
        if "LAST_INSERT_ID" in sql:
            return ScalarResult(self.print_job_id if self.print_job_inserted else self.insert_id)
        return EmptyResult()

    def commit(self):
        self.commit_count += 1

    def rollback(self):
        self.rolled_back = True


class FakeDbConn:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, exc_type, exc, tb):
        return False


class IngresosAtomicCreationTests(unittest.TestCase):
    def test_endpoint_creates_noches_ingreso_when_requested(self):
        created = {
            "id_vehiculo": 77,
            "id_ingreso": 88,
            "pc_job_id": 89,
            "cobro_noche": {"monto_snapshot": 5000, "hora_inicio_snapshot": "22:00", "hora_fin_snapshot": "08:00"},
        }
        with patch.object(
            ingresos,
            "create_ingreso_with_noches_prepaid_and_required_pc_pdf_job",
            return_value=created,
        ) as create:
            response = ingresos.registrar_ingreso(
                ingresos.IngresoRequest(patente="abc123", noches_prepagadas=True),
                user={"sub": "tester"},
            )

        self.assertEqual(response["noches"], created["cobro_noche"])
        self.assertEqual(response["print"]["pc_job_id"], 89)
        create.assert_called_once()

    def test_noches_ingreso_persists_snapshot_and_ticket_in_one_commit(self):
        conn = FakeConnection(
            vehicle_row={"id_vehiculo": 77},
            insert_id=88,
            print_job_id=89,
            config_rows=[
                {"clave": "noches_activo", "valor": "1"},
                {"clave": "noches_hora_inicio", "valor": "22:00"},
                {"clave": "noches_hora_fin", "valor": "08:00"},
                {"clave": "noches_valor", "valor": "5000"},
            ],
        )
        with patch.object(ingresos_repo, "db_conn", return_value=FakeDbConn(conn)):
            result = ingresos_repo.create_ingreso_with_noches_prepaid_and_required_pc_pdf_job(
                "abc123",
                datetime(2026, 1, 1, 23, 0),
                "tester",
                lambda id_ingreso, cobro: {"kind": "TICKET_INGRESO", "id_ingreso": id_ingreso, "noches": cobro},
            )

        self.assertEqual(result["cobro_noche"]["monto_snapshot"], 5000)
        self.assertEqual(result["cobro_noche"]["hora_inicio_snapshot"], "19:30")
        self.assertEqual(result["cobro_noche"]["hora_fin_snapshot"], "09:30")
        self.assertEqual(conn.commit_count, 1)
        self.assertTrue(any("INSERT INTO cobros_noches" in sql for sql, _ in conn.calls))
        self.assertTrue(any("INSERT INTO print_jobs" in sql for sql, _ in conn.calls))

    def test_noches_ingreso_accepts_outside_reference_hours(self):
        conn = FakeConnection(
            vehicle_row={"id_vehiculo": 77},
            config_rows=[
                {"clave": "noches_activo", "valor": "1"},
                {"clave": "noches_hora_inicio", "valor": "20:00"},
                {"clave": "noches_hora_fin", "valor": "08:00"},
                {"clave": "noches_valor", "valor": "5000"},
            ],
        )
        with patch.object(ingresos_repo, "db_conn", return_value=FakeDbConn(conn)):
            result = ingresos_repo.create_ingreso_with_noches_prepaid_and_required_pc_pdf_job(
                "abc123", datetime(2026, 1, 1, 12, 0), "tester", lambda *_: {}
            )

        self.assertEqual(result["cobro_noche"]["monto_snapshot"], 5000)
        self.assertFalse(conn.rolled_back)
        self.assertEqual(conn.commit_count, 1)
        self.assertTrue(any("INSERT INTO cobros_noches" in sql for sql, _ in conn.calls))

    def test_noches_ingreso_uses_fixed_reference_when_legacy_hours_are_present(self):
        conn = FakeConnection(
            vehicle_row={"id_vehiculo": 77},
            config_rows=[
                {"clave": "noches_activo", "valor": "1"},
                {"clave": "noches_hora_inicio", "valor": "20:00"},
                {"clave": "noches_hora_fin", "valor": "06:00"},
                {"clave": "noches_valor", "valor": "5000"},
            ],
        )

        with patch.object(ingresos_repo, "db_conn", return_value=FakeDbConn(conn)):
            result = ingresos_repo.create_ingreso_with_noches_prepaid_and_required_pc_pdf_job(
                "abc123", datetime(2026, 1, 1, 12, 0), "tester", lambda *_: {}
            )

        self.assertEqual(result["cobro_noche"]["hora_inicio_snapshot"], "19:30")
        self.assertEqual(result["cobro_noche"]["hora_fin_snapshot"], "09:30")

    def test_noches_ingreso_rejects_inactive_or_zero_price(self):
        for config_rows in (
            [
                {"clave": "noches_activo", "valor": "0"},
                {"clave": "noches_hora_inicio", "valor": "20:00"},
                {"clave": "noches_hora_fin", "valor": "08:00"},
                {"clave": "noches_valor", "valor": "5000"},
            ],
            [
                {"clave": "noches_activo", "valor": "1"},
                {"clave": "noches_hora_inicio", "valor": "20:00"},
                {"clave": "noches_hora_fin", "valor": "08:00"},
                {"clave": "noches_valor", "valor": "0"},
            ],
        ):
            with self.subTest(config_rows=config_rows):
                conn = FakeConnection(config_rows=config_rows)
                with self.assertRaises(ingresos_repo.NochesNotAvailable):
                    ingresos_repo._create_noches_charge(conn, 88, datetime(2026, 1, 1, 21, 0), "tester")

    def test_endpoint_returns_existing_duplicate_payload_when_atomic_repo_reports_active(self):
        def fake_create_ingreso_with_required_pc_pdf_job(**kwargs):
            raise ingresos.ActiveIngresoAlreadyExists({"id_ingreso": 10, "patente": "ABC123"})

        with patch.object(
            ingresos,
            "create_ingreso_with_required_pc_pdf_job",
            side_effect=fake_create_ingreso_with_required_pc_pdf_job,
        ):
            with self.assertRaises(HTTPException) as raised:
                ingresos.registrar_ingreso(ingresos.IngresoRequest(patente=" abc123 "), user={"sub": "tester"})

        self.assertEqual(raised.exception.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(
            raised.exception.detail,
            {
                "error": {
                    "code": "PLATE_ALREADY_ACTIVE",
                    "message": "La patente ya tiene un ingreso activo",
                    "details": {"patente": "ABC123"},
                }
            },
        )

    def test_repository_releases_named_lock_when_duplicate_found(self):
        conn = FakeConnection(active_row={"id_ingreso": 10, "id_vehiculo": 5, "patente": "ABC123"})

        with patch.object(ingresos_repo, "db_conn", return_value=FakeDbConn(conn)):
            with self.assertRaises(ingresos_repo.ActiveIngresoAlreadyExists):
                ingresos_repo.create_ingreso_for_plate_if_no_active("abc123", datetime(2026, 1, 1, 10, 0), "tester")

        self.assertTrue(conn.rolled_back)
        self.assertTrue(any("RELEASE_LOCK" in sql for sql, _ in conn.calls))
        self.assertEqual(conn.commit_count, 0)

    def test_repository_blocks_waiting_ingreso_without_creating_print_job_or_committing(self):
        conn = FakeConnection(
            active_row={"id_ingreso": 10, "id_vehiculo": 5, "patente": "ABC123", "en_espera": 1}
        )

        with patch.object(ingresos_repo, "db_conn", return_value=FakeDbConn(conn)):
            with self.assertRaises(ingresos_repo.ActiveIngresoAlreadyExists) as raised:
                ingresos_repo.create_ingreso_with_required_pc_pdf_job(
                    "abc123",
                    datetime(2026, 1, 1, 10, 0),
                    "tester",
                    lambda _: {"kind": "TICKET_INGRESO"},
                )

        active_lookup_sql = next(sql for sql, _ in conn.calls if "FROM ingresos i" in sql)
        self.assertEqual(raised.exception.active_ingreso["en_espera"], 1)
        self.assertNotIn("i.en_espera = 0", active_lookup_sql)
        self.assertTrue(conn.rolled_back)
        self.assertEqual(conn.commit_count, 0)
        self.assertFalse(any("INSERT INTO ingresos" in sql for sql, _ in conn.calls))
        self.assertFalse(any("INSERT INTO print_jobs" in sql for sql, _ in conn.calls))

    def test_repository_releases_named_lock_when_insert_succeeds(self):
        conn = FakeConnection(vehicle_row={"id_vehiculo": 77}, insert_id=88)

        with patch.object(ingresos_repo, "db_conn", return_value=FakeDbConn(conn)):
            result = ingresos_repo.create_ingreso_for_plate_if_no_active(
                "abc123",
                datetime(2026, 1, 1, 10, 0),
                "tester",
            )

        self.assertEqual(result, {"id_vehiculo": 77, "id_ingreso": 88})
        self.assertEqual(conn.commit_count, 1)
        self.assertTrue(any("RELEASE_LOCK" in sql for sql, _ in conn.calls))

    def test_required_pc_job_and_ingreso_commit_once(self):
        conn = FakeConnection(vehicle_row={"id_vehiculo": 77}, insert_id=88, print_job_id=89)

        with patch.object(ingresos_repo, "db_conn", return_value=FakeDbConn(conn)):
            result = ingresos_repo.create_ingreso_with_required_pc_pdf_job(
                "abc123",
                datetime(2026, 1, 1, 10, 0),
                "tester",
                lambda id_ingreso: {"kind": "TICKET_INGRESO", "id_ingreso": id_ingreso},
            )

        print_sql, print_params = next((sql, params) for sql, params in conn.calls if "INSERT INTO print_jobs" in sql)
        self.assertIn("'PC_PDF'", print_sql)
        self.assertEqual(print_params["tipo"], "TICKET_INGRESO")
        self.assertEqual(result, {"id_vehiculo": 77, "id_ingreso": 88, "pc_job_id": 89})
        self.assertEqual(conn.commit_count, 1)
        self.assertFalse(conn.rolled_back)

    def test_print_job_insert_failure_rolls_back_ingreso(self):
        conn = FakeConnection(vehicle_row={"id_vehiculo": 77}, print_job_error=RuntimeError("print job unavailable"))

        with patch.object(ingresos_repo, "db_conn", return_value=FakeDbConn(conn)):
            with self.assertRaises(ingresos_repo.RequiredPrintJobCreationFailed):
                ingresos_repo.create_ingreso_with_required_pc_pdf_job(
                    "abc123", datetime(2026, 1, 1, 10, 0), "tester", lambda _: {"kind": "TICKET_INGRESO"}
                )

        self.assertTrue(conn.rolled_back)
        self.assertEqual(conn.commit_count, 0)
        self.assertTrue(any("RELEASE_LOCK" in sql for sql, _ in conn.calls))

    def test_payload_build_failure_rolls_back_ingreso(self):
        conn = FakeConnection(vehicle_row={"id_vehiculo": 77})

        with patch.object(ingresos_repo, "db_conn", return_value=FakeDbConn(conn)):
            with self.assertRaises(ingresos_repo.RequiredPrintJobCreationFailed):
                ingresos_repo.create_ingreso_with_required_pc_pdf_job(
                    "abc123",
                    datetime(2026, 1, 1, 10, 0),
                    "tester",
                    lambda _: (_ for _ in ()).throw(ValueError("payload failed")),
                )

        self.assertTrue(conn.rolled_back)
        self.assertEqual(conn.commit_count, 0)
        self.assertFalse(any("INSERT INTO print_jobs" in sql for sql, _ in conn.calls))


if __name__ == "__main__":
    unittest.main()
