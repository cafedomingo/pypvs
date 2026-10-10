# How pypvs keeps load on the PVS down

[LocalAPI.md](LocalAPI.md) says match queries "search the entire varserver
name space", that it is "strongly recommended, particularly when making
frequent match or tag queries, to cache the query", and not to query "faster
than once every few seconds ... particularly ... on SunVault systems". pypvs
does two things about that.

## Named reads in one request

The gateway updater reads its `/sys/info` variables (and, every five minutes,
the network, cloud and battery-config extras) with one `name=a,b,...` request
each instead of one request per variable. The PVS rejects the whole list if
one name is unknown, so `NamedVarReader` (src/pypvs/updaters/named_reader.py)
falls back to single reads, learns which names the PVS lacks, and stops
batching if batches keep failing. Its docstring lists the rules; each has a
test.

## PVS-side query caches

The device updaters (inverters, meters, ESS, transfer switch) poll with match
queries. `QueryCache` (src/pypvs/query_cache.py) runs each match once with a
cache id and afterwards reads the cache:

```
create:  /vars?match=/sys/devices/meter/&cache=pypvs_sys_devices_meter_<crc32>
read:    /vars?cache=pypvs_sys_devices_meter_<crc32>
```

A cache holds the variable names; a read returns their current values.

### States

One state per match: NONE (no record), LIVE (created at a time) or PLAIN
(until a time).

| State | Request | Outcome | Next |
|---|---|---|---|
| NONE | create | values | LIVE |
| NONE | create | 400: nothing matches (inverters at night) | NONE, raised like a plain match |
| NONE | create | empty, or another error | NONE, returned / raised |
| LIVE, younger than the TTL | read | values | LIVE |
| LIVE, younger than the TTL | read | 400 (the PVS forgot it) or empty | create in the same call |
| LIVE, younger than the TTL | read | the same, for the 3rd time with no good read between | plain match in the same call, PLAIN for an hour |
| LIVE, younger than the TTL | read | another error | LIVE, raised |
| LIVE, TTL reached | create | as NONE | |
| PLAIN | plain match | as a plain match | NONE once the hour is up; one more loss before a good read returns to PLAIN |

`probe()` sets every LIVE match to NONE and keeps losses and PLAIN, which
describe the PVS; a request in flight across it records nothing. Changing
`host` forgets everything, PLAIN included. A call makes one
request, except right after a cache was lost (read, then create), so a match
with nothing behind it costs one request per poll. PLAIN keeps a PVS that
accepts caches but will not serve them from costing two requests per poll.

### What was checked on a PVS6 with SunVault

- Cached reads return the same live values as the match; under load a read
  took 28 ms against 142 ms for the match.
- Re-creating an id replaces the cache; caches are shared across login
  sessions, so several clients using the same deterministic id share one.
- An empty match answers 400 (0x0040) and creates no cache; so does a read of
  an unknown id.
- The PVS restarts around 00:15 local time and forgets every cache; it lists no
  inverters until they report at sunrise, in stages a few minutes apart.

Not seen live: what a read answers once some of the cached names are gone.
Names only disappeared in the restart, which also forgets the caches, so a 400
and an empty answer are both treated as a lost cache.

### TTL

`PVS(query_cache_ttl_s=300)`. The cache freezes the name set, so the TTL is
how long a variable that appears later stays invisible: an inverter waking a
few minutes after the others shows up within five minutes, which is also how
often inverter telemetry changes. With a poll interval at or above the TTL,
caching saves nothing. `query_cache_ttl_s=None` turns caching off; the TTL
must otherwise be positive.

Clients share a cache, so a client re-creating it sets the names the others
read: one that re-creates while an inverter is briefly missing hides it from
the others too, until their own TTL runs out.

### Opting in

The device updaters use the cache through `request_cached_vars`;
`PVS.getVarserverVars(match)` stays a plain match unless called with
`cache=True`. Opt in only for matches you poll: each leaves one cache on the
PVS until its next restart.
