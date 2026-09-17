"""Tests for the Polestar Data Portal config flow."""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_CLIENT_ID, CONF_CLIENT_SECRET
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.polestar_data_portal.const import (
    CONF_ACCOUNT_ID,
    CONF_DELEGATED_ACCOUNT_ID,
    CONF_SCAN_INTERVAL_MINUTES,
    CONF_TOKEN_URL,
    DOMAIN,
)

from .conftest import (
    ACCOUNT_ID,
    CONFIG_DATA,
    TOKEN_URL,
    mock_token,
    mock_vehicles,
)


async def start_flow(hass: HomeAssistant) -> dict[str, Any]:
    """Begin a user-initiated config flow."""
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )


async def test_user_flow_creates_entry(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_setup_entry: Any,
) -> None:
    """Valid credentials create an entry keyed on the account ID."""
    mock_token(aioclient_mock)
    mock_vehicles(aioclient_mock)

    result = await start_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    # The portal URL is offered so users do not guess a market-specific path.
    assert result["description_placeholders"] == {
        "portal_url": "https://data-portal.polestar.com"
    }

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], CONFIG_DATA
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Polestar Data Portal"
    assert result["data"] == CONFIG_DATA
    assert result["result"].unique_id == ACCOUNT_ID


async def test_credentials_are_trimmed(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_setup_entry: Any,
) -> None:
    """Values pasted from the portal keep working despite stray whitespace."""
    mock_token(aioclient_mock)
    mock_vehicles(aioclient_mock)

    result = await start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {key: f"  {value}  " for key, value in CONFIG_DATA.items()},
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == CONFIG_DATA


@pytest.mark.parametrize(
    ("status", "expected_error"),
    [(401, "invalid_auth"), (400, "invalid_auth"), (503, "cannot_connect")],
)
async def test_token_errors_are_reported(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    status: int,
    expected_error: str,
) -> None:
    """Token failures are shown on the form rather than aborting the flow."""
    aioclient_mock.post(TOKEN_URL, status=status, json={"error": "nope"})

    result = await start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], CONFIG_DATA
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected_error}


async def test_recovers_after_an_error(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_setup_entry: Any,
) -> None:
    """A corrected secret succeeds without restarting the flow."""
    aioclient_mock.post(TOKEN_URL, status=401, json={"error": "bad"})

    result = await start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], CONFIG_DATA
    )
    assert result["errors"] == {"base": "invalid_auth"}

    aioclient_mock.clear_requests()
    mock_token(aioclient_mock)
    mock_vehicles(aioclient_mock)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], CONFIG_DATA
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_account_without_vehicles(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Working credentials with no linked car explain what is wrong."""
    mock_token(aioclient_mock)
    mock_vehicles(aioclient_mock, [])

    result = await start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], CONFIG_DATA
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "no_vehicles"}


async def test_invalid_token_url(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """An unusable token endpoint is flagged on its own field."""
    result = await start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**CONFIG_DATA, CONF_TOKEN_URL: "/"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_TOKEN_URL: "invalid_token_url"}


async def test_duplicate_account_is_rejected(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The same Data Portal account cannot be added twice."""
    mock_config_entry.add_to_hass(hass)
    mock_token(aioclient_mock)
    mock_vehicles(aioclient_mock)

    result = await start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], CONFIG_DATA
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_updates_credentials(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
    mock_setup_entry: Any,
) -> None:
    """Re-auth replaces expired credentials on the existing entry."""
    mock_config_entry.add_to_hass(hass)
    mock_token(aioclient_mock)
    mock_vehicles(aioclient_mock)

    result = await mock_config_entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    new_data = {**CONFIG_DATA, CONF_CLIENT_SECRET: "rotated_secret"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], new_data)
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data[CONF_CLIENT_SECRET] == "rotated_secret"
    # The account keeps its identity so entities are not recreated.
    assert mock_config_entry.data[CONF_ACCOUNT_ID] == ACCOUNT_ID


async def test_reauth_rejects_bad_credentials(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Re-auth keeps asking while the new credentials are still wrong."""
    mock_config_entry.add_to_hass(hass)
    aioclient_mock.post(TOKEN_URL, status=401, json={"error": "still bad"})

    result = await mock_config_entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], CONFIG_DATA
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_options_flow_sets_interval(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The polling interval is configurable after setup."""
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_INTERVAL_MINUTES: 30}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options == {CONF_SCAN_INTERVAL_MINUTES: 30}


async def test_form_field_order_matches_the_portal(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The form lists credentials in the order the Data Portal shows them.

    Users copy these four values straight down the credential page, so the
    order is part of the interface, not an accident of the schema.
    """
    result = await start_flow(hass)
    fields = [key.schema for key in result["data_schema"].schema]

    assert fields == [
        CONF_CLIENT_ID,
        CONF_ACCOUNT_ID,
        CONF_CLIENT_SECRET,
        CONF_TOKEN_URL,
        CONF_DELEGATED_ACCOUNT_ID,
    ]


async def test_reauth_form_uses_the_same_order(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Re-authentication shows the same layout as first-time setup."""
    mock_config_entry.add_to_hass(hass)

    result = await mock_config_entry.start_reauth_flow(hass)
    fields = [key.schema for key in result["data_schema"].schema]

    assert fields == [
        CONF_CLIENT_ID,
        CONF_ACCOUNT_ID,
        CONF_CLIENT_SECRET,
        CONF_TOKEN_URL,
        CONF_DELEGATED_ACCOUNT_ID,
    ]
