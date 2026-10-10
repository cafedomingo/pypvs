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

_LOGGER = logging.getLogger(__name__)

# Extras (network, cloud, battery config, board info) change rarely, so they
# are fetched every few minutes rather than on every poll.
EXTRAS_REFRESH_S = 300
# The PVS answers 400 for a variable it doesn't have. That can be temporary
# (services still starting, a battery commissioned later), so ask again later.
UNSUPPORTED_RETRY_S = 3600
# Stop batching after this many batches in a row had to fall back.
BATCH_FAILURES_BEFORE_GIVING_UP = 3
# An empty answer may be a blip; drop the cached value only once it repeats.
EMPTY_REFRESHES_BEFORE_DROP = 3

_MISSING = object()


class PVSGatewayUpdater(PVSUpdater):
    """Class to handle updates for the PVS gateway."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # var name -> monotonic time the PVS answered 400 for it
        self._unsupported_vars: dict[str, float] = {}
        self._extras: dict[str, Any] = {}
        self._extras_at: float | None = None
        # var name -> consecutive refreshes it came back empty
        self._empty_count: dict[str, int] = {}
        # per batch kind ("core", "extras"): consecutive fallbacks, and when
        # batching was given up (it is tried again after UNSUPPORTED_RETRY_S)
        self._batch_failures: dict[str, int] = {}
        self._batching_off_at: dict[str, float] = {}

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
            if e.status != HTTP_BAD_REQUEST:
                raise
            _LOGGER.debug("PVS does not support %s", name)
            self._unsupported_vars[name] = now
            return _MISSING
        self._unsupported_vars.pop(name, None)
        return value

    def _split(self, names: tuple[str, ...], now: float) -> tuple[list[str], list[str]]:
        """(known, retry): names never found unsupported, which can be read in
        one batch, and unsupported ones due another try, which are read one by
        one so a still-missing name can't sink the batch."""
        known, retry = [], []
        for name in names:
            marked = self._unsupported_vars.get(name)
            if marked is None:
                known.append(name)
            elif now - marked >= UNSUPPORTED_RETRY_S:
                retry.append(name)
        return known, retry

    def _batch_failed(self, kind: str, now: float) -> None:
        failures = self._batch_failures.get(kind, 0) + 1
        self._batch_failures[kind] = failures
        if failures == BATCH_FAILURES_BEFORE_GIVING_UP:
            _LOGGER.info("Batched %s reads keep failing; reading one by one", kind)
            self._batching_off_at[kind] = now

    async def _read_batch(
        self, kind: str, names: list[str], now: float
    ) -> dict[str, Any] | None:
        """Read `names` in one request. Returns None when the batch can't be
        used: no batch reader, batching given up on for now, the PVS rejected
        it (400 for an unknown name, or a server error), or the answer was
        malformed. The caller then reads the names one by one, which also
        records unknown ones. Only an unreachable PVS (no HTTP status) raises.
        """
        off_at = self._batching_off_at.get(kind)
        if off_at is not None:
            if now - off_at < UNSUPPORTED_RETRY_S:
                return None
            del self._batching_off_at[kind]
            self._batch_failures[kind] = 0
        if self._request_named_vars is None or not names:
            return None
        try:
            values = await self._request_named_vars(names)
        except PVSDataFormatError:
            values = None
        except PVSCommunicationError as e:
            if e.status is None:
                raise
            values = None
        if values is None:
            self._batch_failed(kind, now)
        else:
            self._batch_failures[kind] = 0
        return values

    async def update(self, pvs_data: PVSData) -> None:
        """Update the PVS for this updater."""
        now = time.monotonic()
        sys_info: dict[str, Any] = {}

        # one request for the known names; one by one when the batch fails
        # or leaves out a required name, and for retries
        known, retry = self._split(CORE_VARS, now)
        batch = await self._read_batch("core", known, now)
        if batch is not None:
            sys_info.update(batch)
            # a 200 that left a name out: keep the rest, read the gaps alone
            singles = [n for n in known if n not in batch] + retry
        else:
            singles = known + retry
        for name in singles:
            if name in OPTIONAL_CORE_VARS:
                value = await self._read(name, now)
                if value is not _MISSING:
                    sys_info[name] = value
            else:
                sys_info[name] = await self._request_var(name)

        if self._extras_at is None or now - self._extras_at >= EXTRAS_REFRESH_S:
            model = sys_info.get("/sys/info/model")
            await self._refresh_extras(now, EXTRA_VARS + interface_vars(model))

        sys_info.update(self._extras)
        pvs_data.raw[VARS_MATCH_INFO] = sys_info
        pvs_data.gateway = PVSGateway.from_varserver(sys_info)

    async def _refresh_extras(self, now: float, names: tuple[str, ...]) -> None:
        """Best effort and never fails the gateway update. A variable the PVS
        lacks (400) is dropped; one that keeps answering empty is dropped after
        a few refreshes; any other error skips just that variable, keeping its
        last value. Names are read in one batch when possible and one by one
        otherwise. Only an unreachable PVS (no HTTP status) ends the refresh
        early, so a slow PVS costs one timeout rather than one per variable."""
        self._extras_at = now
        known, retry = self._split(names, now)
        try:
            batch = await self._read_batch("extras", known, now)
        except PVSError as e:
            _LOGGER.debug("Keeping previous gateway extras: %s", e)
            return
        if batch is not None:
            for name in known:
                self._record_extra(name, batch.get(name, _MISSING))
            singles = retry
        else:
            singles = known + retry
        for name in singles:
            try:
                value = await self._read(name, now)
            except PVSCommunicationError as e:
                if e.status is None:
                    _LOGGER.debug("PVS unreachable; keeping gateway extras: %s", e)
                    return
                _LOGGER.debug("Keeping last value of %s: %s", name, e)
                continue
            except PVSError as e:
                _LOGGER.debug("Keeping last value of %s: %s", name, e)
                continue
            self._record_extra(name, value)

    def _record_extra(self, name: str, value: Any) -> None:
        if value is not _MISSING:
            self._extras[name] = value
            self._empty_count.pop(name, None)
        elif name in self._unsupported_vars:
            self._extras.pop(name, None)
        else:
            empties = self._empty_count.get(name, 0) + 1
            self._empty_count[name] = empties
            if empties >= EMPTY_REFRESHES_BEFORE_DROP:
                self._extras.pop(name, None)
