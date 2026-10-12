import logging
import time
from http import HTTPStatus
from typing import Any

from ..api import Match, Variable
from ..const import SupportedFeatures
from ..exceptions import PVSCommunicationError, PVSDataFormatError, PVSError
from ..models.gateway import CORE_VARS, PVSGateway, extra_vars
from ..models.pvs import PVSData
from .base import PVSUpdater, Varserver

_LOGGER = logging.getLogger(__name__)

# Extras (network, cloud, battery config, board info) change rarely, so they
# are fetched every few minutes rather than on every poll.
EXTRAS_REFRESH_S = 300
# An empty answer may be a blip; drop the cached value only once it repeats.
EMPTY_REFRESHES_BEFORE_DROP = 3


class PVSGatewayUpdater(PVSUpdater):
    """Class to handle updates for the PVS gateway."""

    def __init__(self, pvs: Varserver) -> None:
        super().__init__(pvs)
        self._extras: dict[str, Any] = {}
        self._extras_at: float | None = None
        self._has_ess = False
        # var name -> consecutive refreshes it came back empty
        self._empty_count: dict[str, int] = {}

    async def probe(
        self, discovered_features: SupportedFeatures
    ) -> SupportedFeatures | None:
        """Probe the PVS for this updater and return SupportedFeatures."""

        # This updater is always available
        _LOGGER.debug("Probing PVS for gateway data. It is aways available.")
        self._has_ess = bool(discovered_features & SupportedFeatures.ESS)
        self._supported_features |= SupportedFeatures.GATEWAY
        return self._supported_features

    async def _read(
        self, names: tuple[str, ...]
    ) -> tuple[dict[str, Any], dict[str, PVSError]]:
        """The PVS rejects a whole batch if any name is unknown, so fall back
        to single reads. Unreachable or login failures raise."""
        batch: dict[str, Any] = {}
        batch_error: PVSError | None = None
        try:
            batch = await self._pvs.getVarserverVarsByName(list(names))
        except (PVSCommunicationError, PVSDataFormatError) as e:
            if isinstance(e, PVSCommunicationError) and e.status is None:
                raise
            batch_error = e
        values = {n: batch[n] for n in names if n in batch}
        errors: dict[str, PVSError] = {}
        for name in names:
            if name in values:
                continue
            try:
                values[name] = await self._pvs.getVarserverVar(name)
            except PVSDataFormatError as e:
                errors[name] = e
            except PVSCommunicationError as e:
                if e.status is None:
                    raise
                errors[name] = e
        if batch_error is not None:
            _LOGGER.warning(
                "Batched read of %d variables failed (%s); read one by one, "
                "these failed on their own too: %s",
                len(names),
                batch_error,
                ", ".join(errors) or "none",
            )
        return values, errors

    async def update(self, pvs_data: PVSData) -> None:
        """Update the PVS for this updater."""
        now = time.monotonic()
        sys_info, errors = await self._read(CORE_VARS)
        if errors:  # every core variable is required
            raise next(iter(errors.values()))

        if self._extras_at is None or now - self._extras_at >= EXTRAS_REFRESH_S:
            names = extra_vars(sys_info[Variable.MODEL], self._has_ess)
            await self._refresh_extras(now, names)

        sys_info.update(self._extras)
        pvs_data.raw[Match.INFO] = sys_info
        pvs_data.gateway = PVSGateway.from_varserver(sys_info)

    async def _refresh_extras(self, now: float, names: tuple[str, ...]) -> None:
        """Best effort: never fails the gateway update."""
        self._extras_at = now
        try:
            values, errors = await self._read(names)
        except PVSError as e:
            _LOGGER.debug("Keeping last gateway extras: %s", e)
            return
        for name in names:
            error = errors.get(name)
            if name in values:
                self._extras[name] = values[name]
                self._empty_count.pop(name, None)
            elif isinstance(error, PVSDataFormatError):
                empties = self._empty_count.get(name, 0) + 1
                self._empty_count[name] = empties
                if empties >= EMPTY_REFRESHES_BEFORE_DROP:
                    self._extras.pop(name, None)
            elif (
                isinstance(error, PVSCommunicationError)
                and error.status == HTTPStatus.BAD_REQUEST
            ):
                self._extras.pop(name, None)
            else:
                _LOGGER.debug("Keeping last value of %s: %s", name, error)
