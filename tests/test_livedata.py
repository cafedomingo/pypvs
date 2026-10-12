"""Parsing /sys/livedata values, from varserver and from the websocket."""

from __future__ import annotations

from datetime import UTC, datetime

from pypvs.models.livedata import PVSLiveData

# A /sys/livedata answer as the PVS6 actually returns it: every value a string.
LIVE_STRINGS = {
    "/sys/livedata/midstate": "2",
    "/sys/livedata/net_p": "-1.100000",
    "/sys/livedata/pv_p": "3.200000",
    "/sys/livedata/soc": "0.200000",
    "/sys/livedata/time": "1791612709",
}


def test_parses_string_payload():
    live = PVSLiveData.from_varserver(LIVE_STRINGS)
    assert live.time == datetime.fromtimestamp(1791612709, tz=UTC)
    assert live.pv_p == 3.2
    assert live.net_p == -1.1
    assert live.soc == 0.2
    assert live.midstate == "2"


def test_midstate_is_a_string_whatever_the_wire_type():
    """midstate is declared str | None; an int32 on the wire must not leak through."""
    live = PVSLiveData.from_varserver({"/sys/livedata/midstate": 2})
    assert live.midstate == "2"


def test_non_finite_numbers_are_missing():
    """'nan' strings already map to None; NaN/inf floats must too, or every
    comparison against them is wrong (NaN != NaN)."""
    for raw in (float("nan"), float("inf"), "inf", "-inf"):
        value = PVSLiveData._parse_numeric(raw)
        assert value is None, raw


def test_booleans_are_not_numbers():
    assert PVSLiveData._parse_numeric(True) is None


def test_millisecond_timestamps():
    live = PVSLiveData.from_varserver({"/sys/livedata/time": "1791612709000"})
    assert live.time == datetime.fromtimestamp(1791612709, tz=UTC)


def test_get_by_var_path():
    live = PVSLiveData.from_varserver(LIVE_STRINGS)
    assert live.get("/sys/livedata/pv_p") == 3.2
    assert live.get("/sys/livedata/unknown") is None


def test_out_of_range_values_are_missing_not_errors():
    assert PVSLiveData._parse_numeric(10**400) is None
    assert PVSLiveData._parse_numeric("1e400") is None
    assert PVSLiveData._parse_timestamp(float("inf")) is None
    assert PVSLiveData._parse_timestamp(10**400) is None
