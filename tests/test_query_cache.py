"""PVS-side caching of match queries (doc/LocalAPI.md: cache frequent matches)."""

from __future__ import annotations

import asyncio

import pytest

import pypvs.pvs as pvs_module
from pypvs.exceptions import PVSCommunicationError
from pypvs.pvs import PVS, query_cache_id

INVERTERS = {
    "/sys/devices/inverter/0/sn": "A",
    "/sys/devices/inverter/0/p3phsumKw": "0.25",
}
METER = {"/sys/devices/meter/0/sn": "M", "/sys/devices/meter/0/p3phsumKw": "1.5"}


class FakeVarserver:
    """Models the PVS: a match with no results is 400; a cache holds the names
    matched when it was created and reads their current values; an unknown
    cache id is 400; a restart forgets every cache."""

    def __init__(self, variables):
        self.vars = dict(variables)
        self.caches: dict[str, list[str]] = {}
        self.requests: list[dict] = []

    def restart(self):
        self.caches.clear()

    def answer(self, names):
        return {
            "count": len(names),
            "values": [{"name": n, "value": self.vars[n]} for n in names],
        }

    async def __call__(self, endpoint, params=None):
        self.requests.append(dict(params))
        if "match" in params:
            names = [n for n in self.vars if params["match"] in n]
            if not names:
                raise PVSCommunicationError("HTTP 400: 0x0040", status=400)
            if "cache" in params:
                self.caches[params["cache"]] = names
            return self.answer(names)
        names = self.caches.get(params["cache"])
        if names is None:
            raise PVSCommunicationError("HTTP 400: 0x0040", status=400)
        return self.answer([n for n in names if n in self.vars])


class Clock:
    def __init__(self, monkeypatch):
        self.now = 1000.0
        monkeypatch.setattr(pvs_module.time, "monotonic", lambda: self.now)


def make_pvs(server, **kwargs):
    pvs = PVS(session=None, host="pvs.test", **kwargs)
    pvs.getVarserver = server
    return pvs


def query(pvs, match="/sys/devices/inverter/"):
    return asyncio.run(pvs.getVarserverVars(match))


def test_first_query_creates_the_cache_later_ones_read_it():
    server = FakeVarserver(INVERTERS)
    pvs = make_pvs(server)
    assert query(pvs) == INVERTERS
    assert query(pvs) == INVERTERS
    cache_id = query_cache_id("/sys/devices/inverter/")
    assert server.requests == [
        {"match": "/sys/devices/inverter/", "cache": cache_id},
        {"cache": cache_id},
    ]


def test_cached_reads_return_current_values():
    server = FakeVarserver(INVERTERS)
    pvs = make_pvs(server)
    query(pvs)
    server.vars["/sys/devices/inverter/0/p3phsumKw"] = "0.31"
    assert query(pvs)["/sys/devices/inverter/0/p3phsumKw"] == "0.31"


def test_a_lost_cache_is_recreated_transparently():
    """The PVS restarts nightly and forgets its caches."""
    server = FakeVarserver(INVERTERS)
    pvs = make_pvs(server)
    query(pvs)
    server.restart()
    assert query(pvs) == INVERTERS
    assert server.requests[-1]["match"] == "/sys/devices/inverter/"


def test_no_devices_raises_like_an_uncached_match_and_recovers_later():
    """After the nightly restart the PVS has no inverter vars until sunrise."""
    server = FakeVarserver(METER)
    pvs = make_pvs(server)
    with pytest.raises(PVSCommunicationError):
        query(pvs)
    server.vars.update(INVERTERS)
    assert query(pvs) == INVERTERS


def test_the_cache_is_rebuilt_to_pick_up_new_devices(monkeypatch):
    clock = Clock(monkeypatch)
    server = FakeVarserver(INVERTERS)
    pvs = make_pvs(server)
    query(pvs)
    server.vars["/sys/devices/inverter/1/sn"] = "B"
    assert "/sys/devices/inverter/1/sn" not in query(pvs)  # cached name set
    clock.now += pvs_module.QUERY_CACHE_TTL_S
    assert "/sys/devices/inverter/1/sn" in query(pvs)


def test_other_errors_are_not_mistaken_for_a_lost_cache():
    server = FakeVarserver(INVERTERS)
    pvs = make_pvs(server)
    query(pvs)

    async def broken(endpoint, params=None):
        raise PVSCommunicationError("Cannot reach the PVS", status=None)

    pvs.getVarserver = broken
    with pytest.raises(PVSCommunicationError, match="Cannot reach"):
        query(pvs)
    pvs.getVarserver = server
    query(pvs)  # the cache is still trusted: read, not recreated
    assert server.requests[-1] == {"cache": query_cache_id("/sys/devices/inverter/")}


def test_caching_can_be_turned_off():
    server = FakeVarserver(INVERTERS)
    pvs = make_pvs(server, use_query_cache=False)
    query(pvs)
    query(pvs)
    assert server.requests == [{"match": "/sys/devices/inverter/"}] * 2


def test_cache_ids_are_stable_and_safe():
    assert query_cache_id("/sys/devices/inverter/") == "pypvs_sys_devices_inverter"
    assert query_cache_id("/sys/livedata") == "pypvs_sys_livedata"
