"""Error handling in the FCGI client and PVS varserver helpers."""

from __future__ import annotations

import asyncio
import json

import pytest

from pypvs.exceptions import PVSAuthenticationError, PVSDataFormatError
from pypvs.pvs import PVS
from pypvs.pvs_fcgi import PVSFCGIClient, PVSFCGIClientLoginError


class FakeResponse:
    def __init__(self, status=200, body=""):
        self.status = status
        self._body = body
        self.cookies = {"session": "abc"}

    async def text(self):
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeSession:
    def __init__(self, vars_body=None, login_status=200):
        self.vars_body = vars_body if vars_body is not None else {"values": []}
        self.login_status = login_status
        self.posts = []

    def get(self, url, headers=None, ssl=None):
        return FakeResponse(self.login_status, "bad password")

    def post(self, url, cookies=None, data=None, ssl=None):
        self.posts.append(data)
        return FakeResponse(200, json.dumps(self.vars_body))


def make_client(session):
    client = PVSFCGIClient(session, auth_user="ssm_owner", auth_password="12345")
    client.pvs_url = "https://pvs.test"
    return client


def make_pvs(session):
    pvs = PVS(session=session, host="pvs.test")
    pvs.fcgi_client.auth_password = "12345"
    return pvs


def test_multiple_params_are_joined_with_ampersand():
    session = FakeSession()
    asyncio.run(
        make_client(session).execute_post_request(
            "/vars", params={"match": "inverter", "fmt": "obj"}
        )
    )
    assert session.posts == ["match=inverter&fmt=obj"]


def test_login_failure_message_includes_body():
    client = make_client(FakeSession(login_status=403))
    with pytest.raises(PVSFCGIClientLoginError, match="403 and response: bad password"):
        asyncio.run(client.login_basic())


def test_setup_with_rejected_login_raises_authentication_error():
    pvs = make_pvs(FakeSession(login_status=401))
    pvs._firmware._serial_number = "ZT0000000000000"  # skip discovery
    with pytest.raises(PVSAuthenticationError):
        asyncio.run(pvs.setup())


def test_missing_var_raises_data_format_error_with_details():
    pvs = make_pvs(FakeSession(vars_body={"count": 0, "values": []}))
    with pytest.raises(PVSDataFormatError, match="/sys/info/uptime.*'values': \\[\\]"):
        asyncio.run(pvs.getVarserverVar("/sys/info/uptime"))


def test_malformed_vars_response_raises_data_format_error():
    pvs = make_pvs(FakeSession(vars_body={"unexpected": True}))
    with pytest.raises(PVSDataFormatError, match="unexpected"):
        asyncio.run(pvs.getVarserverVars("/sys/info"))
