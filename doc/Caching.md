# How pypvs keeps load on the PVS down

The PVS's [local API docs](LocalAPI.md) say match queries "search the entire
varserver name space", recommend caching frequent ones, and warn against
polling faster than every few seconds, especially on SunVault systems where the
CPU is already busy. pypvs follows that with three mechanisms.

## 1. Cached match queries (`PVS.getVarserverVars`)

The device updaters (inverters, meters, ESS, transfer switch) read their
groups with match queries, and so does any caller of `getVarserverVars` (a
metrics exporter polling `/sys/livedata`, say). The first query for a match is
plain, so one-off queries leave nothing behind on the PVS. From the second on,
pypvs creates a PVS-side cache once and afterwards only reads it:

```
first:       /vars?match=/sys/devices/meter/
second:      /vars?match=/sys/devices/meter/&cache=pypvs_sys_devices_meter_<crc32>
afterwards:  /vars?cache=pypvs_sys_devices_meter_<crc32>
```

A PVS cache holds the **set of variable names** the match found; reading it
returns their **current values**. On a PVS6 with SunVault a cache read took
about 28 ms against 142 ms for the match.

Because the name set is frozen, the cache is rebuilt:

| When | Why |
|---|---|
| every `QUERY_CACHE_TTL_S` (5 min) | pick up devices that appeared, e.g. inverters waking one by one at sunrise |
| on a full `probe()` (`reset_query_caches()`) | probing must see the PVS as it is now, not an old name set |
| on an inverter re-probe, the inverter cache only | inverters are what's in doubt; the meter, ESS and transfer-switch caches stay |
| when a cache read answers 400 | the PVS forgets all caches when it restarts (it does so nightly, around 00:15 local) |
| when a cache read comes back empty | the devices behind it vanished |
| when the host changes | the caches, and whether `cache=` works, belong to another PVS |

Re-creating a cache id that already exists simply replaces it (checked on a
PVS6). An answer to `match+cache` with no values creates no cache, so it costs
the same as an uncached match.

The PVS answers 400 both for "nothing matches" (inverters asleep after the
nightly restart) and, possibly, for a firmware that rejects `cache=`. Until a
cache has been created once, a 400 on `match+cache` is followed by a plain
match to tell the two apart: if the plain match works, that match is marked
uncacheable (cleared again on the next probe); if it also answers 400, nothing
matches and the error is raised as an uncached match would. Once any cache has
worked, a 400 simply means nothing matches, so a night-time inverter query
costs one request, not two.

Cache ids are `pypvs_<slug>_<crc32 of the match>`, so different matches get
their own cache and other clients' caches are left alone. Each distinct match
used more than once leaves one cache on the PVS until it restarts. Caching can
be turned off with `PVS(..., use_query_cache=False)`.

## 2. Batched named reads (`PVS.getVarserverVarsByName`)

The gateway updater reads ten `/sys/info` and related variables, which used to
be ten requests. The API takes a comma-separated list
(`/vars?name=/sys/info/sw_rev,/sys/info/uptime,...`), so they are one request
now; on a PVS6 that halved the time (about 1.5 s to 0.8 s).

The PVS rejects the **whole** request with 400 if any name is unknown. So:

- names are split into *known* (never seen unsupported), batched together, and
  *retry* (seen unsupported, due another try), read one by one so a name that
  is still missing can't sink the batch;
- when a batch fails (400, server error, malformed answer), the names are read
  one by one, which records any unknown name so later batches leave it out; a
  200 that leaves a name out keeps the rest and reads just the gap;
- the core and extras batches are tracked separately: after three fallbacks in
  a row one of them stops batching (logged once) and tries again after an
  hour.

`PVSUpdater` takes an optional `request_named_vars`; updaters that don't use it
are unaffected.

## 3. Gateway extras on a slower cadence

Network state, cloud/cell flags, battery reserve and mode, board and firmware
info change rarely, so the gateway updater refreshes them every
`EXTRAS_REFRESH_S` (5 min) and serves the cached values in between. They are
best effort and never fail an update:

- a variable the PVS lacks (400) is dropped and asked for again after
  `UNSUPPORTED_RETRY_S` (1 h), since a battery can be commissioned later;
- an empty answer keeps the last value until it has been empty for three
  refreshes in a row, so a blip doesn't flap the value;
- any other error keeps the last value; only an unreachable PVS (no HTTP
  status) ends the refresh early, so a slow PVS costs one timeout, not one per
  variable.

## Behaviour around the nightly restart

The PVS restarts itself around 00:15 local time. Afterwards it has no
`/sys/devices/inverter/` variables at all until the microinverters report
again at sunrise, so inverter queries answer 400. pypvs treats an empty or
missing inverter answer as "not found" and re-probes with backoff (60 s up to
30 min); the probe rebuilds the caches, and the 5-minute cache rebuild picks up
inverters that report later than the first ones.
