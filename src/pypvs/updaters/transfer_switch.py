import logging
from typing import Any

from ..api import Match
from ..const import SupportedFeatures
from ..exceptions import ENDPOINT_PROBE_EXCEPTIONS
from ..models.pvs import PVSData
from ..models.transfer_switch import PVSTransferSwitch
from .base import PVSUpdater, group_device_vars

_LOGGER = logging.getLogger(__name__)


class PVSTransferSwitchUpdater(PVSUpdater):
    """Class to handle updates for transfer switch data."""

    async def probe(
        self, discovered_features: SupportedFeatures
    ) -> SupportedFeatures | None:
        """Probe the PVS for this updater and return SupportedFeatures."""
        try:
            await self._pvs.getVarserverVars(Match.TRANSFER_SWITCH)
        except ENDPOINT_PROBE_EXCEPTIONS as e:
            _LOGGER.debug(
                "No transfer switches found on varserver filter %s: %s",
                Match.TRANSFER_SWITCH,
                e,
            )
            return self._supported_features
        self._supported_features |= SupportedFeatures.TRANSFER_SWITCH
        return self._supported_features

    async def update(self, pvs_data: PVSData) -> None:
        """Update the PVS for this updater."""
        try:
            transfer_switches_dict: dict[str, Any] = await self._pvs.getVarserverVars(
                Match.TRANSFER_SWITCH
            )
        except Exception as e:
            if not self._data_unavailable:
                _LOGGER.warning("Transfer switch data unavailable: %s", e)
                self._data_unavailable = True
            else:
                _LOGGER.debug("Transfer switch data still unavailable: %s", e)
            return

        if self._data_unavailable:
            _LOGGER.info("Transfer switch data recovered")
            self._data_unavailable = False

        try:
            transfer_switches_data = group_device_vars(transfer_switches_dict)
        except Exception as e:
            _LOGGER.error("Failed to process transfer switch data: %s", e)
            return

        pvs_data.raw[Match.TRANSFER_SWITCH] = transfer_switches_data
        pvs_data.transfer_switches = {
            switch["sn"]: PVSTransferSwitch.from_varserver(switch)
            for switch in transfer_switches_data
        }
