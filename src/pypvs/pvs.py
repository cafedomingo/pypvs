import inspect
import logging
import time
from collections.abc import Callable
from typing import Any

import aiohttp

from .const import VAR_UPTIME, SupportedFeatures
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


def _accepts(cls: type, name: str) -> bool:
    params = inspect.signature(cls).parameters.values()
    return any(p.name == name or p.kind is p.VAR_KEYWORD for p in params)


def get_updaters() -> list[type[PVSUpdater]]:
    return UPDATERS


class PVS:
    def __init__(self, session, host=None, user="ssm_owner", password=None):
        self._host: str | None = None
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
        response_data = await self.getVarserver("/vars", params={"name": varname})

        try:
            # sample return:
            # {
            #     "count": 1,
            #     "values": [
            #     {
            #         "name": "/sys/info/uptime",
            #         "value": "106408.20"
            #     }
            #     ]
            # }
            value = response_data["values"][0]["value"]
            _LOGGER.debug(f"Received {varname}: {value}")
            return response_data["values"][0]["value"]
        except (KeyError, IndexError, TypeError) as err:
            raise PVSDataFormatError(
                f"Cannot extract {varname} from response {response_data}"
            ) from err

    async def getVarserverVarsByName(self, names: list[str]) -> dict[str, Any]:
        """Read several variables in one request. The PVS answers 400 for the
        whole request if any of the names is unknown."""
        if not names:
            return {}
        response_data = await self.getVarserver(
            "/vars", params={"name": ",".join(names)}
        )
        try:
            return {item["name"]: item["value"] for item in response_data["values"]}
        except (KeyError, TypeError) as err:
            raise PVSDataFormatError(
                f"Cannot construct dictionary from response {response_data}"
            ) from err

    async def getVarserverVars(self, match):
        response_data = await self.getVarserver("/vars", params={"match": match})

        try:
            # construct a new dictionary with the varname
            # as the key and the value as the value
            value_dict = {}
            for item in response_data["values"]:
                value_dict[item["name"]] = item["value"]
            _LOGGER.debug(f"Received {len(value_dict)} values: {value_dict}")
            return value_dict
        except (KeyError, TypeError) as err:
            raise PVSDataFormatError(
                f"Cannot construct dictionary from response {response_data}"
            ) from err

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
        supported_features = SupportedFeatures(0)
        updaters: list[PVSUpdater] = []
        self._common_properties.reset_probe_properties()

        for updater in get_updaters():
            kwargs = {}
            if _accepts(updater, "request_named_vars"):
                # updaters registered by others may predate this argument
                kwargs["request_named_vars"] = self.getVarserverVarsByName
            klass = updater(
                request_var=self.getVarserverVar,
                request_vars=self.getVarserverVars,
                common_properties=self._common_properties,
                **kwargs,
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
