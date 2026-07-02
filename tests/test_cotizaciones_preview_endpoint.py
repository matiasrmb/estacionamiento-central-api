import inspect
import sys
import types
import unittest


def _install_optional_dependency_stubs():
    if "jose" not in sys.modules:
        jose_stub = types.ModuleType("jose")

        class JWTError(Exception):
            pass

        jose_stub.JWTError = JWTError
        sys.modules["jose"] = jose_stub

    if "app.core.security" not in sys.modules:
        security_stub = types.ModuleType("app.core.security")
        security_stub.decode_token = lambda token: {"sub": "tester", "rol": "operador"}

        class PasswordContextStub:
            def hash(self, value):
                return f"hashed-{value}"

        security_stub.pwd_context = PasswordContextStub()
        sys.modules["app.core.security"] = security_stub


_install_optional_dependency_stubs()

from fastapi import HTTPException

from app.api.v1.endpoints import cotizaciones


def _allowed_roles(function):
    for parameter in inspect.signature(function).parameters.values():
        dependency = getattr(parameter.default, "dependency", None)
        if hasattr(dependency, "allowed_roles"):
            return set(dependency.allowed_roles)
    return set()


class CotizacionesPreviewEndpointTests(unittest.TestCase):
    def test_preview_allows_operator_and_admin(self):
        self.assertEqual(_allowed_roles(cotizaciones.preview_cotizacion), {"operador", "admin"})

    def test_preview_combines_requested_items_without_side_effects(self):
        payload = cotizaciones.CotizacionPreviewIn(
            estadia={"minutos": 90, "monto_estadia": 2500, "tamano_vehiculo": "camioneta"},
            lavado={"tipo_lavado": "Completo", "monto_lavado": 8000},
            mensualidad={
                "vehiculos": [
                    {"patente": "AAA111", "monto_mensual": 60000},
                    {"patente": "BBB222", "monto_configurado": 30000},
                ]
            },
        )

        result = cotizaciones.preview_cotizacion(payload)

        self.assertEqual(result["tipo"], "combinada")
        self.assertEqual(result["total"], 100500)
        self.assertEqual([item["tipo"] for item in result["items"]], ["estadia", "lavado", "mensualidad"])
        self.assertEqual(result["items"][2]["total_mensual"], 90000)
        self.assertEqual(result["items"][2]["total_diario"], 3000)
        self.assertFalse(result["creates_billable_rows"])

    def test_preview_rejects_monthly_vehicle_missing_amount_clearly(self):
        payload = cotizaciones.CotizacionPreviewIn(
            mensualidad={"vehiculos": [{"patente": "SINMONTO", "monto_mensual": None}]}
        )

        with self.assertRaises(HTTPException) as ctx:
            cotizaciones.preview_cotizacion(payload)

        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(ctx.exception.detail, "MONTHLY_AMOUNT_REQUIRED")


if __name__ == "__main__":
    unittest.main()
