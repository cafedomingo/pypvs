"""Reads the PVS itself as a gateway."""

import logging
import time
from http import HTTPStatus
from typing import Any

from ..api import Match, SysType, Variable
from ..exceptions import PVSCommunicationError, PVSDataFormatError, PVSError
from ..models.gateway import CORE_VARS, PVSGateway, extra_vars
from ..models.pvs import PVSData
from ..models.varserver_coerce import str_var
from .base import Varserver

_LOGGER = logging.getLogger(__name__)

# Extras (network, cloud, battery config, board info) change rarely, so they
# are fetched every few minutes rather than on every poll.
EXTRAS_REFRESH_S = 300
# An empty answer may be a blip; drop the cached value only once it repeats.
EMPTY_REFRESHES_BEFORE_DROP = 3


class PVSGatewayUpdater:
    """Reads the PVS gateway variables, refreshing the extras every few minutes."""

    def __init__(self, pvs: Varserver) -> None:
        self._pvs = pvs
        self._extras: dict[str, Any] = {}
        self._extras_at: float | None = None
        self._storage = False
        # var name -> consecutive refreshes it came back empty
        self._empty_count: dict[str, int] = {}

    async def _read(
        self, names: tuple[str, ...]
    ) -> tuple[dict[str, Any], dict[str, PVSError]]:
        """Read names in one request, falling back to one at a time.

        The PVS rejects a whole batch if any name is unknown. Unreachable or
        login failures raise.
        """
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
        """Read the gateway into pvs_data.gateway."""
        now = time.monotonic()
        sys_info, errors = await self._read(CORE_VARS)
        if errors:  # every core variable is required
            raise next(iter(errors.values()))

        # sys_type reads Unknown for a while after a reboot
        storage = str_var(sys_info, Variable.SYS_TYPE).strip() == SysType.STORAGE
        if (
            self._extras_at is None
            or storage != self._storage
            or now - self._extras_at >= EXTRAS_REFRESH_S
        ):
            self._storage = storage
            names = extra_vars(sys_info[Variable.MODEL], storage)
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
