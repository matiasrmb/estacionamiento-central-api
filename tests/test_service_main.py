import os
import unittest
from unittest.mock import patch

import service_main


class ServiceMainTests(unittest.TestCase):
    def test_uses_production_defaults_without_reload(self):
        with patch.dict(os.environ, {}, clear=True):
            config = service_main.get_uvicorn_config()

        self.assertEqual(config["app"], "app.main:app")
        self.assertEqual(config["host"], "0.0.0.0")
        self.assertEqual(config["port"], 8000)
        self.assertFalse(config["reload"])

    def test_reads_host_and_port_from_environment(self):
        with patch.dict(os.environ, {"API_HOST": "127.0.0.1", "API_PORT": "8123"}, clear=True):
            config = service_main.get_uvicorn_config()

        self.assertEqual(config["host"], "127.0.0.1")
        self.assertEqual(config["port"], 8123)


if __name__ == "__main__":
    unittest.main()
