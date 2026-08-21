import re


_VALID_PLATE_PATTERN = re.compile(r"^(?:[A-Z]{4}[0-9]{2}|[A-Z]{3}[0-9]{2}|[A-Z]{2}[0-9]{3}[A-Z]{2}|[A-Z]{3}[0-9]{3}|[A-Z]{2}[0-9]{4})$")


def normalize_plate(value: str) -> str:
    """Uppercase a user plate and remove only spaces and hyphens."""
    return str(value or "").upper().replace(" ", "").replace("-", "")


def is_valid_plate(value: str) -> bool:
    return bool(_VALID_PLATE_PATTERN.fullmatch(normalize_plate(value)))


def require_valid_plate(value: str) -> str:
    plate = normalize_plate(value)
    if not _VALID_PLATE_PATTERN.fullmatch(plate):
        raise ValueError("INVALID_PLATE")
    return plate
