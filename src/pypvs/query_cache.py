"""PVS-side caching of match queries. See doc/Caching.md.

doc/LocalAPI.md: match queries "search the entire varserver name space"; it
is "strongly recommended, particularly when making frequent match or tag
queries, to cache the query". A PVS cache holds the variable names a match
found; reading it returns their current values.
"""

import re
import time
import zlib
from collections.abc import Awaitable, Callable
from typing import Any

from .const import HTTP_BAD_REQUEST
from .exceptions import PVSCommunicationError

#: Default rebuild interval. The cached name set is frozen, so this bounds how
#: long a newly appearing variable stays invisible: at sunrise inverters come
#: back in stages a few minutes apart, and their telemetry only changes every
#: 300 s anyway. With a poll interval at or above this, caching saves nothing.
QUERY_CACHE_TTL_S = 300.0


def cache_id(match: str) -> str:
    """Deterministic and distinct per match, e.g. "/sys/devices/inverter/" ->
    "pypvs_sys_devices_inverter_<crc32>". Deterministic so several clients
    share one cache per match (re-creating an id replaces it)."""
    slug = "_".join(re.findall(r"[A-Za-z0-9]+", match))
    return f"pypvs_{slug}_{zlib.crc32(match.encode()):08x}"


def _has_values(data: Any) -> bool:
    return isinstance(data, dict) and bool(data.get("values"))


class QueryCache:
    """One state per match: NONE (no record) or LIVE (created at a time).

    - NONE: create (match + cache id). With values -> LIVE. A 400 means
      nothing matches and is raised exactly as a plain match would raise it;
      an empty answer is returned and stays NONE.
    - LIVE and younger than the TTL: read the cache. A 400 (the PVS forgot it,
      e.g. after its nightly restart) or an empty answer falls through to a
      create in the same call; any other error is raised and stays LIVE.
    - LIVE and at or past the TTL: create again (replaces the PVS cache).
    - reset() forgets every record (probe, host change).

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
        self._request = request
        self._ttl_s = ttl_s
        self._clock = clock
        self._created: dict[str, float] = {}

    def reset(self) -> None:
        self._created.clear()

    async def read(self, match: str) -> Any:
        cid = cache_id(match)
        now = self._clock()
        created = self._created.get(match)
        if created is not None and now - created < self._ttl_s:
            try:
                data = await self._request({"cache": cid})
            except PVSCommunicationError as err:
                if err.status != HTTP_BAD_REQUEST:
                    raise
                data = None  # the PVS no longer has it
            if _has_values(data):
                return data
        self._created.pop(match, None)
        data = await self._request({"match": match, "cache": cid})
        if _has_values(data):
            self._created[match] = now
        return data
