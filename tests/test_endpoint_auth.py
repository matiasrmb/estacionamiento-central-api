import inspect
import sys
import types
import unittest
from unittest.mock import patch

from fastapi import HTTPException


def _install_optional_dependency_stubs():
    if "sqlalchemy" not in sys.modules:
        sqlalchemy_stub = types.ModuleType("sqlalchemy")
        sqlalchemy_stub.text = lambda value: value
        sqlalchemy_stub.bindparam = lambda value, *args, **kwargs: value
        sqlalchemy_stub.create_engine = lambda *args, **kwargs: object()

        sqlalchemy_engine_stub = types.ModuleType("sqlalchemy.engine")
        sqlalchemy_engine_stub.Connection = object
        sqlalchemy_engine_stub.Engine = object

        sqlalchemy_exc_stub = types.ModuleType("sqlalchemy.exc")

        class IntegrityError(Exception):
            pass

        class DBAPIError(Exception):
            pass

        sqlalchemy_exc_stub.IntegrityError = IntegrityError
        sqlalchemy_exc_stub.DBAPIError = DBAPIError

        sys.modules["sqlalchemy"] = sqlalchemy_stub
        sys.modules["sqlalchemy.engine"] = sqlalchemy_engine_stub
        sys.modules["sqlalchemy.exc"] = sqlalchemy_exc_stub

    if "jose" not in sys.modules:
        jose_stub = types.ModuleType("jose")

        class JWTError(Exception):
            pass

        jose_stub.JWTError = JWTError
        sys.modules["jose"] = jose_stub

    if "app.core.security" not in sys.modules:
        security_stub = types.ModuleType("app.core.security")
        security_stub.decode_token = lambda token: {"sub": "tester", "rol": "operador"}
        security_stub.verify_password = lambda plain, hashed: False
        security_stub.create_access_token = lambda subject, claims: "token"

        class PasswordContextStub:
            def hash(self, value):
                return f"hashed-{value}"

        security_stub.pwd_context = PasswordContextStub()
        sys.modules["app.core.security"] = security_stub


_install_optional_dependency_stubs()

from app.api.v1.endpoints import activos, asistencias, auth, cierres, configuracion, gastos, ingresos, mensuales, operaciones, reportes, resumen_turno, salidas, tarifas, usuarios


def _role_dependency(function):
    for parameter in inspect.signature(function).parameters.values():
        default = parameter.default
        dependency = getattr(default, "dependency", None)
        if hasattr(dependency, "allowed_roles"):
            return dependency
    return None


def _allowed_roles(function):
    dependency = _role_dependency(function)
    if dependency is None:
        return set()
    return set(dependency.allowed_roles)


class EndpointAuthTests(unittest.TestCase):
    def test_ingresos_allows_operator_and_admin(self):
        self.assertEqual(_allowed_roles(ingresos.registrar_ingreso), {"operador", "admin"})

    def test_activos_allows_operator_and_admin(self):
        self.assertEqual(_allowed_roles(activos.listar_activos), {"operador", "admin"})

    def test_resumen_turno_allows_operator_and_admin(self):
        self.assertEqual(_allowed_roles(resumen_turno.obtener_resumen_turno), {"operador", "admin"})

    def test_salida_preview_allows_operator_and_admin(self):
        self.assertEqual(_allowed_roles(salidas.preview_salida), {"operador", "admin"})

    def test_salida_confirm_allows_operator_and_admin(self):
        self.assertEqual(_allowed_roles(salidas.confirmar_salida), {"operador", "admin"})

    def test_configuracion_requires_admin(self):
        self.assertEqual(_allowed_roles(configuracion.obtener_configuracion), {"admin"})
        self.assertEqual(_allowed_roles(configuracion.actualizar_configuracion), {"admin"})

    def test_tarifas_requires_admin(self):
        self.assertEqual(_allowed_roles(tarifas.listar_tarifas_personalizadas), {"admin"})
        self.assertEqual(_allowed_roles(tarifas.crear_tarifa_personalizada), {"admin"})
        self.assertEqual(_allowed_roles(tarifas.actualizar_tarifa_personalizada), {"admin"})
        self.assertEqual(_allowed_roles(tarifas.eliminar_tarifa_personalizada), {"admin"})

    def test_mensuales_allows_operator_and_admin(self):
        allowed = {"operador", "admin"}
        self.assertEqual(_allowed_roles(mensuales.listar_mensuales), allowed)
        self.assertEqual(_allowed_roles(mensuales.crear_mensual), allowed)
        self.assertEqual(_allowed_roles(mensuales.actualizar_tarifa_mensual), allowed)
        self.assertEqual(_allowed_roles(mensuales.actualizar_mensual), allowed)
        self.assertEqual(_allowed_roles(mensuales.registrar_pago_mensual), allowed)
        self.assertEqual(_allowed_roles(mensuales.eliminar_mensual), allowed)

    def test_operaciones_allows_operator_and_admin(self):
        allowed = {"operador", "admin"}
        self.assertEqual(_allowed_roles(operaciones.registrar_bano), allowed)
        self.assertEqual(_allowed_roles(operaciones.listar_lavado_categorias), allowed)
        self.assertEqual(_allowed_roles(operaciones.iniciar_lavado_endpoint), allowed)
        self.assertEqual(_allowed_roles(operaciones.finalizar_lavado_endpoint), allowed)

    def test_cierres_allows_operator_and_admin(self):
        allowed = {"operador", "admin"}
        self.assertEqual(_allowed_roles(cierres.obtener_cierre_pendiente), allowed)
        self.assertEqual(_allowed_roles(cierres.listar_cierres), allowed)
        self.assertEqual(_allowed_roles(cierres.crear_cierre), allowed)

    def test_cierre_lock_conflict_returns_conflict_response(self):
        with patch.object(
            cierres,
            "realizar_cierre",
            side_effect=cierres.DailyCloseInProgressError(),
        ):
            with self.assertRaises(HTTPException) as raised:
                cierres.crear_cierre({"sub": "operador"})

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.detail, "DAILY_CLOSE_IN_PROGRESS")

    def test_login_siempre_registra_asistencia_aunque_el_cliente_intente_omitirse(self):
        user = {"usuario": "operador", "activo": 1, "clave_hash": "hash", "rol": "operador", "id_usuario": 4}
        with (
            patch.object(auth, "get_user_by_username", return_value=user),
            patch.object(auth, "verify_password", return_value=True),
            patch.object(auth, "create_access_token", return_value="token"),
            patch.object(auth, "registrar_asistencia_inicio") as registrar_asistencia,
        ):
            response = auth.login(auth.LoginRequest(usuario="operador", clave="secreta", device_id="mobile-test"))

        self.assertEqual(response.access_token, "token")
        usuario, device_id, session_id = registrar_asistencia.call_args.args
        self.assertEqual((usuario, device_id), ("operador", "mobile-test"))
        self.assertEqual(len(session_id), 32)

    def test_login_generates_legacy_device_and_session_claims_when_device_is_omitted(self):
        user = {"usuario": "operador", "activo": 1, "clave_hash": "hash", "rol": "operador", "id_usuario": 4}
        with (
            patch.object(auth, "get_user_by_username", return_value=user),
            patch.object(auth, "verify_password", return_value=True),
            patch.object(auth, "create_access_token", return_value="token") as create_token,
            patch.object(auth, "registrar_asistencia_inicio"),
        ):
            auth.login(auth.LoginRequest(usuario="operador", clave="secreta"))

        claims = create_token.call_args.kwargs["extra_claims"]
        self.assertEqual(len(claims["sid"]), 32)
        self.assertEqual(claims["device_id"], f"legacy-{claims['sid']}")

    def test_logout_closes_only_the_session_identified_by_the_token(self):
        user = {"sub": "operador", "sid": "session-mobile"}
        with patch.object(auth, "registrar_asistencia_salida", return_value={"cantidad": 0}) as cerrar:
            response = auth.logout(user)

        cerrar.assert_called_once_with("operador", "session-mobile")
        self.assertTrue(response["ok"])

    def test_logout_without_session_claim_does_not_target_username_sessions(self):
        with patch.object(auth, "registrar_asistencia_salida", return_value={"cantidad": 0}) as cerrar:
            auth.logout({"sub": "operador"})

        cerrar.assert_called_once_with("operador", "")

    def test_gastos_allows_operator_and_admin(self):
        allowed = {"operador", "admin"}
        self.assertEqual(_allowed_roles(gastos.crear_gasto_endpoint), allowed)
        self.assertEqual(_allowed_roles(gastos.listar_gastos_pendientes), allowed)

    def test_reportes_requires_admin(self):
        self.assertEqual(_allowed_roles(reportes.listar_movimientos), {"admin"})

    def test_usuarios_requires_admin(self):
        self.assertEqual(_allowed_roles(usuarios.listar_usuarios), {"admin"})
        self.assertEqual(_allowed_roles(usuarios.crear_usuario), {"admin"})
        self.assertEqual(_allowed_roles(usuarios.cambiar_password), {"admin"})
        self.assertEqual(_allowed_roles(usuarios.cambiar_estado), {"admin"})
        self.assertEqual(_allowed_roles(usuarios.eliminar_usuario), {"admin"})

    def test_asistencias_requires_admin(self):
        self.assertEqual(_allowed_roles(asistencias.listar_asistencias), {"admin"})
        self.assertEqual(_allowed_roles(asistencias.cerrar_activas), {"admin"})

    def test_crear_tarifa_uses_repository_alias(self):
        original = tarifas.repo_create_tarifa_personalizada
        calls = []

        def fake_create_tarifa_personalizada(**kwargs):
            calls.append(kwargs)
            return 123

        try:
            tarifas.repo_create_tarifa_personalizada = fake_create_tarifa_personalizada
            payload = tarifas.TarifaPersonalizadaIn(minuto_inicio=0, minuto_fin=30, valor=300)

            result = tarifas.crear_tarifa_personalizada(payload)
        finally:
            tarifas.repo_create_tarifa_personalizada = original

        self.assertEqual(result, {"id_tarifa": 123})
        self.assertEqual(calls, [{"minuto_inicio": 0, "minuto_fin": 30, "valor": 300}])


if __name__ == "__main__":
    unittest.main()
