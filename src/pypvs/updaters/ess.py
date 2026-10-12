import logging
from typing import Any

from ..api import Match
from ..const import SupportedFeatures
from ..exceptions import ENDPOINT_PROBE_EXCEPTIONS
from ..models.ess import PVSESS
from ..models.pvs import PVSData
from .base import PVSUpdater, group_device_vars

_LOGGER = logging.getLogger(__name__)


class PVSESSUpdater(PVSUpdater):
    """Class to handle updates for ESS data."""

    async def probe(
        self, discovered_features: SupportedFeatures
    ) -> SupportedFeatures | None:
        """Probe the PVS for this updater and return SupportedFeatures."""
        try:
            await self._pvs.getVarserverVars(Match.ESS)
        except ENDPOINT_PROBE_EXCEPTIONS as e:
            _LOGGER.debug("No ESS found on varserver filter %s: %s", Match.ESS, e)
            return None
        self._supported_features |= SupportedFeatures.ESS
        return self._supported_features

    async def update(self, pvs_data: PVSData) -> None:
        """Update the PVS for this updater."""
        try:
            ess_dict: dict[str, Any] = await self._pvs.getVarserverVars(Match.ESS)
        except Exception as e:
            if not self._data_unavailable:
                _LOGGER.warning("ESS data unavailable: %s", e)
                self._data_unavailable = True
            else:
                _LOGGER.debug("ESS data still unavailable: %s", e)
            return

        if self._data_unavailable:
            _LOGGER.info("ESS data recovered")
            self._data_unavailable = False

        try:
            ess_data = group_device_vars(ess_dict)
        except Exception as e:
            _LOGGER.error("Failed to process ESS data: %s", e)
            return

        pvs_data.raw[Match.ESS] = ess_data
        pvs_data.ess = {ess["sn"]: PVSESS.from_varserver(ess) for ess in ess_data}
