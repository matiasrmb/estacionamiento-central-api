import unittest
from pathlib import Path

from app.repositories.operaciones_servicio_repo import (
    ESTADO_ACTIVO,
    ESTADO_CONVERTIDO_ESTADIA,
    ESTADO_FINALIZADO_COBRADO,
    build_operacion_servicio_inicio,
    transition_operacion_servicio,
)
from app.schemas.operaciones_servicio import OperacionServicioState


class OperacionesServicioStateTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
