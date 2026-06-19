import inspect
import sys
import types
import unittest


def _install_optional_dependency_stubs():
    if "sqlalchemy" not in sys.modules:
        sqlalchemy_stub = types.ModuleType("sqlalchemy")
        sqlalchemy_stub.text = lambda value: value
        sqlalchemy_stub.create_engine = lambda *args, **kwargs: object()

        sqlalchemy_engine_stub = types.ModuleType("sqlalchemy.engine")
        sqlalchemy_engine_stub.Connection = object
        sqlalchemy_engine_stub.Engine = object

        sys.modules["sqlalchemy"] = sqlalchemy_stub
        sys.modules["sqlalchemy.engine"] = sqlalchemy_engine_stub

    if "jose" not in sys.modules:
        jose_stub = types.ModuleType("jose")

        class JWTError(Exception):
            pass

        jose_stub.JWTError = JWTError
        sys.modules["jose"] = jose_stub

    if "app.core.security" not in sys.modules:
        security_stub = types.ModuleType("app.core.security")
        security_stub.decode_token = lambda token: {"sub": "tester", "rol": "operador"}
        sys.modules["app.core.security"] = security_stub


_install_optional_dependency_stubs()

from app.api.v1.endpoints import activos, ingresos, salidas


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

    def test_salida_preview_allows_operator_and_admin(self):
        self.assertEqual(_allowed_roles(salidas.preview_salida), {"operador", "admin"})

    def test_salida_confirm_allows_operator_and_admin(self):
        self.assertEqual(_allowed_roles(salidas.confirmar_salida), {"operador", "admin"})


if __name__ == "__main__":
    unittest.main()
