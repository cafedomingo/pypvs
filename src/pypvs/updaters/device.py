"""Builds every device of one kind from a read of /sys/devices/."""

import logging
from typing import Any, Generic, TypeVar

from ..exceptions import PVSError
from ..models.ess import PVSESS
from ..models.inverter import PVSInverter
from ..models.meter import PVSMeter
from ..models.pvs import PVSData
from ..models.transfer_switch import PVSTransferSwitch

_LOGGER = logging.getLogger(__name__)


def group_device_vars(vars_dict: dict[str, Any]) -> list[dict[str, Any]]:
    """Pack /sys/devices/{kind}/{i}/{param} vars into one dict per device.

    Ordered by index; devices without a serial number are dropped.

    Raises:
        ValueError: If an index is not an integer.
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


M = TypeVar("M", PVSInverter, PVSMeter, PVSESS, PVSTransferSwitch)


class PVSDeviceUpdater(Generic[M]):
    """Builds every device of one kind, e.g. all meters."""

    def __init__(self, model: type[M]) -> None:
        self._model: type[M] = model
        self._unavailable = False

    def update(
        self, pvs_data: PVSData, device_vars: dict[str, Any] | PVSError
    ) -> dict[str, M]:
        """Build the devices and keep their raw variables in pvs_data.raw.

        Args:
            pvs_data: Where the raw variables go.
            device_vars: The answer to a /sys/devices/ match, or why it failed.

        Returns:
            The devices by serial number; empty if none could be read.
        """
        match = self._model.MATCH
        if isinstance(device_vars, PVSError):
            devices, problem = [], str(device_vars)
        else:
            mine = {k: v for k, v in device_vars.items() if k.startswith(match)}
            try:
                devices = group_device_vars(mine)
                problem = "" if devices else "none with a serial number"
            except ValueError as e:
                devices, problem = [], str(e)

        if problem:
            log = _LOGGER.debug if self._unavailable else _LOGGER.warning
            log("No devices from %s: %s", match, problem)
            self._unavailable = True
            return {}
        if self._unavailable:
            _LOGGER.info("Devices from %s recovered", match)
            self._unavailable = False

        pvs_data.raw[match] = devices
        return {d["sn"]: self._model.from_varserver(d) for d in devices}
