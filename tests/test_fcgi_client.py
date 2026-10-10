"""Tests for the FCGI client against a fake aiohttp session."""

from __future__ import annotations

import asyncio
import json
import logging

from pypvs.pvs_fcgi import PVSFCGIClient

SECRET_COOKIE = "s3cr3t-session-id"


class FakeResponse:
    def __init__(self, status=200, body="", cookies=None):
        self.status = status
        self._body = body
        self.cookies = cookies or {}

    async def text(self):
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeSession:
    """Answers GET /auth with a session cookie and POST /vars with `vars_body`."""

    def __init__(self, vars_body=None, login_status=200):
        self.vars_body = vars_body or {"count": 0, "values": []}
        self.login_status = login_status
        self.posts = []

    def get(self, url, headers=None, ssl=None):
        return FakeResponse(
            status=self.login_status,
            body="unauthorized" if self.login_status != 200 else "",
            cookies={"session": SECRET_COOKIE},
        )

    def post(self, url, cookies=None, data=None, ssl=None):
        self.posts.append((url, data))
        return FakeResponse(body=json.dumps(self.vars_body))


def make_client(session, password="12345"):
    client = PVSFCGIClient(session, auth_user="ssm_owner", auth_password=password)
    client.pvs_url = "https://pvs.test"
    return client


def test_login_does_not_log_credentials(caplog):
    caplog.set_level(logging.DEBUG, logger="pypvs")
    client = make_client(FakeSession(), password="hunter2")

    asyncio.run(
        client.execute_post_request("/vars", params={"name": "/sys/info/uptime"})
    )

    logged = caplog.text
    assert SECRET_COOKIE not in logged
    assert "hunter2" not in logged
    assert "c3NtX293bmVyOmh1bnRlcjI=" not in logged  # base64 of ssm_owner:hunter2
