import unittest

from printer_agent.diagnostics import build_print_diagnostics, build_test_print_guidance


class PrintAgentDiagnosticsTests(unittest.TestCase):
    def test_builds_success_diagnostics_without_printing(self):
        result = build_print_diagnostics(
            sumatra_path=r"C:\EstacionamientoCentral\tools\SumatraPDF\SumatraPDF.exe",
            sumatra_exists=True,
            printer_name="EPSON TM-T20III Receipt",
            printers=[{"name": "EPSON TM-T20III Receipt", "offline": False, "status": "Normal"}],
            queue_count=0,
            last_error="",
        )

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["sumatra"]["status"], "PASS")
        self.assertEqual(result["printer"]["status"], "PASS")
        self.assertEqual(result["printer"]["queue_count"], 0)
        self.assertIn("SumatraPDF", result["supported_path"])

    def test_builds_failure_diagnostics_with_recovery_guidance(self):
        result = build_print_diagnostics(
            sumatra_path="",
            sumatra_exists=False,
            printer_name="POS58 Printer",
            printers=[{"name": "Microsoft Print to PDF", "offline": False, "status": "Normal"}],
            queue_count=-1,
            last_error="Sumatra print failed rc=1",
        )

        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["sumatra"]["status"], "FAIL")
        self.assertEqual(result["printer"]["status"], "WARN")
        self.assertIn("Windows test page", result["next_actions"])
        self.assertIn("Sumatra print failed", result["last_error"])

    def test_test_print_guidance_is_non_destructive(self):
        guidance = build_test_print_guidance(
            pdf_path=r"C:\EstacionamientoCentral\print_out\ticket_prueba.pdf",
            printer_name="EPSON TM-T20III Receipt",
        )

        self.assertIn("ticket de prueba", guidance)
        self.assertIn("no modifica caja", guidance)
        self.assertIn("EPSON TM-T20III Receipt", guidance)


if __name__ == "__main__":
    unittest.main()
