import logging
import os
from typing import Any, Mapping


SENSITIVE_KEYS = ("password", "passwd", "pwd", "token", "secret", "key")


def _threshold_ms(name: str, default_ms: int) -> int:
    try:
        return int(os.getenv(name, str(default_ms)))
    except (TypeError, ValueError):
        return default_ms


def _safe_value(key: str, value: Any) -> str:
    if any(part in key.lower() for part in SENSITIVE_KEYS):
        return "[REDACTED]"
    text = str(value).replace("\r", " ").replace("\n", " ")
    return text[:120]


def log_if_slow(
    logger: logging.Logger,
    *,
    threshold_env: str,
    default_ms: int,
    area: str,
    operation: str,
    duration_ms: float,
    context: Mapping[str, Any] | None = None,
) -> bool:
    threshold = _threshold_ms(threshold_env, default_ms)
    if threshold <= 0 or duration_ms <= threshold:
        return False

    fields = [
        "slow_operation",
        f"area={area}",
        f"operation={operation}",
        f"duration_ms={duration_ms:.2f}",
        f"threshold_ms={threshold}",
    ]
    for key, value in (context or {}).items():
        fields.append(f"{key}={_safe_value(key, value)}")

    logger.warning(" ".join(fields))
    return True
