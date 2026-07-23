import importlib
import sys
import types
import unittest
from unittest.mock import Mock, patch

from app.core.config import Settings


def _real_security_module():
    jose_module = sys.modules.get("jose")
    if jose_module is not None and not hasattr(jose_module, "jwt"):
        jose_module.jwt = types.SimpleNamespace(encode=Mock(), decode=Mock())

    module = importlib.import_module("app.core.security")
    if not hasattr(module, "settings"):
        del sys.modules["app.core.security"]
        module = importlib.import_module("app.core.security")
    return module


class ConfigRuntimeSafetyTests(unittest.TestCase):
    def test_dev_allows_empty_generated_secrets(self):
        settings = Settings(env="dev", db_password="", jwt_secret="")

        settings.validate_runtime_safety()

    def test_production_rejects_missing_jwt_secret(self):
        settings = Settings(env="prod", db_password="generated-db-password", jwt_secret="")

        with self.assertRaisesRegex(RuntimeError, "JWT_SECRET must be configured"):
            settings.validate_runtime_safety()

    def test_production_rejects_missing_db_password(self):
        settings = Settings(env="production", db_password="", jwt_secret="generated-jwt-secret")

        with self.assertRaisesRegex(RuntimeError, "DB_PASSWORD must be configured"):
            settings.validate_runtime_safety()

    def test_production_rejects_root_db_user(self):
        settings = Settings(
            env="prod",
            db_user="root",
            db_password="generated-db-password",
            jwt_secret="generated-jwt-secret",
        )

        with self.assertRaisesRegex(RuntimeError, "DB_USER must not be root"):
            settings.validate_runtime_safety()

    def test_production_accepts_generated_secrets_and_app_user(self):
        settings = Settings(
            env="prod",
            db_user="estacionamiento_app",
            db_password="generated-db-password",
            jwt_secret="generated-jwt-secret",
        )

        settings.validate_runtime_safety()

    def test_token_creation_uses_central_runtime_validation(self):
        security = _real_security_module()

        fake_settings = Mock(
            jwt_access_token_expire_minutes=720,
            jwt_secret="generated-jwt-secret",
            jwt_algorithm="HS256",
        )

        with patch.object(security, "settings", fake_settings), patch.object(
            security.jwt, "encode", return_value="token"
        ):
            self.assertEqual(security.create_access_token("tester", {"rol": "admin"}), "token")

        fake_settings.validate_runtime_safety.assert_called_once_with()

    def test_token_decoding_uses_central_runtime_validation(self):
        security = _real_security_module()

        fake_settings = Mock(jwt_secret="generated-jwt-secret", jwt_algorithm="HS256")

        with patch.object(security, "settings", fake_settings), patch.object(
            security.jwt, "decode", return_value={"sub": "tester"}
        ):
            self.assertEqual(security.decode_token("token"), {"sub": "tester"})

        fake_settings.validate_runtime_safety.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
