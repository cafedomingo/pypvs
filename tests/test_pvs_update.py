"""PVS.update(): probing and re-probing for devices."""

from __future__ import annotations

import asyncio
from collections import Counter

import pytest

from pypvs.api import Match, SysType, Variable
from pypvs.exceptions import PVSCommunicationError
from pypvs.pvs import PVS, REPROBE_S
from pypvs.updaters.gateway import EXTRAS_REFRESH_S


def make_pvs(device_responses, sys_type=SysType.PV_ONLY):
    """A PVS with a gateway. `device_responses` maps a device match to what
    each query of it returns, in order, the last repeating; an exception is
    raised. Unlisted matches return {}."""
    pvs = PVS(session=None, host="pvs.test")
    remaining = {match: list(seq) for match, seq in device_responses.items()}
    queries = Counter()

    async def get_var(name):
        return "1"

    async def get_vars(match):
        queries[match] += 1
        queue = remaining.get(match) or [{}]
        response = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(response, Exception):
            raise response
        return response

    async def get_named(names):
        queries.update(names)
        return {n: sys_type if n == Variable.SYS_TYPE else "1" for n in names}

    pvs.getVarserverVar = get_var
    pvs.getVarserverVars = get_vars
    pvs.getVarserverVarsByName = get_named
    # the updaters were bound at construction time
    pvs._firmware._request_var = get_var
    return pvs, queries


INV = {"/sys/devices/inverter/0/sn": "A", "/sys/devices/inverter/0/p3phsumKw": "0.3"}
METER = {"/sys/devices/meter/0/sn": "M"}
ESS = {"/sys/devices/ess/0/sn": "E"}
UNLISTED = PVSCommunicationError("HTTP 400", status=400)


def test_inverters_absent_at_startup_are_found_later(clock):
    pvs, _ = make_pvs({Match.INVERTERS: [{}, {}, INV]})
    asyncio.run(pvs.update())  # night: no inverters
    clock.now += REPROBE_S
    asyncio.run(pvs.update())  # still none
    clock.now += REPROBE_S
    data = asyncio.run(pvs.update())
    assert list(data.inverters) == ["A"]


def test_meters_unlisted_at_startup_are_found_later(clock):
    """Right after a boot the PVS answers 400 for device types it has not
    listed yet, while others may already be there."""
    responses = {Match.INVERTERS: [INV], Match.METERS: [UNLISTED, METER]}
    pvs, _ = make_pvs(responses)
    assert asyncio.run(pvs.update()).meters == {}
    clock.now += REPROBE_S
    assert list(asyncio.run(pvs.update()).meters) == ["M"]


def test_a_reprobe_keeps_the_devices_already_found(clock):
    # meters: probe, update, then a failed re-probe while inverters are missing
    responses = {Match.METERS: [METER, METER, UNLISTED, METER]}
    pvs, _ = make_pvs(responses)
    asyncio.run(pvs.update())
    clock.now += REPROBE_S
    assert list(asyncio.run(pvs.update()).meters) == ["M"]


def test_a_pv_only_system_stops_probing_once_everything_is_found(clock):
    responses = {
        Match.INVERTERS: [INV],
        Match.METERS: [METER],
        Match.ESS: [UNLISTED],
        Match.TRANSFER_SWITCH: [UNLISTED],
    }
    pvs, queries = make_pvs(responses)
    asyncio.run(pvs.update())
    clock.now += REPROBE_S
    asyncio.run(pvs.update())
    assert queries[Match.ESS] == 1


def test_a_storage_system_finds_a_battery_unlisted_at_startup(clock):
    responses = {
        Match.INVERTERS: [INV],
        Match.METERS: [METER],
        Match.ESS: [UNLISTED, ESS],
    }
    pvs, queries = make_pvs(responses, sys_type=SysType.STORAGE)
    assert asyncio.run(pvs.update()).ess == {}
    assert queries[Variable.ESS_CONTROL_MODE] == 0
    clock.now += REPROBE_S
    assert list(asyncio.run(pvs.update()).ess) == ["E"]
    clock.now += EXTRAS_REFRESH_S
    asyncio.run(pvs.update())
    assert queries[Variable.ESS_CONTROL_MODE]


def test_the_next_poll_does_not_reprobe_straight_away(clock):
    """The first probe found no inverters; the next poll a second later must
    not re-probe straight away."""
    pvs, queries = make_pvs({})
    asyncio.run(pvs.update())
    probes_after_startup = queries[Match.INVERTERS]
    clock.now += 1
    asyncio.run(pvs.update())
    assert queries[Match.INVERTERS] == probes_after_startup


def test_websocket_needs_a_host():
    with pytest.raises(ValueError, match="host"):
        PVS(session=None).get_websocket()


def test_clearing_the_host_clears_the_client_url():
    pvs = PVS(session=None, host="10.0.0.5")
    assert pvs.fcgi_client.pvs_url == "https://10.0.0.5"
    pvs.host = None
    assert pvs.fcgi_client.pvs_url is None


@pytest.mark.parametrize("has_ess", [True, False])
def test_the_gateway_asks_for_battery_config_only_with_a_battery(has_ess):
    pvs = PVS(session=None, host="pvs.test")
    batches = []

    async def get_vars(match):
        if match == "/sys/devices/ess/" and has_ess:
            return {"/sys/devices/ess/0/sn": "E"}
        raise PVSCommunicationError("HTTP 400", status=400)  # no such devices

    async def get_named(names):
        batches.append(names)
        return {name: "PVS6" if name == "/sys/info/model" else "1" for name in names}

    pvs.getVarserverVars = get_vars
    pvs.getVarserverVarsByName = get_named
    asyncio.run(pvs.update())
    asked = {n for batch in batches for n in batch}
    assert ("/ess/config/dcm/mode_param/control_mode" in asked) is has_ess
