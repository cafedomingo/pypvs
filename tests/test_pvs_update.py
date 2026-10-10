"""PVS.update(): probing and re-probing for inverters."""

from __future__ import annotations

import asyncio

import pytest

import pypvs.pvs as pvs_module
from pypvs.pvs import PVS


class Clock:
    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now


def make_pvs(monkeypatch, inverter_answers):
    """A PVS whose varserver has a gateway, no other devices, and inverters
    according to `inverter_answers` (one entry consumed per inverter query)."""
    clock = Clock()
    monkeypatch.setattr(pvs_module.time, "monotonic", clock.monotonic)
    pvs = PVS(session=None, host="pvs.test")
    answers = list(inverter_answers)
    calls = {"inverter_queries": 0}

    async def get_var(name):
        return "1"

    async def get_vars(match):
        if match == "/sys/devices/inverter/":
            calls["inverter_queries"] += 1
            return answers.pop(0) if answers else {}
        return {}

    pvs.getVarserverVar = get_var
    pvs.getVarserverVars = get_vars
    # the updaters were bound at construction time
    pvs._firmware._request_var = get_var
    return pvs, clock, calls


def test_inverters_absent_at_startup_are_found_later(monkeypatch):
    inv = {
        "/sys/devices/inverter/0/sn": "A",
        "/sys/devices/inverter/0/p3phsumKw": "0.3",
    }
    pvs, clock, _ = make_pvs(monkeypatch, [{}, {}, inv, inv])
    asyncio.run(pvs.update())  # night: no inverters
    clock.now += 61
    asyncio.run(pvs.update())  # still none
    clock.now += 121
    data = asyncio.run(pvs.update())
    assert list(data.inverters) == ["A"]


def test_reprobe_waits_for_the_backoff_after_the_first_probe(monkeypatch):
    """The first probe found no inverters; the next poll a second later must
    not re-probe straight away."""
    pvs, clock, calls = make_pvs(monkeypatch, [])
    asyncio.run(pvs.update())
    probes_after_startup = calls["inverter_queries"]
    clock.now += 1
    asyncio.run(pvs.update())
    assert calls["inverter_queries"] == probes_after_startup


def test_websocket_needs_a_host():
    with pytest.raises(ValueError, match="host"):
        PVS(session=None).get_websocket()


def test_clearing_the_host_clears_the_client_url():
    pvs = PVS(session=None, host="10.0.0.5")
    assert pvs.fcgi_client.pvs_url == "https://10.0.0.5"
    pvs.host = None
    assert pvs.fcgi_client.pvs_url is None
