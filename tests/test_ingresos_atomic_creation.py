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


class EmptyResult:
    pass


class FakeConnection:
    def __init__(self, active_row=None, vehicle_row=None, insert_id=99):
        self.active_row = active_row
        self.vehicle_row = vehicle_row
        self.insert_id = insert_id
        self.calls = []
        self.committed = False
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
        if "LAST_INSERT_ID" in sql:
            return ScalarResult(self.insert_id)
        return EmptyResult()

    def commit(self):
        self.committed = True

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
    def test_endpoint_returns_existing_duplicate_payload_when_atomic_repo_reports_active(self):
        original_create = ingresos.create_ingreso_for_plate_if_no_active
        original_print = ingresos.create_print_job_pc_pdf

        def fake_create_ingreso_for_plate_if_no_active(**kwargs):
            raise ingresos.ActiveIngresoAlreadyExists({"id_ingreso": 10, "patente": "ABC123"})

        try:
            ingresos.create_ingreso_for_plate_if_no_active = fake_create_ingreso_for_plate_if_no_active
            ingresos.create_print_job_pc_pdf = lambda **kwargs: 1

            with self.assertRaises(HTTPException) as raised:
                ingresos.registrar_ingreso(ingresos.IngresoRequest(patente=" abc123 "), user={"sub": "tester"})
        finally:
            ingresos.create_ingreso_for_plate_if_no_active = original_create
            ingresos.create_print_job_pc_pdf = original_print

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
        self.assertFalse(conn.committed)

    def test_repository_releases_named_lock_when_insert_succeeds(self):
        conn = FakeConnection(vehicle_row={"id_vehiculo": 77}, insert_id=88)

        with patch.object(ingresos_repo, "db_conn", return_value=FakeDbConn(conn)):
            result = ingresos_repo.create_ingreso_for_plate_if_no_active(
                "abc123",
                datetime(2026, 1, 1, 10, 0),
                "tester",
            )

        self.assertEqual(result, {"id_vehiculo": 77, "id_ingreso": 88})
        self.assertTrue(conn.committed)
        self.assertTrue(any("RELEASE_LOCK" in sql for sql, _ in conn.calls))


if __name__ == "__main__":
    unittest.main()
