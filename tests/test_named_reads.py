"""PVS.getVarserverVarsByName and how updaters get it."""

from __future__ import annotations

import asyncio

import pytest

from pypvs.exceptions import PVSDataFormatError
from pypvs.pvs import PVS


def make_pvs(answer):
    pvs = PVS(session=None, host="pvs.test")
    sent = []

    async def get(endpoint, params=None):
        sent.append(params)
        return answer

    pvs.getVarserver = get
    return pvs, sent


def test_names_are_sent_as_one_comma_separated_list():
    answer = {"values": [{"name": "/a", "value": "1"}, {"name": "/b", "value": "2"}]}
    pvs, sent = make_pvs(answer)
    assert asyncio.run(pvs.getVarserverVarsByName(["/a", "/b"])) == {
        "/a": "1",
        "/b": "2",
    }
    assert sent == [{"name": "/a,/b"}]


def test_no_names_make_no_request():
    pvs, sent = make_pvs({})
    assert asyncio.run(pvs.getVarserverVarsByName([])) == {}
    assert sent == []


@pytest.mark.parametrize(
    "answer", [{"count": 1}, {"values": [{"name": "/a"}]}, {"values": None}]
)
def test_a_malformed_answer_is_a_data_format_error(answer):
    pvs, _ = make_pvs(answer)
    with pytest.raises(PVSDataFormatError):
        asyncio.run(pvs.getVarserverVarsByName(["/a"]))


def test_enabling_the_telemetry_websocket_sets_its_flag():
    pvs, sent = make_pvs({})
    asyncio.run(pvs.enable_telemetry_websocket())
    assert sent == [{"set": "/sys/telemetryws/enable=1"}]
