import logging
from abc import abstractmethod
from collections.abc import Awaitable, Callable
from typing import Any

from ..const import SupportedFeatures
from ..models.common import CommonProperties
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


class PVSUpdater:
    """Base class for PVS updaters."""

    def __init__(
        self,
        request_var: Callable[[str], Awaitable[Any]],
        request_vars: Callable[[str], Awaitable[dict[str, Any]]],
        common_properties: CommonProperties,
        request_named_vars: Callable[[list[str]], Awaitable[dict[str, Any]]]
        | None = None,
    ) -> None:
        """Initialize the PVS updater.

        request_named_vars, when given, reads several variables in one request
        (the PVS answers 400 for the whole request if any name is unknown).
        """
        self._request_var = request_var
        self._request_vars = request_vars
        self._request_named_vars = request_named_vars
        self._supported_features = SupportedFeatures(0)
        self._common_properties = common_properties
        self._data_unavailable = False

    @abstractmethod
    async def probe(
        self, discovered_features: SupportedFeatures
    ) -> SupportedFeatures | None:
        """Probe the PVS for this updater and return SupportedFeatures."""

    @abstractmethod
    async def update(self, pvs_data: PVSData) -> None:
        """Update the PVS for this updater."""
