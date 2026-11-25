"""The PVS serial number stays out of the debug logs.

The PVS's default password is the last 5 characters of its serial number,
and debug logs get shared when reporting problems.
"""

from __future__ import annotations

import asyncio
import json
import logging

from pypvs.pvs import PVS

SERIAL = "ZT000000000000Q7K9X"
PASSWORD = SERIAL[-5:]
VARIABLES = {
    "/sys/info/serialnum": SERIAL,
    "/sys/info/lmac": "02:aa:bb:cc:dd:01",
    "/sys/info/uptime": "81436.77",
}


class FakeResponse:
    def __init__(self, body=""):
        self.status = 200
        self._body = body
        self.cookies = {"session": "abc"}

    async def text(self):
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeSession:
    """Answers single-name reads from VARIABLES."""

    def get(self, url, headers=None, ssl=None):
        return FakeResponse()

    def post(self, url, cookies=None, data=None, ssl=None):
        name = data.removeprefix("name=")
        values = [{"name": name, "value": VARIABLES[name]}]
        return FakeResponse(json.dumps({"count": 1, "values": values}))


def test_setup_does_not_log_the_serial_number(caplog):
    caplog.set_level(logging.DEBUG, logger="pypvs")
    pvs = PVS(session=FakeSession(), host="pvs.test")

    asyncio.run(pvs.setup())

    assert pvs.serial_number == SERIAL
    assert SERIAL not in caplog.text
    assert PASSWORD not in caplog.text
    # the other reads are still logged
    assert "Received /sys/info/uptime: 81436.77" in caplog.text
