"""Coerce varserver / JSON dict values (missing keys and explicit nulls).

Missing or unparseable values come back as None rather than zero, so a
reading the PVS did not report is not mistaken for a real 0 (for lifetime
energy counters, a false 0 looks like a counter reset).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, overload


def float_var(
    data: dict[str, Any], key: str, default: float | None = None
) -> float | None:
    v = data.get(key)
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def int_var(data: dict[str, Any], key: str, default: int | None = None) -> int | None:
    v = data.get(key)
    if v is None:
        return default
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


@overload
def str_var(data: dict[str, Any], key: str, default: str = "") -> str: ...
@overload
def str_var(data: dict[str, Any], key: str, default: str | None) -> str | None: ...
def str_var(data: dict[str, Any], key: str, default: str | None = "") -> str | None:
    v = data.get(key)
    return default if v is None else str(v)


def report_time_var(data: dict[str, Any]) -> int:
    """A device's msmtEps ("2024-09-30T16:15:00Z") in UTC seconds; 0 if absent
    or malformed."""
    try:
        dt = datetime.strptime(str_var(data, "msmtEps"), "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return 0
    return int(dt.replace(tzinfo=UTC).timestamp())
