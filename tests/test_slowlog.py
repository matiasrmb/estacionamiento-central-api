import logging
import os
import unittest
from unittest.mock import patch


class ListHandler(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.messages = []

    def emit(self, record):
        self.messages.append(self.format(record))


class SlowLogTests(unittest.TestCase):
    def capture_messages(self, logger):
        handler = ListHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.WARNING)
        return handler

    def test_fast_operation_stays_quiet(self):
        from app.core.slowlog import log_if_slow

        logger = logging.getLogger("tests.api.slowlog.fast")
        handler = self.capture_messages(logger)
        try:
            with patch.dict(os.environ, {"SLOW_API_REQUEST_MS": "100"}, clear=False):
                emitted = log_if_slow(
                    logger,
                    threshold_env="SLOW_API_REQUEST_MS",
                    default_ms=100,
                    area="api",
                    operation="request",
                    duration_ms=99.0,
                    context={"path": "/api/v1/health"},
                )
        finally:
            logger.removeHandler(handler)

        self.assertFalse(emitted)
        self.assertEqual(handler.messages, [])

    def test_slow_operation_logs_safe_context_and_redacts_secrets(self):
        from app.core.slowlog import log_if_slow

        logger = logging.getLogger("tests.api.slowlog.slow")
        handler = self.capture_messages(logger)
        try:
            with patch.dict(os.environ, {"SLOW_API_DB_MS": "50"}, clear=False):
                emitted = log_if_slow(
                    logger,
                    threshold_env="SLOW_API_DB_MS",
                    default_ms=500,
                    area="api_db",
                    operation="select",
                    duration_ms=51.25,
                    context={"table": "ingresos", "token": "secret-value"},
                )
        finally:
            logger.removeHandler(handler)

        self.assertTrue(emitted)
        message = handler.messages[0]
        self.assertIn("slow_operation", message)
        self.assertIn("area=api_db", message)
        self.assertIn("operation=select", message)
        self.assertIn("duration_ms=51.25", message)
        self.assertIn("table=ingresos", message)
        self.assertIn("token=[REDACTED]", message)
        self.assertNotIn("secret-value", message)

    def test_disabled_threshold_does_not_log(self):
        from app.core.slowlog import log_if_slow

        logger = logging.getLogger("tests.api.slowlog.disabled")
        handler = self.capture_messages(logger)
        try:
            with patch.dict(os.environ, {"SLOW_PRINT_JOB_MS": "0"}, clear=False):
                emitted = log_if_slow(
                    logger,
                    threshold_env="SLOW_PRINT_JOB_MS",
                    default_ms=3000,
                    area="print_agent",
                    operation="print",
                    duration_ms=9000.0,
                    context={"job_id": 7},
                )
        finally:
            logger.removeHandler(handler)

        self.assertFalse(emitted)
        self.assertEqual(handler.messages, [])


if __name__ == "__main__":
    unittest.main()
