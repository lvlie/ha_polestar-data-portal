"""Tests for the polling behaviour of the coordinator."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.polestar_data_portal.const import (
    DOMAIN_BATTERY,
    DOMAIN_ODOMETER,
)
from custom_components.polestar_data_portal.discovery import DiscoveryCache

from .conftest import (
    VIN,
    mock_all_domains,
    mock_full_account,
    mock_token,
    mock_vehicles,
)


async def setup(hass: HomeAssistant, entry: MockConfigEntry, **kwargs: object) -> None:
    """Set up the integration with a fully mocked account."""
    mock_full_account(aioclient_mock=kwargs.pop("aioclient_mock"), **kwargs)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_one_failing_domain_keeps_the_others(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A single flaky endpoint must not blank out every entity."""
    await setup(hass, mock_config_entry, aioclient_mock=aioclient_mock)
    coordinator = mock_config_entry.runtime_data.coordinators[0]
    before = coordinator.data[DOMAIN_BATTERY]

    # Next poll: battery breaks, everything else still answers.
    aioclient_mock.clear_requests()
    mock_token(aioclient_mock)
    mock_all_domains(aioclient_mock, VIN, status_for={DOMAIN_BATTERY: 500})

    await coordinator.async_refresh()

    assert coordinator.last_update_success
    # The stale battery payload is kept rather than dropped, so the sensors
    # hold their last known values instead of flapping to unavailable.
    assert coordinator.data[DOMAIN_BATTERY] == before
    assert coordinator.data[DOMAIN_ODOMETER]


async def test_total_failure_marks_the_update_failed(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """When nothing answers, the coordinator reports failure."""
    await setup(hass, mock_config_entry, aioclient_mock=aioclient_mock)
    coordinator = mock_config_entry.runtime_data.coordinators[0]

    aioclient_mock.clear_requests()
    mock_token(aioclient_mock)
    mock_all_domains(
        aioclient_mock,
        VIN,
        status_for=dict.fromkeys(coordinator.supported_domains, 503),
    )

    await coordinator.async_refresh()

    assert not coordinator.last_update_success


async def test_scope_revoked_mid_run_stops_polling_that_domain(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A 403 after setup drops the domain instead of retrying it forever."""
    await setup(hass, mock_config_entry, aioclient_mock=aioclient_mock)
    coordinator = mock_config_entry.runtime_data.coordinators[0]
    assert DOMAIN_ODOMETER in coordinator.supported_domains

    aioclient_mock.clear_requests()
    mock_token(aioclient_mock)
    mock_all_domains(aioclient_mock, VIN, status_for={DOMAIN_ODOMETER: 403})
    await coordinator.async_refresh()

    assert DOMAIN_ODOMETER not in coordinator.supported_domains

    # The following poll no longer spends a request on it.
    aioclient_mock.clear_requests()
    mock_token(aioclient_mock)
    mock_all_domains(aioclient_mock, VIN)
    await coordinator.async_refresh()

    requested = [str(call[1]) for call in aioclient_mock.mock_calls]
    assert not any("telemetry/odometer" in url for url in requested)


async def test_rate_limit_does_not_crash_the_poll(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """HTTP 429 is survivable: previous data is kept and polling continues."""
    await setup(hass, mock_config_entry, aioclient_mock=aioclient_mock)
    coordinator = mock_config_entry.runtime_data.coordinators[0]
    supported = set(coordinator.supported_domains)

    aioclient_mock.clear_requests()
    mock_token(aioclient_mock)
    mock_all_domains(aioclient_mock, VIN, status_for={DOMAIN_BATTERY: 429})
    await coordinator.async_refresh()

    # Being throttled is not the same as losing the scope.
    assert coordinator.supported_domains == supported
    assert coordinator.last_update_success


async def test_expired_credentials_mid_run_request_reauth(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A 401 during polling starts the re-authentication flow."""
    await setup(hass, mock_config_entry, aioclient_mock=aioclient_mock)
    coordinator = mock_config_entry.runtime_data.coordinators[0]

    aioclient_mock.clear_requests()
    mock_token(aioclient_mock)
    mock_all_domains(
        aioclient_mock,
        VIN,
        status_for=dict.fromkeys(coordinator.supported_domains, 401),
    )

    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert not coordinator.last_update_success
    assert any(
        flow["context"]["source"] == "reauth"
        for flow in hass.config_entries.flow.async_progress()
    )


async def test_stale_discovery_cache_is_ignored(
    hass: HomeAssistant, hass_storage: dict
) -> None:
    """A cache older than the TTL is discarded so domains get re-probed."""
    cache = DiscoveryCache(hass)
    await cache.async_set("entry-1", {VIN: [DOMAIN_BATTERY]})
    assert await cache.async_get("entry-1") == {VIN: [DOMAIN_BATTERY]}

    stored = hass_storage["polestar_data_portal.discovery"]["data"]
    stored["entry-1"]["discovered_at"] = (
        datetime.now(UTC) - timedelta(days=8)
    ).isoformat()

    assert await cache.async_get("entry-1") is None


@pytest.mark.parametrize(
    "stored",
    [
        {"discovered_at": "not-a-date", "vehicles": {VIN: ["battery"]}},
        {"vehicles": {VIN: ["battery"]}},
        {"discovered_at": datetime.now(UTC).isoformat(), "vehicles": {}},
        {"discovered_at": datetime.now(UTC).isoformat()},
        "nonsense",
    ],
)
async def test_corrupt_discovery_cache_is_ignored(
    hass: HomeAssistant, hass_storage: dict, stored: object
) -> None:
    """A damaged cache falls back to a fresh probe instead of raising."""
    hass_storage["polestar_data_portal.discovery"] = {
        "version": 1,
        "minor_version": 1,
        "key": "polestar_data_portal.discovery",
        "data": {"entry-1": stored},
    }

    assert await DiscoveryCache(hass).async_get("entry-1") is None


async def test_changing_options_clears_the_discovery_cache(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Reconfiguring is the supported way to rediscover vehicles and scopes."""
    denied = {DOMAIN_ODOMETER}
    mock_token(aioclient_mock)
    mock_vehicles(aioclient_mock, [VIN])
    mock_all_domains(aioclient_mock, VIN, status_for=dict.fromkeys(denied, 403))
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry.runtime_data.coordinators[0]
    assert DOMAIN_ODOMETER not in coordinator.supported_domains

    # The scope is granted in the portal; the full account now answers.
    aioclient_mock.clear_requests()
    mock_full_account(aioclient_mock)

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    await hass.config_entries.options.async_configure(
        result["flow_id"], {"scan_interval_minutes": 30}
    )
    await hass.async_block_till_done()

    coordinator = mock_config_entry.runtime_data.coordinators[0]
    assert DOMAIN_ODOMETER in coordinator.supported_domains
    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert coordinator.update_interval == timedelta(minutes=30)
