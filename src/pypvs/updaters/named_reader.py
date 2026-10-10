"""Read several named varserver variables, in one request when possible."""

import logging
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from ..const import HTTP_BAD_REQUEST
from ..exceptions import PVSCommunicationError, PVSDataFormatError, PVSError

_LOGGER = logging.getLogger(__name__)

# The PVS answers 400 for a variable it doesn't have. That can be temporary
# (services still starting, a battery commissioned later), so ask again later.
UNSUPPORTED_RETRY_S = 3600
# Stop batching after this many batches in a row had to fall back.
BATCH_FAILURES_BEFORE_GIVING_UP = 3


class NamedVarReader:
    """Reads named variables with as few requests as the PVS allows.

    The PVS takes a comma-separated name list but rejects the whole request
    with 400 if any name is unknown, so:

    - names not known to be unsupported are requested in one batch;
    - if the batch is rejected (400 or a server error) or malformed, they are
      read one by one; a name the PVS answers 400 for on its own is unknown,
      and if optional it is left out of later batches and retried alone after
      UNSUPPORTED_RETRY_S; required names are never left out;
    - if the batch answers 200 but leaves names out, only those are read alone;
    - after BATCH_FAILURES_BEFORE_GIVING_UP fallbacks in a row, batching stops
      (logged once) and a single batch is tried again every UNSUPPORTED_RETRY_S;
    - an unreachable PVS (no HTTP status) raises; other per-name failures are
      returned for the caller to judge.
    """

    def __init__(
        self,
        kind: str,
        request_var: Callable[[str], Awaitable[Any]],
        request_named_vars: Callable[[list[str]], Awaitable[dict[str, Any]]] | None,
        optional: Iterable[str] = (),
    ) -> None:
        self._kind = kind
        self._request_var = request_var
        self._request_named_vars = request_named_vars
        self._optional = frozenset(optional)
        #: optional var name -> monotonic time the PVS answered 400 for it
        self.unsupported: dict[str, float] = {}
        self._failures = 0
        self._off_at: float | None = None
        self._logged = False

    def is_unsupported(self, name: str, now: float) -> bool:
        marked = self.unsupported.get(name)
        return marked is not None and now - marked < UNSUPPORTED_RETRY_S

    async def read(
        self, names: Iterable[str], now: float
    ) -> tuple[dict[str, Any], dict[str, PVSError]]:
        """Return (values, errors) for `names`. Names currently unsupported are
        in neither. Raises PVSCommunicationError when the PVS is unreachable."""
        names = list(names)
        known = [n for n in names if n not in self.unsupported]
        retry = [
            n
            for n in names
            if n in self.unsupported and not self.is_unsupported(n, now)
        ]
        values: dict[str, Any] = {}
        errors: dict[str, PVSError] = {}

        batch = await self._batch(known, now)
        if batch is not None:
            values.update({n: batch[n] for n in known if n in batch})
        singles = [n for n in known if n not in values] + retry

        for name in singles:
            try:
                values[name] = await self._request_var(name)
            except PVSCommunicationError as e:
                if e.status is None:
                    raise
                errors[name] = e
                if e.status == HTTP_BAD_REQUEST and name in self._optional:
                    _LOGGER.debug("PVS does not support %s", name)
                    self.unsupported[name] = now
                continue
            except PVSDataFormatError as e:
                errors[name] = e  # answered, but without a value
                continue
            self.unsupported.pop(name, None)
        return values, errors

    async def _batch(self, names: list[str], now: float) -> dict[str, Any] | None:
        if self._request_named_vars is None or not names:
            return None
        if self._off_at is not None:
            if now - self._off_at < UNSUPPORTED_RETRY_S:
                return None
            self._off_at = None  # try one batch; a failure turns it off again
        try:
            values: dict[str, Any] | None = await self._request_named_vars(names)
        except PVSDataFormatError:
            values = None
        except PVSCommunicationError as e:
            if e.status is None:
                raise
            values = None
        if values is not None and all(n in values for n in names):
            self._failures = 0
            return values
        self._failures += 1
        if self._failures >= BATCH_FAILURES_BEFORE_GIVING_UP:
            self._off_at = now
            if not self._logged:
                _LOGGER.info(
                    "Batched %s reads keep failing; reading one by one", self._kind
                )
                self._logged = True
        return values
