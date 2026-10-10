"""Message handling in the telemetry websocket client (no network)."""

from __future__ import annotations

import asyncio

import aiohttp
import pytest

from pypvs.models.livedata import PVSLiveData
from pypvs.pvs_websocket import PVSWebSocket


def connected_ws():
    ws = PVSWebSocket(host="pvs.test")
    ws._live_data = PVSLiveData()  # as set up on a successful connect
    return ws


def power(**params):
    return {"notification": "power", "params": params}


def test_power_message_updates_values_and_reports_changes():
    ws = connected_ws()
    seen = []
    ws.add_listener(seen.append)
    ws._process_message(power(pv_p="3.2", soc="0.5"))
    assert ws.live_data.pv_p == 3.2
    assert ws.live_data.soc == 0.5
    assert seen == [{"/sys/livedata/pv_p", "/sys/livedata/soc"}]


def test_unchanged_values_do_not_notify():
    ws = connected_ws()
    seen = []
    ws.add_listener(seen.append)
    ws._process_message(power(pv_p="3.2"))
    ws._process_message(power(pv_p="3.2"))
    assert len(seen) == 1


def test_repeated_nan_does_not_notify_every_time():
    ws = connected_ws()
    seen = []
    ws.add_listener(seen.append)
    ws._process_message(power(pv_p=float("nan")))
    ws._process_message(power(pv_p=float("nan")))
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
    """Anything that raises here propagates out of the receive loop and tears
    down a healthy connection."""
    ws = connected_ws()
    ws._process_message(message)
    assert ws.live_data == PVSLiveData()


def test_other_notifications_are_ignored():
    ws = connected_ws()
    ws._process_message({"notification": "status", "params": {"pv_p": "1"}})
    assert ws.live_data.pv_p is None


def test_a_failing_listener_does_not_stop_the_others():
    ws = connected_ws()
    seen = []

    def boom(_):
        raise RuntimeError("listener bug")

    ws.add_listener(boom)
    ws.add_listener(seen.append)
    ws._process_message(power(pv_p="1"))
    assert seen == [{"/sys/livedata/pv_p"}]


def test_removed_listener_is_not_called():
    ws = connected_ws()
    seen = []
    remove = ws.add_listener(seen.append)
    remove()
    ws._process_message(power(pv_p="1"))
    assert seen == []


def test_a_bad_field_does_not_lose_the_rest_of_the_message():
    """time=Infinity (valid JSON to Python) must not abort the update half-way
    and skip the listeners for fields already applied."""
    ws = connected_ws()
    seen = []
    ws.add_listener(seen.append)
    ws._process_message(power(pv_p="1.5", time=float("inf")))
    assert ws.live_data.pv_p == 1.5
    assert ws.live_data.time is None
    assert seen == [{"/sys/livedata/pv_p"}]


class FakeMsg:
    def __init__(self, data):
        self.type = aiohttp.WSMsgType.TEXT
        self.data = data


class FakeWS:
    def __init__(self, messages, ws_client):
        self._messages = list(messages)
        self._client = ws_client

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._messages:
            # server went away; stop the client so the loop ends
            self._client._stopping = True
            raise StopAsyncIteration
        return FakeMsg(self._messages.pop(0))

    async def close(self):
        pass


class FakeSession:
    def __init__(self, messages, ws_client):
        self.closed = False
        self._ws = FakeWS(messages, ws_client)
        self.connects = 0

    def ws_connect(self, url, **kwargs):
        self.connects += 1
        return self._ws

    async def close(self):
        self.closed = True


def test_a_bad_message_does_not_drop_the_connection(monkeypatch):
    ws = PVSWebSocket(host="pvs.test")
    session = FakeSession(
        [
            '["not", "an", "object"]',
            '{"notification": "power", "params": {"pv_p": "2.5"}}',
        ],
        ws,
    )
    monkeypatch.setattr(aiohttp, "ClientSession", lambda **kw: session)
    states, seen = [], []
    ws.add_state_listener(states.append)
    ws.add_listener(seen.append)

    asyncio.run(ws._run_websocket())

    assert session.connects == 1
    assert seen == [{"/sys/livedata/pv_p"}]
    assert [s.value for s in states] == ["connecting", "connected", "disconnected"]
