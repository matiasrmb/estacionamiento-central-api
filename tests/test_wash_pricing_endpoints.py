import inspect
import sys
import types
import unittest
from unittest.mock import patch


def _install_optional_dependency_stubs():
    if "jose" not in sys.modules:
        jose_stub = types.ModuleType("jose")

        class JWTError(Exception):
            pass

        jose_stub.JWTError = JWTError
        sys.modules["jose"] = jose_stub

    if "app.core.security" not in sys.modules:
        security_stub = types.ModuleType("app.core.security")
        security_stub.decode_token = lambda token: {"sub": "tester", "rol": "admin"}

        class PasswordContextStub:
            def hash(self, value):
                return f"hashed-{value}"

        security_stub.pwd_context = PasswordContextStub()
        sys.modules["app.core.security"] = security_stub


_install_optional_dependency_stubs()

from fastapi import HTTPException

from app.api.v1.endpoints import wash_pricing


def _allowed_roles(function):
    for parameter in inspect.signature(function).parameters.values():
        dependency = getattr(parameter.default, "dependency", None)
        if hasattr(dependency, "allowed_roles"):
            return set(dependency.allowed_roles)
    return set()


class WashPricingEndpointsTests(unittest.TestCase):
    def test_vehicle_type_crud_is_admin_only(self):
        self.assertEqual(_allowed_roles(wash_pricing.listar_tipos_vehiculo_lavado), {"admin"})
        self.assertEqual(_allowed_roles(wash_pricing.crear_tipo_vehiculo_lavado), {"admin"})
        self.assertEqual(_allowed_roles(wash_pricing.actualizar_tipo_vehiculo_lavado), {"admin"})
        self.assertEqual(_allowed_roles(wash_pricing.eliminar_tipo_vehiculo_lavado), {"admin"})

    @patch.object(wash_pricing, "repo_list_wash_vehicle_types")
    def test_lists_vehicle_types_without_parking_tariff_fields(self, repo_list):
        repo_list.return_value = [{
            "id_tipo_vehiculo_lavado": 1,
            "codigo": "suv",
            "nombre": "SUV",
            "valor_lavado": 9000,
            "activo": 1,
        }]

        result = wash_pricing.listar_tipos_vehiculo_lavado()

        self.assertEqual(result["items"][0]["valor_lavado"], 9000)
        self.assertNotIn("tarifa_hora", result["items"][0])

    @patch.object(wash_pricing, "repo_delete_wash_vehicle_type")
    def test_delete_reports_deactivated_when_type_has_history(self, repo_delete):
        repo_delete.return_value = "deactivated"

        result = wash_pricing.eliminar_tipo_vehiculo_lavado(8)

        self.assertEqual(result, {"ok": True, "action": "deactivated"})

    @patch.object(wash_pricing, "repo_update_wash_vehicle_type")
    def test_missing_vehicle_type_maps_to_404(self, repo_update):
        repo_update.side_effect = LookupError("WASH_VEHICLE_TYPE_NOT_FOUND")

        with self.assertRaises(HTTPException) as ctx:
            wash_pricing.actualizar_tipo_vehiculo_lavado(
                99,
                wash_pricing.WashVehicleTypeIn(codigo="suv", nombre="SUV", valor_lavado=9000),
            )

        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(ctx.exception.detail, "WASH_VEHICLE_TYPE_NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
