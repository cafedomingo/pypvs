"""Message handling in the telemetry websocket client (no network)."""

from __future__ import annotations

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
    assert len(seen) <= 1


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
