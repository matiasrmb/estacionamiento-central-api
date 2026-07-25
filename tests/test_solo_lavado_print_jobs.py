import unittest
from datetime import datetime
from unittest.mock import patch

from app.repositories import operaciones_servicio_repo
from app.services import print_jobs
from app.services.print_jobs import crear_print_job_solo_lavado, solo_lavado_idempotency_key


class MappingResult:
    def __init__(self, row):
        self.row = row

    def mappings(self):
        return self

    def first(self):
        return self.row


class UpdateResult:
    rowcount = 1


class FakeConnection:
    def __init__(self, operation):
        self.operation = operation
        self.calls = []
        self.committed = False
        self.rolled_back = False

    def execute(self, statement, params=None):
        sql = str(statement)
        self.calls.append((sql, params or {}))
        if "FROM operaciones_servicio" in sql:
            return MappingResult(self.operation)
        if "UPDATE operaciones_servicio" in sql:
            return UpdateResult()
        raise AssertionError(f"Unexpected SQL: {sql}")

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


class FakeDbConn:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self.connection

    def __exit__(self, exc_type, exc, traceback):
        return False


class SoloLavadoPrintJobTests(unittest.TestCase):
    def _operation(self, state="ACTIVO"):
        return {
            "id_operacion_servicio": 31,
            "patente": "ABC123",
            "estado": state,
            "valor_lavado_snapshot": 9000,
            "tipo_vehiculo_lavado_snapshot": "SUV",
            "fecha_hora_inicio": datetime(2026, 7, 25, 10, 0),
        }

    @patch.object(operaciones_servicio_repo, "ensure_operaciones_servicio_schema")
    @patch.object(operaciones_servicio_repo, "crear_print_job_solo_lavado", return_value=True)
    @patch.object(operaciones_servicio_repo, "db_conn")
    def test_cobrar_crea_job_durable_en_la_misma_transaccion(self, db_conn, create_job, _ensure):
        connection = FakeConnection(self._operation())
        db_conn.return_value = FakeDbConn(connection)

        result = operaciones_servicio_repo.finalizar_solo_lavado_cobrar(31, "cajero")

        self.assertTrue(connection.committed)
        create_job.assert_called_once()
        args = create_job.call_args.args
        self.assertIs(args[0], connection)
        self.assertEqual(args[1]["id_operacion_servicio"], 31)
        self.assertEqual(args[3], "cajero")
        self.assertTrue(result["cobra_ahora"])

    @patch.object(operaciones_servicio_repo, "ensure_operaciones_servicio_schema")
    @patch.object(operaciones_servicio_repo, "crear_print_job_solo_lavado")
    @patch.object(operaciones_servicio_repo, "db_conn")
    def test_finalized_operation_does_not_create_a_second_job(self, db_conn, create_job, _ensure):
        db_conn.return_value = FakeDbConn(FakeConnection(self._operation("FINALIZADO_COBRADO")))

        with self.assertRaisesRegex(RuntimeError, "SOLO_WASH_NOT_ACTIVE"):
            operaciones_servicio_repo.finalizar_solo_lavado_cobrar(31, "cajero")

        create_job.assert_not_called()

    @patch.object(operaciones_servicio_repo, "ensure_operaciones_servicio_schema")
    @patch.object(operaciones_servicio_repo, "crear_print_job_solo_lavado", side_effect=RuntimeError("print job unavailable"))
    @patch.object(operaciones_servicio_repo, "db_conn")
    def test_job_failure_rolls_back_service_finalization(self, db_conn, _create_job, _ensure):
        connection = FakeConnection(self._operation())
        db_conn.return_value = FakeDbConn(connection)

        with self.assertRaisesRegex(RuntimeError, "print job unavailable"):
            operaciones_servicio_repo.finalizar_solo_lavado_cobrar(31, "cajero")

        self.assertFalse(connection.committed)
        self.assertTrue(connection.rolled_back)

    @patch.object(operaciones_servicio_repo, "ensure_operaciones_servicio_schema")
    @patch.object(operaciones_servicio_repo, "crear_print_job_solo_lavado", return_value=False)
    @patch.object(operaciones_servicio_repo, "db_conn")
    def test_job_not_created_rolls_back_service_finalization(self, db_conn, _create_job, _ensure):
        connection = FakeConnection(self._operation())
        db_conn.return_value = FakeDbConn(connection)

        with self.assertRaisesRegex(RuntimeError, "SOLO_WASH_PRINT_JOB_NOT_CREATED"):
            operaciones_servicio_repo.finalizar_solo_lavado_cobrar(31, "cajero")

        self.assertFalse(connection.committed)
        self.assertTrue(connection.rolled_back)
        self.assertTrue(any("UPDATE operaciones_servicio" in sql for sql, _ in connection.calls))

    @patch.object(print_jobs, "crear_print_job", return_value=True)
    def test_crear_job_solo_lavado_uses_expected_payload(self, create_job):
        operation = self._operation()
        finished_at = datetime(2026, 7, 25, 10, 35, 42)
        connection = object()

        self.assertTrue(crear_print_job_solo_lavado(connection, operation, finished_at, "cajero"))

        create_job.assert_called_once_with(
            connection,
            tipo="TICKET_SOLO_LAVADO",
            destino="PC_PDF",
            id_ingreso=None,
            patente="ABC123",
            payload={
                "kind": "TICKET_SOLO_LAVADO",
                "id_operacion_servicio": 31,
                "patente": "ABC123",
                "servicio": "SUV",
                "hora_inicio": "2026-07-25 10:00:00",
                "hora_fin": "2026-07-25 10:35:42",
                "minutos": 35,
                "monto_final": 9000,
                "total": 9000,
                "detalle_texto": "Lavado SUV",
                "usuario": {"usuario": "cajero"},
                "meta": {"server_time": "2026-07-25 10:35:42", "version": 1},
            },
            idempotency_key="api-solo-lavado:31:pc-pdf",
            prioridad=50,
        )

    def test_idempotency_key_is_stable(self):
        self.assertEqual(solo_lavado_idempotency_key(31), "api-solo-lavado:31:pc-pdf")
        self.assertEqual(solo_lavado_idempotency_key(31), solo_lavado_idempotency_key(31))


if __name__ == "__main__":
    unittest.main()
