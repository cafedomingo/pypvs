"""A full setup and update against the variables of a PVS6 and a PVS5.

The fixtures come from upstream (SunStrong-Management/pypvs#61): variables
captured from a PVS6, anonymized, and a PVS5 derived from them. They are
kept as upstream has them so later upstream changes merge cleanly; what
they lack is added here.
"""

from __future__ import annotations

import asyncio
import json
from http import HTTPStatus
from pathlib import Path

import pytest

from pypvs.exceptions import PVSCommunicationError
from pypvs.pvs import PVS

FIXTURES = Path(__file__).parent / "fixtures"

# Read by the fork but not in the captures, with the values of a PVS6 in
# tests/test_gateway_updater.py and the PVS5's interfaces from
# doc/varserver-variables-public-pvs5.csv
NETWORK = {
    "pvs6": {
        "/sys/toggle_cell/broadband_connected": "1",
        "/sys/toggle_cell/cell_connected": "0",
        "/sys/toggle_cell/low_data_mode": "0",
        "/net/sta0/state": "ready",
        "/net/wan0/state": "online",
        "/net/wan1/state": "N/A",
        "/net/wwan0/state": "N/A",
    },
    "pvs5": {
        "/sys/toggle_cell/broadband_connected": "1",
        "/sys/toggle_cell/cell_connected": "0",
        "/sys/toggle_cell/low_data_mode": "0",
        "/net/cell/state": "N/A",
        "/net/plc/state": "N/A",
        "/net/sta0/state": "ready",
        "/net/wan/state": "online",
    },
}


def pvs_with_variables(variables, rejected):
    """A PVS that answers from variables; requests it rejects go in rejected."""
    pvs = PVS(session=None, host="127.0.0.1")

    async def get_varserver(endpoint, params=None):
        if "name" in params:
            names = params["name"].split(",")
            if any(name not in variables for name in names):
                # A PVS answers 400 for the whole request if any name is unknown
                rejected.append(params["name"])
                raise PVSCommunicationError(
                    "POST request failed: 400", status=HTTPStatus.BAD_REQUEST
                )
        else:
            names = [name for name in variables if name.startswith(params["match"])]
        return {
            "count": len(names),
            "values": [{"name": name, "value": variables[name]} for name in names],
        }

    pvs.getVarserver = get_varserver
    return pvs


async def setup_and_update(pvs):
    await pvs.setup()
    return await pvs.update()


@pytest.mark.parametrize(
    (
        "fixture",
        "serial_number",
        "model",
        "flashwear",
        "usb_erase_count",
        "interface_states",
        "inverters",
        "meters",
    ),
    [
        pytest.param(
            "pvs6",
            "ZT000000000000T0001",
            "PVS6",
            30,
            0,
            {"sta0": "ready", "wan0": "online", "wan1": "N/A", "wwan0": "N/A"},
            {"E00000000000001", "E00000000000002"},
            {"PVS6M00000001p", "PVS6M00000001c"},
            id="pvs6",
        ),
        pytest.param(
            "pvs5",
            "ZA000000000000T0002",
            "PVS5",
            None,
            # in the derived capture, but not a PVS5 variable, so not read
            None,
            {"cell": "N/A", "plc": "N/A", "sta0": "ready", "wan": "online"},
            {"E00000000000003", "E00000000000004"},
            {"PVS5M00000002p", "PVS5M00000002c"},
            id="pvs5",
        ),
    ],
)
def test_update(
    fixture,
    serial_number,
    model,
    flashwear,
    usb_erase_count,
    interface_states,
    inverters,
    meters,
):
    variables = json.loads((FIXTURES / f"{fixture}.json").read_text())
    rejected = []
    pvs = pvs_with_variables(variables | NETWORK[fixture], rejected)

    data = asyncio.run(setup_and_update(pvs))

    # every variable the fork asks this model for is there, so no batch
    # falls back to reading one at a time
    assert rejected == []
    assert pvs.serial_number == serial_number
    assert data.gateway.hardware_version.startswith(model)
    assert data.gateway.flashwear_type_b_percent == flashwear
    assert data.gateway.usb_erase_count == usb_erase_count
    assert data.gateway.interface_states == interface_states
    assert data.gateway.broadband_connected is True
    assert data.gateway.cell_connected is False
    assert set(data.inverters) == inverters
    assert set(data.meters) == meters
    assert data.inverters[min(inverters)].lte_kwh == pytest.approx(5279.367676)
    assert data.meters[min(meters)].net_lte_kwh == pytest.approx(2775.040039)
    assert data.ess == {}
    assert data.transfer_switches == {}
