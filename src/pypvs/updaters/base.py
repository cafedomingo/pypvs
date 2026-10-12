import logging
from abc import abstractmethod
from typing import Any, Protocol

from ..const import SupportedFeatures
from ..models.pvs import PVSData

_LOGGER = logging.getLogger(__name__)


def group_device_vars(vars_dict: dict[str, Any]) -> list[dict[str, Any]]:
    """Pack /sys/devices/{kind}/{i}/{param} vars into one dict per device,
    ordered by index. Devices without a serial number are dropped.

    Raises ValueError if an index is not an integer.
    """
    grouped: dict[int, dict[str, Any]] = {}
    for key, val in vars_dict.items():
        # e.g. '/sys/devices/meter/0/freqHz' -> index 0, param 'freqHz'
        parts = key.split("/")
        if len(parts) >= 6:
            grouped.setdefault(int(parts[4]), {})[parts[5]] = val
    devices = []
    for idx in sorted(grouped):
        if grouped[idx].get("sn"):
            devices.append(grouped[idx])
        else:
            _LOGGER.debug("Skipping device %d with no serial number", idx)
    return devices


class Varserver(Protocol):
    """The reads an updater makes; PVS implements them."""

    async def getVarserverVar(self, varname: str) -> Any: ...

    async def getVarserverVars(self, match: str) -> dict[str, Any]: ...

    async def getVarserverVarsByName(self, names: list[str]) -> dict[str, Any]: ...


class PVSUpdater:
    """Base class for PVS updaters."""

    def __init__(self, pvs: Varserver) -> None:
        """Initialize the PVS updater."""
        self._pvs = pvs
        self._supported_features = SupportedFeatures(0)
        self._data_unavailable = False

    @abstractmethod
    async def probe(
        self, discovered_features: SupportedFeatures
    ) -> SupportedFeatures | None:
        """Probe the PVS for this updater and return SupportedFeatures."""

    @abstractmethod
    async def update(self, pvs_data: PVSData) -> None:
        """Update the PVS for this updater."""
