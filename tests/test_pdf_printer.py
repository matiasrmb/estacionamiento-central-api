import subprocess
import unittest
from unittest.mock import patch

from printer_agent.pdf_printer import (
    AmbiguousPrintDispatchError,
    PrintDispatchStartError,
    print_pdf_with_sumatra,
)


class PdfPrinterTests(unittest.TestCase):
    @patch("printer_agent.pdf_printer.subprocess.run")
    @patch("printer_agent.pdf_printer.Path.exists", return_value=False)
    def test_missing_sumatra_is_retryable_before_dispatch(self, _exists, run):
        with self.assertRaisesRegex(PrintDispatchStartError, "SumatraPDF not found"):
            print_pdf_with_sumatra(
                sumatra_path="C:/missing/SumatraPDF.exe",
                pdf_path="ticket.pdf",
                printer_name="Test Printer",
            )

        run.assert_not_called()

    @patch("printer_agent.pdf_printer.subprocess.run")
    @patch("printer_agent.pdf_printer.Path.exists", side_effect=[True, False])
    def test_missing_pdf_is_retryable_before_dispatch(self, _exists, run):
        with self.assertRaisesRegex(PrintDispatchStartError, "PDF not found"):
            print_pdf_with_sumatra(
                sumatra_path="C:/SumatraPDF.exe",
                pdf_path="missing-ticket.pdf",
                printer_name="Test Printer",
            )

        run.assert_not_called()

    @patch("printer_agent.pdf_printer.Path.exists", return_value=True)
    @patch("printer_agent.pdf_printer.subprocess.run")
    def test_sumatra_dispatch_exception_is_ambiguous(self, run, _exists):
        run.side_effect = subprocess.TimeoutExpired("SumatraPDF.exe", 20)

        with self.assertRaises(AmbiguousPrintDispatchError):
            print_pdf_with_sumatra(
                sumatra_path="C:/SumatraPDF.exe",
                pdf_path="ticket.pdf",
                printer_name="Test Printer",
            )

    @patch("printer_agent.pdf_printer.Path.exists", return_value=True)
    @patch("printer_agent.pdf_printer.subprocess.run")
    def test_sumatra_process_start_failure_is_retryable(self, run, _exists):
        run.side_effect = FileNotFoundError("SumatraPDF.exe")

        with self.assertRaises(PrintDispatchStartError):
            print_pdf_with_sumatra(
                sumatra_path="C:/SumatraPDF.exe",
                pdf_path="ticket.pdf",
                printer_name="Test Printer",
            )


if __name__ == "__main__":
    unittest.main()
