"""The gateway (/sys/info and friends) updater."""

from __future__ import annotations

import asyncio

import pytest

import pypvs.updaters.gateway as gateway_module
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

# values as a PVS6 with a SunVault returned them
EXTRAS = {
    "/ess/config/dcm/control_param/min_customer_soc": "0.20",
    "/ess/config/dcm/mode_param/control_mode": "SELF_CONSUMPTION",
    "/sys/info/active_interface": "wan0",
    "/sys/toggle_cell/broadband_connected": "1",
    "/sys/toggle_cell/cell_connected": "0",
    "/sys/toggle_cell/low_data_mode": "0",
    "/sys/pvs/usb_erase_count": "0",
    "/sys/info/fwrev": "",
    "/sys/info/boardtype": "A0K LIB 1.0 PSoC5",
}
NET = {
    "/net/wan0/state": "online",
    "/net/wan1/state": "N/A",
    "/net/sta0/state": "ready",
    "/net/wwan0/state": "N/A",
}

BAD_REQUEST = PVSCommunicationError("POST request failed: HTTP 400", status=400)


class FakePVS:
    """Answers single vars from `values` and the /net/ match from `net`; a var
    that isn't there gets HTTP 400, like the real PVS."""

    def __init__(self, values, net=None, failures=None):
        self.values = values
        self.net = net
        self.failures = failures or {}
        self.calls = []

    async def request_var(self, name):
        self.calls.append(name)
        if name in self.failures:
            raise self.failures[name]
        if name not in self.values:
            raise BAD_REQUEST
        return self.values[name]

    async def request_vars(self, match):
        self.calls.append(match)
        if self.net is None:
            raise BAD_REQUEST
        return self.net

    def updater(self):
        return PVSGatewayUpdater(
            request_var=self.request_var,
            request_vars=self.request_vars,
            common_properties=CommonProperties(),
        )


class Clock:
    def __init__(self, monkeypatch):
        self.now = 1000.0
        monkeypatch.setattr(gateway_module.time, "monotonic", lambda: self.now)


def run(updater):
    data = PVSData()
    asyncio.run(updater.update(data))
    return data.gateway


def test_full_sys_info():
    gw = run(FakePVS(SYS_INFO).updater())
    assert gw.pvs_type == "PVS6"
    assert gw.uptime_s == 81436.77
    assert gw.flashwear_type_b_percent == 10


def test_pvs_without_flashwear_still_reports_the_gateway():
    """flashwear_type_b only exists on the PVS6; a PVS5 answers 400 for it.
    That one optional variable must not fail the whole gateway update."""
    values = {k: v for k, v in SYS_INFO.items() if k != "/sys/pvs/flashwear_type_b"}
    gw = run(FakePVS(values).updater())
    assert gw.uptime_s == 81436.77
    assert gw.flashwear_type_b_percent is None


def test_timeout_on_a_core_var_fails_the_update():
    """Only a 400 means 'no such variable'; a timeout on the core info must
    still fail the update rather than silently reporting the value as missing."""
    timeout = PVSCommunicationError("Cannot reach the PVS: timeout")
    pvs = FakePVS(SYS_INFO, failures={"/sys/pvs/flashwear_type_b": timeout})
    with pytest.raises(PVSCommunicationError):
        run(pvs.updater())


def test_gateway_extras():
    gw = run(FakePVS({**SYS_INFO, **EXTRAS}, net=NET).updater())
    assert gw.ess_reserve_soc == 0.2
    assert gw.ess_control_mode == "SELF_CONSUMPTION"
    assert gw.interface_states == {
        "wan0": "online",
        "wan1": "N/A",
        "sta0": "ready",
        "wwan0": "N/A",
    }
    assert gw.active_interface == "wan0"
    assert gw.broadband_connected is True
    assert gw.cell_connected is False
    assert gw.low_data_mode == 0
    assert gw.usb_erase_count == 0
    # an empty string is no value, not an empty firmware revision
    assert gw.firmware_revision is None
    assert gw.board_type == "A0K LIB 1.0 PSoC5"


def test_pvs5_interface_names_are_picked_up():
    net = {"/net/wan/state": "online", "/net/cell/state": "N/A"}
    gw = run(FakePVS(SYS_INFO, net=net).updater())
    assert gw.interface_states == {"wan": "online", "cell": "N/A"}


def test_text_values_are_trimmed_and_placeholders_dropped():
    values = {
        **SYS_INFO,
        "/sys/info/fwrev": " Major 2, Revision 0x00000001, Build 3",
        "/sys/info/boardtype": "TBD",
        "/sys/pvs/usb_erase_count": "0x00ab",
    }
    gw = run(FakePVS(values).updater())
    assert gw.firmware_revision == "Major 2, Revision 0x00000001, Build 3"
    assert gw.board_type is None
    assert gw.usb_erase_count == 0xAB


def test_gateway_without_extras_or_battery():
    """A PVS without a battery (or older firmware) answers 400 for these."""
    gw = run(FakePVS(SYS_INFO).updater())
    assert gw.ess_reserve_soc is None
    assert gw.ess_control_mode is None
    assert gw.interface_states == {}
    assert gw.broadband_connected is None


def test_partial_support_keeps_the_rest():
    values = {**SYS_INFO, **EXTRAS}
    del values["/ess/config/dcm/control_param/min_customer_soc"]
    gw = run(FakePVS(values, net=NET).updater())
    assert gw.ess_reserve_soc is None
    assert gw.ess_control_mode == "SELF_CONSUMPTION"


def test_extras_are_refreshed_every_few_minutes_not_every_poll(monkeypatch):
    clock = Clock(monkeypatch)
    pvs = FakePVS({**SYS_INFO, **EXTRAS}, net=NET)
    updater = pvs.updater()
    run(updater)
    clock.now += 30
    pvs.calls.clear()
    gw = run(updater)
    assert "/sys/info/boardtype" not in pvs.calls
    assert gw.board_type == "A0K LIB 1.0 PSoC5"  # cached
    clock.now += gateway_module.EXTRAS_REFRESH_S
    pvs.calls.clear()
    run(updater)
    assert "/sys/info/boardtype" in pvs.calls


def test_a_timeout_on_an_extra_keeps_its_last_value(monkeypatch):
    clock = Clock(monkeypatch)
    pvs = FakePVS({**SYS_INFO, **EXTRAS}, net=NET)
    updater = pvs.updater()
    run(updater)
    pvs.failures["/ess/config/dcm/mode_param/control_mode"] = PVSCommunicationError(
        "Cannot reach the PVS: timeout"
    )
    clock.now += gateway_module.EXTRAS_REFRESH_S
    gw = run(updater)
    assert gw.ess_control_mode == "SELF_CONSUMPTION"


def test_unsupported_vars_are_asked_again_later(monkeypatch):
    """A 400 can be temporary (battery commissioned later, services starting)."""
    clock = Clock(monkeypatch)
    values = {k: v for k, v in SYS_INFO.items() if k != "/sys/pvs/flashwear_type_b"}
    pvs = FakePVS(values)
    updater = pvs.updater()
    run(updater)
    clock.now += 30
    run(updater)
    assert pvs.calls.count("/sys/pvs/flashwear_type_b") == 1
    clock.now += gateway_module.UNSUPPORTED_RETRY_S
    values["/sys/pvs/flashwear_type_b"] = "0x02"
    gw = run(updater)
    assert gw.flashwear_type_b_percent == 20
