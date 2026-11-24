"""The PVS serial number stays out of logs and errors.

The PVS's default password is the last 5 characters of its serial number,
and debug logs get shared when reporting problems.
"""

from __future__ import annotations

import asyncio
import json
import logging

import pytest

from pypvs.exceptions import PVSDataFormatError
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
    """Answers name and match reads from VARIABLES, or with a fixed answer."""

    def __init__(self, answer=None):
        self.answer = answer

    def get(self, url, headers=None, ssl=None):
        return FakeResponse()

    def post(self, url, cookies=None, data=None, ssl=None):
        if self.answer is not None:
            return FakeResponse(json.dumps(self.answer))
        key, _, value = data.partition("=")
        if key == "name":
            names = value.split(",")
        else:
            names = [name for name in VARIABLES if value in name]
        values = [{"name": name, "value": VARIABLES[name]} for name in names]
        return FakeResponse(json.dumps({"count": len(values), "values": values}))


def test_setup_and_reads_do_not_log_the_serial_number(caplog):
    caplog.set_level(logging.DEBUG, logger="pypvs")
    pvs = PVS(session=FakeSession(), host="pvs.test")

    asyncio.run(pvs.setup())
    by_match = asyncio.run(pvs.getVarserverVars("/sys/info/"))
    by_name = asyncio.run(
        pvs.getVarserverVarsByName(["/sys/info/serialnum", "/sys/info/uptime"])
    )

    assert pvs.serial_number == SERIAL
    assert by_match["/sys/info/serialnum"] == SERIAL
    assert by_name["/sys/info/serialnum"] == SERIAL
    # the responses are still logged, with the serial number hidden
    assert "/sys/info/serialnum" in caplog.text
    assert "81436.77" in caplog.text
    assert SERIAL not in caplog.text
    assert PASSWORD not in caplog.text


def test_a_malformed_response_error_hides_the_serial_number():
    answer = {
        "values": [{"name": "/sys/info/serialnum", "value": SERIAL}, {"name": "/a"}]
    }
    pvs = PVS(session=FakeSession(answer), host="pvs.test")

    with pytest.raises(PVSDataFormatError, match="/sys/info/serialnum") as err:
        asyncio.run(pvs.getVarserverVars("/sys/info/"))

    assert SERIAL not in str(err.value)
