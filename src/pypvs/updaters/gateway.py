import logging
import time
from typing import Any

from ..const import VARS_MATCH_INFO, SupportedFeatures
from ..exceptions import PVSCommunicationError, PVSDataFormatError
from ..models.gateway import (
    CORE_VARS,
    EXTRA_VARS,
    NET_MATCH,
    OPTIONAL_CORE_VARS,
    PVSGateway,
)
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

    def _skip(self, name: str, now: float) -> bool:
        marked = self._unsupported_vars.get(name)
        return marked is not None and now - marked < UNSUPPORTED_RETRY_S

    async def update(self, pvs_data: PVSData) -> None:
        """Update the PVS for this updater."""
        now = time.monotonic()
        sys_info: dict[str, Any] = {}

        # individual vars rather than a match, as the match takes a long time
        for name in CORE_VARS:
            if self._skip(name, now):
                continue
            try:
                sys_info[name] = await self._request_var(name)
            except PVSCommunicationError as e:
                if name not in OPTIONAL_CORE_VARS or e.status != HTTP_BAD_REQUEST:
                    raise
                _LOGGER.debug("PVS does not support %s", name)
                self._unsupported_vars[name] = now

        if self._extras_at is None or now - self._extras_at >= EXTRAS_REFRESH_S:
            await self._refresh_extras(now)

        sys_info.update(self._extras)
        pvs_data.raw[VARS_MATCH_INFO] = sys_info
        pvs_data.gateway = PVSGateway.from_varserver(sys_info)

    async def _refresh_extras(self, now: float) -> None:
        """Best effort: a failure keeps the previous value rather than failing
        the gateway update."""
        for name in EXTRA_VARS:
            if self._skip(name, now):
                continue
            try:
                self._extras[name] = await self._request_var(name)
                self._unsupported_vars.pop(name, None)
            except PVSCommunicationError as e:
                if e.status == HTTP_BAD_REQUEST:
                    _LOGGER.debug("PVS does not support %s", name)
                    self._unsupported_vars[name] = now
                    self._extras.pop(name, None)
                else:
                    _LOGGER.debug("Keeping last value of %s: %s", name, e)
            except PVSDataFormatError:
                self._extras.pop(name, None)  # answered, but with no value

        if not self._skip(NET_MATCH, now):
            try:
                states = await self._request_vars(NET_MATCH)
            except PVSCommunicationError as e:
                if e.status == HTTP_BAD_REQUEST:
                    self._unsupported_vars[NET_MATCH] = now
                    states = {}
                else:
                    states = None  # keep the previous states
            except PVSDataFormatError:
                states = {}
            if states is not None:
                self._extras = {
                    k: v for k, v in self._extras.items() if not k.startswith(NET_MATCH)
                }
                self._extras.update(states)

        self._extras_at = now
