import logging
from typing import Any

from ..api import Match
from ..const import SupportedFeatures
from ..exceptions import ENDPOINT_PROBE_EXCEPTIONS
from ..models.meter import PVSMeter
from ..models.pvs import PVSData
from .base import PVSUpdater, group_device_vars

_LOGGER = logging.getLogger(__name__)


class PVSProductionMetersUpdater(PVSUpdater):
    """Class to handle updates for meter data."""

    async def probe(
        self, discovered_features: SupportedFeatures
    ) -> SupportedFeatures | None:
        """Probe the PVS for this updater and return SupportedFeatures."""
        try:
            await self._pvs.getVarserverVars(Match.METERS)
        except ENDPOINT_PROBE_EXCEPTIONS as e:
            _LOGGER.debug("No meters found on varserver filter %s: %s", Match.METERS, e)
            return self._supported_features
        self._supported_features |= SupportedFeatures.METERING
        return self._supported_features

    async def update(self, pvs_data: PVSData) -> None:
        """Update the PVS for this updater."""
        try:
            meters_dict: dict[str, Any] = await self._pvs.getVarserverVars(Match.METERS)
        except Exception as e:
            if not self._data_unavailable:
                _LOGGER.warning("Meter data unavailable: %s", e)
                self._data_unavailable = True
            else:
                _LOGGER.debug("Meter data still unavailable: %s", e)
            return

        if self._data_unavailable:
            _LOGGER.info("Meter data recovered")
            self._data_unavailable = False

        try:
            meters_data = group_device_vars(meters_dict)
        except Exception as e:
            _LOGGER.error("Failed to process meter data: %s", e)
            return

        pvs_data.raw[Match.METERS] = meters_data
        pvs_data.meters = {
            meter["sn"]: PVSMeter.from_varserver(meter) for meter in meters_data
        }
