"""What updaters need from the PVS."""

from typing import Any, Protocol


class Varserver(Protocol):
    """The reads an updater makes; PVS implements them."""

    async def getVarserverVar(self, varname: str) -> Any:
        """Read one variable."""

    async def getVarserverVarsByName(self, names: list[str]) -> dict[str, Any]:
        """Read several variables in one request."""
