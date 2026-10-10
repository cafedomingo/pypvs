"""PVS.getVarserverVarsByName and how updaters get it."""

from __future__ import annotations

import asyncio

import pytest

from pypvs.exceptions import PVSDataFormatError
from pypvs.pvs import PVS, register_updater
from pypvs.updaters.base import PVSUpdater


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


def test_an_updater_without_the_new_argument_still_works():
    """Updaters registered by others may predate request_named_vars."""

    class OldStyle(PVSUpdater):
        def __init__(self, request_var, request_vars, common_properties):
            super().__init__(request_var, request_vars, common_properties)

        async def probe(self, discovered_features):
            return None

        async def update(self, pvs_data):
            pass

    pvs, _ = make_pvs({"values": []})

    async def get_var(name):
        return "1"

    async def get_vars(match):
        raise PVSDataFormatError("none")

    pvs.getVarserverVar = get_var
    pvs.getVarserverVars = get_vars
    remove = register_updater(OldStyle)
    try:
        asyncio.run(pvs.probe())  # constructing OldStyle must not raise
    finally:
        remove()
