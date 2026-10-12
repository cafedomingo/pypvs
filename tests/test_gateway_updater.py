"""The gateway (/sys/info and friends) updater."""

from __future__ import annotations

import asyncio

import pytest

import pypvs.updaters.gateway as gateway_module
from pypvs.const import SupportedFeatures
from pypvs.exceptions import (
    PVSAuthenticationError,
    PVSCommunicationError,
    PVSDataFormatError,
)
from pypvs.models.pvs import PVSData
from pypvs.updaters.gateway import PVSGatewayUpdater

SYS_INFO = {
    "/sys/info/cpu_usage": "6",
    "/sys/info/flash_usage": "73",
    "/sys/info/hwrev": "6.02",
    "/sys/info/lmac": "02:aa:bb:cc:dd:01",
    "/sys/info/model": "PVS6",
    "/sys/info/ram_usage": "7",
    "/sys/info/sw_rev": "2025.06.06.61839",
    "/sys/info/sys_type": "Storage",
    "/sys/info/uptime": "81436.77",
    "/sys/pvs/flashwear_type_b": "0x01",
}

# values as a PVS6 with a SunVault returned them
EXTRAS = {
    "/ess/config/dcm/control_param/min_customer_soc": "0.20",
    "/ess/config/dcm/mode_param/control_mode": "SELF_CONSUMPTION",
    "/sys/info/active_interface": "wan0",
    "/sys/info/boardtype": "A0K LIB 1.0 PSoC5",
    "/sys/info/fwrev": "",
    "/sys/pvs/usb_erase_count": "0",
    "/sys/toggle_cell/broadband_connected": "1",
    "/sys/toggle_cell/cell_connected": "0",
    "/sys/toggle_cell/low_data_mode": "0",
}
NET = {
    "/net/sta0/state": "ready",
    "/net/wan0/state": "online",
    "/net/wan1/state": "N/A",
    "/net/wwan0/state": "N/A",
}

BAD_REQUEST = PVSCommunicationError("POST request failed: HTTP 400", status=400)
UNREACHABLE = PVSCommunicationError("Cannot reach the PVS: timeout")


class FakePVS:
    """Answers single vars from `values`; a var that isn't there gets HTTP 400,
    like the real PVS."""

    def __init__(self, values, failures=None):
        self.values = values
        self.failures = failures or {}
        self.calls = []
        self.batches = []

    async def getVarserverVar(self, name):
        self.calls.append(name)
        if name in self.failures:
            raise self.failures[name]
        if name not in self.values:
            raise BAD_REQUEST
        return self.values[name]

    async def getVarserverVars(self, match):
        raise AssertionError("the gateway updater should not use match queries")

    async def getVarserverVarsByName(self, names):
        self.batches.append(list(names))
        for name in names:
            if name in self.failures:
                raise self.failures[name]
        if any(name not in self.values for name in names):
            raise BAD_REQUEST  # the PVS rejects the whole request
        return {name: self.values[name] for name in names}

    def asked(self):
        return self.calls + [n for batch in self.batches for n in batch]

    def updater(self, ess=True):
        updater = PVSGatewayUpdater(self)
        features = SupportedFeatures.ESS if ess else SupportedFeatures(0)
        asyncio.run(updater.probe(features))
        return updater


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


def test_timeout_on_a_core_var_fails_the_update():
    """Every core variable is required: a failure must fail the update rather
    than silently report the value as missing."""
    pvs = FakePVS(SYS_INFO, failures={"/sys/info/uptime": UNREACHABLE})
    with pytest.raises(PVSCommunicationError):
        run(pvs.updater())


def test_gateway_extras():
    gw = run(FakePVS({**SYS_INFO, **EXTRAS, **NET}).updater())
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
    pvs5 = {**SYS_INFO, "/sys/info/model": "PVS5"}
    gw = run(FakePVS({**pvs5, **net}).updater())
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
    """Extras the PVS answers 400 for are left out."""
    gw = run(FakePVS(SYS_INFO).updater())
    assert gw.ess_reserve_soc is None
    assert gw.ess_control_mode is None
    assert gw.interface_states == {}
    assert gw.broadband_connected is None


def test_partial_support_keeps_the_rest():
    values = {**SYS_INFO, **EXTRAS, **NET}
    del values["/ess/config/dcm/control_param/min_customer_soc"]
    gw = run(FakePVS(values).updater())
    assert gw.ess_reserve_soc is None
    assert gw.ess_control_mode == "SELF_CONSUMPTION"


def test_extras_are_refreshed_every_few_minutes_not_every_poll(monkeypatch):
    clock = Clock(monkeypatch)
    pvs = FakePVS({**SYS_INFO, **EXTRAS, **NET})
    updater = pvs.updater()
    run(updater)
    clock.now += 30
    pvs.batches.clear()
    gw = run(updater)
    assert "/sys/info/boardtype" not in pvs.asked()
    assert gw.board_type == "A0K LIB 1.0 PSoC5"  # cached
    clock.now += gateway_module.EXTRAS_REFRESH_S
    pvs.batches.clear()
    run(updater)
    assert "/sys/info/boardtype" in pvs.asked()


def test_a_timeout_on_an_extra_keeps_its_last_value(monkeypatch):
    clock = Clock(monkeypatch)
    pvs = FakePVS({**SYS_INFO, **EXTRAS, **NET})
    updater = pvs.updater()
    run(updater)
    pvs.failures["/ess/config/dcm/mode_param/control_mode"] = PVSCommunicationError(
        "Cannot reach the PVS: timeout"
    )
    clock.now += gateway_module.EXTRAS_REFRESH_S
    gw = run(updater)
    assert gw.ess_control_mode == "SELF_CONSUMPTION"


def test_no_failure_on_an_extra_fails_the_gateway_update():
    """Extras are best effort: a login hiccup, empty answer or timeout on one
    must not lose the core gateway data (or the other device updates)."""
    for error in (
        PVSAuthenticationError("login failed"),
        PVSDataFormatError("no value"),
        PVSCommunicationError("Cannot reach the PVS: timeout"),
    ):
        pvs = FakePVS(
            {**SYS_INFO, **EXTRAS, **NET},
            failures={"/sys/toggle_cell/low_data_mode": error},
        )
        gw = run(pvs.updater())
        assert gw.uptime_s == 81436.77, error


def test_an_empty_answer_keeps_the_last_value(monkeypatch):
    clock = Clock(monkeypatch)
    pvs = FakePVS({**SYS_INFO, **EXTRAS, **NET})
    updater = pvs.updater()
    run(updater)
    pvs.failures["/ess/config/dcm/mode_param/control_mode"] = PVSDataFormatError("")
    clock.now += gateway_module.EXTRAS_REFRESH_S
    assert run(updater).ess_control_mode == "SELF_CONSUMPTION"


def test_a_slow_pvs_costs_one_timeout_per_refresh():
    timeout = PVSCommunicationError("Cannot reach the PVS: timeout")
    pvs = FakePVS(
        {**SYS_INFO, **EXTRAS, **NET},
        failures=dict.fromkeys(EXTRAS, timeout),
    )
    run(pvs.updater())
    assert pvs.calls == []
    assert len(pvs.batches) == 2


def test_an_extra_that_appears_later_is_picked_up(monkeypatch):
    """e.g. a battery commissioned after the exporter started."""
    clock = Clock(monkeypatch)
    values = {**SYS_INFO, **NET}
    updater = FakePVS(values).updater()
    assert run(updater).ess_control_mode is None
    values["/ess/config/dcm/mode_param/control_mode"] = "SELF_CONSUMPTION"
    clock.now += gateway_module.EXTRAS_REFRESH_S
    assert run(updater).ess_control_mode == "SELF_CONSUMPTION"


def test_odd_values_are_normalised():
    values = {
        **SYS_INFO,
        "/net/wan1/state": "TBD",
        "/sys/toggle_cell/low_data_mode": "1.0",
        "/sys/pvs/usb_erase_count": "-1",
    }
    gw = run(FakePVS(values).updater())
    assert "wan1" not in gw.interface_states
    assert gw.low_data_mode == 1
    assert gw.usb_erase_count is None


def test_only_the_models_interfaces_are_asked_for():
    pvs = FakePVS({**SYS_INFO, **NET})
    run(pvs.updater())
    assert "/net/wan0/state" in pvs.asked()
    assert "/net/cell/state" not in pvs.asked()  # PVS5-only


def test_a_persistent_error_on_one_extra_does_not_starve_the_rest():
    server_error = PVSCommunicationError("POST request failed: HTTP 500", status=500)
    pvs = FakePVS(
        {**SYS_INFO, **EXTRAS, **NET},
        failures={"/sys/info/fwrev": server_error},
    )
    gw = run(pvs.updater())
    assert gw.ess_control_mode == "SELF_CONSUMPTION"
    assert gw.interface_states["wan0"] == "online"


def test_a_value_that_stays_empty_is_dropped(monkeypatch):
    clock = Clock(monkeypatch)
    pvs = FakePVS({**SYS_INFO, **EXTRAS, **NET})
    updater = pvs.updater()
    run(updater)
    pvs.failures["/ess/config/dcm/mode_param/control_mode"] = PVSDataFormatError("")
    for _ in range(gateway_module.EMPTY_REFRESHES_BEFORE_DROP - 1):
        clock.now += gateway_module.EXTRAS_REFRESH_S
        assert run(updater).ess_control_mode == "SELF_CONSUMPTION"
    clock.now += gateway_module.EXTRAS_REFRESH_S
    assert run(updater).ess_control_mode is None


def test_core_and_extras_take_two_requests():
    pvs = FakePVS({**SYS_INFO, **EXTRAS, **NET})
    gw = run(pvs.updater())
    assert pvs.calls == []
    assert len(pvs.batches) == 2
    assert gw.uptime_s == 81436.77
    assert gw.ess_control_mode == "SELF_CONSUMPTION"
    assert gw.interface_states["wan0"] == "online"


def test_a_missing_required_var_fails_the_update():
    values = {k: v for k, v in SYS_INFO.items() if k != "/sys/info/uptime"}
    with pytest.raises(PVSCommunicationError):
        run(FakePVS(values).updater())


def test_extras_keep_their_values_through_errors(monkeypatch):
    clock = Clock(monkeypatch)
    pvs = FakePVS({**SYS_INFO, **EXTRAS, **NET})
    updater = pvs.updater()
    run(updater)
    pvs.failures["/sys/info/boardtype"] = PVSCommunicationError("HTTP 500", status=500)
    clock.now += gateway_module.EXTRAS_REFRESH_S
    gw = run(updater)
    assert gw.board_type == "A0K LIB 1.0 PSoC5"  # kept
    assert gw.ess_control_mode == "SELF_CONSUMPTION"  # read singly


def test_a_server_error_on_a_core_var_fails_the_update():
    server_error = PVSCommunicationError("HTTP 500", status=500)
    pvs = FakePVS(SYS_INFO, failures={"/sys/info/uptime": server_error})
    with pytest.raises(PVSCommunicationError, match="500"):
        run(pvs.updater())


def test_an_unreachable_pvs_fails_without_single_reads():
    pvs = FakePVS(SYS_INFO, failures={"/sys/info/uptime": UNREACHABLE})
    with pytest.raises(PVSCommunicationError, match="Cannot reach"):
        run(pvs.updater())
    assert pvs.calls == []


def test_names_a_batch_leaves_out_are_read_alone():
    pvs = FakePVS({**SYS_INFO, **EXTRAS, **NET})
    full = pvs.getVarserverVarsByName

    async def without_uptime(names):
        return {k: v for k, v in (await full(names)).items() if k != "/sys/info/uptime"}

    pvs.getVarserverVarsByName = without_uptime
    gw = run(pvs.updater())
    assert pvs.calls == ["/sys/info/uptime"]
    assert gw.uptime_s == 81436.77


def test_pvs5_is_not_asked_for_pvs6_only_vars():
    pvs6_only = {
        "/sys/pvs/flashwear_type_b",
        "/sys/pvs/usb_erase_count",
        "/ess/config/dcm/control_param/min_customer_soc",
        "/ess/config/dcm/mode_param/control_mode",
    }
    values = {k: v for k, v in {**SYS_INFO, **EXTRAS}.items() if k not in pvs6_only}
    values["/sys/info/model"] = "PVS5"
    values["/net/wan/state"] = "online"
    values["/net/cell/state"] = "N/A"
    values["/net/plc/state"] = "N/A"
    values["/net/sta0/state"] = "ready"
    pvs = FakePVS(values)
    gw = run(pvs.updater())
    assert pvs.calls == []
    assert len(pvs.batches) == 2
    assert not pvs6_only & {n for batch in pvs.batches for n in batch}
    assert gw.interface_states["wan"] == "online"


def test_a_failing_batch_is_logged_with_the_names_that_failed_alone(caplog):
    server_error = PVSCommunicationError("HTTP 500", status=500)
    pvs = FakePVS(SYS_INFO, failures={"/sys/info/uptime": server_error})
    with pytest.raises(PVSCommunicationError):
        run(pvs.updater())
    assert "Batched read of 9 variables failed" in caplog.text
    assert "failed on their own too: /sys/info/uptime" in caplog.text


def test_a_malformed_batch_falls_back_to_single_reads():
    pvs = FakePVS({**SYS_INFO, **EXTRAS, **NET})

    async def malformed(names):
        raise PVSDataFormatError("no values list")

    pvs.getVarserverVarsByName = malformed
    gw = run(pvs.updater())
    assert gw.uptime_s == 81436.77
    assert gw.ess_control_mode == "SELF_CONSUMPTION"


def test_an_extra_that_starts_answering_400_is_dropped(monkeypatch):
    clock = Clock(monkeypatch)
    values = {**SYS_INFO, **EXTRAS, **NET}
    updater = FakePVS(values).updater()
    assert run(updater).ess_control_mode == "SELF_CONSUMPTION"
    del values["/ess/config/dcm/mode_param/control_mode"]
    clock.now += gateway_module.EXTRAS_REFRESH_S
    assert run(updater).ess_control_mode is None


def test_without_a_battery_its_config_is_not_asked_for(caplog):
    values = {
        k: v for k, v in {**SYS_INFO, **EXTRAS, **NET}.items() if "/ess/" not in k
    }
    pvs = FakePVS(values)
    gw = run(pvs.updater(ess=False))
    assert pvs.calls == []
    assert len(pvs.batches) == 2
    assert not any("/ess/" in n for batch in pvs.batches for n in batch)
    assert gw.ess_control_mode is None
    assert "Batched read" not in caplog.text
