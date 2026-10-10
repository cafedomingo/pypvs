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
# Stop batching after this many rejected or malformed batches in a row.
BATCH_FAILURES_BEFORE_GIVING_UP = 3


class NamedVarReader:
    """Reads named variables with as few requests as the PVS allows.

    The PVS takes a comma-separated name list but rejects the whole request
    with 400 if any name is unknown. Rules:

    1. Names not known to be unsupported are requested in one batch.
    2. A batch rejected with an HTTP error status, or malformed, falls back to
       reading the names one by one. A 200 that leaves names out still counts
       as a working batch; only the missing names are read alone.
    3. After BATCH_FAILURES_BEFORE_GIVING_UP rejected or malformed batches in
       a row, batching stops (logged once); one batch is tried every
       UNSUPPORTED_RETRY_S and a success turns it back on.
    4. A name that answers 400 on its own is unknown. An optional one is left
       out and retried alone every UNSUPPORTED_RETRY_S; a retry that fails in
       any way keeps it out for another period. Required names are never left
       out.
    5. Per-name HTTP errors and empty answers are collected per name. Any
       other error (PVS unreachable, login failed) stops reading; it is
       recorded for the name being read and every name not yet read, and the
       values already read are kept.
    6. A strict reader raises instead of returning when a required name has
       no value, or an optional one failed with anything but a 400 or an empty
       answer.
    """

    def __init__(
        self,
        kind: str,
        request_var: Callable[[str], Awaitable[Any]],
        request_named_vars: Callable[[list[str]], Awaitable[dict[str, Any]]] | None,
        optional: Iterable[str] = (),
        strict: bool = False,
    ) -> None:
        self._kind = kind
        self._request_var = request_var
        self._request_named_vars = request_named_vars
        self._optional = frozenset(optional)
        self._strict = strict
        #: optional var name -> monotonic time it was last found unsupported
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
        """Return (values, errors) for `names`. Names currently left out as
        unsupported are in neither. See the class docstring for the rules."""
        names = list(names)
        known = [n for n in names if n not in self.unsupported]
        retry = [
            n
            for n in names
            if n in self.unsupported and not self.is_unsupported(n, now)
        ]
        values: dict[str, Any] = {}
        errors: dict[str, PVSError] = {}

        try:
            batch = await self._batch(known, now)
        except PVSError as e:  # rule 5: nothing could be read
            errors.update({n: e for n in known + retry})
            return self._finish(names, values, errors)
        if batch is not None:
            values.update({n: batch[n] for n in known if n in batch})
        singles = [n for n in known if n not in values] + retry

        for i, name in enumerate(singles):
            try:
                values[name] = await self._request_var(name)
            except PVSDataFormatError as e:
                errors[name] = e  # answered, but without a value
            except PVSCommunicationError as e:
                if e.status is None:  # rule 5
                    errors.update({n: e for n in singles[i:]})
                    break
                errors[name] = e
                if name in self._optional and (
                    e.status == HTTP_BAD_REQUEST or name in self.unsupported
                ):
                    _LOGGER.debug("PVS does not support %s", name)
                    self.unsupported[name] = now  # rule 4
            except PVSError as e:  # rule 5: login failed, ...
                errors.update({n: e for n in singles[i:]})
                break
            else:
                self.unsupported.pop(name, None)
        return self._finish(names, values, errors)

    def _finish(
        self, names: list[str], values: dict[str, Any], errors: dict[str, PVSError]
    ) -> tuple[dict[str, Any], dict[str, PVSError]]:
        if self._strict:  # rule 6
            for name in names:
                if name in values:
                    continue
                error = errors.get(name)
                if name not in self._optional:
                    raise error or PVSDataFormatError(f"The PVS did not return {name}")
                if error is not None and not (
                    isinstance(error, PVSDataFormatError)
                    or getattr(error, "status", None) == HTTP_BAD_REQUEST
                ):
                    raise error
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
        if values is not None:  # rule 2: a partial 200 still works
            self._failures = 0
            return values
        self._failures += 1  # rule 3
        if self._failures >= BATCH_FAILURES_BEFORE_GIVING_UP:
            self._off_at = now
            if not self._logged:
                _LOGGER.info(
                    "Batched %s reads keep failing; reading one by one", self._kind
                )
                self._logged = True
        return None
