"""QueryCache transitions and how PVS uses it (see doc/Caching.md)."""

from __future__ import annotations

import asyncio
import re

import pytest
from fake_varserver import INVERTER, METER, FakeVarserver, inverter_vars

import pypvs.pvs as pvs_module
from pypvs.exceptions import PVSCommunicationError
from pypvs.pvs import PVS
from pypvs.query_cache import (
    LOSS_LIMIT,
    QUERY_CACHE_TTL_S,
    UNREADABLE_RETRY_S,
    QueryCache,
    cache_id,
)

TWELVE = [f"E0012220212{n:04d}" for n in range(12)]


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def cache_for(server, clock=None, ttl=QUERY_CACHE_TTL_S):
    return QueryCache(server.handle, ttl, clock or Clock())


def read(cache, match=INVERTER):
    return asyncio.run(cache.read(match))


# --- one test per transition ----------------------------------------------


def test_first_use_creates_then_reads():
    server = FakeVarserver(inverter_vars(TWELVE))
    cache = cache_for(server)
    for _ in range(3):
        assert len(read(cache)["values"]) == 24
    assert server.kinds() == ["create", "read", "read"]


def test_create_with_no_match_raises_400_and_stays_none():
    server = FakeVarserver(METER)  # night: no inverters
    cache = cache_for(server)
    for _ in range(2):
        with pytest.raises(PVSCommunicationError) as err:
            read(cache)
        assert err.value.status == 400
    assert server.kinds() == ["create", "create"]  # never a read


def test_create_with_empty_values_returns_empty_and_stays_none():
    class Empty(FakeVarserver):
        async def handle(self, params):
            self.requests.append(dict(params))
            return {"count": 0, "values": []}

    server = Empty({})
    cache = cache_for(server)
    assert read(cache)["values"] == []
    read(cache)
    assert server.kinds() == ["create", "create"]


def test_create_timeout_raises_and_stays_none():
    server = FakeVarserver(METER)
    cache = cache_for(server)
    server.fail_next(PVSCommunicationError("Cannot reach the PVS"))
    with pytest.raises(PVSCommunicationError):
        read(cache, "/sys/devices/meter/")
    read(cache, "/sys/devices/meter/")
    assert server.kinds() == ["create", "create"]


def test_read_after_ttl_recreates():
    clock = Clock()
    server = FakeVarserver(METER)
    cache = cache_for(server, clock)
    read(cache, "/sys/devices/meter/")
    clock.now += QUERY_CACHE_TTL_S - 1
    read(cache, "/sys/devices/meter/")
    clock.now += 1
    read(cache, "/sys/devices/meter/")
    assert server.kinds() == ["create", "read", "create"]


def test_create_400_after_the_ttl_raises_and_stays_none():
    clock = Clock()
    server = FakeVarserver({**METER, **inverter_vars(TWELVE)})
    cache = cache_for(server, clock)
    read(cache)
    server.vars = dict(METER)  # inverters gone, cache still on the PVS
    clock.now += QUERY_CACHE_TTL_S
    with pytest.raises(PVSCommunicationError):
        read(cache)
    with pytest.raises(PVSCommunicationError):
        read(cache)
    assert server.kinds() == ["create", "create", "create"]


def test_create_timeout_after_the_ttl_raises_and_stays_none():
    clock = Clock()
    server = FakeVarserver(METER)
    cache = cache_for(server, clock)
    read(cache, "/sys/devices/meter/")
    clock.now += QUERY_CACHE_TTL_S
    server.fail_next(PVSCommunicationError("Cannot reach the PVS"))
    with pytest.raises(PVSCommunicationError):
        read(cache, "/sys/devices/meter/")
    read(cache, "/sys/devices/meter/")
    assert server.kinds() == ["create", "create", "create"]


def test_read_400_recreates_in_the_same_call():
    server = FakeVarserver(METER)
    cache = cache_for(server)
    read(cache, "/sys/devices/meter/")
    server.restart()  # the PVS forgot its caches
    server.requests.clear()
    assert len(read(cache, "/sys/devices/meter/")["values"]) == 2
    assert server.kinds() == ["read", "create"]


def test_read_400_then_create_400_raises_and_next_poll_is_one_request():
    server = FakeVarserver({**METER, **inverter_vars(TWELVE)})
    cache = cache_for(server)
    read(cache)
    server.restart()  # nightly restart: caches and inverters gone
    server.requests.clear()
    with pytest.raises(PVSCommunicationError):
        read(cache)
    assert server.kinds() == ["read", "create"]
    server.requests.clear()
    with pytest.raises(PVSCommunicationError):
        read(cache)
    assert server.kinds() == ["create"]  # no doubling on later polls


def test_read_empty_recreates_in_the_same_call():
    server = FakeVarserver({**METER, **inverter_vars(TWELVE)}, stale_reads_empty=True)
    cache = cache_for(server)
    read(cache)
    server.vars = {k: v for k, v in server.vars.items() if not k.startswith(INVERTER)}
    server.vars[f"{INVERTER}50/sn"] = "NEWSERIAL"  # not among the cached names
    server.requests.clear()
    values = read(cache)["values"]
    assert {v["value"] for v in values} >= {"NEWSERIAL"}
    assert server.kinds() == ["read", "create"]


def test_read_timeout_raises_and_keeps_the_cache():
    server = FakeVarserver(METER)
    cache = cache_for(server)
    read(cache, "/sys/devices/meter/")
    server.fail_next(PVSCommunicationError("Cannot reach the PVS"))
    with pytest.raises(PVSCommunicationError):
        read(cache, "/sys/devices/meter/")
    server.requests.clear()
    read(cache, "/sys/devices/meter/")
    assert server.kinds() == ["read"]


def test_read_500_raises_and_keeps_the_cache():
    server = FakeVarserver(METER)
    cache = cache_for(server)
    read(cache, "/sys/devices/meter/")
    server.fail_next(PVSCommunicationError("HTTP 500", status=500))
    with pytest.raises(PVSCommunicationError):
        read(cache, "/sys/devices/meter/")
    server.requests.clear()
    read(cache, "/sys/devices/meter/")
    assert server.kinds() == ["read"]


class Forgetful(FakeVarserver):
    """Accepts a create, then cannot read the cache back."""

    async def handle(self, params):
        if set(params) == {"cache"}:
            self.requests.append(dict(params))
            raise PVSCommunicationError("HTTP 400: 0x0040", status=400)
        return await super().handle(params)


def test_a_cache_lost_every_time_goes_plain_for_a_while(caplog):
    clock = Clock()
    server = Forgetful(METER)
    cache = cache_for(server, clock)
    for _ in range(LOSS_LIMIT + 2):
        assert len(read(cache, "/sys/devices/meter/")["values"]) == 2
    assert server.kinds() == ["create"] + ["read", "create"] * (LOSS_LIMIT - 1) + [
        "read",
        "match",
        "match",
    ]
    server.requests.clear()
    clock.now += UNREADABLE_RETRY_S
    for _ in range(3):
        read(cache, "/sys/devices/meter/")
    # one trial; its first loss goes straight back
    assert server.kinds() == ["create", "read", "match", "match"]
    assert caplog.text.count("keeps losing the cache") == 1


def test_a_good_read_clears_the_losses():
    server = FakeVarserver(METER)
    cache = cache_for(server)
    for _ in range(3):
        read(cache, "/sys/devices/meter/")
        for _ in range(LOSS_LIMIT - 1):
            server.caches.clear()
            read(cache, "/sys/devices/meter/")
    assert "match" not in server.kinds()


def test_reset_during_a_create_records_nothing():
    server = FakeVarserver(METER)
    cache = cache_for(server)

    async def create_then_reset(params):
        data = await server.handle(params)
        cache.reset()  # e.g. a probe while the create was in flight
        return data

    cache._request = create_then_reset
    read(cache, "/sys/devices/meter/")
    cache._request = server.handle
    read(cache, "/sys/devices/meter/")
    assert server.kinds() == ["create", "create"]


@pytest.mark.parametrize("ttl", [0, -1.0])
def test_ttl_must_be_positive(ttl):
    with pytest.raises(ValueError):
        QueryCache(FakeVarserver({}).handle, ttl)
    with pytest.raises(ValueError):
        PVS(session=None, host="pvs.test", query_cache_ttl_s=ttl)


def test_reset_forces_a_create():
    server = FakeVarserver(METER)
    cache = cache_for(server)
    read(cache, "/sys/devices/meter/")
    cache.reset()
    read(cache, "/sys/devices/meter/")
    assert server.kinds() == ["create", "create"]


def test_ttl_none_sends_plain_matches():
    server = FakeVarserver(METER)
    pvs = PVS(session=None, host="pvs.test", query_cache_ttl_s=None)
    pvs.getVarserver = server.get_varserver
    for _ in range(2):
        asyncio.run(pvs.getVarserverVars("/sys/devices/meter/", cache=True))
    assert server.kinds() == ["match", "match"]


def test_cache_ids_are_deterministic_and_distinct():
    cid = cache_id(INVERTER)
    assert cid == cache_id(INVERTER)
    assert re.fullmatch(r"pypvs_[A-Za-z0-9_]+_[0-9a-f]{8}", cid)
    assert cache_id("/sys/info") != cache_id("/sys/info/")


def test_cached_values_are_live():
    server = FakeVarserver(METER)
    cache = cache_for(server)
    read(cache, "/sys/devices/meter/")
    server.vars["/sys/devices/meter/0/p3phsumKw"] = "2.0"
    values = {
        v["name"]: v["value"] for v in read(cache, "/sys/devices/meter/")["values"]
    }
    assert values["/sys/devices/meter/0/p3phsumKw"] == "2.0"


def test_two_clients_share_one_cache_per_match():
    server = FakeVarserver(METER)
    a, b = cache_for(server), cache_for(server)
    read(a, "/sys/devices/meter/")
    read(b, "/sys/devices/meter/")
    assert list(server.caches) == [cache_id("/sys/devices/meter/")]


# --- through PVS --------------------------------------------------------------

SYS_INFO = {
    name: "1"
    for name in (
        "/sys/info/sys_type",
        "/sys/info/model",
        "/sys/info/hwrev",
        "/sys/info/sw_rev",
        "/sys/info/uptime",
        "/sys/info/lmac",
        "/sys/info/ram_usage",
        "/sys/info/flash_usage",
        "/sys/info/cpu_usage",
    )
}


def make_pvs(monkeypatch, server):
    clock = Clock()
    monkeypatch.setattr(pvs_module.time, "monotonic", clock)
    pvs = PVS(session=None, host="pvs.test")
    pvs.getVarserver = server.get_varserver
    return pvs, clock


def update(pvs):
    return asyncio.run(pvs.update())


def device_requests(server, match):
    """Requests for one match: by its match string or by its cache id."""
    keys = (match, cache_id(match))
    return [
        k
        for k, r in zip(server.kinds(), server.requests, strict=True)
        if r.get("match") == match or r.get("cache") in keys
    ]


def test_public_getvarservervars_never_caches_unless_asked(monkeypatch):
    server = FakeVarserver(METER)
    pvs, _ = make_pvs(monkeypatch, server)
    asyncio.run(pvs.getVarserverVars("/sys/devices/meter/"))
    assert server.kinds() == ["match"]
    asyncio.run(pvs.getVarserverVars("/sys/devices/meter/", cache=True))
    assert server.kinds() == ["match", "create"]


def test_device_updaters_poll_through_the_cache(monkeypatch):
    server = FakeVarserver({**SYS_INFO, **METER, **inverter_vars(TWELVE)})
    pvs, clock = make_pvs(monkeypatch, server)
    update(pvs)
    server.requests.clear()
    clock.now += 30
    data = update(pvs)
    assert len(data.inverters) == 12 and list(data.meters) == ["PVS6M1p"]
    assert device_requests(server, "/sys/devices/meter/") == ["read"]
    assert device_requests(server, INVERTER) == ["read"]


def test_sunrise_staged_inverters_appear_within_the_ttl(monkeypatch):
    server = FakeVarserver({**SYS_INFO, **METER})
    pvs, clock = make_pvs(monkeypatch, server)
    update(pvs)  # night
    server.sunrise(TWELVE[:10])
    clock.now += 61  # the first re-probe
    assert len(update(pvs).inverters) == 10
    server.sunrise(TWELVE)
    clock.now += 30
    assert len(update(pvs).inverters) == 10  # cached name set
    clock.now += QUERY_CACHE_TTL_S
    assert len(update(pvs).inverters) == 12


def test_nightly_restart_meters_recover_in_the_same_poll(monkeypatch, caplog):
    server = FakeVarserver({**SYS_INFO, **METER, **inverter_vars(TWELVE)})
    pvs, clock = make_pvs(monkeypatch, server)
    update(pvs)
    server.restart()
    clock.now += 30
    data = update(pvs)
    assert list(data.meters) == ["PVS6M1p"]
    assert data.inverters == {}
    assert "Meter data unavailable" not in caplog.text


def test_probe_and_host_change_reset_the_caches(monkeypatch):
    server = FakeVarserver({**SYS_INFO, **METER})
    pvs, clock = make_pvs(monkeypatch, server)
    update(pvs)
    clock.now += 30
    update(pvs)  # reads
    server.requests.clear()
    asyncio.run(pvs.probe())
    assert device_requests(server, "/sys/devices/meter/") == ["create"]
    server.requests.clear()
    pvs.host = "other.test"
    asyncio.run(pvs.getVarserverVars("/sys/devices/meter/", cache=True))
    assert server.kinds() == ["create"]


def test_caching_off_keeps_old_style_request_vars_working(monkeypatch):
    server = FakeVarserver({**SYS_INFO, **METER})
    pvs = PVS(session=None, host="pvs.test", query_cache_ttl_s=None)
    pvs.getVarserver = server.get_varserver
    plain = pvs.getVarserverVars

    async def get_vars(match):  # no cache keyword, as before caching
        return await plain(match)

    pvs.getVarserverVars = get_vars
    assert list(update(pvs).meters) == ["PVS6M1p"]
    assert set(device_requests(server, "/sys/devices/meter/")) == {"match"}
