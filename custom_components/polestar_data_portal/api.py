"""Async client for the Polestar Data Portal M2M API.

The surface implemented here follows ``resources/openapi.json`` (the
"EU Data Act API" spec published on the Polestar Data Portal). Two details of
that spec drive the shape of this module:

* ``POST /token`` is a client-credentials grant that does **not** follow
  RFC 6749 naming. It takes ``clientId``/``clientSecret`` in a JSON body and
  answers with ``accessToken``/``expiresIn``/``tokenType``, so the stock
  OAuth2 helpers in Home Assistant cannot be reused.
* Every vehicle request additionally requires an ``x-client-id`` header
  holding the account ID, which is a *different* value from the OAuth client
  ID used to obtain the token.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any
from urllib.parse import quote

import aiohttp

from .const import API_DOMAIN_PATHS, TOKEN_EXPIRY_MARGIN

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)


class PolestarApiError(Exception):
    """Raised for a request that failed and may succeed when retried."""


class PolestarAuthError(PolestarApiError):
    """Raised when the credentials are rejected and re-authentication is due."""


class PolestarForbiddenError(PolestarApiError):
    """Raised when the credential lacks the scope for an endpoint."""


class PolestarNotFoundError(PolestarApiError):
    """Raised when the vehicle reports no data for a domain."""


class PolestarRateLimitError(PolestarApiError):
    """Raised when the daily or per-minute request budget is exhausted."""


class PolestarDataPortalApi:
    """Thin async wrapper around the Data Portal M2M REST API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        client_id: str,
        client_secret: str,
        account_id: str,
        token_url: str,
        delegated_account_id: str | None = None,
    ) -> None:
        """Initialize the client."""
        self._session = session
        self._client_id = client_id
        self._client_secret = client_secret
        self._account_id = account_id
        self._delegated_account_id = delegated_account_id or None

        self._token_url = self._normalize_token_url(token_url)
        self._base_url = self._token_url[: -len("/token")]

        self._access_token: str | None = None
        self._token_type: str = "Bearer"
        self._token_expires_at: float = 0.0
        self._token_lock = asyncio.Lock()

    @staticmethod
    def _normalize_token_url(token_url: str) -> str:
        """Return the token endpoint URL, appending /token when omitted.

        Users copy this value out of the Data Portal, where it is shown both
        with and without the trailing path segment depending on the market.
        """
        url = token_url.strip().rstrip("/")
        if not url:
            raise ValueError("token_url must not be empty")
        if not url.endswith("/token"):
            url = f"{url}/token"
        return url

    @property
    def base_url(self) -> str:
        """Return the API base URL derived from the token endpoint."""
        return self._base_url

    # --- authentication ----------------------------------------------------

    async def async_get_access_token(self, *, force: bool = False) -> str:
        """Return a valid access token, fetching a new one when needed."""
        async with self._token_lock:
            if (
                not force
                and self._access_token is not None
                and time.monotonic() < self._token_expires_at
            ):
                return self._access_token

            # The spec marks `scope` optional. It is deliberately omitted so
            # the portal grants whatever the credential is entitled to;
            # naming a scope the credential does not hold fails the whole
            # token request rather than just that one endpoint.
            payload = {
                "clientId": self._client_id,
                "clientSecret": self._client_secret,
            }

            try:
                async with self._session.post(
                    self._token_url, json=payload, timeout=REQUEST_TIMEOUT
                ) as response:
                    body = await self._read_json(response)

                    if response.status in (400, 401):
                        raise PolestarAuthError(
                            self._oauth_error_message(body, response.status)
                        )
                    if response.status == 429:
                        raise PolestarRateLimitError(
                            "Rate limit reached while requesting a token"
                        )
                    if response.status >= 500:
                        raise PolestarApiError(
                            f"Token endpoint returned HTTP {response.status}"
                        )
                    if response.status != 200:
                        raise PolestarApiError(
                            f"Unexpected token response HTTP {response.status}"
                        )
            except TimeoutError as err:
                raise PolestarApiError("Timeout requesting access token") from err
            except aiohttp.ClientError as err:
                raise PolestarApiError(f"Error requesting access token: {err}") from err

            access_token = body.get("accessToken")
            if not access_token:
                raise PolestarApiError("Token response did not contain accessToken")

            expires_in = body.get("expiresIn")
            try:
                lifetime = float(expires_in)
            except (TypeError, ValueError):
                lifetime = 3600.0

            self._access_token = access_token
            self._token_type = body.get("tokenType") or "Bearer"
            self._token_expires_at = time.monotonic() + max(
                lifetime - TOKEN_EXPIRY_MARGIN, 0.0
            )

            _LOGGER.debug("Obtained Data Portal access token (valid %ss)", lifetime)
            return access_token

    @staticmethod
    def _oauth_error_message(body: dict[str, Any], status: int) -> str:
        """Build a message from an OAuth2ErrorResponse payload."""
        error = body.get("error")
        description = body.get("error_description")
        if error and description:
            return f"{error}: {description}"
        return error or description or f"Token request failed with HTTP {status}"

    # --- requests ----------------------------------------------------------

    async def _async_request(self, path: str) -> dict[str, Any]:
        """Perform an authenticated GET and return the decoded body."""
        token = await self.async_get_access_token()

        for attempt in range(2):
            headers = {
                "Authorization": f"{self._token_type} {token}",
                "x-client-id": self._account_id,
                "Accept": "application/json",
            }
            if self._delegated_account_id:
                headers["x-delegated-account-id"] = self._delegated_account_id

            url = f"{self._base_url}{path}"
            try:
                async with self._session.get(
                    url, headers=headers, timeout=REQUEST_TIMEOUT
                ) as response:
                    # An expired token is indistinguishable from bad
                    # credentials by status alone, so retry once with a fresh
                    # token before giving up and asking the user to re-auth.
                    if response.status == 401 and attempt == 0:
                        token = await self.async_get_access_token(force=True)
                        continue

                    body = await self._read_json(response)
                    self._raise_for_status(response.status, body, url)
                    return body
            except TimeoutError as err:
                raise PolestarApiError(f"Timeout calling {path}") from err
            except aiohttp.ClientError as err:
                raise PolestarApiError(f"Error calling {path}: {err}") from err

        raise PolestarAuthError("Authentication failed after refreshing the token")

    @staticmethod
    def _raise_for_status(status: int, body: dict[str, Any], url: str) -> None:
        """Translate an M2mErrorResponse into a typed exception."""
        if status == 200:
            return

        error = body.get("error") or {}
        message = error.get("message") or f"HTTP {status}"

        if status == 401:
            raise PolestarAuthError(f"Credentials rejected: {message}")
        if status == 403:
            raise PolestarForbiddenError(f"Access denied for {url}: {message}")
        if status == 404:
            raise PolestarNotFoundError(f"No data available at {url}: {message}")
        if status == 429:
            raise PolestarRateLimitError(f"Rate limit reached for {url}: {message}")
        raise PolestarApiError(f"{url} returned HTTP {status}: {message}")

    @staticmethod
    async def _read_json(response: aiohttp.ClientResponse) -> dict[str, Any]:
        """Decode a JSON body, tolerating empty or non-JSON error pages."""
        try:
            body = await response.json(content_type=None)
        except (aiohttp.ContentTypeError, ValueError):
            return {}
        return body if isinstance(body, dict) else {}

    # --- endpoints ---------------------------------------------------------

    async def async_get_vehicles(self) -> list[str]:
        """Return the VINs this credential may access."""
        body = await self._async_request("/v1/vehicles")
        data = body.get("data")
        if not isinstance(data, list):
            return []
        return [vin for vin in data if isinstance(vin, str) and vin]

    async def async_get_domain(self, domain: str, vin: str) -> dict[str, Any]:
        """Return the ``data`` object for one telemetry or charging domain."""
        path = API_DOMAIN_PATHS[domain].format(vin=quote(vin, safe=""))
        body = await self._async_request(path)
        data = body.get("data")
        return data if isinstance(data, dict) else {}
