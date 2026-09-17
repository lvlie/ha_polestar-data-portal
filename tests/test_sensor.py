"""Tests for the entity platforms."""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.polestar_data_portal.const import (
    DOMAIN_BATTERY,
    DOMAIN_EXTERIOR,
    DOMAIN_HEALTH,
    DOMAIN_LOCATION,
    DOMAIN_ODOMETER,
)

from .conftest import VIN, mock_full_account

PREFIX = f"polestar_{VIN.lower()}"


async def setup_with(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    entry: MockConfigEntry,
    overrides: dict[str, dict[str, Any]] | None = None,
) -> None:
    """Set up the integration with tweaked telemetry payloads."""
    mock_full_account(aioclient_mock, overrides=overrides)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_battery_values(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Battery readings and their units come through unchanged."""
    await setup_with(
        hass,
        aioclient_mock,
        mock_config_entry,
        {DOMAIN_BATTERY: {"batteryChargeLevelPercentage": 73.5}},
    )

    state = hass.states.get(f"sensor.{PREFIX}_battery")
    assert state.state == "73.5"
    assert state.attributes["device_class"] == "battery"
    assert state.attributes["unit_of_measurement"] == "%"


async def test_enum_prefix_is_stripped(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Protobuf enum values become readable Home Assistant options."""
    await setup_with(
        hass,
        aioclient_mock,
        mock_config_entry,
        {DOMAIN_BATTERY: {"chargingStatusV2": "CHARGING_STATUS_V2_SMART_CHARGING"}},
    )

    state = hass.states.get(f"sensor.{PREFIX}_charging_status")
    assert state.state == "smart_charging"
    assert state.state in state.attributes["options"]


async def test_placeholder_enum_is_unknown(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """An UNSPECIFIED enum reads as unknown, never as an invalid option."""
    await setup_with(
        hass,
        aioclient_mock,
        mock_config_entry,
        {DOMAIN_BATTERY: {"chargingStatusV2": "CHARGING_STATUS_V2_UNSPECIFIED"}},
    )

    state = hass.states.get(f"sensor.{PREFIX}_charging_status")
    assert state.state == STATE_UNKNOWN
    assert "unspecified" not in state.attributes["options"]


async def test_unknown_enum_value_is_not_reported(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A value added upstream but absent from the spec does not break the sensor."""
    await setup_with(
        hass,
        aioclient_mock,
        mock_config_entry,
        {DOMAIN_BATTERY: {"chargingType": "CHARGING_TYPE_PLASMA"}},
    )

    # Home Assistant refuses an enum state outside `options`, so an unmapped
    # value has to read as unknown instead of reaching the state machine.
    state = hass.states.get(f"sensor.{PREFIX}_charging_type")
    assert state.state == STATE_UNKNOWN


async def test_odometer_is_converted_to_kilometres(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The API reports metres; the sensor reports kilometres."""
    await setup_with(
        hass,
        aioclient_mock,
        mock_config_entry,
        {DOMAIN_ODOMETER: {"odometerMeters": 123_456}},
    )

    state = hass.states.get(f"sensor.{PREFIX}_odometer")
    assert float(state.state) == pytest.approx(123.456)
    assert state.attributes["unit_of_measurement"] == "km"


async def test_string_encoded_numbers_are_parsed(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Location speed and altitude arrive as strings in the spec."""
    await setup_with(
        hass,
        aioclient_mock,
        mock_config_entry,
        {DOMAIN_LOCATION: {"speed": "88.5", "altitude": "12"}},
    )

    speed = hass.states.get(f"sensor.{PREFIX}_speed")
    altitude = hass.states.get(f"sensor.{PREFIX}_altitude")
    assert float(speed.state) == pytest.approx(88.5)
    assert float(altitude.state) == pytest.approx(12)


async def test_device_tracker_reports_position(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The tracker exposes the coordinate pair as GPS attributes."""
    await setup_with(
        hass,
        aioclient_mock,
        mock_config_entry,
        {DOMAIN_LOCATION: {"coordinate": {"latitude": 52.37, "longitude": 4.89}}},
    )

    state = hass.states.get(f"device_tracker.{PREFIX}_location")
    assert state.attributes["latitude"] == pytest.approx(52.37)
    assert state.attributes["longitude"] == pytest.approx(4.89)
    assert state.attributes["source_type"] == "gps"


async def test_timestamp_is_converted(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Epoch timestamps with string seconds become ISO datetimes."""
    await setup_with(
        hass,
        aioclient_mock,
        mock_config_entry,
        {DOMAIN_BATTERY: {"timestamp": {"seconds": "1788362002", "nanos": 0}}},
    )

    state = hass.states.get(f"sensor.{PREFIX}_battery_data_updated")
    assert state.state.startswith("2026-09-02T")


async def test_zero_timestamp_is_unknown(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A zero timestamp means "never", not 1970."""
    await setup_with(
        hass,
        aioclient_mock,
        mock_config_entry,
        {DOMAIN_BATTERY: {"timestamp": {"seconds": "0", "nanos": 0}}},
    )

    state = hass.states.get(f"sensor.{PREFIX}_battery_data_updated")
    assert state.state == STATE_UNKNOWN


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("OPEN_STATUS_OPEN", STATE_ON),
        ("OPEN_STATUS_AJAR", STATE_ON),
        ("OPEN_STATUS_CLOSED", STATE_OFF),
        ("OPEN_STATUS_UNSPECIFIED", STATE_UNKNOWN),
    ],
)
async def test_door_states(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
    value: str,
    expected: str,
) -> None:
    """A door that is ajar counts as open, and the exact value is kept."""
    await setup_with(
        hass,
        aioclient_mock,
        mock_config_entry,
        {DOMAIN_EXTERIOR: {"frontLeftDoor": value}},
    )

    state = hass.states.get(f"binary_sensor.{PREFIX}_front_left_door")
    assert state.state == expected
    if expected is not STATE_UNKNOWN:
        assert state.attributes["state"] == value.removeprefix("OPEN_STATUS_").lower()


@pytest.mark.parametrize(
    ("value", "expected"),
    [("LOCK_STATUS_UNLOCKED", STATE_ON), ("LOCK_STATUS_LOCKED", STATE_OFF)],
)
async def test_lock_polarity(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
    value: str,
    expected: str,
) -> None:
    """Home Assistant lock sensors are "on" when unlocked."""
    await setup_with(
        hass,
        aioclient_mock,
        mock_config_entry,
        {DOMAIN_EXTERIOR: {"centralLock": value}},
    )

    assert hass.states.get(f"binary_sensor.{PREFIX}_central_lock").state == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("TYRE_PRESSURE_WARNING_NO_WARNING", STATE_OFF),
        ("TYRE_PRESSURE_WARNING_LOW_PRESSURE", STATE_ON),
        ("TYRE_PRESSURE_WARNING_VERY_LOW_PRESSURE", STATE_ON),
    ],
)
async def test_problem_sensors(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
    value: str,
    expected: str,
) -> None:
    """Warning enums collapse to a problem sensor keeping the severity."""
    await setup_with(
        hass,
        aioclient_mock,
        mock_config_entry,
        {DOMAIN_HEALTH: {"frontLeftTyrePressureWarning": value}},
    )

    state = hass.states.get(f"binary_sensor.{PREFIX}_tyre_pressure_warning_front_left")
    assert state.state == expected
    assert (
        state.attributes["state"]
        == value.removeprefix("TYRE_PRESSURE_WARNING_").lower()
    )


async def test_light_failure_is_aggregated(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """One failing bulb lights the aggregate sensor and is named in attributes."""
    await setup_with(
        hass,
        aioclient_mock,
        mock_config_entry,
        {
            DOMAIN_HEALTH: {
                "lightWarnings": {
                    "lowBeamLeft": "EXTERIOR_LIGHT_WARNING_FAILURE",
                    "lowBeamRight": "EXTERIOR_LIGHT_WARNING_NO_WARNING",
                }
            }
        },
    )

    state = hass.states.get(f"binary_sensor.{PREFIX}_exterior_light_failure")
    assert state.state == STATE_ON
    assert state.attributes["failed_lights"] == ["low_beam_left"]


async def test_missing_field_is_unknown(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A field the car does not report reads as unknown, not as zero."""
    await setup_with(
        hass,
        aioclient_mock,
        mock_config_entry,
        {DOMAIN_BATTERY: {"chargingPowerWatts": None}},
    )

    assert hass.states.get(f"sensor.{PREFIX}_charging_power").state == STATE_UNKNOWN


async def test_entities_go_unavailable_on_failure(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Entities report unavailable once the coordinator stops succeeding."""
    await setup_with(hass, aioclient_mock, mock_config_entry)
    assert hass.states.get(f"sensor.{PREFIX}_battery").state != STATE_UNAVAILABLE

    coordinator = mock_config_entry.runtime_data.coordinators[0]
    coordinator.async_set_update_error(RuntimeError("boom"))
    await hass.async_block_till_done()

    assert hass.states.get(f"sensor.{PREFIX}_battery").state == STATE_UNAVAILABLE
