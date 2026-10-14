from typing import Any, Protocol


class Varserver(Protocol):
    """The reads an updater makes; PVS implements them."""

    async def getVarserverVar(self, varname: str) -> Any: ...

    async def getVarserverVars(self, match: str) -> dict[str, Any]: ...

    async def getVarserverVarsByName(self, names: list[str]) -> dict[str, Any]: ...
