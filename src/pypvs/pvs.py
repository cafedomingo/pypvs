import logging
import time
from collections.abc import Callable
from typing import Any

import aiohttp

from .api import WEBSOCKET_PORT, Endpoint, Variable
from .const import SupportedFeatures
from .exceptions import (
    PVSAuthenticationError,
    PVSCommunicationError,
    PVSDataFormatError,
    PVSError,
    PVSProbeFailed,
)
from .firmware import PVSFirmware
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
    PVSProductionInvertersUpdater,
    PVSProductionMetersUpdater,
    PVSESSUpdater,
    PVSTransferSwitchUpdater,
    PVSGatewayUpdater,  # last, so its probe knows whether there is an ESS
]

_LOGGER = logging.getLogger(__name__)


def register_updater(updater: type["PVSUpdater"]) -> Callable[[], None]:
    """Register an updater."""
    UPDATERS.append(updater)

    def _remove_updater() -> None:
        UPDATERS.remove(updater)

    return _remove_updater


def _values(response_data: Any) -> dict[str, Any]:
    """{name: value} from a /vars response's "values" list."""
    try:
        return {item["name"]: item["value"] for item in response_data["values"]}
    except (KeyError, TypeError) as err:
        raise PVSDataFormatError(
            f"Cannot construct dictionary from response {response_data}"
        ) from err


def get_updaters() -> list[type[PVSUpdater]]:
    return UPDATERS


class PVS:
    def __init__(self, session, host=None, user="ssm_owner", password=None):
        self._host: str | None = None

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

    async def getVarserverVar(self, varname: str) -> Any:
        response_data = await self.getVarserver(Endpoint.VARS, params={"name": varname})

        try:
            value = response_data["values"][0]["value"]
            _LOGGER.debug(f"Received {varname}: {value}")
            return value
        except (KeyError, IndexError, TypeError) as err:
            raise PVSDataFormatError(
                f"Cannot extract {varname} from response {response_data}"
            ) from err

    async def getVarserverVarsByName(self, names: list[str]) -> dict[str, Any]:
        """Read several variables in one request. The PVS answers 400 for the
        whole request if any of the names is unknown."""
        if not names:
            return {}
        return _values(
            await self.getVarserver(Endpoint.VARS, params={"name": ",".join(names)})
        )

    async def getVarserverVars(self, match: str) -> dict[str, Any]:
        values = _values(
            await self.getVarserver(Endpoint.VARS, params={"match": match})
        )
        _LOGGER.debug(f"Received {len(values)} values: {values}")
        return values

    async def discover(self) -> None:
        """Discover the PVS and its capabilities."""
        await self._firmware.setup()

    async def setup(self, auth_password: str | None = None) -> None:
        if not self._firmware.serial:
            await self.discover()

        if auth_password:
            # set the password for the PVS
            self.fcgi_client.auth_password = auth_password

        # A rejected login surfaces here as PVSAuthenticationError.
        await self.getVarserverVar(Variable.UPTIME)

    async def validate(self) -> bool:
        # just try to read some variables to see if the connection to the PVS is ok
        await self._firmware.setup()
        return True

    async def probe(self) -> None:
        """Probe for model and supported features."""
        supported_features = SupportedFeatures(0)
        updaters: list[PVSUpdater] = []

        for updater in get_updaters():
            klass = updater(self)
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
        await self.getVarserver(
            Endpoint.VARS, params={"set": f"{Variable.TELEMETRYWS_ENABLE}=1"}
        )

    def get_websocket(self, port: int = WEBSOCKET_PORT) -> PVSWebSocket:
        """Create a PVSWebSocket pre-configured to enable telemetry on connect.

        Args:
            port: WebSocket port

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
