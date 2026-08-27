import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import schema_migrations_main


class SchemaMigrationsMainTests(unittest.TestCase):
    def test_loads_explicit_env_file_before_delegating_without_printing_values(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / "installer.env"
            env_file.write_text("DB_NAME=parking\nDB_PASSWORD=not-for-output\n", encoding="utf-8")
            output = io.StringIO()
            with patch.dict(os.environ, {}, clear=True):
                with patch("app.db.schema_migration_runner.main", return_value=0) as runner_main:
                    with redirect_stdout(output):
                        exit_code = schema_migrations_main.main(["--env-file", str(env_file), "--dry-run"])

                self.assertEqual(os.environ["DB_NAME"], "parking")
                self.assertEqual(exit_code, 0)

        runner_main.assert_called_once_with(["--dry-run"])
        self.assertNotIn("not-for-output", output.getvalue())

    def test_rejects_missing_env_file_before_importing_database(self):
        with self.assertRaisesRegex(SystemExit, "2"):
            schema_migrations_main.main(["--env-file", "missing-installer.env", "--dry-run"])


if __name__ == "__main__":
    unittest.main()
