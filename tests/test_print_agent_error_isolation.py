import unittest
from unittest.mock import Mock, patch

import printer_agent.agent as agent


class _ExecuteResult:
    def __init__(self, scalar_value=None):
        self._scalar_value = scalar_value

    def scalar(self):
        return self._scalar_value


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


if __name__ == "__main__":
    unittest.main()
