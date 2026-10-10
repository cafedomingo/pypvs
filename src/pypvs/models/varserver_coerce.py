"""Coerce varserver / JSON dict values (missing keys and explicit nulls).

Missing or unparseable values come back as None rather than zero, so a
reading the PVS did not report is not mistaken for a real 0 (for lifetime
energy counters, a false 0 looks like a counter reset).
"""

from __future__ import annotations

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
def str_var(data: dict[str, Any], key: str, default: None) -> str | None: ...
def str_var(data: dict[str, Any], key: str, default: str | None = "") -> str | None:
    v = data.get(key)
    return default if v is None else str(v)
