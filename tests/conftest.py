"""Fixtures for the Polestar Data Portal tests."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any
from unittest.mock import patch

import pytest
from homeassistant.const import CONF_CLIENT_ID, CONF_CLIENT_SECRET
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.polestar_data_portal.const import (
    API_DOMAIN_PATHS,
    CONF_ACCOUNT_ID,
    CONF_TOKEN_URL,
    DOMAIN,
)

from .openapi import response_for, telemetry_payload

BASE_URL = "https://pc-api.polestar.com/eu-north-1/data-portal/m2m"
TOKEN_URL = f"{BASE_URL}/token"

VIN = "YV1CZ0000000000000"
ACCOUNT_ID = "cf50b789-4e95-4636-977d-4ffb10164d11"

CONFIG_DATA = {
    CONF_CLIENT_ID: "client_12345",
    CONF_CLIENT_SECRET: "secret_67890",
    CONF_ACCOUNT_ID: ACCOUNT_ID,
    CONF_TOKEN_URL: TOKEN_URL,
}

TOKEN_RESPONSE = {
    "accessToken": "test-access-token",
    "expiresIn": 3600,
    "tokenType": "Bearer",
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: None,
) -> Generator[None]:
    """Make the custom component loadable in every test."""
    yield


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a config entry for the integration."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Polestar Data Portal",
        data=CONFIG_DATA,
        unique_id=ACCOUNT_ID,
    )


def mock_token(aioclient_mock: AiohttpClientMocker, **kwargs: Any) -> None:
    """Register the token endpoint."""
    aioclient_mock.post(TOKEN_URL, json=TOKEN_RESPONSE, **kwargs)


def mock_vehicles(
    aioclient_mock: AiohttpClientMocker, vins: list[str] | None = None
) -> None:
    """Register the vehicle list endpoint."""
    body = response_for("/v1/vehicles")
    if vins is not None:
        body = {"data": vins, "meta": {"count": len(vins)}}
    aioclient_mock.get(f"{BASE_URL}/v1/vehicles", json=body)


def mock_all_domains(
    aioclient_mock: AiohttpClientMocker,
    vin: str = VIN,
    *,
    skip: set[str] | None = None,
    status_for: dict[str, int] | None = None,
    overrides: dict[str, dict[str, Any]] | None = None,
) -> None:
    """Register every documented telemetry and charging endpoint.

    ``skip`` leaves a domain unregistered and ``status_for`` answers a domain
    with an error status, so tests can reproduce a credential that lacks a
    scope. ``overrides`` replaces individual fields in the spec-derived payload
    of a domain.
    """
    skip = skip or set()
    status_for = status_for or {}
    overrides = overrides or {}

    for domain, template in API_DOMAIN_PATHS.items():
        if domain in skip:
            continue

        url = f"{BASE_URL}{template.format(vin=vin)}"
        if (status := status_for.get(domain)) is not None:
            aioclient_mock.get(
                url,
                status=status,
                json={"error": {"code": "forbidden", "message": "no scope"}},
            )
            continue

        suffix = template.split("{vin}/", 1)[1]
        body = telemetry_payload(suffix, vin)
        if (override := overrides.get(domain)) and isinstance(body.get("data"), dict):
            body["data"].update(override)
        aioclient_mock.get(url, json=body)


def mock_full_account(
    aioclient_mock: AiohttpClientMocker,
    vins: list[str] | None = None,
    **kwargs: Any,
) -> None:
    """Register a complete, working account."""
    mock_token(aioclient_mock)
    mock_vehicles(aioclient_mock, vins if vins is not None else [VIN])
    for vin in vins if vins is not None else [VIN]:
        mock_all_domains(aioclient_mock, vin, **kwargs)


@pytest.fixture
def mock_setup_entry() -> Generator[Any]:
    """Prevent the integration from being set up during config flow tests."""
    with patch(
        "custom_components.polestar_data_portal.async_setup_entry",
        return_value=True,
    ) as mock:
        yield mock
