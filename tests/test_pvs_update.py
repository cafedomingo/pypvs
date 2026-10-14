"""PVS.update(): which device types are read, and when."""

from __future__ import annotations

import asyncio
from collections import Counter

import pytest

from pypvs.api import Match, SysType, Variable
from pypvs.exceptions import PVSCommunicationError
from pypvs.pvs import PVS


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
    # bound at construction time
    pvs._firmware._request_var = get_var
    return pvs, queries


INV = {"/sys/devices/inverter/0/sn": "A", "/sys/devices/inverter/0/p3phsumKw": "0.3"}
METER = {"/sys/devices/meter/0/sn": "M"}
ESS = {"/sys/devices/ess/0/sn": "E"}
SWITCH = {"/sys/devices/transfer_switch/0/sn": "T"}
UNLISTED = PVSCommunicationError("HTTP 400", status=400)
DEVICE_MATCHES = (Match.INVERTERS, Match.METERS, Match.ESS, Match.TRANSFER_SWITCH)


def test_every_device_is_read_in_one_request_per_poll():
    every_device = INV | METER | ESS | SWITCH
    pvs, queries = make_pvs({Match.DEVICES: [every_device]}, sys_type=SysType.STORAGE)
    asyncio.run(pvs.update())
    data = asyncio.run(pvs.update())
    assert queries[Match.DEVICES] == 2
    assert not any(queries[m] for m in DEVICE_MATCHES)
    kinds = (data.inverters, data.meters, data.ess, data.transfer_switches)
    assert [list(k) for k in kinds] == [["A"], ["M"], ["E"], ["T"]]


@pytest.mark.parametrize("missing", [UNLISTED, {}])
def test_a_type_missing_on_one_poll_is_back_on_the_next(missing):
    """Right after a boot the PVS answers 400 or nothing for types it has
    not listed yet."""
    pvs, _ = make_pvs({Match.DEVICES: [missing, INV | METER]})
    first = asyncio.run(pvs.update())
    second = asyncio.run(pvs.update())
    assert first.inverters == {}
    assert first.meters == {}
    assert list(second.inverters) == ["A"]
    assert list(second.meters) == ["M"]


@pytest.mark.parametrize("sys_type", [SysType.PV_ONLY, SysType.UNKNOWN])
def test_battery_devices_are_built_only_on_a_storage_system(sys_type):
    pvs, _ = make_pvs({Match.DEVICES: [ESS | SWITCH]}, sys_type=sys_type)
    data = asyncio.run(pvs.update())
    assert data.ess == {}
    assert data.transfer_switches == {}


@pytest.mark.parametrize("sys_type", [SysType.STORAGE, "Storage\n"])
def test_a_storage_system_reads_its_battery_devices(sys_type):
    pvs, _ = make_pvs({Match.DEVICES: [ESS | SWITCH]}, sys_type=sys_type)
    data = asyncio.run(pvs.update())
    assert list(data.ess) == ["E"]
    assert list(data.transfer_switches) == ["T"]


def test_a_failed_device_read_keeps_the_gateway():
    pvs, _ = make_pvs({Match.DEVICES: [PVSCommunicationError("Cannot reach the PVS")]})
    data = asyncio.run(pvs.update())
    assert data.gateway is not None
    assert data.inverters == {}


def test_a_gateway_failure_fails_the_update_and_keeps_the_last_data():
    pvs, _ = make_pvs({Match.DEVICES: [INV]})
    last = asyncio.run(pvs.update())

    async def unreachable(names):
        raise PVSCommunicationError("Cannot reach the PVS: timeout")

    pvs.getVarserverVarsByName = unreachable
    with pytest.raises(PVSCommunicationError):
        asyncio.run(pvs.update())
    assert pvs.data is last


@pytest.mark.parametrize(
    ("sys_type", "asks"), [(SysType.STORAGE, True), (SysType.PV_ONLY, False)]
)
def test_the_gateway_asks_for_battery_config_only_on_a_storage_system(sys_type, asks):
    pvs, queries = make_pvs({}, sys_type=sys_type)
    asyncio.run(pvs.update())
    assert (queries[Variable.ESS_CONTROL_MODE] > 0) is asks


def test_websocket_needs_a_host():
    with pytest.raises(ValueError, match="host"):
        PVS(session=None).get_websocket()


def test_clearing_the_host_clears_the_client_url():
    pvs = PVS(session=None, host="10.0.0.5")
    assert pvs.fcgi_client.pvs_url == "https://10.0.0.5"
    pvs.host = None
    assert pvs.fcgi_client.pvs_url is None
