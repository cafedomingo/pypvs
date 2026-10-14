"""Reading typed values out of varserver data."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from pypvs.models.values import (
    get_count,
    get_flag,
    get_float,
    get_hex,
    get_int,
    get_report_time,
    get_str,
    get_text,
    get_unix_time,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("3.200000", 3.2),
        (-1.5, -1.5),
        (7, 7.0),
        (None, None),
        ("", None),
        ("abc", None),
        # nan/inf are "no reading"; NaN would also never compare equal
        ("nan", None),
        (float("nan"), None),
        ("inf", None),
        ("-inf", None),
        (float("inf"), None),
        ("1e400", None),
        (10**400, None),  # too large for a float
        (True, None),
        ([1], None),
    ],
)
def test_get_float(raw, expected):
    assert get_float({"k": raw}, "k") == expected


def test_missing_key_is_none():
    assert get_float({}, "k") is None
    assert get_int({}, "k") is None
    assert get_flag({}, "k") is None
    assert get_count({}, "k") is None
    assert get_unix_time({}, "k") is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("6", 6), ("12.0", 12), (3, 3), ("12.5", None), ("x", None), (True, None)],
)
def test_get_int_takes_whole_numbers_only(raw, expected):
    assert get_int({"k": raw}, "k") == expected


def test_get_str():
    assert get_str({}, "k") == ""
    assert get_str({}, "k", None) is None
    assert get_str({"k": 5}, "k", None) == "5"
    assert get_str({"k": " PVS6 \n"}, "k") == " PVS6 \n"  # as the PVS sent it


@pytest.mark.parametrize(
    ("raw", "expected"), [(" wan0 ", "wan0"), ("", None), ("TBD", None), (2, "2")]
)
def test_get_text(raw, expected):
    assert get_text({"k": raw}, "k") == expected


@pytest.mark.parametrize(
    ("raw", "expected"), [("1", True), ("0", False), (0.0, False), ("x", None)]
)
def test_get_flag(raw, expected):
    assert get_flag({"k": raw}, "k") is expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0", 0),
        ("42", 42),
        ("0x00ab", 0xAB),
        ("0X1F", 0x1F),
        ("-1", None),
        ("", None),
        ("9" * 5000, None),  # over int()'s digit limit
    ],
)
def test_get_count(raw, expected):
    assert get_count({"k": raw}, "k") == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("0x01", 1), ("0x0B", 11), ("10", 16), ("0A", 10), ("garbage", None), ("", None)],
)
def test_get_hex(raw, expected):
    assert get_hex({"k": raw}, "k") == expected


@pytest.mark.parametrize(
    "raw", ["1791612709", 1791612709, "1791612709.0", "1791612709000"]
)
def test_get_unix_time_seconds_or_milliseconds(raw):
    expected = datetime.fromtimestamp(1791612709, tz=UTC)
    assert get_unix_time({"k": raw}, "k") == expected


@pytest.mark.parametrize("raw", [-1, float("inf"), 10**400, True, "x"])
def test_get_unix_time_rejects_implausible(raw):
    assert get_unix_time({"k": raw}, "k") is None


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({"msmtEps": "2024-09-30T16:15:00Z"}, 1727712900),
        ({"msmtEps": "2024-09-30T16:15:00"}, 1727712900),  # assumed UTC
        ({"msmtEps": "2024-09-30T18:15:00+02:00"}, 1727712900),
        ({}, 0),
        ({"msmtEps": "not a date"}, 0),
    ],
)
def test_get_report_time(data, expected):
    assert get_report_time(data) == expected
