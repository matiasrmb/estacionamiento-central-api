"""Production service entrypoint for the packaged API executable.

This module is intentionally separate from ``run.ps1``. The PowerShell script
remains the manual/development launcher; the Windows service uses the executable
built from this module.
"""

from __future__ import annotations

import os
from pathlib import Path

def _load_env_file(path: Path) -> None:
    """Load simple KEY=VALUE lines without overriding process environment."""
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _get_port() -> int:
    raw_port = os.getenv("API_PORT", "8000")
    try:
        return int(raw_port)
    except ValueError as exc:
        raise SystemExit(f"Invalid API_PORT value: {raw_port}") from exc


def get_uvicorn_config() -> dict:
    return {
        "app": "app.main:app",
        "host": os.getenv("API_HOST", "0.0.0.0"),
        "port": _get_port(),
        "log_level": os.getenv("LOG_LEVEL", "info").lower(),
        "reload": False,
    }


def main() -> None:
    import uvicorn

    _load_env_file(Path.cwd() / ".env")
    uvicorn.run(**get_uvicorn_config())


if __name__ == "__main__":
    main()
