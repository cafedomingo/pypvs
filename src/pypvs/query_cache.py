"""PVS-side caching of match queries. See doc/Caching.md.

doc/LocalAPI.md: match queries "search the entire varserver name space"; it
is "strongly recommended, particularly when making frequent match or tag
queries, to cache the query". A PVS cache holds the variable names a match
found; reading it returns their current values.
"""

import logging
import re
import time
import zlib
from collections.abc import Awaitable, Callable
from typing import Any

from .const import HTTP_BAD_REQUEST
from .exceptions import PVSCommunicationError

_LOGGER = logging.getLogger(__name__)

#: Default rebuild interval. The cached name set is frozen, so this bounds how
#: long a newly appearing variable stays invisible: at sunrise inverters come
#: back in stages a few minutes apart, and their telemetry only changes every
#: 300 s anyway. With a poll interval at or above this, caching saves nothing.
QUERY_CACHE_TTL_S = 300.0

#: A cache lost this many times in a row, with no good read between, is one the
#: PVS is not keeping: that match is sent plain for UNREADABLE_RETRY_S.
LOSS_LIMIT = 3
UNREADABLE_RETRY_S = 3600.0


def cache_id(match: str) -> str:
    """Deterministic and distinct per match, e.g. "/sys/devices/inverter/" ->
    "pypvs_sys_devices_inverter_<crc32>". Deterministic so several clients
    share one cache per match (re-creating an id replaces it)."""
    slug = "_".join(re.findall(r"[A-Za-z0-9]+", match))
    return f"pypvs_{slug}_{zlib.crc32(match.encode()):08x}"


def _has_values(data: Any) -> bool:
    return isinstance(data, dict) and bool(data.get("values"))


class QueryCache:
    """One state per match: NONE (no record), LIVE (created at a time) or
    PLAIN (until a time).

    - NONE: create (match + cache id). With values -> LIVE. A 400 means
      nothing matches and is raised exactly as a plain match would raise it;
      an empty answer is returned and stays NONE.
    - LIVE and younger than the TTL: read the cache. A 400 (the PVS forgot it,
      e.g. after its nightly restart) or an empty answer is a loss and falls
      through to a create in the same call; any other error is raised and
      stays LIVE. The LOSS_LIMIT-th loss in a row with no good read between
      sends a plain match instead and goes PLAIN for UNREADABLE_RETRY_S.
    - LIVE and at or past the TTL: create again (replaces the PVS cache).
    - PLAIN: plain match; after UNREADABLE_RETRY_S, NONE. One more loss
      before a good read goes back to PLAIN.
    - reset() (probe) sets every LIVE match to NONE. A request in flight
      across it records nothing. Losses and PLAIN describe the PVS and stay.

    A call makes one request, except the one right after a cache was lost,
    which makes two; so polling a match that has nothing (inverters at night)
    costs one request per poll.
    """

    def __init__(
        self,
        request: Callable[[dict[str, str]], Awaitable[Any]],
        ttl_s: float = QUERY_CACHE_TTL_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not ttl_s > 0:
            raise ValueError(f"cache TTL must be positive, got {ttl_s}")
        self._request = request
        self._ttl_s = ttl_s
        self._clock = clock
        self._created: dict[str, float] = {}
        self._losses: dict[str, int] = {}
        self._plain_until: dict[str, float] = {}
        self._warned: set[str] = set()
        self._generation = 0

    def reset(self) -> None:
        self._created.clear()
        self._generation += 1

    async def read(self, match: str) -> Any:
        cid = cache_id(match)
        now = self._clock()
        generation = self._generation
        if now < self._plain_until.get(match, now):
            return await self._request({"match": match})
        created = self._created.get(match)
        if created is not None and now - created < self._ttl_s:
            try:
                data = await self._request({"cache": cid})
            except PVSCommunicationError as err:
                if err.status != HTTP_BAD_REQUEST:
                    raise
                data = None  # the PVS no longer has it
            if _has_values(data):
                self._readable(match)
                return data
            if generation == self._generation and self._lost(match, now):
                return await self._request({"match": match})
        self._created.pop(match, None)
        data = await self._request({"match": match, "cache": cid})
        if _has_values(data) and generation == self._generation:
            self._created[match] = now
        return data

    def _readable(self, match: str) -> None:
        self._losses.pop(match, None)
        if match in self._warned:
            self._warned.discard(match)
            _LOGGER.info("PVS cache for %s is readable again", match)

    def _lost(self, match: str, now: float) -> bool:
        """Count a loss; True if the match goes PLAIN."""
        losses = self._losses.get(match, 0) + 1
        if losses < LOSS_LIMIT:
            self._losses[match] = losses
            return False
        self._losses[match] = LOSS_LIMIT - 1  # a failed trial goes straight back
        self._created.pop(match, None)
        self._plain_until[match] = now + UNREADABLE_RETRY_S
        if match not in self._warned:
            self._warned.add(match)
            _LOGGER.warning(
                "PVS keeps losing the cache for %s; plain matches for %ds",
                match,
                UNREADABLE_RETRY_S,
            )
        return True
