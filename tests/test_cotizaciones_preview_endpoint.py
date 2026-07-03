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
        security_stub.decode_token = lambda token: {"sub": "tester", "rol": "operador"}

        class PasswordContextStub:
            def hash(self, value):
                return f"hashed-{value}"

        security_stub.pwd_context = PasswordContextStub()
        sys.modules["app.core.security"] = security_stub


_install_optional_dependency_stubs()

from fastapi import HTTPException

from app.api.v1.endpoints import cotizaciones
from app.repositories import wash_pricing_repo


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

    def test_preview_can_resolve_estadia_amount_from_configured_tariffs(self):
        payload = cotizaciones.CotizacionPreviewIn(estadia={"minutos": 90})

        with patch.object(cotizaciones, "calcular_monto_preview", return_value={"monto": 2500, "detalle": {}}):
            result = cotizaciones.preview_cotizacion(payload)

        self.assertEqual(result["total"], 2500)
        self.assertEqual(result["items"][0]["monto"], 2500)

    def test_options_are_available_to_operator_and_admin(self):
        self.assertEqual(_allowed_roles(cotizaciones.opciones_cotizacion), {"operador", "admin"})

    def test_options_do_not_query_monthly_customers_and_allow_manual_monthly_amount(self):
        with patch.object(cotizaciones, "list_wash_vehicle_types_for_quotes", return_value=[]):
            result = cotizaciones.opciones_cotizacion()

        self.assertEqual(result["mensualidades"], [])
        self.assertTrue(result["mensualidad_manual"])
        self.assertIn("manual", result["messages"]["mensualidades"])

    def test_options_return_wash_fallback_values_from_repository(self):
        fallback = [{"codigo": "lavado_suv", "nombre": "SUV", "valor_lavado": 8000, "activo": 1}]

        with patch.object(cotizaciones, "list_wash_vehicle_types_for_quotes", return_value=fallback):
            result = cotizaciones.opciones_cotizacion()

        self.assertEqual(result["lavados"], fallback)
        self.assertIsNone(result["messages"]["lavados"])

    def test_wash_quote_repository_falls_back_when_new_table_is_missing(self):
        missing_table = Exception("Table 'estacionamiento_db.tipos_vehiculo_lavado' doesn't exist")
        fallback = [{"codigo": "lavado_citycar", "nombre": "CityCar", "valor_lavado": 5000, "activo": 1}]

        with patch.object(wash_pricing_repo, "list_wash_vehicle_types", side_effect=missing_table), \
             patch.object(wash_pricing_repo, "list_legacy_wash_quote_options", return_value=fallback):
            result = wash_pricing_repo.list_wash_vehicle_types_for_quotes()

        self.assertEqual(result, fallback)

    def test_wash_quote_repository_falls_back_when_new_table_is_empty(self):
        fallback = [{"codigo": "lavado_citycar", "nombre": "CityCar", "valor_lavado": 5000, "activo": 1}]

        with patch.object(wash_pricing_repo, "list_wash_vehicle_types", return_value=[]), \
             patch.object(wash_pricing_repo, "list_legacy_wash_quote_options", return_value=fallback):
            result = wash_pricing_repo.list_wash_vehicle_types_for_quotes()

        self.assertEqual(result, fallback)

    def test_wash_quote_repository_falls_back_when_new_table_has_no_active_rows(self):
        fallback = [{"codigo": "lavado_citycar", "nombre": "CityCar", "valor_lavado": 5000, "activo": 1}]

        with patch.object(wash_pricing_repo, "list_wash_vehicle_types", return_value=[{
            "codigo": "suv", "nombre": "SUV", "valor_lavado": 8000, "activo": 0,
        }]), patch.object(wash_pricing_repo, "list_legacy_wash_quote_options", return_value=fallback):
            result = wash_pricing_repo.list_wash_vehicle_types_for_quotes()

        self.assertEqual(result, fallback)

    def test_wash_quote_repository_accepts_plural_table_name_drift(self):
        singular_missing = Exception("Table 'estacionamiento_db.tipos_vehiculo_lavado' doesn't exist")
        plural_rows = [{"codigo": "suv", "nombre": "SUV", "valor_lavado": 8000, "activo": 1}]

        with patch.object(wash_pricing_repo, "list_wash_vehicle_types", side_effect=[singular_missing, plural_rows]):
            result = wash_pricing_repo.list_wash_vehicle_types_for_quotes()

        self.assertEqual(result, plural_rows)


if __name__ == "__main__":
    unittest.main()
