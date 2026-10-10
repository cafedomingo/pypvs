import logging
from typing import Any

from ..const import VARS_MATCH_INFO, SupportedFeatures
from ..exceptions import PVSCommunicationError
from ..models.gateway import PVSGateway
from ..models.pvs import PVSData
from .base import PVSUpdater

_LOGGER = logging.getLogger(__name__)

# Variables not every PVS has (flashwear_type_b is PVS6-only). The PVS answers
# 400 for a variable it doesn't know; that marks it unsupported for good, while
# other failures (timeouts, 5xx) still fail the update.
OPTIONAL_VARS = {"/sys/pvs/flashwear_type_b"}
HTTP_BAD_REQUEST = 400


class PVSGatewayUpdater(PVSUpdater):
    """Class to handle updates for the PVS gateway."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._unsupported_vars: set[str] = set()

    async def probe(
        self, discovered_features: SupportedFeatures
    ) -> SupportedFeatures | None:
        """Probe the PVS for this updater and return SupportedFeatures."""

        # This updater is always available
        _LOGGER.debug("Probing PVS for gateway data. It is aways available.")
        self._supported_features |= SupportedFeatures.GATEWAY
        return self._supported_features

    async def update(self, pvs_data: PVSData) -> None:
        """Update the PVS for this updater."""
        sys_info: dict[str, Any] = {
            "/sys/info/sys_type": None,
            "/sys/info/model": None,
            "/sys/info/hwrev": None,
            "/sys/info/sw_rev": None,
            "/sys/info/uptime": None,
            "/sys/info/lmac": None,
            "/sys/info/ram_usage": None,
            "/sys/info/flash_usage": None,
            "/sys/info/cpu_usage": None,
            "/sys/pvs/flashwear_type_b": None,
        }

        # undate individual vars and not by match as the match takes a long time
        for var_name, var_value in sys_info.items():
            if var_value is not None:
                continue
            if var_name in self._unsupported_vars:
                continue
            try:
                sys_info[var_name] = await self._request_var(var_name)
            except PVSCommunicationError as e:
                if var_name not in OPTIONAL_VARS or e.status != HTTP_BAD_REQUEST:
                    raise
                _LOGGER.debug("PVS does not support %s; not asking again", var_name)
                self._unsupported_vars.add(var_name)

        pvs_data.raw[VARS_MATCH_INFO] = sys_info
        pvs_data.gateway = PVSGateway.from_varserver(sys_info)
