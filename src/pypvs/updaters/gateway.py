import logging
import time
from typing import Any

from ..const import HTTP_BAD_REQUEST, VARS_MATCH_INFO, SupportedFeatures
from ..exceptions import PVSCommunicationError, PVSDataFormatError, PVSError
from ..models.gateway import (
    CORE_VARS,
    EXTRA_VARS,
    OPTIONAL_CORE_VARS,
    PVSGateway,
    interface_vars,
)
from ..models.pvs import PVSData
from .base import PVSUpdater
from .named_reader import UNSUPPORTED_RETRY_S, NamedVarReader

_LOGGER = logging.getLogger(__name__)

# Extras (network, cloud, battery config, board info) change rarely, so they
# are fetched every few minutes rather than on every poll.
EXTRAS_REFRESH_S = 300
# An empty answer may be a blip; drop the cached value only once it repeats.
EMPTY_REFRESHES_BEFORE_DROP = 3

__all__ = ["PVSGatewayUpdater", "EXTRAS_REFRESH_S", "UNSUPPORTED_RETRY_S"]


class PVSGatewayUpdater(PVSUpdater):
    """Class to handle updates for the PVS gateway."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._core = NamedVarReader(
            "core", self._request_var, self._request_named_vars, OPTIONAL_CORE_VARS
        )
        # every extra is optional; the set is per PVS model, so pass it in full
        self._extras_reader = NamedVarReader(
            "extras",
            self._request_var,
            self._request_named_vars,
            EXTRA_VARS + interface_vars(None),
        )
        self._extras: dict[str, Any] = {}
        self._extras_at: float | None = None
        # var name -> consecutive refreshes it came back empty
        self._empty_count: dict[str, int] = {}

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
        now = time.monotonic()
        values, errors = await self._core.read(CORE_VARS, now)
        for name in CORE_VARS:
            if name in values:
                continue
            error = errors.get(name)
            if name not in OPTIONAL_CORE_VARS:
                raise error or PVSDataFormatError(f"The PVS did not return {name}")
            # an optional var may be missing (400) or empty, not failing
            if (
                isinstance(error, PVSCommunicationError)
                and error.status != HTTP_BAD_REQUEST
            ):
                raise error
        sys_info: dict[str, Any] = dict(values)

        if self._extras_at is None or now - self._extras_at >= EXTRAS_REFRESH_S:
            model = sys_info.get("/sys/info/model")
            await self._refresh_extras(now, EXTRA_VARS + interface_vars(model))

        sys_info.update(self._extras)
        pvs_data.raw[VARS_MATCH_INFO] = sys_info
        pvs_data.gateway = PVSGateway.from_varserver(sys_info)

    async def _refresh_extras(self, now: float, names: tuple[str, ...]) -> None:
        """Best effort and never fails the gateway update. A variable the PVS
        lacks (400) is dropped; one that keeps answering empty is dropped after
        a few refreshes; any other error keeps its last value. If the PVS is
        unreachable (or the login fails) every last value is kept until the next
        refresh."""
        self._extras_at = now
        try:
            values, errors = await self._extras_reader.read(names, now)
        except PVSError as e:  # unreachable, login failed, ...
            _LOGGER.debug("Keeping previous gateway extras: %s", e)
            return
        for name in names:
            if name in values:
                self._extras[name] = values[name]
                self._empty_count.pop(name, None)
            elif self._extras_reader.is_unsupported(name, now):
                self._extras.pop(name, None)
            elif isinstance(errors.get(name), PVSDataFormatError):
                empties = self._empty_count.get(name, 0) + 1
                self._empty_count[name] = empties
                if empties >= EMPTY_REFRESHES_BEFORE_DROP:
                    self._extras.pop(name, None)
            elif name in errors:
                _LOGGER.debug("Keeping last value of %s: %s", name, errors[name])
