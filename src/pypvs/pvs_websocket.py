"""WebSocket client for PVS live data."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Awaitable, Callable
from enum import Enum
from typing import Any

import aiohttp

from .api import WEBSOCKET_PORT
from .models.livedata import LIVEDATA_FIELD_DEFINITIONS, PVSLiveData

_LOGGER = logging.getLogger(__name__)

RETRY_S = 5
CONNECT_TIMEOUT_S = 10
# the PVS sends a message every second
STALE_S = 10

_CLOSED = (
    aiohttp.WSMsgType.CLOSE,
    aiohttp.WSMsgType.CLOSING,
    aiohttp.WSMsgType.CLOSED,
)


class ConnectionState(Enum):
    """WebSocket connection state."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"


LiveDataCallback = Callable[[set[str]], None]
ConnectionStateCallback = Callable[[ConnectionState], None]


def _remover(callbacks: list[Any], callback: Any) -> Callable[[], None]:
    def remove() -> None:
        with contextlib.suppress(ValueError):
            callbacks.remove(callback)

    return remove


class PVSWebSocket:
    """Live data the PVS pushes once a second. Reconnects until disconnect()."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        port: int = WEBSOCKET_PORT,
        enable_callback: Callable[[], Awaitable[Any]] | None = None,
    ) -> None:
        self._session = session
        self._url = f"ws://{host}:{port}"
        self._enable_callback = enable_callback
        self._callbacks: list[LiveDataCallback] = []
        self._state_callbacks: list[ConnectionStateCallback] = []
        self._task: asyncio.Task[None] | None = None
        self._live_data: PVSLiveData | None = None
        self._state = ConnectionState.DISCONNECTED
        self._warned = False  # about the current outage

    @property
    def live_data(self) -> PVSLiveData | None:
        """The latest values; None while disconnected."""
        return self._live_data

    @property
    def is_connected(self) -> bool:
        return self._state is ConnectionState.CONNECTED

    @property
    def state(self) -> ConnectionState:
        return self._state

    def add_listener(self, callback: LiveDataCallback) -> Callable[[], None]:
        """Call `callback` with the var paths whose values changed. Returns a
        function that removes it."""
        self._callbacks.append(callback)
        return _remover(self._callbacks, callback)

    def add_state_listener(
        self, callback: ConnectionStateCallback
    ) -> Callable[[], None]:
        """Call `callback` with each new state. Returns a function that removes
        it."""
        self._state_callbacks.append(callback)
        return _remover(self._state_callbacks, callback)

    async def connect(self) -> None:
        """Start connecting in the background."""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    async def disconnect(self) -> None:
        task, self._task = self._task, None
        self._live_data = None
        self._set_state(ConnectionState.DISCONNECTED)
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            current = asyncio.current_task()
            if current is not None and current.cancelling():
                raise  # the caller is being cancelled too

    async def _run(self) -> None:
        while not self._session.closed:
            try:
                reason = await self._connect_once()
            except TimeoutError:
                reason = "timed out"
            except (aiohttp.ClientError, OSError) as e:
                reason = str(e) or type(e).__name__
            except Exception:
                _LOGGER.exception("Live data websocket %s failed", self._url)
                reason = "unexpected error"
            self._live_data = None
            self._set_state(ConnectionState.DISCONNECTED)
            log = _LOGGER.debug if self._warned else _LOGGER.warning
            log(
                "Live data websocket %s unavailable: %s; retrying every %ss",
                self._url,
                reason,
                RETRY_S,
            )
            self._warned = True
            await asyncio.sleep(RETRY_S)

    async def _connect_once(self) -> str:
        """Returns why the connection ended; raises if it could not be made."""
        self._set_state(ConnectionState.CONNECTING)
        if self._enable_callback is not None:
            try:
                async with asyncio.timeout(CONNECT_TIMEOUT_S):
                    await self._enable_callback()
            except Exception as e:
                _LOGGER.debug("Could not enable the telemetry websocket: %s", e)
        async with asyncio.timeout(CONNECT_TIMEOUT_S):
            ws = await self._session.ws_connect(self._url)
        async with ws:
            self._live_data = PVSLiveData()
            self._set_state(ConnectionState.CONNECTED)
            while True:
                try:
                    msg = await ws.receive(timeout=STALE_S)
                except TimeoutError:
                    return f"no message in {STALE_S}s"
                if msg.type is aiohttp.WSMsgType.TEXT:
                    if self._warned:
                        _LOGGER.info("Live data websocket %s recovered", self._url)
                        self._warned = False
                    try:
                        data = json.loads(msg.data)
                    except ValueError:
                        _LOGGER.debug("Ignoring a message that is not JSON")
                        continue
                    self._handle_message(data)
                elif msg.type is aiohttp.WSMsgType.ERROR:
                    return str(ws.exception())
                elif msg.type in _CLOSED:
                    return "closed by the PVS"

    def _handle_message(self, data: Any) -> None:
        if not isinstance(data, dict) or data.get("notification") != "power":
            return
        params = data.get("params")
        if not isinstance(params, dict) or self._live_data is None:
            return
        changed = set()
        for ws_field, var_path, attr, value_type in LIVEDATA_FIELD_DEFINITIONS:
            if ws_field not in params:
                continue
            value = getattr(PVSLiveData, f"_parse_{value_type}")(params[ws_field])
            if getattr(self._live_data, attr) != value:
                setattr(self._live_data, attr, value)
                changed.add(var_path)
        if not changed:
            return
        for callback in list(self._callbacks):
            try:
                callback(changed)
            except Exception:
                _LOGGER.exception("Live data listener failed")

    def _set_state(self, state: ConnectionState) -> None:
        if state is self._state:
            return
        self._state = state
        for callback in list(self._state_callbacks):
            try:
                callback(state)
            except Exception:
                _LOGGER.exception("Connection state listener failed")
