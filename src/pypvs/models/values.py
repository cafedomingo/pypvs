"""Typed values from varserver data.

Each function takes a dict of variables (a /vars answer, one device's
variables, or a websocket message's params) and a key. A value that is
missing or does not parse comes back as None rather than zero, so a reading
the PVS did not report is not mistaken for a real 0 (for lifetime energy
counters, a false 0 looks like a counter reset).
"""

from __future__ import annotations

import math
import re
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, overload

# "TBD" is varserver's default for a string variable nothing has set
_PLACEHOLDERS = {"", "TBD"}
# a Unix time further ahead than this is in milliseconds, or wrong
_MAX_AHEAD_S = 365 * 24 * 3600


def _number(value: Any) -> float | None:
    """A finite float from a number or numeric string."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        number = float(value)
    except (ValueError, OverflowError):  # OverflowError: an int too large
        return None
    # nan/inf are "no reading"; NaN would also never compare equal
    return number if math.isfinite(number) else None


def get_float(data: Mapping[str, Any], key: str) -> float | None:
    """data[key] as a finite float."""
    return _number(data.get(key))


def get_int(data: Mapping[str, Any], key: str) -> int | None:
    """data[key] as an int, if it is a whole number."""
    number = _number(data.get(key))
    return None if number is None or not number.is_integer() else int(number)


@overload
def get_str(data: Mapping[str, Any], key: str, default: str = "") -> str: ...
@overload
def get_str(data: Mapping[str, Any], key: str, default: None) -> str | None: ...
def get_str(data: Mapping[str, Any], key: str, default: str | None = "") -> str | None:
    """data[key] as a str."""
    value = data.get(key)
    return default if value is None else str(value)


def get_text(data: Mapping[str, Any], key: str) -> str | None:
    """data[key] as a stripped str; None if it is empty or varserver's "TBD"."""
    value = get_str(data, key, None)
    if value is None:
        return None
    value = value.strip()
    return None if value in _PLACEHOLDERS else value


def get_flag(data: Mapping[str, Any], key: str) -> bool | None:
    """data[key] as a bool: True if it is a non-zero number."""
    number = _number(data.get(key))
    return None if number is None else number != 0


def get_count(data: Mapping[str, Any], key: str) -> int | None:
    """data[key] as an unsigned decimal counter."""
    value = get_text(data, key)
    if value is None:
        return None
    try:
        return int(value) if re.fullmatch(r"[0-9]+", value) else None
    except ValueError:  # over int()'s limit of 4300 decimal digits
        return None


def get_hex(data: Mapping[str, Any], key: str) -> int | None:
    """data[key], hex with or without a 0x prefix, as an int."""
    value = get_text(data, key)
    if value is None:
        return None
    try:
        return int(value, 16)
    except ValueError:
        return None


def get_unix_time(data: Mapping[str, Any], key: str) -> datetime | None:
    """data[key], Unix time in seconds or milliseconds, as a UTC datetime."""
    seconds = _number(data.get(key))
    if seconds is None:
        return None
    latest = time.time() + _MAX_AHEAD_S
    if seconds > latest:
        seconds /= 1000
    if not 0 <= seconds <= latest:
        return None
    return datetime.fromtimestamp(seconds, tz=UTC)


def get_report_time(data: Mapping[str, Any]) -> int:
    """A device's msmtEps ("2024-09-30T16:15:00Z") in UTC seconds.

    Returns 0 if it is absent or malformed.
    """
    try:
        dt = datetime.fromisoformat(get_str(data, "msmtEps"))
    except ValueError:
        return 0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return int(dt.timestamp())
