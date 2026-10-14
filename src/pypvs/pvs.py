"""The PVS client: varserver reads and the poll that builds PVSData."""

import logging
from typing import Any

import aiohttp

from .api import WEBSOCKET_PORT, Endpoint, Match, SysType, Variable
from .exceptions import (
    PVSAuthenticationError,
    PVSCommunicationError,
    PVSDataFormatError,
    PVSError,
)
from .firmware import PVSFirmware
from .models.ess import PVSESS
from .models.inverter import PVSInverter
from .models.meter import PVSMeter
from .models.pvs import PVSData
from .models.transfer_switch import PVSTransferSwitch
from .pvs_fcgi import PVSFCGIClient, PVSFCGIClientLoginError, PVSFCGIClientPostError
from .pvs_websocket import PVSWebSocket
from .updaters.device import PVSDeviceUpdater
from .updaters.gateway import PVSGatewayUpdater

_LOGGER = logging.getLogger(__name__)


def _values(response_data: Any) -> dict[str, Any]:
    """{name: value} from a /vars response's "values" list."""
    try:
        return {item["name"]: item["value"] for item in response_data["values"]}
    except (KeyError, TypeError) as err:
        raise PVSDataFormatError(
            f"Cannot construct dictionary from response {response_data}"
        ) from err


class PVS:
    """A PVS gateway on the local network.

    Call setup() once, then update() to poll.

    Args:
        session: The aiohttp session to make requests with.
        host: The PVS host name or IP address.
        user: The local API user.
        password: The local API password; by default the last 5 characters
            of the serial number.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str | None = None,
        user: str = "ssm_owner",
        password: str | None = None,
    ) -> None:
        self._host: str | None = None
        self._firmware = PVSFirmware(self.getVarserverVar)
        self.data: PVSData | None = None
        # built once: they keep the gateway extras and what has been logged
        self._gateway = PVSGatewayUpdater(self)
        self._inverters = PVSDeviceUpdater(PVSInverter)
        self._meters = PVSDeviceUpdater(PVSMeter)
        self._ess = PVSDeviceUpdater(PVSESS)
        self._transfer_switches = PVSDeviceUpdater(PVSTransferSwitch)
        self.fcgi_client = PVSFCGIClient(
            session=session, auth_user=user, auth_password=password
        )
        self.host = host

    def update_clients(self) -> None:
        """Point the FCGI client at the current host."""
        self.fcgi_client.pvs_url = f"https://{self.host}" if self.host else None

    async def getVarserver(
        self, endpoint: str, params: dict[str, str] | None = None
    ) -> Any:
        """POST to a local API endpoint and return the decoded JSON.

        Raises:
            PVSAuthenticationError: If the PVS rejects the login.
            PVSCommunicationError: If the PVS cannot be reached or answers
                with an error status.
            PVSError: On any other failure.
        """
        try:
            response_data = await self.fcgi_client.execute_post_request(
                endpoint, params=params
            )
            _LOGGER.debug("Received response: %s", response_data)
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
        """Read one variable."""
        response_data = await self.getVarserver(Endpoint.VARS, params={"name": varname})

        try:
            value = response_data["values"][0]["value"]
            _LOGGER.debug("Received %s: %s", varname, value)
            return value
        except (KeyError, IndexError, TypeError) as err:
            raise PVSDataFormatError(
                f"Cannot extract {varname} from response {response_data}"
            ) from err

    async def getVarserverVarsByName(self, names: list[str]) -> dict[str, Any]:
        """Read several variables in one request.

        The PVS answers 400 for the whole request if any name is unknown.
        """
        if not names:
            return {}
        return _values(
            await self.getVarserver(Endpoint.VARS, params={"name": ",".join(names)})
        )

    async def getVarserverVars(self, match: str) -> dict[str, Any]:
        """Read every variable whose name starts with match."""
        values = _values(
            await self.getVarserver(Endpoint.VARS, params={"match": match})
        )
        _LOGGER.debug("Received %s values: %s", len(values), values)
        return values

    async def discover(self) -> None:
        """Discover the PVS and its capabilities."""
        await self._firmware.setup()

    async def setup(self, auth_password: str | None = None) -> None:
        """Discover the PVS if needed, then check that login works.

        Args:
            auth_password: Replaces the password given to the constructor.
        """
        if not self._firmware.serial:
            await self.discover()

        if auth_password:
            # set the password for the PVS
            self.fcgi_client.auth_password = auth_password

        # A rejected login surfaces here as PVSAuthenticationError.
        await self.getVarserverVar(Variable.UPTIME)

    async def validate(self) -> bool:
        """Check that the PVS answers: True, or raises PVSError."""
        await self._firmware.setup()
        return True

    async def update(self) -> PVSData:
        """Read the gateway and its devices; the result is also kept in data."""
        data = PVSData()
        await self._gateway.update(data)
        device_vars = await self._read_devices()
        data.inverters = self._inverters.update(data, device_vars)
        data.meters = self._meters.update(data, device_vars)
        if data.gateway and data.gateway.model == SysType.STORAGE:
            data.ess = self._ess.update(data, device_vars)
            data.transfer_switches = self._transfer_switches.update(data, device_vars)
        self.data = data
        return data

    async def _read_devices(self) -> dict[str, Any] | PVSError:
        """Every device's variables in one request, or why the read failed."""
        try:
            return await self.getVarserverVars(Match.DEVICES)
        except PVSError as e:
            return e

    @property
    def host(self) -> str | None:
        """Return the PVS host."""
        return self._host

    @host.setter
    def host(self, value: str | None) -> None:
        self._host = value
        self.update_clients()

    @property
    def serial_number(self) -> str | None:
        """Return the PVS serial number."""
        return self._firmware.serial

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
            session=self.fcgi_client.session,
            host=self._host,
            port=port,
            enable_callback=self.enable_telemetry_websocket,
        )
