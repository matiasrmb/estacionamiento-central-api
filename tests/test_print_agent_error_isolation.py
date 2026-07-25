import unittest
from unittest.mock import Mock, patch

import printer_agent.agent as agent
from printer_agent.pdf_printer import AmbiguousPrintDispatchError, PrintDispatchStartError


class _ExecuteResult:
    def __init__(self, scalar_value=None, rowcount=1):
        self._scalar_value = scalar_value
        self.rowcount = rowcount

    def scalar(self):
        return self._scalar_value

    def mappings(self):
        return self

    def first(self):
        return None


class _FakeConnection:
    def __init__(self, scalar_value=None):
        self.scalar_value = scalar_value
        self.executed = []

    def execute(self, statement, params=None):
        self.executed.append((str(statement), params or {}))
        return _ExecuteResult(self.scalar_value)


class _FakeBegin:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self.connection

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeEngine:
    def __init__(self, connection):
        self.connection = connection

    def begin(self):
        return _FakeBegin(self.connection)


class PrintAgentErrorIsolationTests(unittest.TestCase):
    def test_exception_before_claim_does_not_mark_previous_job_error(self):
        sleep_calls = 0

        def sleep(_seconds):
            nonlocal sleep_calls
            sleep_calls += 1
            if sleep_calls == 2:
                raise StopIteration

        with patch.object(agent, "PRINTER_NAME", "Test Printer"), \
            patch.object(agent, "PRINT_ENGINE", "SUMATRA"), \
            patch.object(agent, "SUMATRA_PATH", "C:/SumatraPDF.exe"), \
            patch.object(agent, "release_stale_locks", side_effect=[None, RuntimeError("pre-claim failure")]), \
            patch.object(agent, "claim_next_job", return_value={
                "id_print_job": 123,
                "tipo": "TICKET",
                "patente": "ABC123",
                "payload_json": "{}",
            }), \
            patch.object(agent, "render_ticket_pdf", return_value="ticket.pdf"), \
            patch.object(agent, "mark_dispatch_started"), \
            patch.object(agent, "print_pdf_with_sumatra"), \
            patch.object(agent, "mark_printed"), \
            patch.object(agent, "mark_error") as mark_error, \
            patch.object(agent.time, "sleep", side_effect=sleep):
            with self.assertRaises(StopIteration):
                agent.run_loop()

        mark_error.assert_not_called()

    def test_mark_error_skips_job_not_currently_printing_for_this_agent(self):
        connection = _FakeConnection(scalar_value=None)

        with patch.object(agent, "engine", _FakeEngine(connection)):
            agent.mark_error(123, "boom")

        self.assertEqual(len(connection.executed), 1)
        select_sql, select_params = connection.executed[0]
        self.assertIn("estado='IMPRIMIENDO'", select_sql)
        self.assertIn("locked_by=:agent", select_sql)
        self.assertEqual(select_params["agent"], agent.AGENT_ID)

    def test_mark_error_update_is_guarded_by_printing_state_and_agent_lock(self):
        connection = _FakeConnection(scalar_value=1)

        with patch.object(agent, "engine", _FakeEngine(connection)):
            agent.mark_error(123, "boom")

        self.assertEqual(len(connection.executed), 2)
        update_sql, update_params = connection.executed[1]
        self.assertIn("estado='IMPRIMIENDO'", update_sql)
        self.assertIn("locked_by=:agent", update_sql)
        self.assertEqual(update_params["agent"], agent.AGENT_ID)

    def test_pre_dispatch_error_remains_automatically_retryable(self):
        connection = _FakeConnection(scalar_value=1)

        with patch.object(agent, "engine", _FakeEngine(connection)):
            agent.mark_error(123, "PDF render failed")

        update_sql, update_params = connection.executed[1]
        self.assertIn("intentos=intentos+1", update_sql)
        self.assertIn("next_retry_at=DATE_ADD", update_sql)
        self.assertEqual(update_params["err"], "PDF render failed")

    def test_ambiguous_dispatch_error_requires_manual_review(self):
        connection = _FakeConnection()

        with patch.object(agent, "engine", _FakeEngine(connection)):
            agent.mark_ambiguous_dispatch_error(123, "Sumatra timed out")

        self.assertEqual(len(connection.executed), 1)
        update_sql, update_params = connection.executed[0]
        self.assertIn("estado='REVISION_MANUAL'", update_sql)
        self.assertNotIn("intentos=", update_sql)
        self.assertIn("next_retry_at=NULL", update_sql)
        self.assertIn("estado='IMPRIMIENDO'", update_sql)
        self.assertEqual(update_params["err"], "AMBIGUOUS_PRINT_DISPATCH: Sumatra timed out")

    def test_release_stale_lock_with_dispatch_start_marker_requires_manual_review(self):
        connection = _FakeConnection()

        with patch.object(agent, "engine", _FakeEngine(connection)):
            agent.release_stale_locks()

        update_sql, update_params = connection.executed[0]
        self.assertIn("WHEN last_error LIKE :dispatch_started_prefix THEN 'REVISION_MANUAL'", update_sql)
        self.assertNotIn("intentos=", update_sql)
        self.assertIn("WHEN last_error LIKE :dispatch_started_prefix THEN NULL", update_sql)
        self.assertIn("CONCAT('AMBIGUOUS_PRINT_DISPATCH: ', last_error)", update_sql)
        self.assertEqual(
            update_params["dispatch_started_prefix"],
            "AMBIGUOUS_PRINT_DISPATCH_STARTED:%",
        )

    def test_release_stale_lock_without_dispatch_start_marker_remains_retryable(self):
        connection = _FakeConnection()

        with patch.object(agent, "engine", _FakeEngine(connection)):
            agent.release_stale_locks()

        update_sql, _ = connection.executed[0]
        self.assertNotIn("intentos=", update_sql)
        self.assertIn("ELSE NOW()", update_sql)

    def test_claim_next_job_excludes_manual_review_jobs(self):
        connection = _FakeConnection()

        with patch.object(agent, "engine", _FakeEngine(connection)):
            agent.claim_next_job()

        claim_sql, _ = connection.executed[0]
        self.assertIn("estado='PENDIENTE'", claim_sql)
        self.assertIn("estado='ERROR' AND (next_retry_at IS NULL OR next_retry_at <= NOW())", claim_sql)
        self.assertIn("estado='ERROR'", claim_sql)
        self.assertNotIn("REVISION_MANUAL", claim_sql)
        self.assertIn("AND intentos < max_intentos", claim_sql)

    def test_dispatch_start_marker_is_persisted_while_job_is_locked(self):
        connection = _FakeConnection()

        with patch.object(agent, "engine", _FakeEngine(connection)):
            agent.mark_dispatch_started(123)

        update_sql, update_params = connection.executed[0]
        self.assertIn("estado='IMPRIMIENDO'", update_sql)
        self.assertIn("locked_by=:agent", update_sql)
        self.assertEqual(
            update_params["err"],
            f"AMBIGUOUS_PRINT_DISPATCH_STARTED: agent={agent.AGENT_ID}",
        )

    def test_mark_printed_clears_dispatch_start_marker(self):
        connection = _FakeConnection()

        with patch.object(agent, "engine", _FakeEngine(connection)):
            agent.mark_printed(123)

        update_sql, _ = connection.executed[0]
        self.assertIn("estado='IMPRESO'", update_sql)
        self.assertIn("last_error=NULL", update_sql)

    def test_sumatra_ambiguous_failure_blocks_automatic_retry(self):
        sleep_calls = 0

        def sleep(_seconds):
            nonlocal sleep_calls
            sleep_calls += 1
            raise StopIteration

        with patch.object(agent, "PRINTER_NAME", "Test Printer"), \
            patch.object(agent, "PRINT_ENGINE", "SUMATRA"), \
            patch.object(agent, "SUMATRA_PATH", "C:/SumatraPDF.exe"), \
            patch.object(agent, "release_stale_locks"), \
            patch.object(agent, "claim_next_job", return_value={
                "id_print_job": 123,
                "tipo": "TICKET",
                "patente": "ABC123",
                "payload_json": "{}",
            }), \
            patch.object(agent, "render_ticket_pdf", return_value="ticket.pdf"), \
            patch.object(agent, "mark_dispatch_started"), \
            patch.object(agent, "print_pdf_with_sumatra", side_effect=AmbiguousPrintDispatchError("timed out")), \
            patch.object(agent, "mark_error") as mark_error, \
            patch.object(agent, "mark_ambiguous_dispatch_error") as mark_ambiguous_error, \
            patch.object(agent.time, "sleep", side_effect=sleep):
            with self.assertRaises(StopIteration):
                agent.run_loop()

        mark_error.assert_not_called()
        mark_ambiguous_error.assert_called_once_with(123, "timed out")

    def test_post_dispatch_error_before_mark_printed_blocks_automatic_retry(self):
        sleep_calls = 0

        def sleep(_seconds):
            nonlocal sleep_calls
            sleep_calls += 1
            raise StopIteration

        with patch.object(agent, "PRINTER_NAME", "Test Printer"), \
            patch.object(agent, "PRINT_ENGINE", "SUMATRA"), \
            patch.object(agent, "SUMATRA_PATH", "C:/SumatraPDF.exe"), \
            patch.object(agent, "release_stale_locks"), \
            patch.object(agent, "claim_next_job", return_value={
                "id_print_job": 123,
                "tipo": "TICKET",
                "patente": "ABC123",
                "payload_json": "{}",
            }), \
            patch.object(agent, "render_ticket_pdf", return_value="ticket.pdf"), \
            patch.object(agent, "mark_dispatch_started"), \
            patch.object(agent, "print_pdf_with_sumatra"), \
            patch.object(agent, "mark_printed", side_effect=RuntimeError("database unavailable")), \
            patch.object(agent, "mark_error") as mark_error, \
            patch.object(agent, "mark_ambiguous_dispatch_error") as mark_ambiguous_error, \
            patch.object(agent.time, "sleep", side_effect=sleep):
            with self.assertRaises(StopIteration):
                agent.run_loop()

        mark_error.assert_not_called()
        mark_ambiguous_error.assert_called_once_with(123, "database unavailable")

    def test_known_sumatra_start_failure_remains_automatically_retryable(self):
        sleep_calls = 0

        def sleep(_seconds):
            nonlocal sleep_calls
            sleep_calls += 1
            raise StopIteration

        with patch.object(agent, "PRINTER_NAME", "Test Printer"), \
            patch.object(agent, "PRINT_ENGINE", "SUMATRA"), \
            patch.object(agent, "SUMATRA_PATH", "C:/SumatraPDF.exe"), \
            patch.object(agent, "release_stale_locks"), \
            patch.object(agent, "claim_next_job", return_value={
                "id_print_job": 123,
                "tipo": "TICKET",
                "patente": "ABC123",
                "payload_json": "{}",
            }), \
            patch.object(agent, "render_ticket_pdf", return_value="ticket.pdf"), \
            patch.object(agent, "mark_dispatch_started"), \
            patch.object(
                agent,
                "print_pdf_with_sumatra",
                side_effect=PrintDispatchStartError("Sumatra executable missing"),
            ), \
            patch.object(agent, "mark_error") as mark_error, \
            patch.object(agent, "mark_ambiguous_dispatch_error") as mark_ambiguous_error, \
            patch.object(agent.time, "sleep", side_effect=sleep):
            with self.assertRaises(StopIteration):
                agent.run_loop()

        mark_error.assert_called_once_with(123, "Sumatra executable missing")
        mark_ambiguous_error.assert_not_called()


if __name__ == "__main__":
    unittest.main()
