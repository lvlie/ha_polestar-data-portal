"""Regression tests against a payload from a real vehicle.

``fixtures/polestar_2_2022.json`` mirrors the *shape* of what a 2022 Polestar 2
actually returned: which fields the car sends, which it leaves out, and the
formats it uses. Every value in it is synthetic -- identifiers, timestamps,
readings and schedules were all replaced -- because the shape is the only part
these tests care about, and the readings would otherwise describe a real car.

The spec's own examples fill in every field, so they cannot catch what owners
actually hit: a field the car omits, or a format the spec types only as
"string".
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from custom_components.polestar_data_portal import binary_sensor, sensor
from custom_components.polestar_data_portal.helpers import (
    daily_time_to_string,
    iso_to_datetime,
)

FIXTURE = Path(__file__).parent / "fixtures" / "polestar_2_2022.json"

# The car is available, so the API reports no reason for it not to be. This is
# the correct unknown, not a gap: the sensor exists to say why a car is
# unreachable, and there is nothing to say while it is reachable.
EXPECTED_UNKNOWN = {"unavailable_reason"}


@pytest.fixture(scope="module")
def real() -> dict[str, Any]:
    """Return the recorded vehicle payload, keyed by API domain."""
    return json.loads(FIXTURE.read_text())


def _evaluate(real: dict[str, Any]) -> list[tuple[str, bool, Any]]:
    """Run every entity description against the recorded payload."""
    rows: list[tuple[str, bool, Any]] = []
    for description in sensor.ALL_SENSOR_DESCRIPTIONS:
        if description.api_domain in real:
            rows.append(
                (
                    description.key,
                    description.entity_registry_enabled_default,
                    description.value_fn(real[description.api_domain]),
                )
            )
    for description in binary_sensor.BINARY_SENSOR_DESCRIPTIONS:
        if description.api_domain in real:
            rows.append(
                (
                    description.key,
                    description.entity_registry_enabled_default,
                    description.is_on_fn(real[description.api_domain]),
                )
            )
    return rows


def test_no_enabled_entity_is_permanently_unknown(real: dict[str, Any]) -> None:
    """Everything on by default has a value on a real car.

    This is the test that would have caught the 24 entities sitting at unknown
    for this model. A new entity that is enabled but unpopulated fails here.
    """
    unknown = {
        key for key, enabled, value in _evaluate(real) if enabled and value is None
    }
    assert unknown == EXPECTED_UNKNOWN


def test_the_car_reports_the_core_values(real: dict[str, Any]) -> None:
    """The headline entities read correctly from real data."""
    values = {key: value for key, _, value in _evaluate(real)}

    assert values["battery_charge_level"] == 55
    assert values["range"] == 250
    assert values["charging_status"] == "charging"
    assert values["charging_power"] == 3700
    assert values["charging_type"] == "ac"
    assert values["target_battery_charge_level"] == 80
    # Reported as 12_345_600 metres.
    assert values["odometer"] == pytest.approx(12345.6)
    assert values["central_lock"] is False  # locked
    assert values["availability_status"] == "available"


def test_absent_collections_read_as_empty_not_unknown(real: dict[str, Any]) -> None:
    """The API omits a collection key entirely when it holds nothing."""
    values = {key: value for key, _, value in _evaluate(real)}

    # No charge locations stored on this car.
    assert "chargeLocations" not in real["charge_locations"]
    assert values["charge_locations"] == 0

    # No climatisation errors or warnings to report.
    assert "errors" not in real["parking_climatization"]
    assert values["climatization_error"] is False
    assert values["climatization_warning"] is False


def test_updated_at_is_epoch_milliseconds(real: dict[str, Any]) -> None:
    """Charging settings timestamp in epoch millis, not ISO 8601.

    The spec types this field as a bare string, so only real traffic shows it.
    """
    raw = real["amp_limit"]["updatedAt"]
    assert raw.isdigit()

    parsed = iso_to_datetime(raw)
    assert parsed is not None
    assert parsed.year == 2026

    values = {key: value for key, _, value in _evaluate(real)}
    assert values["amp_limit_updated_at"] == parsed


def test_daily_time_omits_a_zero_component(real: dict[str, Any]) -> None:
    """A timer set on the hour arrives without a ``minute`` key."""
    timer = real["parking_climate_timer"]["parkingClimateTimers"][0]
    assert "minute" not in timer["readyAt"]
    assert daily_time_to_string(timer["readyAt"]) == "07:00"


def test_tyre_pressure_is_absent_for_this_model(real: dict[str, Any]) -> None:
    """The model reports no tyre pressure at all, hence the disabled default."""
    health = real["health"]
    assert not [key for key in health if "Tyre" in key]

    tyre = [(key, enabled) for key, enabled, _ in _evaluate(real) if "tyre" in key]
    assert tyre
    assert not any(enabled for _, enabled in tyre)


def test_light_warnings_cover_only_the_fitted_lamps(real: dict[str, Any]) -> None:
    """The car reports a subset of the 40 documented lamps."""
    reported = real["health"]["lightWarnings"]
    assert 0 < len(reported) < len(binary_sensor.LIGHT_WARNING_FIELDS)

    values = {key: value for key, _, value in _evaluate(real)}
    # The aggregate still works off the subset that is reported.
    assert values["light_failure"] is False
