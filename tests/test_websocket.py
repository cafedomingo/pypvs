"""The live data websocket client."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from dataclasses import asdict
from types import SimpleNamespace

import aiohttp
import pytest
from aiohttp import web

import pypvs.pvs_websocket as pvs_websocket
from pypvs.exceptions import PVSCommunicationError
from pypvs.models.livedata import PVSLiveData
from pypvs.pvs import PVS
from pypvs.pvs_websocket import ConnectionState, PVSWebSocket

POWER = json.dumps(
    {"notification": "power", "params": {"time": 1791944553, "pv_p": 1.5}}
)


@pytest.fixture(autouse=True)
def fast_timing(monkeypatch):
    monkeypatch.setattr(pvs_websocket, "RETRY_S", 0.01)
    monkeypatch.setattr(pvs_websocket, "STALE_S", 0.2)
    monkeypatch.setattr(pvs_websocket, "CONNECT_TIMEOUT_S", 0.2)


def connected_ws():
    ws = PVSWebSocket(None, "pvs.test")
    ws._live_data = PVSLiveData()  # as set up on a successful connect
    return ws


def power(**params):
    return {"notification": "power", "params": params}


def test_power_message_updates_values_and_reports_changes():
    ws = connected_ws()
    seen = []
    ws.add_listener(seen.append)
    ws._handle_message(power(pv_p="3.2", soc="0.5"))
    assert ws.live_data.pv_p == 3.2
    assert ws.live_data.soc == 0.5
    assert seen == [{"/sys/livedata/pv_p", "/sys/livedata/soc"}]


def test_unchanged_values_do_not_notify():
    ws = connected_ws()
    seen = []
    ws.add_listener(seen.append)
    ws._handle_message(power(pv_p="3.2"))
    ws._handle_message(power(pv_p="3.2"))
    assert len(seen) == 1


def test_repeated_nan_does_not_notify_every_time():
    ws = connected_ws()
    seen = []
    ws.add_listener(seen.append)
    ws._handle_message(power(pv_p=float("nan")))
    ws._handle_message(power(pv_p=float("nan")))
    assert seen == []
    assert ws.live_data.pv_p is None


@pytest.mark.parametrize(
    "message",
    [
        [],
        42,
        "power",
        None,
        {"notification": "power", "params": None},
        {"notification": "power", "params": ["pv_p"]},
    ],
)
def test_malformed_messages_are_ignored_not_raised(message):
    ws = connected_ws()
    ws._handle_message(message)
    assert ws.live_data == PVSLiveData()


def test_other_notifications_are_ignored():
    ws = connected_ws()
    ws._handle_message({"notification": "status", "params": {"pv_p": "1"}})
    assert ws.live_data.pv_p is None


def test_a_failing_listener_does_not_stop_the_others():
    ws = connected_ws()
    seen = []

    def boom(_):
        raise RuntimeError("listener bug")

    ws.add_listener(boom)
    ws.add_listener(seen.append)
    ws._handle_message(power(pv_p="1"))
    assert seen == [{"/sys/livedata/pv_p"}]


def test_removed_listener_is_not_called():
    ws = connected_ws()
    seen = []
    remove = ws.add_listener(seen.append)
    remove()
    remove()  # removing twice is harmless
    ws._handle_message(power(pv_p="1"))
    assert seen == []


def test_a_bad_field_does_not_lose_the_rest_of_the_message():
    """time=Infinity (valid JSON to Python) must not abort the update half-way
    and skip the listeners for fields already applied."""
    ws = connected_ws()
    seen = []
    ws.add_listener(seen.append)
    ws._handle_message(power(pv_p="1.5", time=float("inf")))
    assert ws.live_data.pv_p == 1.5
    assert ws.live_data.time is None
    assert seen == [{"/sys/livedata/pv_p"}]


def test_the_websocket_uses_the_pvs_session():
    session = object()
    ws = PVS(session=session, host="10.0.0.5").get_websocket()
    assert ws._session is session


@contextlib.asynccontextmanager
async def pvs_server(*connections):
    """A loopback stand-in for the PVS. Each websocket connection gets the next
    of `connections`: "refuse" (HTTP 503), or (frames, ending) where ending is
    "close" or "stall" (send nothing more until the client goes). Once they run
    out, connections stall."""
    remaining = list(connections)
    server = SimpleNamespace(connects=0, events=[])

    async def handler(request):
        script = remaining.pop(0) if remaining else ((), "stall")
        if script == "refuse":
            raise web.HTTPServiceUnavailable()
        server.connects += 1
        server.events.append("connect")
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        frames, ending = script
        for frame in frames:
            await ws.send_str(frame)
        if ending == "stall":
            await ws.receive()  # returns once the client closes
        await ws.close()
        return ws

    app = web.Application()
    app.router.add_get("/", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", 0).start()
    server.port = runner.addresses[0][1]
    try:
        yield server
    finally:
        await runner.cleanup()


@contextlib.asynccontextmanager
async def client(port, **kwargs):
    async with aiohttp.ClientSession() as session:
        ws = PVSWebSocket(session, "127.0.0.1", port, **kwargs)
        try:
            yield ws
        finally:
            await ws.disconnect()


async def until(condition):
    for _ in range(200):  # up to 2 s
        if condition():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition never became true")


def has_pv(ws, value):
    return ws.live_data is not None and ws.live_data.pv_p == value


def test_live_data_arrives_from_the_stream():
    async def main():
        async with pvs_server(((POWER,), "stall")) as server, client(server.port) as ws:
            seen = []
            ws.add_listener(seen.append)
            await ws.connect()
            await until(lambda: seen)
            assert ws.is_connected
            assert ws.live_data.pv_p == 1.5
            assert ws.live_data.time.timestamp() == 1791944553

    asyncio.run(main())


def test_telemetry_is_enabled_before_every_connect():
    async def main():
        async with pvs_server(((POWER,), "close")) as server:

            async def enable():
                server.events.append("enable")

            async with client(server.port, enable_callback=enable) as ws:
                await ws.connect()
                await until(lambda: server.connects == 2)
        assert server.events[:4] == ["enable", "connect", "enable", "connect"]

    asyncio.run(main())


def test_a_failing_enable_still_connects():
    async def enable():
        raise PVSCommunicationError("HTTP 500", status=500)

    async def main():
        async with (
            pvs_server(((POWER,), "stall")) as server,
            client(server.port, enable_callback=enable) as ws,
        ):
            await ws.connect()
            await until(lambda: has_pv(ws, 1.5))
            assert server.connects == 1

    asyncio.run(main())


def test_a_stalled_stream_reconnects(caplog):
    async def main():
        async with (
            pvs_server(((), "stall"), ((POWER,), "stall")) as server,
            client(server.port) as ws,
        ):
            await ws.connect()
            await until(lambda: has_pv(ws, 1.5))
            assert server.connects == 2

    asyncio.run(main())
    assert "no message in 0.2s" in caplog.text


def test_the_pvs_closing_the_stream_reconnects():
    async def main():
        async with pvs_server(((POWER,), "close")) as server, client(server.port) as ws:
            states = []
            ws.add_state_listener(states.append)
            await ws.connect()
            await until(lambda: server.connects == 2 and ws.is_connected)
            assert states == [
                ConnectionState.CONNECTING,
                ConnectionState.CONNECTED,
                ConnectionState.DISCONNECTED,
                ConnectionState.CONNECTING,
                ConnectionState.CONNECTED,
            ]

    asyncio.run(main())


def test_failures_warn_once_then_log_the_recovery(caplog):
    caplog.set_level(logging.DEBUG, logger="pypvs")

    async def main():
        async with (
            pvs_server("refuse", "refuse", "refuse", ((POWER,), "stall")) as server,
            client(server.port) as ws,
        ):
            await ws.connect()
            await until(lambda: ws.is_connected)

    asyncio.run(main())
    records = [r for r in caplog.records if r.name == "pypvs.pvs_websocket"]
    outages = [r.levelname for r in records if "unavailable" in r.getMessage()]
    assert outages == ["WARNING", "DEBUG", "DEBUG"]
    assert any(r.levelname == "INFO" and "recovered" in r.getMessage() for r in records)


def test_a_connect_that_hangs_times_out(caplog):
    async def main():
        async def silent(reader, writer):
            await reader.read()
            writer.close()

        server = await asyncio.start_server(silent, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        async with server, client(port) as ws:
            await ws.connect()
            await until(lambda: "unavailable: timed out" in caplog.text)

    asyncio.run(main())


def test_a_bad_message_does_not_drop_the_connection():
    frames = ("not json", '["not", "an", "object"]', POWER)

    async def main():
        async with pvs_server((frames, "stall")) as server, client(server.port) as ws:
            await ws.connect()
            await until(lambda: has_pv(ws, 1.5))
            assert server.connects == 1

    asyncio.run(main())


def test_an_unexpected_error_is_logged_and_retried(caplog):
    async def main():
        async with pvs_server(((POWER,), "stall")) as server, client(server.port) as ws:

            def bug(data):
                raise RuntimeError("bug")

            ws._handle_message = bug
            await ws.connect()
            await until(lambda: server.connects >= 2)

    asyncio.run(main())
    failures = [r for r in caplog.records if "failed" in r.getMessage()]
    assert failures
    assert failures[0].exc_info is not None


def test_disconnect_stops_and_leaves_the_session_open():
    async def main():
        async with (
            pvs_server(((POWER,), "stall")) as server,
            aiohttp.ClientSession() as session,
        ):
            ws = PVSWebSocket(session, "127.0.0.1", server.port)
            await ws.connect()
            await ws.connect()  # already running: no second loop
            await until(lambda: ws.is_connected)
            await ws.disconnect()
            assert ws.live_data is None
            assert ws.state is ConnectionState.DISCONNECTED
            assert not session.closed
            await asyncio.sleep(0.1)
            assert server.connects == 1

    asyncio.run(main())


def test_a_hanging_enable_does_not_block_the_connect():
    async def enable():
        await asyncio.Event().wait()

    async def main():
        async with (
            pvs_server(((POWER,), "stall")) as server,
            client(server.port, enable_callback=enable) as ws,
        ):
            await ws.connect()
            await until(lambda: has_pv(ws, 1.5))

    asyncio.run(main())


def test_closing_the_session_stops_the_client(caplog):
    async def main():
        async with pvs_server(((POWER,), "stall")) as server:
            session = aiohttp.ClientSession()
            ws = PVSWebSocket(session, "127.0.0.1", server.port)
            await ws.connect()
            await until(lambda: ws.is_connected)
            await session.close()
            await until(lambda: ws._task.done())
            await ws.disconnect()

    asyncio.run(main())
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_recovery_is_logged_once_data_flows(caplog):
    """A PVS that accepts the connection but sends nothing has not recovered."""
    caplog.set_level(logging.DEBUG, logger="pypvs")

    async def main():
        async with (
            pvs_server(((), "stall"), ((), "stall"), ((POWER,), "stall")) as server,
            client(server.port) as ws,
        ):
            await ws.connect()
            await until(lambda: has_pv(ws, 1.5))

    asyncio.run(main())
    records = [r for r in caplog.records if r.name == "pypvs.pvs_websocket"]
    outages = [r.levelname for r in records if "unavailable" in r.getMessage()]
    recoveries = [r for r in records if "recovered" in r.getMessage()]
    assert outages == ["WARNING", "DEBUG"]
    assert len(recoveries) == 1


def test_a_cancelled_disconnect_stays_cancelled():
    async def main():
        async with (
            pvs_server(((POWER,), "stall")) as server,
            aiohttp.ClientSession() as session,
        ):
            ws = PVSWebSocket(session, "127.0.0.1", server.port)
            await ws.connect()
            await until(lambda: ws.is_connected)
            disconnecting = asyncio.create_task(ws.disconnect())
            await asyncio.sleep(0)  # let it reach the wait for the loop
            disconnecting.cancel()
            with pytest.raises(asyncio.CancelledError):
                await disconnecting
            assert ws.live_data is None

    asyncio.run(main())


def test_reads_every_live_data_param():
    """The params the PVS6 sends (doc/LocalAPI.md), plus backupTimeRemaining and
    midstate, which it does not send but which are read the same way."""
    ws = connected_ws()
    ws._handle_message(
        power(
            time=1790000000,
            soc=0.5,
            site_load_p=0.8,
            net_p=-1.2,
            pv_p=2.5,
            ess_p=-0.5,
            site_load_en=9500.75,
            net_en=3000.25,
            pv_en=12000.5,
            ess_en=-500.0,
            backupTimeRemaining=90,
            midstate=2,
        )
    )
    assert None not in asdict(ws.live_data).values()


def test_unusable_params_read_as_missing():
    ws = connected_ws()
    ws._handle_message(power(pv_p="3.2", soc="0.5", time=1791944553))
    ws._handle_message(power(pv_p="nan", soc=True, time=float("inf")))
    assert ws.live_data == PVSLiveData()
