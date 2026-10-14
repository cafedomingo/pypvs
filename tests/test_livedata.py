"""Parsing /sys/livedata values, from varserver and from the websocket."""

from __future__ import annotations

from dataclasses import fields
from datetime import UTC, datetime

from pypvs.models.livedata import LIVEDATA_FIELDS, PVSLiveData

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


def test_millisecond_timestamps():
    live = PVSLiveData.from_varserver({"/sys/livedata/time": "1791612709000"})
    assert live.time == datetime.fromtimestamp(1791612709, tz=UTC)


def test_get_by_var_path():
    live = PVSLiveData.from_varserver(LIVE_STRINGS)
    assert live.get("/sys/livedata/pv_p") == 3.2
    assert live.get("/sys/livedata/unknown") is None


def test_every_field_has_a_variable():
    assert set(LIVEDATA_FIELDS) == {f.name for f in fields(PVSLiveData)}
