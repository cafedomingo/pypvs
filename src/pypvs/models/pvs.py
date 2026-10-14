"""Model for one poll of the PVS."""

from dataclasses import dataclass, field
from typing import Any

from .ess import PVSESS
from .gateway import PVSGateway
from .inverter import PVSInverter
from .meter import PVSMeter
from .transfer_switch import PVSTransferSwitch


@dataclass(slots=True)
class PVSData:
    """Everything one poll read from the PVS and its devices."""

    gateway: PVSGateway | None = None

    inverters: dict[str, PVSInverter] = field(default_factory=dict)

    meters: dict[str, PVSMeter] = field(default_factory=dict)

    ess: dict[str, PVSESS] = field(default_factory=dict)

    transfer_switches: dict[str, PVSTransferSwitch] = field(default_factory=dict)

    # Raw data is exposed so we can __eq__ the data to see if
    # anything has changed and consumers of the library can
    # avoid dispatching data if nothing has changed.
    raw: dict[str, Any] = field(default_factory=dict)
