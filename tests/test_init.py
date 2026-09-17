"""Tests for setting up and tearing down the integration."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.polestar_data_portal.const import (
    API_DOMAIN_PATHS,
    CONF_SCAN_INTERVAL_MINUTES,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DOMAIN,
    DOMAIN_BATTERY,
    DOMAIN_LOCATION,
    DOMAIN_ODOMETER,
)

from .conftest import (
    BASE_URL,
    ENTITY_PREFIX,
    TOKEN_URL,
    VIN,
    mock_all_domains,
    mock_full_account,
    mock_token,
    mock_vehicles,
)


async def setup_integration(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Add and set up the config entry."""
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_setup_and_unload(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A working account loads and unloads cleanly."""
    mock_full_account(aioclient_mock)
    await setup_integration(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert len(mock_config_entry.runtime_data.coordinators) == 1
    assert mock_config_entry.runtime_data.coordinators[0].vin == VIN

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED


async def test_entities_are_created(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Sensors, binary sensors and the tracker all appear."""
    mock_full_account(aioclient_mock)
    await setup_integration(hass, mock_config_entry)

    assert hass.states.get(f"sensor.{ENTITY_PREFIX}_battery")
    assert hass.states.get(f"sensor.{ENTITY_PREFIX}_odometer")
    assert hass.states.get(f"binary_sensor.{ENTITY_PREFIX}_front_left_door")
    assert hass.states.get(f"device_tracker.{ENTITY_PREFIX}_location")


async def test_bad_credentials_trigger_reauth(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Rejected credentials put the entry into the re-auth state."""
    aioclient_mock.post(TOKEN_URL, status=401, json={"error": "invalid_client"})
    await setup_integration(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR
    assert any(
        flow["context"]["source"] == "reauth"
        for flow in hass.config_entries.flow.async_progress()
    )


async def test_unreachable_portal_retries(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A server-side outage leaves the entry retrying rather than failed."""
    mock_token(aioclient_mock)
    aioclient_mock.get(f"{BASE_URL}/v1/vehicles", status=503, json={})
    await setup_integration(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_missing_scopes_are_skipped(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Endpoints the credential cannot read produce no entities at all."""
    denied = {DOMAIN_LOCATION, DOMAIN_ODOMETER}
    mock_token(aioclient_mock)
    mock_vehicles(aioclient_mock, [VIN])
    mock_all_domains(aioclient_mock, VIN, status_for=dict.fromkeys(denied, 403))
    await setup_integration(hass, mock_config_entry)

    coordinator = mock_config_entry.runtime_data.coordinators[0]
    assert not denied & coordinator.supported_domains
    assert DOMAIN_BATTERY in coordinator.supported_domains

    # No always-unknown entities are left behind for the denied domains.
    assert hass.states.get(f"sensor.{ENTITY_PREFIX}_odometer") is None
    assert hass.states.get(f"device_tracker.{ENTITY_PREFIX}_location") is None
    assert hass.states.get(f"sensor.{ENTITY_PREFIX}_battery")


async def test_setup_does_not_double_fetch(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Discovery hands its payloads to the first refresh instead of re-reading.

    Setup should cost one token, one vehicle list and one request per
    documented domain -- not two rounds of domain requests.
    """
    mock_full_account(aioclient_mock)
    await setup_integration(hass, mock_config_entry)

    assert aioclient_mock.call_count == 2 + len(API_DOMAIN_PATHS)


async def test_second_setup_reuses_discovery(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A restart skips the vehicle list and only polls the known domains.

    This is what keeps a restart loop from burning through the daily request
    allowance.
    """
    denied = {DOMAIN_LOCATION, DOMAIN_ODOMETER}
    mock_token(aioclient_mock)
    mock_vehicles(aioclient_mock, [VIN])
    mock_all_domains(aioclient_mock, VIN, status_for=dict.fromkeys(denied, 403))
    await setup_integration(hass, mock_config_entry)

    await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    aioclient_mock.clear_requests()

    mock_token(aioclient_mock)
    mock_vehicles(aioclient_mock, [VIN])
    mock_all_domains(aioclient_mock, VIN, status_for=dict.fromkeys(denied, 403))

    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # One token plus the 13 cached domains: no vehicle list, and no requests
    # to the two endpoints already known to be denied.
    expected = 1 + len(API_DOMAIN_PATHS) - len(denied)
    assert aioclient_mock.call_count == expected


async def test_default_interval_respects_budget(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Many vehicles raise the default interval to stay inside the allowance."""
    vins = [f"YV1CZ00000000000{index:02d}" for index in range(10)]
    mock_full_account(aioclient_mock, vins)
    await setup_integration(hass, mock_config_entry)

    coordinators = mock_config_entry.runtime_data.coordinators
    assert len(coordinators) == 10

    # 10 vehicles x 15 domains is 150 requests per poll, which does not fit in
    # the budget at the 15 minute default.
    interval = coordinators[0].update_interval
    assert interval > timedelta(minutes=DEFAULT_SCAN_INTERVAL_MINUTES)
    assert all(coordinator.update_interval == interval for coordinator in coordinators)


async def test_configured_interval_is_honoured(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """An explicit interval from the options flow wins over the default."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, options={CONF_SCAN_INTERVAL_MINUTES: 60}
    )
    mock_full_account(aioclient_mock)

    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry.runtime_data.coordinators[0]
    assert coordinator.update_interval == timedelta(minutes=60)


async def test_single_vehicle_device_name_is_short(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """One car on the account produces sensor.polestar_* entity IDs."""
    mock_full_account(aioclient_mock)
    await setup_integration(hass, mock_config_entry)

    devices = dr.async_get(hass)
    device = devices.async_get_device(identifiers={(DOMAIN, VIN)})
    assert device.name == "Polestar"
    # The full VIN is still recorded, just not in the name.
    assert device.serial_number == VIN

    assert hass.states.get("sensor.polestar_battery")


async def test_several_vehicles_get_distinct_names(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A second car adds a VIN suffix so the devices stay distinguishable."""
    vins = ["YV1CZ0000000123456", "YV1CZ0000000654321"]
    mock_full_account(aioclient_mock, vins)
    await setup_integration(hass, mock_config_entry)

    devices = dr.async_get(hass)
    names = {devices.async_get_device(identifiers={(DOMAIN, vin)}).name for vin in vins}
    assert names == {"Polestar 123456", "Polestar 654321"}

    assert hass.states.get("sensor.polestar_123456_battery")
    assert hass.states.get("sensor.polestar_654321_battery")
    assert hass.states.get("sensor.polestar_battery") is None


async def test_a_vehicle_that_fails_setup_still_shapes_the_names(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Names come from the account's vehicle list, not from what set up.

    Otherwise a car that temporarily loses a scope would silently rename the
    other cars' devices, churning their entity IDs.
    """
    vins = ["YV1CZ0000000123456", "YV1CZ0000000654321"]
    mock_token(aioclient_mock)
    mock_vehicles(aioclient_mock, vins)
    mock_all_domains(aioclient_mock, vins[0])
    # The second car answers nothing, so it is skipped entirely.
    mock_all_domains(
        aioclient_mock, vins[1], status_for=dict.fromkeys(API_DOMAIN_PATHS, 403)
    )
    await setup_integration(hass, mock_config_entry)

    assert len(mock_config_entry.runtime_data.coordinators) == 1
    devices = dr.async_get(hass)
    device = devices.async_get_device(identifiers={(DOMAIN, vins[0])})
    assert device.name == "Polestar 123456"
