"""Tests for the production inverter updater."""

from __future__ import annotations

import asyncio
import logging

from pypvs.const import SupportedFeatures
from pypvs.models.pvs import PVSData
from pypvs.updaters.production_inverters import PVSProductionInvertersUpdater


def inverter_vars(*serials):
    out = {}
    for i, sn in enumerate(serials):
        base = f"/sys/devices/inverter/{i}"
        out[f"{base}/sn"] = sn
        out[f"{base}/p3phsumKw"] = "0.25"
        out[f"{base}/ltea3phsumKwh"] = "1200.5"
    return out


class MatchReads:
    """Answers each match query with the next of `responses`."""

    def __init__(self, responses):
        self.responses = list(responses)

    async def getVarserverVars(self, match):
        return self.responses.pop(0)


def make_updater(responses):
    return PVSProductionInvertersUpdater(MatchReads(responses))


def test_probe_finds_inverters():
    updater = make_updater([inverter_vars("A", "B")])
    found = asyncio.run(updater.probe(SupportedFeatures(0)))
    assert found & SupportedFeatures.INVERTERS


def test_probe_with_empty_answer_reports_not_found():
    """An empty answer (PVS rebooting, night) must not count as discovered."""
    updater = make_updater([{}])
    assert asyncio.run(updater.probe(SupportedFeatures(0))) is None


def test_update_recovers_after_empty_answer(caplog):
    caplog.set_level(logging.INFO, logger="pypvs")
    updater = make_updater([inverter_vars("A"), {}, inverter_vars("A")])

    first, empty, again = PVSData(), PVSData(), PVSData()
    asyncio.run(updater.update(first))
    asyncio.run(updater.update(empty))
    asyncio.run(updater.update(again))

    assert list(first.inverters) == ["A"]
    assert empty.inverters == {}
    assert list(again.inverters) == ["A"]
    assert "PVS returned no inverter data" in caplog.text
    assert "Inverter data recovered" in caplog.text


def test_update_ignores_short_var_names():
    """'/sys/devices/inverter/0' has no param segment and must not raise."""
    data = inverter_vars("A")
    data["/sys/devices/inverter/0"] = "x"
    updater = make_updater([data])
    out = PVSData()
    asyncio.run(updater.update(out))
    assert list(out.inverters) == ["A"]
    assert out.inverters["A"].lte_kwh == 1200.5


def test_update_without_serials_says_so(caplog):
    caplog.set_level(logging.INFO, logger="pypvs")
    updater = make_updater([{"/sys/devices/inverter/0/p3phsumKw": "0.1"}])
    out = PVSData()
    asyncio.run(updater.update(out))
    assert out.inverters == {}
    assert "without serial numbers" in caplog.text


def test_meter_updater_ignores_short_var_names():
    from pypvs.updaters.meter import PVSProductionMetersUpdater

    meter = {
        "/sys/devices/meter/0": "x",
        "/sys/devices/meter/0/sn": "M1",
        "/sys/devices/meter/0/p3phsumKw": "1.5",
    }
    updater = PVSProductionMetersUpdater(MatchReads([meter]))
    out = PVSData()
    asyncio.run(updater.update(out))
    assert out.meters["M1"].power_3ph_kw == 1.5
