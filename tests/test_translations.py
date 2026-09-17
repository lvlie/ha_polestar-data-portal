"""Every entity and flow string must have a translation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from custom_components.polestar_data_portal import binary_sensor, device_tracker, sensor

TRANSLATIONS = (
    Path(__file__).resolve().parent.parent
    / "custom_components"
    / "polestar_data_portal"
    / "translations"
    / "en.json"
)


@pytest.fixture(scope="module")
def strings() -> dict:
    """Return the English translations."""
    return json.loads(TRANSLATIONS.read_text())


@pytest.mark.parametrize(
    ("platform", "descriptions"),
    [
        ("sensor", sensor.ALL_SENSOR_DESCRIPTIONS),
        ("binary_sensor", binary_sensor.BINARY_SENSOR_DESCRIPTIONS),
    ],
)
def test_every_entity_has_a_name(
    strings: dict, platform: str, descriptions: tuple
) -> None:
    """A new entity cannot ship without a display name."""
    translated = strings["entity"][platform]
    missing = [
        description.translation_key
        for description in descriptions
        if description.translation_key not in translated
        or not translated[description.translation_key].get("name")
    ]
    assert not missing


def test_device_tracker_has_a_name(strings: dict) -> None:
    """The tracker is named too."""
    key = device_tracker.TRACKER_DESCRIPTION.translation_key
    assert strings["entity"]["device_tracker"][key]["name"]


def test_enum_sensors_translate_every_option(strings: dict) -> None:
    """Every enum option a sensor can report has a label."""
    translated = strings["entity"]["sensor"]
    for description in sensor.ALL_SENSOR_DESCRIPTIONS:
        if not description.options:
            continue
        states = translated[description.translation_key].get("state", {})
        missing = set(description.options) - set(states)
        assert not missing, f"{description.key}: {sorted(missing)}"


def test_no_orphan_translations(strings: dict) -> None:
    """Removed entities do not leave stale strings behind."""
    for platform, descriptions in (
        ("sensor", sensor.ALL_SENSOR_DESCRIPTIONS),
        ("binary_sensor", binary_sensor.BINARY_SENSOR_DESCRIPTIONS),
    ):
        keys = {description.translation_key for description in descriptions}
        assert set(strings["entity"][platform]) == keys


def test_config_flow_strings_are_complete(strings: dict) -> None:
    """Both credential steps document all four portal values."""
    required = {"client_id", "client_secret", "account_id", "token_url"}
    for step in ("user", "reauth_confirm"):
        data = strings["config"]["step"][step]["data"]
        assert required <= set(data)
        assert required <= set(strings["config"]["step"][step]["data_description"])
        # The setup text points at the portal root, not a market URL.
        assert "{portal_url}" in strings["config"]["step"][step]["description"]
        assert "Credential" in strings["config"]["step"][step]["description"]


def test_all_flow_errors_are_translated(strings: dict) -> None:
    """Every error the config flow can raise has a message."""
    expected = {
        "cannot_connect",
        "invalid_auth",
        "invalid_token_url",
        "no_vehicles",
        "unknown",
    }
    assert expected <= set(strings["config"]["error"])
    assert {"already_configured", "reauth_successful"} <= set(
        strings["config"]["abort"]
    )


def test_options_flow_is_translated(strings: dict) -> None:
    """The polling interval option is explained."""
    step = strings["options"]["step"]["init"]
    assert "scan_interval_minutes" in step["data"]
    assert step["description"]
