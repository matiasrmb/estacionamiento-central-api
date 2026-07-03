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

from app.api.v1.endpoints import solo_lavados


def _allowed_roles(function):
    for parameter in inspect.signature(function).parameters.values():
        dependency = getattr(parameter.default, "dependency", None)
        if hasattr(dependency, "allowed_roles"):
            return set(dependency.allowed_roles)
    return set()


class SoloLavadoApiDomainTests(unittest.TestCase):
    def test_start_solo_lavado_creates_service_operation_with_snapshot(self):
        self.assertEqual(_allowed_roles(solo_lavados.iniciar_solo_lavado), {"operador", "admin"})

        with patch.object(solo_lavados, "repo_iniciar_solo_lavado") as repo_start:
            repo_start.return_value = {
                "id_operacion_servicio": 11,
                "patente": "AA111AA",
                "estado": "ACTIVO",
                "valor_lavado_snapshot": 9000,
            }

            result = solo_lavados.iniciar_solo_lavado(
                solo_lavados.SoloLavadoInicioIn(
                    patente="aa111aa",
                    id_tipo_vehiculo_lavado=7,
                ),
                user={"sub": "operador"},
            )

        self.assertEqual(result["patente"], "AA111AA")
        self.assertEqual(result["estado"], "ACTIVO")
        self.assertEqual(result["valor_lavado_snapshot"], 9000)
        repo_start.assert_called_once_with("aa111aa", 7, "operador")

    def test_finalize_solo_lavado_charge_now_returns_separate_revenue_state(self):
        with patch.object(solo_lavados, "repo_finalizar_solo_lavado_cobrar") as repo_finish:
            repo_finish.return_value = {
                "id_operacion_servicio": 11,
                "estado": "FINALIZADO_COBRADO",
                "cobra_ahora": True,
                "valor_lavado_snapshot": 9000,
            }

            result = solo_lavados.finalizar_solo_lavado_cobrar(
                11,
                user={"sub": "cajero"},
            )

        self.assertTrue(result["cobra_ahora"])
        self.assertEqual(result["estado"], "FINALIZADO_COBRADO")
        self.assertEqual(result["valor_lavado_snapshot"], 9000)
        repo_finish.assert_called_once_with(11, "cajero")

    def test_finalize_solo_lavado_convert_to_stay_defers_wash_charge(self):
        with patch.object(solo_lavados, "repo_convertir_solo_lavado_a_estadia") as repo_convert:
            repo_convert.return_value = {
                "id_operacion_servicio": 12,
                "estado": "CONVERTIDO_ESTADIA",
                "cobra_ahora": False,
                "id_ingreso_generado": 42,
                "fecha_hora_ingreso": "2026-07-01T11:45:00",
            }

            result = solo_lavados.convertir_solo_lavado_a_estadia(
                12,
                user={"sub": "operador"},
            )

        self.assertFalse(result["cobra_ahora"])
        self.assertEqual(result["estado"], "CONVERTIDO_ESTADIA")
        self.assertEqual(result["id_ingreso_generado"], 42)
        self.assertEqual(result["fecha_hora_ingreso"], "2026-07-01T11:45:00")
        repo_convert.assert_called_once_with(12, "operador")

    def test_list_solo_lavados_active_is_available_to_operator(self):
        self.assertEqual(_allowed_roles(solo_lavados.listar_solo_lavados_activos), {"operador", "admin"})

        with patch.object(solo_lavados, "repo_list_solo_lavados_activos") as repo_list:
            repo_list.return_value = [{"id_operacion_servicio": 12, "patente": "AA111AA"}]

            result = solo_lavados.listar_solo_lavados_activos(
                patente="aa111aa",
                _user={"sub": "operador"},
            )

        self.assertEqual(result["items"][0]["id_operacion_servicio"], 12)
        repo_list.assert_called_once_with("aa111aa")


if __name__ == "__main__":
    unittest.main()
