"""HTTP client for the PVS local API, logging in as needed."""

import base64
import json
import logging
from http import HTTPStatus
from http.cookies import SimpleCookie
from typing import Any

import aiohttp

from .api import Endpoint

_LOGGER = logging.getLogger(__name__)

_BODY_EXCERPT_CHARS = 200


class PVSFCGIClientLoginError(Exception):
    """Exception raised when login to the PVS fails."""


class PVSFCGIClientPostError(Exception):
    """Exception raised when POST request to the PVS fails."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class PVSFCGIClient:
    """Posts to the PVS local API with a session from basic auth."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        auth_user: str | None = None,
        auth_password: str | None = None,
    ) -> None:
        self.session = session
        self.auth_user = auth_user
        self.auth_password = auth_password
        self._pvs_url: str | None = None
        self.login_endpoint = Endpoint.AUTH_LOGIN
        self.cookies: SimpleCookie | None = None

    @property
    def pvs_url(self) -> str | None:
        """The PVS base URL, e.g. https://192.168.1.10; None until set."""
        return self._pvs_url

    @pvs_url.setter
    def pvs_url(self, value: str | None) -> None:
        self._pvs_url = value
        _LOGGER.debug("PVS URL set to %s", self._pvs_url)

    async def login_basic(self) -> None:
        """Log in with the user and password."""
        if not self.auth_user or not self.auth_password:
            raise PVSFCGIClientLoginError(
                "Auth user and password must be set before logging in."
            )

        # The PVS uses basic authentication with the username and password
        auth_token = base64.b64encode(
            f"{self.auth_user}:{self.auth_password}".encode()
        ).decode()
        headers = {"Authorization": f"basic {auth_token}"}
        await self.login(headers=headers)

    async def login(self, headers: dict[str, str] | None = None) -> None:
        """Log in to start a session; its cookies are kept for later requests."""
        if not self._pvs_url:
            raise PVSFCGIClientLoginError("PVS URL must be set before logging in.")

        login_url = f"{self._pvs_url}{self.login_endpoint}"

        _LOGGER.debug("Logging in to %s", login_url)
        # TODO: Ignore certificate errors for now
        async with self.session.get(login_url, headers=headers, ssl=False) as response:
            if response.status != HTTPStatus.OK:
                body = await response.text()
                raise PVSFCGIClientLoginError(
                    f"Login failed with status code: {response.status}"
                    f" and response: {body[:_BODY_EXCERPT_CHARS]}"
                )

            self.cookies = response.cookies
            _LOGGER.info("Login successful")

    async def _post_internal(self, url: str, payload_str: str) -> Any:
        # TODO: Ignore certificate errors for now
        async with self.session.post(
            url, cookies=self.cookies, data=payload_str, ssl=False
        ) as response:
            response_body = await response.text()

            if response.status == HTTPStatus.OK:
                _LOGGER.debug("POST request successful!")
                return json.loads(response_body)
            message = f"HTTP {response.status}: {response_body[:_BODY_EXCERPT_CHARS]}"
            _LOGGER.debug("PVS returned %s for %s", message, url)
            # an expired session is 401; only that is worth logging in again for
            if response.status == HTTPStatus.UNAUTHORIZED:
                raise PVSFCGIClientLoginError(message)
            raise PVSFCGIClientPostError(message, status=response.status)

    async def execute_post_request(
        self, endpoint: str, params: dict[str, str] | None = None
    ) -> Any:
        """POST to an endpoint with the session cookies, logging in as needed.

        If the PVS answers 401, log in again and retry once.

        Args:
            endpoint: The path, relative to the PVS URL.
            params: Form parameters, sent without URL encoding.

        Returns:
            The decoded JSON response.
        """
        if not self._pvs_url:
            raise PVSFCGIClientPostError(
                "PVS URL must be set before making POST requests."
            )

        url = f"{self._pvs_url}{endpoint}"
        # Not URL-encoded: the PVS takes raw paths and set=name=value pairs,
        # e.g. set=/sys/telemetryws/enable=1.
        payload_str = "&".join(
            f"{key}={value}" for key, value in (params or {}).items()
        )
        _LOGGER.debug("POST request to %s with payload: %s", url, payload_str)

        # Proactively login if we don't have a session yet
        if self.cookies is None and self.auth_user and self.auth_password:
            await self.login_basic()

        # Try the request — may fail if session expired
        try:
            return await self._post_internal(url, payload_str)
        except PVSFCGIClientLoginError:
            _LOGGER.debug("Session expired. Re-authenticating...")

        # Retry login to refresh the session cookies
        await self.login_basic()

        # Retry the request after re-authentication
        return await self._post_internal(url, payload_str)
