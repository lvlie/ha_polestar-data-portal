"""Checks that credentials and personal data stay out of logs and dumps."""

from __future__ import annotations

import logging
from typing import Any

import pytest
from aiohttp import ClientSession
from homeassistant.const import CONF_CLIENT_ID, CONF_CLIENT_SECRET
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.polestar_data_portal.api import (
    PolestarApiError,
    PolestarDataPortalApi,
)
from custom_components.polestar_data_portal.const import (
    CONF_ACCOUNT_ID,
    DOMAIN_BATTERY,
)
from custom_components.polestar_data_portal.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.polestar_data_portal.helpers import mask_vin

from .conftest import (
    ACCOUNT_ID,
    BASE_URL,
    CONFIG_DATA,
    TOKEN_URL,
    VIN,
    mock_all_domains,
    mock_full_account,
    mock_token,
    mock_vehicles,
)

SECRET = CONFIG_DATA[CONF_CLIENT_SECRET]


def spy_on_requests(session: ClientSession) -> list[tuple[str, str, dict[str, Any]]]:
    """Record the keyword arguments the client passes to aiohttp.

    ``AiohttpClientMocker`` replaces ``ClientSession._request`` and does not
    keep the redirect setting in ``mock_calls``, so it is captured here. This
    is the only place a test reaches past the public API, and it does so
    because ``allow_redirects`` is a security property that has no observable
    effect through a mock that never redirects.
    """
    calls: list[tuple[str, str, dict[str, Any]]] = []
    inner = session._request

    async def record(method: str, url: Any, **kwargs: Any) -> Any:
        calls.append((method, str(url), kwargs))
        return await inner(method, url, **kwargs)

    object.__setattr__(session, "_request", record)
    return calls


@pytest.mark.parametrize(
    "token_url",
    [
        "http://pc-api.polestar.com/eu-north-1/data-portal/m2m/token",
        "http://example.com/token",
    ],
)
def test_plain_http_token_endpoint_is_refused(token_url: str) -> None:
    """The client secret is never sent over an unencrypted connection."""
    with pytest.raises(ValueError, match="https"):
        PolestarDataPortalApi._normalize_token_url(token_url)


@pytest.mark.parametrize(
    "token_url",
    ["http://127.0.0.1:4010/token", "http://localhost:4010/token"],
)
def test_loopback_may_use_plain_http(token_url: str) -> None:
    """The spec-driven mock server in CI stays reachable."""
    assert PolestarDataPortalApi._normalize_token_url(token_url) == token_url


@pytest.mark.parametrize("token_url", ["not-a-url", "ftp://example.com/token", "//x"])
def test_unusable_token_endpoints_are_refused(token_url: str) -> None:
    """Anything that is not an http(s) URL is rejected up front."""
    with pytest.raises(ValueError):
        PolestarDataPortalApi._normalize_token_url(token_url)


async def test_token_request_does_not_follow_redirects(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A redirect must not replay the client secret to another host."""
    mock_token(aioclient_mock)
    session = async_get_clientsession(hass)
    calls = spy_on_requests(session)
    api = PolestarDataPortalApi(
        session,
        client_id="client_12345",
        client_secret=SECRET,
        account_id=ACCOUNT_ID,
        token_url=TOKEN_URL,
    )

    await api.async_get_access_token()

    method, url, kwargs = calls[0]
    assert method == "POST"
    assert url == TOKEN_URL
    assert kwargs["allow_redirects"] is False


async def test_data_requests_do_not_follow_redirects(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A redirect must not replay the bearer token to another host."""
    mock_token(aioclient_mock)
    mock_vehicles(aioclient_mock, [VIN])
    session = async_get_clientsession(hass)
    calls = spy_on_requests(session)
    api = PolestarDataPortalApi(
        session,
        client_id="client_12345",
        client_secret=SECRET,
        account_id=ACCOUNT_ID,
        token_url=TOKEN_URL,
    )

    await api.async_get_vehicles()

    gets = [call for call in calls if call[0] == "GET"]
    assert gets, "no GET was recorded"
    for _method, _url, kwargs in gets:
        assert "Authorization" in kwargs["headers"]
        assert kwargs["allow_redirects"] is False


async def test_a_redirected_response_is_reported_not_parsed(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A 3xx is surfaced as an error rather than treated as data."""
    mock_token(aioclient_mock)
    aioclient_mock.get(
        f"{BASE_URL}/v1/vehicles",
        status=302,
        headers={"Location": "https://example.invalid/v1/vehicles"},
    )
    api = PolestarDataPortalApi(
        async_get_clientsession(hass),
        client_id="client_12345",
        client_secret=SECRET,
        account_id=ACCOUNT_ID,
        token_url=TOKEN_URL,
    )

    with pytest.raises(PolestarApiError, match="redirected"):
        await api.async_get_vehicles()


async def test_secrets_never_reach_the_log(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Debug logging is safe to paste into a bug report.

    Runs the whole setup path with debug logging on and asserts that the
    credentials and the full VIN are absent from everything logged.
    """
    caplog.set_level(logging.DEBUG)
    mock_full_account(aioclient_mock)

    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # pytest-homeassistant-custom-component's mock Store logs every payload it
    # writes, which real Home Assistant does not do. Judge production loggers.
    log = "\n".join(
        record.getMessage()
        for record in caplog.records
        if not record.name.startswith("pytest_homeassistant_custom_component")
    )

    assert SECRET not in log
    assert CONFIG_DATA[CONF_CLIENT_ID] not in log
    assert ACCOUNT_ID not in log
    assert "test-access-token" not in log
    # The VIN identifies the owner's car, so only its masked form may appear.
    assert VIN not in log


async def test_failure_messages_do_not_leak_the_vin(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Error paths mask the VIN too, not just the happy path."""
    caplog.set_level(logging.DEBUG)
    mock_token(aioclient_mock)
    mock_vehicles(aioclient_mock, [VIN])
    mock_all_domains(aioclient_mock, VIN, status_for={DOMAIN_BATTERY: 500})

    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    log = "\n".join(
        record.getMessage()
        for record in caplog.records
        if not record.name.startswith("pytest_homeassistant_custom_component")
    )
    assert VIN not in log
    assert mask_vin(VIN) in log


async def test_a_failed_poll_does_not_leak_the_vin(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The total-failure path masks the VIN too.

    Home Assistant logs an ``UpdateFailed`` message verbatim, so a poll where
    no domain answers is the one error path that reaches the log without going
    through the client.
    """
    mock_full_account(aioclient_mock)
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry.runtime_data.coordinators[0]
    aioclient_mock.clear_requests()
    mock_token(aioclient_mock)
    mock_all_domains(
        aioclient_mock,
        VIN,
        status_for=dict.fromkeys(coordinator.supported_domains, 503),
    )

    caplog.clear()
    caplog.set_level(logging.DEBUG)
    await coordinator.async_refresh()

    assert not coordinator.last_update_success
    log = "\n".join(
        record.getMessage()
        for record in caplog.records
        if not record.name.startswith("pytest_homeassistant_custom_component")
    )
    assert VIN not in log
    assert mask_vin(VIN) in log


async def test_diagnostics_redact_credentials_and_location(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The diagnostics download is safe to attach to an issue."""
    mock_full_account(aioclient_mock)
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    diagnostics = await async_get_config_entry_diagnostics(hass, mock_config_entry)
    dumped = str(diagnostics)

    for secret in (SECRET, CONFIG_DATA[CONF_CLIENT_ID], ACCOUNT_ID, VIN):
        assert secret not in dumped

    entry_data = diagnostics["entry"]["data"]
    assert entry_data[CONF_CLIENT_SECRET] == "**REDACTED**"
    assert entry_data[CONF_CLIENT_ID] == "**REDACTED**"
    assert entry_data[CONF_ACCOUNT_ID] == "**REDACTED**"

    # The supported domains are the point of the dump and must survive.
    assert diagnostics["vehicles"][0]["supported_domains"]
    assert diagnostics["vehicles"][0]["required_scopes"]


async def test_diagnostics_redact_gps_coordinates(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Position data is personal data and is stripped from diagnostics."""
    mock_full_account(
        aioclient_mock,
        overrides={
            "location": {"coordinate": {"latitude": 52.3702, "longitude": 4.8952}}
        },
    )
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    dumped = str(await async_get_config_entry_diagnostics(hass, mock_config_entry))

    assert "52.3702" not in dumped
    assert "4.8952" not in dumped


@pytest.mark.parametrize(
    ("vin", "expected"),
    [
        ("YV1CZ0000000000000", "****0000"),
        ("LPSVS0000000001234", "****1234"),
        ("", "****"),
        ("ABC", "****"),
    ],
)
def test_mask_vin(vin: str, expected: str) -> None:
    """Only the last four characters of a VIN survive masking."""
    assert mask_vin(vin) == expected


async def test_secret_is_not_written_to_the_discovery_cache(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
    hass_storage: dict,
) -> None:
    """The on-disk discovery cache holds no credentials."""
    mock_full_account(aioclient_mock)
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    stored = str(hass_storage.get("polestar_data_portal.discovery", {}))
    assert SECRET not in stored
    assert CONFIG_DATA[CONF_CLIENT_ID] not in stored
