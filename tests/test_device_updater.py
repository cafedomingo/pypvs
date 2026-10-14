"""The device updater: one kind of device from /sys/devices/."""

from __future__ import annotations

import asyncio
import logging

import pytest

from pypvs.api import Match
from pypvs.exceptions import PVSCommunicationError
from pypvs.models.ess import PVSESS
from pypvs.models.inverter import PVSInverter
from pypvs.models.meter import PVSMeter
from pypvs.models.pvs import PVSData
from pypvs.models.transfer_switch import PVSTransferSwitch
from pypvs.updaters.device import PVSDeviceUpdater


def inverter_vars(*serials):
    out = {}
    for i, sn in enumerate(serials):
        base = f"/sys/devices/inverter/{i}"
        out[f"{base}/sn"] = sn
        out[f"{base}/p3phsumKw"] = "0.25"
        out[f"{base}/ltea3phsumKwh"] = "1200.5"
    return out


class MatchReads:
    """Answers each match query with the next of `responses`; an exception is
    raised."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.matches = []

    async def getVarserverVars(self, match):
        self.matches.append(match)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def read(updater):
    data = PVSData()
    return asyncio.run(updater.update(data)), data


@pytest.mark.parametrize(
    ("model", "match"),
    [
        (PVSInverter, Match.INVERTERS),
        (PVSMeter, Match.METERS),
        (PVSESS, Match.ESS),
        (PVSTransferSwitch, Match.TRANSFER_SWITCH),
    ],
)
def test_each_device_model_names_its_match(model, match):
    assert match == model.MATCH


def test_devices_are_keyed_by_serial_and_kept_raw():
    pvs = MatchReads([inverter_vars("A", "B")])
    devices, data = read(PVSDeviceUpdater(pvs, PVSInverter))
    assert pvs.matches == [Match.INVERTERS]
    assert list(devices) == ["A", "B"]
    assert devices["A"].lte_kwh == 1200.5
    assert [d["sn"] for d in data.raw[Match.INVERTERS]] == ["A", "B"]


def test_meters_come_from_the_meter_match():
    meter = {"/sys/devices/meter/0/sn": "M1", "/sys/devices/meter/0/p3phsumKw": "1.5"}
    pvs = MatchReads([meter])
    devices, _ = read(PVSDeviceUpdater(pvs, PVSMeter))
    assert pvs.matches == [Match.METERS]
    assert devices["M1"].power_3ph_kw == 1.5


def test_short_var_names_are_ignored():
    """'/sys/devices/inverter/0' has no param segment and must not raise."""
    answer = inverter_vars("A")
    answer["/sys/devices/inverter/0"] = "x"
    devices, _ = read(PVSDeviceUpdater(MatchReads([answer]), PVSInverter))
    assert list(devices) == ["A"]


@pytest.mark.parametrize(
    ("answer", "reason"),
    [
        (PVSCommunicationError("HTTP 400", status=400), "HTTP 400"),
        ({}, "none with a serial number"),
        ({"/sys/devices/inverter/0/p3phsumKw": "0.1"}, "none with a serial number"),
        ({"/sys/devices/inverter/x/sn": "A"}, "invalid literal"),
    ],
)
def test_no_devices_warns_once_then_recovers(caplog, answer, reason):
    caplog.set_level(logging.DEBUG, logger="pypvs")
    pvs = MatchReads([answer, answer, inverter_vars("A")])
    updater = PVSDeviceUpdater(pvs, PVSInverter)

    first, _ = read(updater)
    second, data = read(updater)
    third, _ = read(updater)

    assert first == {}
    assert second == {}
    assert Match.INVERTERS not in data.raw
    assert list(third) == ["A"]
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert warnings[0].startswith("No devices from /sys/devices/inverter/: ")
    assert reason in warnings[0]
    assert "Devices from /sys/devices/inverter/ recovered" in caplog.text
