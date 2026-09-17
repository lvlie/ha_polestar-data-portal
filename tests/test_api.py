"""Tests for the Data Portal API client."""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.polestar_data_portal.api import (
    PolestarApiError,
    PolestarAuthError,
    PolestarDataPortalApi,
    PolestarForbiddenError,
    PolestarNotFoundError,
    PolestarRateLimitError,
)

from .conftest import ACCOUNT_ID, BASE_URL, TOKEN_URL, VIN, mock_token, mock_vehicles


def build_api(hass: HomeAssistant, **kwargs: str) -> PolestarDataPortalApi:
    """Return a client wired to the mocked Home Assistant session."""
    options: dict[str, str] = {
        "client_id": "client_12345",
        "client_secret": "secret_67890",
        "account_id": ACCOUNT_ID,
        "token_url": TOKEN_URL,
    }
    options.update(kwargs)
    return PolestarDataPortalApi(async_get_clientsession(hass), **options)


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        (f"{BASE_URL}/token", f"{BASE_URL}/token"),
        # The portal shows the base URL without the path in some markets.
        (BASE_URL, f"{BASE_URL}/token"),
        (f"{BASE_URL}/token/", f"{BASE_URL}/token"),
        (f"  {BASE_URL}/token  ", f"{BASE_URL}/token"),
    ],
)
def test_token_url_is_normalized(given: str, expected: str) -> None:
    """The token endpoint accepts the shapes users paste from the portal."""
    assert PolestarDataPortalApi._normalize_token_url(given) == expected


def test_empty_token_url_is_rejected() -> None:
    """An empty token endpoint is a configuration error."""
    with pytest.raises(ValueError):
        PolestarDataPortalApi._normalize_token_url("   ")


async def test_token_uses_camel_case_fields(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The non-standard camelCase token contract is honoured in both directions."""
    mock_token(aioclient_mock)
    api = build_api(hass)

    assert await api.async_get_access_token() == "test-access-token"

    method, url, data, _ = aioclient_mock.mock_calls[0]
    assert method == "POST"
    assert str(url) == TOKEN_URL
    # The spec names these clientId/clientSecret, not client_id/client_secret.
    assert data == {"clientId": "client_12345", "clientSecret": "secret_67890"}
    # Scope is deliberately omitted so the portal grants the credential's own
    # entitlement rather than failing on an unheld scope.
    assert "scope" not in data


async def test_token_is_cached(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A valid token is reused instead of re-requested on every call."""
    mock_token(aioclient_mock)
    api = build_api(hass)

    await api.async_get_access_token()
    await api.async_get_access_token()

    assert aioclient_mock.call_count == 1


async def test_bad_credentials_raise_auth_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """HTTP 401 on the token endpoint asks the user to re-authenticate."""
    aioclient_mock.post(
        TOKEN_URL,
        status=401,
        json={"error": "invalid_client", "error_description": "bad secret"},
    )
    api = build_api(hass)

    with pytest.raises(PolestarAuthError, match="bad secret"):
        await api.async_get_access_token()


async def test_requests_send_account_header(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Every vehicle request carries the bearer token and x-client-id header."""
    mock_token(aioclient_mock)
    mock_vehicles(aioclient_mock)
    api = build_api(hass)

    assert await api.async_get_vehicles() == [
        "YV1CZ0000000000000",
        "LPSVS0000000000000",
    ]

    headers = aioclient_mock.mock_calls[-1][3]
    assert headers["Authorization"] == "Bearer test-access-token"
    # The account ID is a different value from the OAuth client ID.
    assert headers["x-client-id"] == ACCOUNT_ID
    assert "x-delegated-account-id" not in headers


async def test_delegated_account_header(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Third-party credentials may target another account's shared vehicles."""
    mock_token(aioclient_mock)
    mock_vehicles(aioclient_mock)
    api = build_api(hass, delegated_account_id="jane.doe@acme.com")

    await api.async_get_vehicles()

    headers = aioclient_mock.mock_calls[-1][3]
    assert headers["x-delegated-account-id"] == "jane.doe@acme.com"


async def test_expired_token_is_refreshed_once(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A 401 on a data call retries once with a freshly minted token."""
    mock_token(aioclient_mock)
    aioclient_mock.get(f"{BASE_URL}/v1/vehicles", status=401)
    api = build_api(hass)

    with pytest.raises(PolestarAuthError):
        await api.async_get_vehicles()

    # Token, failing call, refreshed token, failing call again.
    assert aioclient_mock.call_count == 4


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (403, PolestarForbiddenError),
        (404, PolestarNotFoundError),
        (429, PolestarRateLimitError),
        (500, PolestarApiError),
        (503, PolestarApiError),
    ],
)
async def test_error_statuses_are_typed(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    status: int,
    expected: type[Exception],
) -> None:
    """Documented error statuses map onto distinct exceptions."""
    mock_token(aioclient_mock)
    aioclient_mock.get(
        f"{BASE_URL}/v1/vehicles/{VIN}/telemetry/battery",
        status=status,
        json={"error": {"code": "err", "message": "nope"}},
    )
    api = build_api(hass)

    with pytest.raises(expected):
        await api.async_get_domain("battery", VIN)


async def test_domain_returns_unwrapped_data(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Responses are unwrapped from their ``data`` envelope."""
    mock_token(aioclient_mock)
    aioclient_mock.get(
        f"{BASE_URL}/v1/vehicles/{VIN}/telemetry/odometer",
        json={"data": {"odometerMeters": 123456}, "meta": {"vin": VIN}},
    )
    api = build_api(hass)

    assert await api.async_get_domain("odometer", VIN) == {"odometerMeters": 123456}


async def test_a_second_request_does_not_refresh_the_token_again(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Only the first of several 401s mints a new token.

    Each poll fires one request per domain concurrently. They all hold the
    same token, so when it expires they all get a 401 at once. Only the first
    to reach the lock should refresh; the rest must pick up the new token
    instead of minting one each and spending the daily budget on it.
    """
    mock_token(aioclient_mock)
    api = build_api(hass)

    _, generation = await api._async_token()
    assert aioclient_mock.call_count == 1

    # First request to notice the 401 refreshes.
    _, refreshed_generation = await api._async_token(stale_generation=generation)
    assert aioclient_mock.call_count == 2
    assert refreshed_generation != generation

    # The others were holding the same, now superseded, generation.
    for _ in range(3):
        _, current = await api._async_token(stale_generation=generation)
        assert current == refreshed_generation

    assert aioclient_mock.call_count == 2


async def test_identical_replacement_token_still_counts_as_a_refresh(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Refresh tracking cannot rely on the token string changing.

    The mocked endpoint returns the same token value every time, as a real
    server may when it reissues before expiry.
    """
    mock_token(aioclient_mock)
    api = build_api(hass)

    first_token, first_generation = await api._async_token()
    second_token, second_generation = await api._async_token(
        stale_generation=first_generation
    )

    assert first_token == second_token
    assert second_generation != first_generation
