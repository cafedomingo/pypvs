import logging
import re
import time
import zlib
from collections.abc import Callable
from typing import Any

import aiohttp

from .const import HTTP_BAD_REQUEST, VAR_UPTIME, SupportedFeatures
from .exceptions import (
    PVSAuthenticationError,
    PVSCommunicationError,
    PVSDataFormatError,
    PVSError,
    PVSProbeFailed,
)
from .firmware import PVSFirmware
from .models.common import CommonProperties
from .models.pvs import PVSData
from .pvs_fcgi import PVSFCGIClient, PVSFCGIClientLoginError, PVSFCGIClientPostError
from .pvs_websocket import PVSWebSocket
from .updaters.base import PVSUpdater
from .updaters.ess import PVSESSUpdater
from .updaters.gateway import PVSGatewayUpdater
from .updaters.meter import PVSProductionMetersUpdater
from .updaters.production_inverters import PVSProductionInvertersUpdater
from .updaters.transfer_switch import PVSTransferSwitchUpdater

# The cache holds the matched names, so rebuild it often enough that devices
# appearing (inverters waking after the PVS's nightly restart) show up soon.
QUERY_CACHE_TTL_S = 600


def query_cache_id(match: str) -> str:
    """A stable PVS-side cache id for a match expression, unique per match,
    e.g. "/sys/devices/inverter/" -> "pypvs_sys_devices_inverter_1a2b3c4d"."""
    slug = "_".join(re.findall(r"[A-Za-z0-9]+", match))
    return f"pypvs_{slug}_{zlib.crc32(match.encode()):08x}"


def _values(response_data: Any) -> dict[str, Any]:
    try:
        return {item["name"]: item["value"] for item in response_data["values"]}
    except (KeyError, TypeError) as err:
        raise PVSDataFormatError(
            f"Cannot construct dictionary from response {response_data}"
        ) from err


UPDATERS: list[type["PVSUpdater"]] = [
    PVSGatewayUpdater,
    PVSProductionInvertersUpdater,
    PVSProductionMetersUpdater,
    PVSESSUpdater,
    PVSTransferSwitchUpdater,
]

_LOGGER = logging.getLogger(__name__)


def register_updater(updater: type["PVSUpdater"]) -> Callable[[], None]:
    """Register an updater."""
    UPDATERS.append(updater)

    def _remove_updater() -> None:
        UPDATERS.remove(updater)

    return _remove_updater


def get_updaters() -> list[type[PVSUpdater]]:
    return UPDATERS


class PVS:
    def __init__(
        self,
        session,
        host=None,
        user="ssm_owner",
        password=None,
        use_query_cache: bool = True,
    ):
        """
        Args:
            use_query_cache: run match queries once with a PVS-side cache id and
                re-read the cache afterwards, as doc/LocalAPI.md recommends for
                frequent match queries (cheaper for the PVS, ~5x faster on a
                PVS6 with SunVault). Pass False to always run the match.
        """
        self._host: str | None = None
        self._use_query_cache = use_query_cache
        # match -> monotonic time its PVS-side cache was (re)created
        self._query_caches: dict[str, float] = {}
        # matches whose cache= the PVS rejected while the plain match works
        self._uncacheable: set[str] = set()
        self._common_properties: CommonProperties = CommonProperties()

        self._firmware = PVSFirmware(self.getVarserverVar)
        self._supported_features: SupportedFeatures | None = None
        self._updaters: list[PVSUpdater] = []
        self.data: PVSData | None = None

        # Exponential backoff for inverter re-probe attempts
        self._inverter_reprobe_interval: int = 60  # seconds
        self._inverter_last_reprobe: float | None = None
        self._inverter_reprobe_max: int = 1800  # 30 minutes

        self.fcgi_client = PVSFCGIClient(
            session=session, auth_user=user, auth_password=password
        )
        self.host = host

    def update_clients(self) -> None:
        self.fcgi_client.pvs_url = f"https://{self.host}" if self.host else None

    async def getVarserver(self, endpoint, params=None):
        try:
            response_data = await self.fcgi_client.execute_post_request(
                endpoint, params=params
            )
            _LOGGER.debug(f"Received response: {response_data}")
            return response_data
        except PVSFCGIClientLoginError as err:
            raise PVSAuthenticationError(f"Login to the PVS failed: {err}") from err
        except PVSFCGIClientPostError as err:
            raise PVSCommunicationError(
                f"POST request failed: {err}", status=err.status
            ) from err
        except (TimeoutError, aiohttp.ClientError) as err:
            raise PVSCommunicationError(f"Cannot reach the PVS: {err}") from err
        except Exception as err:
            raise PVSError(f"Unexpected error communicating with PVS: {err}") from err

    async def getVarserverVar(self, varname):
        values = await self.getVarserverVarsByName([varname])
        if varname not in values:
            raise PVSDataFormatError(
                f"Cannot extract {varname}; the PVS returned {values}"
            )
        _LOGGER.debug("Received %s: %s", varname, values[varname])
        return values[varname]

    async def getVarserverVarsByName(self, names: list[str]) -> dict[str, Any]:
        """Read several variables in one request. The PVS answers 400 for the
        whole request if any of the names is unknown."""
        return _values(
            await self.getVarserver("/vars", params={"name": ",".join(names)})
        )

    async def getVarserverVars(self, match):
        values = _values(await self._match_query(match))
        _LOGGER.debug("Received %d values for %s", len(values), match)
        return values

    def reset_query_caches(self) -> None:
        """Forget the PVS-side caches so the next match queries rebuild them."""
        self._query_caches.clear()

    async def _match_query(self, match: str) -> Any:
        """Run a match query, through a PVS-side cache when enabled.

        The cache holds the set of matched names (values are read live), so it
        is rebuilt every QUERY_CACHE_TTL_S and on every probe to pick up devices
        that appeared, and when a read fails with 400 (the PVS forgets its
        caches when it restarts) or comes back empty. If the PVS rejects the
        cache parameter but answers the plain match, caching is turned off for
        that match. A plain match that answers 400 means nothing matches and is
        raised as before.
        """
        if not self._use_query_cache or match in self._uncacheable:
            return await self.getVarserver("/vars", params={"match": match})
        cache_id = query_cache_id(match)
        now = time.monotonic()
        created = self._query_caches.get(match)
        if created is not None and now - created < QUERY_CACHE_TTL_S:
            try:
                data = await self.getVarserver("/vars", params={"cache": cache_id})
            except PVSCommunicationError as err:
                if err.status != HTTP_BAD_REQUEST:
                    raise
                _LOGGER.debug("Query cache %s is gone; recreating it", cache_id)
            else:
                if isinstance(data, dict) and data.get("values"):
                    return data
                _LOGGER.debug("Query cache %s came back empty; recreating it", cache_id)
        self._query_caches.pop(match, None)
        try:
            data = await self.getVarserver(
                "/vars", params={"match": match, "cache": cache_id}
            )
        except PVSCommunicationError as err:
            if err.status != HTTP_BAD_REQUEST:
                raise
            # "nothing matches" and "cache not supported" look the same; the
            # plain match tells them apart (and raises 400 if nothing matches)
            data = await self.getVarserver("/vars", params={"match": match})
            _LOGGER.debug("PVS rejected cache=%s; not caching %s", cache_id, match)
            self._uncacheable.add(match)
            return data
        self._query_caches[match] = now
        return data

    async def discover(self) -> None:
        """Discover the PVS and its capabilities."""
        await self._firmware.setup()
        self.fcgi_client.set_pvs_details({"serial": self._firmware.serial})

    async def setup(self, auth_password: str | None = None) -> None:
        if not self._firmware.serial:
            await self.discover()

        if auth_password:
            # set the password for the PVS
            self.fcgi_client.auth_password = auth_password

        # A rejected login surfaces here as PVSAuthenticationError.
        await self.getVarserverVar(VAR_UPTIME)

    async def validate(self) -> bool:
        # just try to read some variables to see if the connection to the PVS is ok
        await self._firmware.setup()
        return True

    async def probe(self) -> None:
        """Probe for model and supported features."""
        # probe against a fresh view of the PVS, not cached name sets
        self.reset_query_caches()
        supported_features = SupportedFeatures(0)
        updaters: list[PVSUpdater] = []
        self._common_properties.reset_probe_properties()

        for updater in get_updaters():
            klass = updater(
                request_var=self.getVarserverVar,
                request_vars=self.getVarserverVars,
                request_named_vars=self.getVarserverVarsByName,
                common_properties=self._common_properties,
            )
            if updater_features := await klass.probe(supported_features):
                supported_features |= updater_features
                updaters.append(klass)

        if not supported_features & SupportedFeatures.GATEWAY:
            raise PVSProbeFailed("Unable to find gateway information")

        self._updaters = updaters
        self._supported_features = supported_features

    async def update(self) -> PVSData:
        """Update data."""
        if not self._supported_features:
            await self.probe()
            features = self._supported_features or SupportedFeatures(0)
            if not (features & SupportedFeatures.INVERTERS):
                # start the re-probe backoff from this probe
                self._inverter_last_reprobe = time.monotonic()
        elif not (self._supported_features & SupportedFeatures.INVERTERS):
            # Inverters not yet discovered — devices may have been offline
            # during initial probe. Re-probe with exponential backoff.
            now = time.monotonic()
            if (
                self._inverter_last_reprobe is None
                or now - self._inverter_last_reprobe >= self._inverter_reprobe_interval
            ):
                _LOGGER.debug(
                    "Inverters not yet discovered, re-probing (next retry in %ds)",
                    self._inverter_reprobe_interval,
                )
                self._inverter_last_reprobe = now
                await self.probe()
                if not (self._supported_features & SupportedFeatures.INVERTERS):
                    self._inverter_reprobe_interval = min(
                        self._inverter_reprobe_interval * 2,
                        self._inverter_reprobe_max,
                    )
                else:
                    # Found inverters — reset backoff state
                    self._inverter_reprobe_interval = 60
                    self._inverter_last_reprobe = None

        data = PVSData()
        for updater in self._updaters:
            await updater.update(data)

        self.data = data
        return data

    @property
    def host(self) -> str | None:
        """Return the PVS host."""
        return self._host

    @host.setter
    def host(self, value: str | None):
        self._host = value
        self._query_caches.clear()
        self._uncacheable.clear()
        self.update_clients()

    @property
    def serial_number(self) -> str | None:
        """Return the PVS serial number."""
        return self._firmware.serial

    @property
    def supported_features(self) -> SupportedFeatures:
        """Return the supported features."""
        assert self._supported_features is not None, "Call setup() first"  # nosec
        return self._supported_features

    async def enable_telemetry_websocket(self) -> None:
        """Enable the telemetry websocket on the PVS."""
        await self.getVarserver("/vars", params={"set": "/sys/telemetryws/enable=1"})

    def get_websocket(self, port: int = 9002) -> PVSWebSocket:
        """Create a PVSWebSocket pre-configured to enable telemetry on connect.

        Args:
            port: WebSocket port (default 9002)

        Returns:
            PVSWebSocket instance with enable callback wired up

        Raises:
            ValueError: if no host is set
        """
        if not self._host:
            raise ValueError("PVS host must be set before creating a websocket")
        return PVSWebSocket(
            host=self._host,
            port=port,
            enable_callback=self.enable_telemetry_websocket,
        )
