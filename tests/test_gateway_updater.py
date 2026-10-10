"""The gateway (/sys/info) updater."""

from __future__ import annotations

import asyncio

from pypvs.exceptions import PVSCommunicationError
from pypvs.models.common import CommonProperties
from pypvs.models.pvs import PVSData
from pypvs.updaters.gateway import PVSGatewayUpdater

SYS_INFO = {
    "/sys/info/sys_type": "Storage",
    "/sys/info/model": "PVS6",
    "/sys/info/hwrev": "6.02",
    "/sys/info/sw_rev": "2025.06.06.61839",
    "/sys/info/uptime": "81436.77",
    "/sys/info/lmac": "02:aa:bb:cc:dd:01",
    "/sys/info/ram_usage": "7",
    "/sys/info/flash_usage": "73",
    "/sys/info/cpu_usage": "6",
    "/sys/pvs/flashwear_type_b": "0x01",
}


def make_updater(values):
    async def request_var(name):
        if name not in values:
            # what the PVS does for a variable it doesn't have: HTTP 400
            raise PVSCommunicationError("POST request failed: HTTP 400")
        return values[name]

    async def request_vars(match):
        raise AssertionError("not used")

    return PVSGatewayUpdater(
        request_var=request_var,
        request_vars=request_vars,
        common_properties=CommonProperties(),
    )


def test_full_sys_info():
    data = PVSData()
    asyncio.run(make_updater(SYS_INFO).update(data))
    gw = data.gateway
    assert gw.pvs_type == "PVS6"
    assert gw.uptime_s == 81436.77
    assert gw.flashwear_type_b_percent == 10


def test_pvs_without_flashwear_still_reports_the_gateway():
    """flashwear_type_b only exists on the PVS6; a PVS5 answers 400 for it.
    That one optional variable must not fail the whole gateway update."""
    values = {k: v for k, v in SYS_INFO.items() if k != "/sys/pvs/flashwear_type_b"}
    data = PVSData()
    asyncio.run(make_updater(values).update(data))
    assert data.gateway is not None
    assert data.gateway.uptime_s == 81436.77
    assert data.gateway.flashwear_type_b_percent is None
