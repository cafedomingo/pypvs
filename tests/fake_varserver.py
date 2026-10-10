"""A varserver that behaves like the PVS6 did when checked live:

- match=M (+ cache=ID): names containing M; none -> 400 (0x0040). With an id,
  the names are recorded as that cache, replacing any cache with that id.
- cache=ID alone: unknown id -> 400 (0x0040); else the recorded names' current
  values (names that no longer exist are dropped).
- caches are shared across sessions; restart() forgets them all and, like the
  nightly restart, removes every inverter variable until sunrise().
"""

from __future__ import annotations

from pypvs.exceptions import PVSCommunicationError

INVERTER = "/sys/devices/inverter/"


def inverter_vars(serials):
    out = {}
    for i, sn in enumerate(serials):
        out[f"{INVERTER}{i}/sn"] = sn
        out[f"{INVERTER}{i}/p3phsumKw"] = "0.25"
    return out


METER = {
    "/sys/devices/meter/0/sn": "PVS6M1p",
    "/sys/devices/meter/0/p3phsumKw": "1.5",
}


class FakeVarserver:
    def __init__(self, variables, stale_reads_empty=False):
        self.vars = dict(variables)
        self.caches: dict[str, list[str]] = {}
        self.requests: list[dict] = []
        self.stale_reads_empty = stale_reads_empty
        self._fail_next: Exception | None = None

    def fail_next(self, error: Exception) -> None:
        self._fail_next = error

    def restart(self) -> None:
        self.caches.clear()
        self.vars = {k: v for k, v in self.vars.items() if not k.startswith(INVERTER)}

    def sunrise(self, serials) -> None:
        self.vars.update(inverter_vars(serials))

    def _answer(self, names):
        return {
            "count": len(names),
            "values": [{"name": n, "value": self.vars[n]} for n in names],
        }

    async def handle(self, params):
        self.requests.append(dict(params))
        if self._fail_next is not None:
            error, self._fail_next = self._fail_next, None
            raise error
        if "match" in params:
            names = [n for n in self.vars if params["match"] in n]
            if not names:
                raise PVSCommunicationError("HTTP 400: 0x0040", status=400)
            if "cache" in params:
                self.caches[params["cache"]] = names
            return self._answer(names)
        if "cache" in params:
            names = self.caches.get(params["cache"])
            if names is None:
                raise PVSCommunicationError("HTTP 400: 0x0040", status=400)
            alive = [n for n in names if n in self.vars]
            if not alive and self.stale_reads_empty:
                return {"count": 0, "values": []}
            if not alive:
                raise PVSCommunicationError("HTTP 400: 0x0040", status=400)
            return self._answer(alive)
        if "name" in params:
            names = params["name"].split(",")
            if any(n not in self.vars for n in names):
                raise PVSCommunicationError("HTTP 400: 0x0100", status=400)
            return self._answer(names)
        raise AssertionError(f"unexpected request {params}")

    async def get_varserver(self, endpoint, params=None):
        return await self.handle(params)

    def kinds(self):
        """Each request as 'create', 'read', 'match' or 'name'."""
        out = []
        for r in self.requests:
            if "match" in r:
                out.append("create" if "cache" in r else "match")
            elif "cache" in r:
                out.append("read")
            else:
                out.append("name")
        return out
