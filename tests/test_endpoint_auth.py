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

from app.api.deps import get_current_user
from app.api.v1.endpoints import activos, salidas


def _has_current_user_dependency(function):
    for parameter in inspect.signature(function).parameters.values():
        default = parameter.default
        if getattr(default, "dependency", None) is get_current_user:
            return True
    return False


class EndpointAuthTests(unittest.TestCase):
    def test_activos_requires_current_user(self):
        self.assertTrue(_has_current_user_dependency(activos.listar_activos))

    def test_salida_preview_requires_current_user(self):
        self.assertTrue(_has_current_user_dependency(salidas.preview_salida))

    def test_salida_confirm_requires_current_user(self):
        self.assertTrue(_has_current_user_dependency(salidas.confirmar_salida))


if __name__ == "__main__":
    unittest.main()
