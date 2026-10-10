import logging
from typing import Any

from ..const import VARS_MATCH_INVERTERS, SupportedFeatures
from ..exceptions import ENDPOINT_PROBE_EXCEPTIONS
from ..models.inverter import PVSInverter
from ..models.pvs import PVSData
from .base import PVSUpdater, group_device_vars

_LOGGER = logging.getLogger(__name__)


class PVSProductionInvertersUpdater(PVSUpdater):
    """Class to handle updates for inverter production data."""

    async def probe(
        self, discovered_features: SupportedFeatures
    ) -> SupportedFeatures | None:
        """Probe the PVS for this updater and return SupportedFeatures."""
        try:
            inverters_dict = await self._match(VARS_MATCH_INVERTERS)
        except ENDPOINT_PROBE_EXCEPTIONS as e:
            _LOGGER.debug(
                "No inverters found on varserver filter %s: %s", VARS_MATCH_INVERTERS, e
            )
            return None
        try:
            found = bool(group_device_vars(inverters_dict))
        except ValueError:
            found = False
        if not found:
            # An empty answer (e.g. right after a PVS reboot or at night) is not
            # proof there are no inverters; leave the feature unset so update()
            # re-probes with backoff.
            _LOGGER.debug(
                "Varserver filter %s returned no inverters", VARS_MATCH_INVERTERS
            )
            return None
        self._supported_features |= SupportedFeatures.INVERTERS
        return self._supported_features

    async def update(self, pvs_data: PVSData) -> None:
        """Update the PVS for this updater."""
        try:
            inverters_dict: dict[str, Any] = await self._match(VARS_MATCH_INVERTERS)
        except Exception as e:
            if not self._data_unavailable:
                _LOGGER.warning("Inverter data unavailable: %s", e)
                self._data_unavailable = True
            else:
                _LOGGER.debug("Inverter data still unavailable: %s", e)
            return

        try:
            inverters_data = group_device_vars(inverters_dict)
        except Exception as e:
            _LOGGER.error("Failed to process inverter data: %s", e)
            return

        if not inverters_data:
            if not self._data_unavailable:
                _LOGGER.warning(
                    "PVS returned no inverter data"
                    if not inverters_dict
                    else "PVS returned inverter data without serial numbers"
                )
                self._data_unavailable = True
            return

        if self._data_unavailable:
            _LOGGER.info("Inverter data recovered")
            self._data_unavailable = False

        pvs_data.raw[VARS_MATCH_INVERTERS] = inverters_data
        pvs_data.inverters = {
            inverter["sn"]: PVSInverter.from_varserver(inverter)
            for inverter in inverters_data
        }
