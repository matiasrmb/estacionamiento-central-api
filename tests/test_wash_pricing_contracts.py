import unittest

from app.repositories.wash_pricing_repo import (
    build_wash_price_snapshot,
    build_wash_vehicle_type_payload,
    resolve_wash_type_delete_action,
)
from app.schemas.wash_pricing import WashPriceSnapshot, WashVehicleTypeIn


class WashPricingContractsTests(unittest.TestCase):
    def test_active_type_snapshots_label_and_price(self):
        snapshot = build_wash_price_snapshot({
            "id_tipo_vehiculo_lavado": 7,
            "nombre": "SUV",
            "valor_lavado": "9000",
            "activo": 1,
        })

        self.assertEqual(snapshot, WashPriceSnapshot(
            id_tipo_vehiculo_lavado=7,
            tipo_vehiculo_lavado_snapshot="SUV",
            valor_lavado_snapshot=9000,
        ))

    def test_inactive_type_cannot_create_new_snapshot(self):
        with self.assertRaises(ValueError):
            build_wash_price_snapshot({
                "id_tipo_vehiculo_lavado": 8,
                "nombre": "Furgon",
                "valor_lavado": 15000,
                "activo": 0,
            })

    def test_referenced_type_deactivates_instead_of_deleting(self):
        self.assertEqual(resolve_wash_type_delete_action(3), "deactivate")
        self.assertEqual(resolve_wash_type_delete_action(0), "delete")

    def test_schema_contract_accepts_wash_vehicle_type_payload(self):
        payload = WashVehicleTypeIn(codigo="suv", nombre="SUV", valor_lavado=9000, activo=True)

        self.assertEqual(payload.codigo, "suv")
        self.assertEqual(payload.nombre, "SUV")
        self.assertEqual(payload.valor_lavado, 9000)
        self.assertTrue(payload.activo)

    def test_config_payload_normalizes_label_price_and_active_state(self):
        payload = build_wash_vehicle_type_payload(WashVehicleTypeIn(
            codigo=" suv ",
            nombre=" SUV ",
            valor_lavado=9000,
            activo=False,
        ))

        self.assertEqual(payload, {
            "codigo": "suv",
            "nombre": "SUV",
            "valor_lavado": 9000,
            "activo": 0,
        })

    def test_config_payload_rejects_parking_tariff_fields(self):
        with self.assertRaises(ValueError) as ctx:
            build_wash_vehicle_type_payload({
                "codigo": "camioneta",
                "nombre": "Camioneta",
                "valor_lavado": 12000,
                "tarifa_hora": 5000,
            })

        self.assertEqual(str(ctx.exception), "PARKING_TARIFF_FIELDS_NOT_ALLOWED")


if __name__ == "__main__":
    unittest.main()
