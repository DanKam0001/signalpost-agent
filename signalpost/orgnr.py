"""Norwegian organisation numbers: normalisation and mod-11 validation."""

from __future__ import annotations

import re

_WEIGHTS = (3, 2, 7, 6, 5, 4, 3, 2)
_SEPARATORS = re.compile(r"[\s.\- ]")


def normalise(raw: object) -> str:
    """Strip whitespace, dots, dashes and an optional NO/MVA wrapper."""
    text = str(raw if raw is not None else "").strip().upper()
    if text.startswith("NO"):
        text = text[2:]
    if text.endswith("MVA"):
        text = text[:-3]
    return _SEPARATORS.sub("", text)


def check_digit(first_eight: str) -> int | None:
    total = sum(int(d) * w for d, w in zip(first_eight, _WEIGHTS, strict=True))
    remainder = 11 - total % 11
    if remainder == 11:
        return 0
    if remainder == 10:
        return None  # no valid number has this prefix
    return remainder


def validation_error(number: str) -> str | None:
    """Return a human message when `number` (already normalised) is invalid."""
    if not number:
        return "empty organisation number"
    if not number.isdigit():
        return "organisation number must contain only digits"
    if len(number) != 9:
        return f"organisation number must have exactly 9 digits (got {len(number)})"
    expected = check_digit(number[:8])
    if expected is None or expected != int(number[8]):
        return "organisation number fails the mod-11 check digit"
    return None


def is_valid(number: str) -> bool:
    return validation_error(number) is None
