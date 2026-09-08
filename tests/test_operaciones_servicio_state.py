import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app import main
from app.db import schema_ensure
from app.repositories.operaciones_servicio_repo import (
    ESTADO_ACTIVO,
    ESTADO_CONVERTIDO_ESTADIA,
    ESTADO_FINALIZADO_COBRADO,
    build_operacion_servicio_inicio,
    transition_operacion_servicio,
)
from app.repositories import operaciones_servicio_repo, wash_pricing_repo
from app.schemas.operaciones_servicio import OperacionServicioState
from app.db.schema_ensure import SoloLavadoSchemaUnavailable


class OperacionesServicioStateTests(unittest.TestCase):
    def test_start_translates_missing_wash_table_before_any_write(self):
        empty_result = Mock()
        empty_result.first.return_value = None
        missing_table = Exception('(pymysql.err.ProgrammingError) (1146, "Table \'estacionamiento.tipos_vehiculo_lavado\' doesn\'t exist")')

        with patch.object(operaciones_servicio_repo, "db_conn") as db_conn:
            conn = db_conn.return_value.__enter__.return_value
            conn.execute.side_effect = [empty_result, empty_result, missing_table]

            with self.assertRaises(SoloLavadoSchemaUnavailable):
                operaciones_servicio_repo.iniciar_solo_lavado("AA111AA", 7, "operador")

            statements = [str(call.args[0]).upper() for call in conn.execute.call_args_list]
            self.assertEqual(len(statements), 3)
            self.assertTrue(all(statement.lstrip().startswith("SELECT") for statement in statements))
            self.assertFalse(any("CREATE" in statement or "ALTER" in statement or "INSERT" in statement for statement in statements))
            conn.commit.assert_not_called()

    def test_active_operation_can_finish_as_charged_with_price_snapshot(self):
        operacion = build_operacion_servicio_inicio(
            patente="AA111AA",
            wash_snapshot={
                "id_tipo_vehiculo_lavado": 7,
                "tipo_vehiculo_lavado_snapshot": "SUV",
                "valor_lavado_snapshot": 9000,
            },
            usuario_inicio="operador",
            fecha_hora_inicio="2026-07-01 10:00:00",
        )

        finalizada = transition_operacion_servicio(
            operacion,
            ESTADO_FINALIZADO_COBRADO,
            usuario_fin="cajero",
            fecha_hora_fin="2026-07-01 10:30:00",
        )

        self.assertEqual(finalizada.estado, OperacionServicioState.FINALIZADO_COBRADO)
        self.assertEqual(finalizada.patente, "AA111AA")
        self.assertEqual(finalizada.valor_lavado_snapshot, 9000)
        self.assertEqual(finalizada.usuario_fin, "cajero")
        self.assertEqual(finalizada.fecha_hora_fin, "2026-07-01 10:30:00")

    def test_active_operation_can_convert_to_parking_stay_without_immediate_charge(self):
        operacion = build_operacion_servicio_inicio(
            patente="BB222BB",
            wash_snapshot={
                "id_tipo_vehiculo_lavado": 8,
                "tipo_vehiculo_lavado_snapshot": "Camioneta",
                "valor_lavado_snapshot": 10000,
            },
            usuario_inicio="operador",
            fecha_hora_inicio="2026-07-01 11:00:00",
        )

        convertida = transition_operacion_servicio(
            operacion,
            ESTADO_CONVERTIDO_ESTADIA,
            usuario_fin="operador",
            fecha_hora_fin="2026-07-01 11:45:00",
            id_ingreso_generado=42,
        )

        self.assertEqual(convertida.estado, OperacionServicioState.CONVERTIDO_ESTADIA)
        self.assertEqual(convertida.id_ingreso_generado, 42)
        self.assertFalse(convertida.cobra_ahora)

    def test_finished_operation_cannot_transition_again(self):
        with self.assertRaises(ValueError):
            transition_operacion_servicio(
                {"estado": ESTADO_FINALIZADO_COBRADO},
                ESTADO_CONVERTIDO_ESTADIA,
                usuario_fin="operador",
                fecha_hora_fin="2026-07-01 12:00:00",
            )

    def test_schema_contract_accepts_operation_state_values(self):
        self.assertEqual(OperacionServicioState.ACTIVO.value, ESTADO_ACTIVO)
        self.assertEqual(OperacionServicioState.FINALIZADO_COBRADO.value, ESTADO_FINALIZADO_COBRADO)
        self.assertEqual(OperacionServicioState.CONVERTIDO_ESTADIA.value, ESTADO_CONVERTIDO_ESTADIA)

    def test_migration_declares_additive_operaciones_servicio_contract(self):
        migration = Path(__file__).resolve().parents[1].joinpath(
            "app", "db", "migrations", "002_operaciones_servicio_state.sql"
        ).read_text(encoding="utf-8")

        self.assertIn("CREATE TABLE IF NOT EXISTS operaciones_servicio", migration)
        self.assertIn("estado ENUM('ACTIVO', 'FINALIZADO_COBRADO', 'CONVERTIDO_ESTADIA')", migration)
        self.assertIn("id_ingreso_generado INT NULL", migration)
        self.assertIn("valor_lavado_snapshot INT NOT NULL", migration)

    def test_runtime_does_not_expose_operaciones_schema_ensure(self):
        self.assertFalse(hasattr(schema_ensure, "ensure_operaciones_servicio_schema"))
        self.assertFalse(hasattr(schema_ensure, "_ensure_operaciones_servicio_schema_on_connection"))
        self.assertFalse(hasattr(main, "ensure_operaciones_servicio_schema"))
        self.assertFalse(hasattr(operaciones_servicio_repo, "ensure_operaciones_servicio_schema"))
        self.assertFalse(hasattr(wash_pricing_repo, "ensure_operaciones_servicio_schema"))

if __name__ == "__main__":
    unittest.main()
