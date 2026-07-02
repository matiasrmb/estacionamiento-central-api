import os
import unittest
from unittest.mock import patch

import print_agent_service_main


class PrintAgentServiceMainTests(unittest.TestCase):
    def test_uses_service_safe_defaults(self):
        with patch.dict(os.environ, {}, clear=True):
            config = print_agent_service_main.get_print_agent_config()

        self.assertEqual(config["agent_module"], "printer_agent.agent")
        self.assertEqual(config["agent_id"], "PC-PRINT-AGENT-01")
        self.assertEqual(config["print_engine"], "SUMATRA")
        self.assertEqual(config["workdir"], "print_out")
        self.assertEqual(config["sumatra_path"], "")

    def test_reads_installer_environment_overrides(self):
        env = {
            "AGENT_ID": "INSTALLER-AGENT",
            "PRINT_ENGINE": "sumatra",
            "PRINT_WORKDIR": r"C:\EstacionamientoCentral\print_out",
            "PRINTER_NAME": "POS-58",
            "SUMATRA_PATH": r"C:\EstacionamientoCentral\tools\SumatraPDF\SumatraPDF.exe",
        }
        with patch.dict(os.environ, env, clear=True):
            config = print_agent_service_main.get_print_agent_config()

        self.assertEqual(config["agent_id"], "INSTALLER-AGENT")
        self.assertEqual(config["print_engine"], "SUMATRA")
        self.assertEqual(config["workdir"], r"C:\EstacionamientoCentral\print_out")
        self.assertEqual(config["printer_name"], "POS-58")
        self.assertEqual(config["sumatra_path"], r"C:\EstacionamientoCentral\tools\SumatraPDF\SumatraPDF.exe")


if __name__ == "__main__":
    unittest.main()
