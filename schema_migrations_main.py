"""Dedicated executable entrypoint for managed schema migrations."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Sequence


def _load_env_file(path: Path) -> None:
    """Load simple KEY=VALUE lines without echoing values or overriding process env."""
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip().strip('"').strip("'")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--env-file", type=Path)
    args, runner_args = parser.parse_known_args(argv)
    if args.env_file is not None:
        if not args.env_file.is_file():
            parser.error("--env-file must identify an existing file")
        _load_env_file(args.env_file)

    # Delay the runner import so environment settings exist before its DB import.
    from app.db.schema_migration_runner import main as runner_main

    return runner_main(runner_args)


if __name__ == "__main__":
    raise SystemExit(main())
