"""PVS-side caching of match queries (doc/LocalAPI.md: cache frequent matches)."""

from __future__ import annotations

import asyncio
import re

import pytest

import pypvs.pvs as pvs_module
from pypvs.exceptions import PVSCommunicationError, PVSDataFormatError
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

    def __init__(self, variables, supports_cache=True):
        self.vars = dict(variables)
        self.supports_cache = supports_cache
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
        if "cache" in params and not self.supports_cache:
            raise PVSCommunicationError("HTTP 400: 0x0040", status=400)
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


def test_a_match_is_cached_from_its_second_use():
    """A one-off match leaves no cache on the PVS; a repeated one is cached."""
    server = FakeVarserver(INVERTERS)
    pvs = make_pvs(server)
    for _ in range(3):
        assert query(pvs) == INVERTERS
    cache_id = query_cache_id("/sys/devices/inverter/")
    assert server.requests == [
        {"match": "/sys/devices/inverter/"},
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
    query(pvs)  # creates the cache
    server.vars["/sys/devices/inverter/1/sn"] = "B"
    assert "/sys/devices/inverter/1/sn" not in query(pvs)  # cached name set
    clock.now += pvs_module.QUERY_CACHE_TTL_S
    assert "/sys/devices/inverter/1/sn" in query(pvs)


def test_other_errors_are_not_mistaken_for_a_lost_cache():
    server = FakeVarserver(INVERTERS)
    pvs = make_pvs(server)
    query(pvs)
    query(pvs)  # creates the cache

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


def test_cache_ids_are_stable_safe_and_distinct():
    cid = query_cache_id("/sys/devices/inverter/")
    assert cid == query_cache_id("/sys/devices/inverter/")
    assert re.fullmatch(r"pypvs_sys_devices_inverter_[0-9a-f]{8}", cid)
    # matches that slug the same still get their own cache
    assert cid != query_cache_id("/sys/devices/inverter")
    assert query_cache_id("a/b") != query_cache_id("a_b")


def test_probing_rebuilds_the_cache():
    """At sunrise a cache can be built while only some inverters have
    reported; a re-probe must see the PVS as it is now, not that name set."""
    server = FakeVarserver({"/sys/devices/inverter/0/p3phsumKw": "0.1"})  # no sn yet
    pvs = make_pvs(server)
    query(pvs)
    server.vars.update(INVERTERS)
    pvs.reset_query_caches()  # what probe() does first
    assert "/sys/devices/inverter/0/sn" in query(pvs)


def test_an_empty_cached_read_rebuilds_the_cache():
    server = FakeVarserver(INVERTERS)
    pvs = make_pvs(server)
    query(pvs)
    for name in INVERTERS:
        del server.vars[name]  # devices vanished but the cache survived
    server.vars["/sys/devices/inverter/1/sn"] = "B"
    assert query(pvs) == {"/sys/devices/inverter/1/sn": "B"}


def test_a_pvs_that_rejects_cache_ids_still_answers():
    server = FakeVarserver(INVERTERS, supports_cache=False)
    pvs = make_pvs(server)
    assert query(pvs) == INVERTERS
    assert query(pvs) == INVERTERS
    assert server.requests[-1] == {"match": "/sys/devices/inverter/"}  # no retry
    with pytest.raises(PVSCommunicationError):
        query(pvs, "/sys/devices/ess/")  # nothing matches: still an error


def test_named_reads_parse_and_reject_malformed_answers():
    server = FakeVarserver(METER)
    pvs = make_pvs(server)

    async def answer(endpoint, params=None):
        names = params["name"].split(",")
        return server.answer([n for n in names if n in server.vars])

    pvs.getVarserver = answer
    names = list(METER)
    assert asyncio.run(pvs.getVarserverVarsByName(names)) == METER

    async def malformed(endpoint, params=None):
        return {"count": 1}

    pvs.getVarserver = malformed
    with pytest.raises(PVSDataFormatError):
        asyncio.run(pvs.getVarserverVarsByName(names))


def test_once_caching_works_an_empty_match_costs_one_request():
    """At night the inverter match has no results; with caching known to work
    that must not turn into two full-namespace queries."""
    server = FakeVarserver(METER)
    pvs = make_pvs(server)
    query(pvs, "/sys/devices/meter/")  # caching works here
    server.requests.clear()
    with pytest.raises(PVSCommunicationError):
        query(pvs)
    assert len(server.requests) == 1


def test_a_probe_retries_caching_for_a_match_marked_uncacheable():
    server = FakeVarserver(INVERTERS, supports_cache=False)
    pvs = make_pvs(server)
    query(pvs)
    server.supports_cache = True  # e.g. a firmware update
    pvs.reset_query_caches()
    query(pvs)
    assert "cache" in server.requests[-1]


def test_reading_no_names_makes_no_request():
    server = FakeVarserver(METER)
    pvs = make_pvs(server)
    assert asyncio.run(pvs.getVarserverVarsByName([])) == {}
    assert server.requests == []


def test_a_single_var_is_read_whatever_name_the_pvs_echoes():
    pvs = make_pvs(FakeVarserver(METER))

    async def answer(endpoint, params=None):
        return {"count": 1, "values": [{"name": "/Sys/Info/Uptime ", "value": "42"}]}

    pvs.getVarserver = answer
    assert asyncio.run(pvs.getVarserverVar("/sys/info/uptime")) == "42"


def test_an_empty_answer_creates_no_cache():
    """A PVS answering an empty match with 200 and no values must not make
    every later poll pay an empty cache read plus a rebuild."""
    server = FakeVarserver(METER)
    pvs = make_pvs(server)

    async def empty_ok(endpoint, params=None):
        server.requests.append(dict(params))
        return {"count": 0, "values": []}

    pvs.getVarserver = empty_ok
    for _ in range(3):
        assert query(pvs) == {}
    assert all("cache" not in r or "match" in r for r in server.requests)
    assert pvs._query_caches == {}


def test_a_new_host_relearns_cache_support():
    server = FakeVarserver(METER)
    pvs = make_pvs(server)
    query(pvs, "/sys/devices/meter/")
    query(pvs, "/sys/devices/meter/")  # caching worked on the first PVS
    other = FakeVarserver(INVERTERS, supports_cache=False)
    pvs.host = "other.test"
    pvs.getVarserver = other
    query(pvs)
    assert query(pvs) == INVERTERS  # fell back to a plain match, not an error


def test_an_inverter_reprobe_keeps_the_other_caches(monkeypatch):
    server = FakeVarserver({**METER})
    pvs = make_pvs(server)
    query(pvs, "/sys/devices/meter/")
    query(pvs, "/sys/devices/meter/")
    pvs.reset_query_caches("/sys/devices/inverter/")
    server.requests.clear()
    query(pvs, "/sys/devices/meter/")
    assert server.requests == [{"cache": query_cache_id("/sys/devices/meter/")}]
