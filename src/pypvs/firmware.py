"""PVS identity read at discovery."""

from collections.abc import Awaitable, Callable
from typing import Any

from .api import Variable


class PVSFirmware:
    """The PVS serial number (its last 5 characters are the default password)
    and LAN MAC address."""

    def __init__(
        self,
        request_var: Callable[[str], Awaitable[Any]],
    ) -> None:
        self._request_var = request_var
        self._serial_number: str | None = None
        self._lmac: str | None = None

    async def setup(self) -> None:
        """Read the serial number and LAN MAC address."""
        self._serial_number = await self._request_var(Variable.SERIALNUM)
        self._lmac = await self._request_var(Variable.LMAC)

    @property
    def serial(self) -> str | None:
        return self._serial_number

    @property
    def lmac(self) -> str | None:
        return self._lmac
