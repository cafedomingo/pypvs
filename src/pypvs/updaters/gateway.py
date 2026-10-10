import logging
import time
from typing import Any

from ..const import VARS_MATCH_INFO, SupportedFeatures
from ..exceptions import PVSCommunicationError, PVSDataFormatError, PVSError
from ..models.gateway import CORE_VARS, EXTRA_VARS, OPTIONAL_CORE_VARS, PVSGateway
from ..models.pvs import PVSData
from .base import PVSUpdater

_LOGGER = logging.getLogger(__name__)

HTTP_BAD_REQUEST = 400
# Extras (network, cloud, battery config, board info) change rarely, so they
# are fetched every few minutes rather than on every poll.
EXTRAS_REFRESH_S = 300
# The PVS answers 400 for a variable it doesn't have. That can be temporary
# (services still starting, a battery commissioned later), so ask again later.
UNSUPPORTED_RETRY_S = 3600

_MISSING = object()


def _is_unsupported(error: PVSError) -> bool:
    return isinstance(error, PVSCommunicationError) and error.status == HTTP_BAD_REQUEST


class PVSGatewayUpdater(PVSUpdater):
    """Class to handle updates for the PVS gateway."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # var name -> monotonic time the PVS answered 400 for it
        self._unsupported_vars: dict[str, float] = {}
        self._extras: dict[str, Any] = {}
        self._extras_at: float | None = None

    async def probe(
        self, discovered_features: SupportedFeatures
    ) -> SupportedFeatures | None:
        """Probe the PVS for this updater and return SupportedFeatures."""

        # This updater is always available
        _LOGGER.debug("Probing PVS for gateway data. It is aways available.")
        self._supported_features |= SupportedFeatures.GATEWAY
        return self._supported_features

    async def _read(self, name: str, now: float) -> Any:
        """Read one variable. Returns _MISSING when the PVS doesn't have it
        (400, remembered for UNSUPPORTED_RETRY_S) or answered without a value;
        other errors propagate."""
        marked = self._unsupported_vars.get(name)
        if marked is not None and now - marked < UNSUPPORTED_RETRY_S:
            return _MISSING
        try:
            value = await self._request_var(name)
        except PVSDataFormatError:
            return _MISSING
        except PVSCommunicationError as e:
            if not _is_unsupported(e):
                raise
            _LOGGER.debug("PVS does not support %s", name)
            self._unsupported_vars[name] = now
            return _MISSING
        self._unsupported_vars.pop(name, None)
        return value

    async def update(self, pvs_data: PVSData) -> None:
        """Update the PVS for this updater."""
        now = time.monotonic()
        sys_info: dict[str, Any] = {}

        # individual vars rather than a match, as the match takes a long time
        for name in CORE_VARS:
            if name in OPTIONAL_CORE_VARS:
                value = await self._read(name, now)
                if value is not _MISSING:
                    sys_info[name] = value
            else:
                sys_info[name] = await self._request_var(name)

        if self._extras_at is None or now - self._extras_at >= EXTRAS_REFRESH_S:
            await self._refresh_extras(now)

        sys_info.update(self._extras)
        pvs_data.raw[VARS_MATCH_INFO] = sys_info
        pvs_data.gateway = PVSGateway.from_varserver(sys_info)

    async def _refresh_extras(self, now: float) -> None:
        """Best effort and never fails the gateway update: a variable the PVS
        lacks is dropped; any other failure keeps the previous values and ends
        this refresh, so a slow PVS costs one timeout, not one per variable."""
        self._extras_at = now
        for name in EXTRA_VARS:
            try:
                value = await self._read(name, now)
            except PVSError as e:
                _LOGGER.debug("Keeping previous gateway extras: %s", e)
                return
            if value is _MISSING:
                if name in self._unsupported_vars:
                    self._extras.pop(name, None)
            else:
                self._extras[name] = value
