#!/usr/bin/env python3
"""Regenerate ``translations/en.json`` from the entity descriptions.

Entity names and enum state labels are derived from the description keys so a
new sensor can never ship without a translation. Wording that reads badly when
derived mechanically is corrected through ``NAME_OVERRIDES``.

    python3 scripts/generate_translations.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from custom_components.polestar_data_portal import (  # noqa: E402
    binary_sensor,
    device_tracker,
    sensor,
)

COMPONENT = REPO / "custom_components" / "polestar_data_portal"
TARGET = COMPONENT / "translations" / "en.json"

NAME_OVERRIDES: dict[str, str] = {
    # Battery
    "battery_charge_level": "Battery",
    "charging_status_legacy": "Charging status (legacy)",
    "range": "Range",
    "range_miles": "Range (miles)",
    "average_energy_consumption": "Average consumption",
    "average_energy_consumption_automatic": "Average consumption (automatic trip)",
    "average_energy_consumption_since_charge": "Average consumption since charge",
    "total_energy_consumption": "Total energy consumption",
    "total_energy_consumption_automatic": "Total energy consumption (automatic trip)",
    "total_energy_consumption_since_charge": "Energy consumption since charge",
    "charging_time_to_full": "Charging time remaining",
    "charging_time_to_target_distance": "Charging time to target range",
    "charging_time_to_minimum_soc": "Charging time to minimum charge",
    "discharge_energy_available": "Dischargeable energy",
    "discharge_energy_available_increase": "Dischargeable energy increase",
    "discharge_power_limit": "Discharge power limit",
    "battery_updated_at": "Battery data updated",
    # Availability
    "availability_updated_at": "Availability data updated",
    # Health
    "distance_to_service": "Distance to service",
    "days_to_service": "Days to service",
    "engine_hours_to_service": "Engine hours to service",
    "tyre_reference_pressure_front": "Tyre reference pressure front",
    "tyre_reference_pressure_rear": "Tyre reference pressure rear",
    "light_failure": "Exterior light failure",
    "low_voltage_battery_warning": "12V battery warning",
    # Location / odometer
    "location_updated_at": "Location updated",
    "odometer_updated_at": "Odometer data updated",
    "trip_meter_manual": "Trip meter",
    "trip_meter_automatic": "Trip meter (automatic)",
    "trip_meter_since_charge": "Trip meter since charge",
    "average_speed_manual": "Average speed",
    "average_speed_automatic": "Average speed (automatic trip)",
    "average_speed_since_charge": "Average speed since charge",
    # Climate
    "cabin_temperature": "Cabin temperature",
    "requested_cabin_temperature": "Requested cabin temperature",
    "cabin_air_quality_index": "Cabin air quality index",
    "cabin_particulate_matter": "Cabin particulate matter",
    "climatization_status": "Parking climatization",
    "climatization_runtime_left": "Climatization runtime left",
    "pre_cleaning_status": "Cabin pre-cleaning",
    "pre_cleaning_runtime_left": "Pre-cleaning runtime left",
    "pre_cleaning_last_cycle_completed": "Pre-cleaning last completed",
    "pre_cleaning_measured_at": "Pre-cleaning measured at",
    "pre_cleaning_last_cycle_valid": "Pre-cleaning last cycle valid",
    # Charging
    "amp_limit": "Charging current limit",
    "pending_amp_limit": "Pending charging current limit",
    "amp_limit_updated_at": "Charging current limit updated",
    "charge_locations": "Charge locations",
    "charge_timer_start": "Charge timer start",
    "charge_timer_stop": "Charge timer stop",
    "charge_timer_activated": "Charge timer",
    "charge_timer_sync_status": "Charge timer sync status",
    "current_charge_location": "Current charge location",
    "charge_location_arrived_at": "Arrived at charge location",
    "at_charge_location": "At charge location",
    "charge_now": "Charge now",
    "pending_charge_now": "Pending charge now",
    "target_battery_charge_level": "Charge limit",
    "pending_target_battery_charge_level": "Pending charge limit",
    "target_soc_setting_type": "Charge limit type",
    "target_soc_updated_at": "Charge limit updated",
    "parking_climate_timers": "Parking climate timers",
    "timer_requested_cabin_temperature": "Timer cabin temperature",
    "timer_battery_preconditioning": "Timer battery preconditioning",
    "timer_steering_wheel_heating": "Timer steering wheel heating",
    # Exterior
    "charge_port": "Charge port",
    "central_lock": "Central lock",
    "tailgate_lock": "Tailgate lock",
}

VARIANT_LABELS = {
    "manual": "trip",
    "automatic": "automatic trip",
    "since_charge": "since charge",
}


def humanize(value: str) -> str:
    """Turn a snake_case key into a sentence-cased label."""
    return value.replace("_", " ").capitalize()


def entity_name(key: str) -> str:
    """Return the display name for one entity key."""
    if (override := NAME_OVERRIDES.get(key)) is not None:
        return override

    # The generated per-category consumption sensors read badly when
    # humanized directly, so they get a shape of their own.
    for variant, label in VARIANT_LABELS.items():
        if key.startswith("energy_consumption_percentage_") and key.endswith(
            tuple(f"_{variant}_{c}" for c in ("other", "driving", "climate", "battery"))
        ):
            category = key.rsplit("_", 1)[-1]
            return f"Energy share {category} ({label})"
        if key.startswith("energy_consumption_") and f"_{variant}_" in key:
            category = key.rsplit("_", 1)[-1]
            return f"Energy consumption {category} ({label})"

    if key.startswith("light_"):
        return humanize(key.removeprefix("light_")) + " light"

    return humanize(key)


def enum_states(description: object) -> dict[str, str] | None:
    """Return the state labels for an enum sensor, if it is one."""
    options = getattr(description, "options", None)
    if not options:
        return None
    return {option: humanize(option) for option in options}


def build() -> dict:
    """Build the full translation document."""
    sensors: dict[str, dict] = {}
    for description in sensor.ALL_SENSOR_DESCRIPTIONS:
        entry: dict = {"name": entity_name(description.translation_key)}
        if (states := enum_states(description)) is not None:
            entry["state"] = states
        sensors[description.translation_key] = entry

    binary_sensors = {
        description.translation_key: {"name": entity_name(description.translation_key)}
        for description in binary_sensor.BINARY_SENSOR_DESCRIPTIONS
    }

    trackers = {
        device_tracker.TRACKER_DESCRIPTION.translation_key: {"name": "Location"}
    }

    # Ordered as the Data Portal credential page presents them.
    credential_fields = {
        "client_id": "App client ID",
        "account_id": "Expected x-client-id header",
        "client_secret": "Client secret",
        "token_url": "M2M token endpoint",
        "delegated_account_id": "Delegated account e-mail (optional)",
    }
    credential_descriptions = {
        "client_id": "The App client ID shown on the credential page.",
        "account_id": (
            "The 'Expected x-client-id header' value from the credential page. "
            "This is your account ID and is not the same as the App client ID."
        ),
        "client_secret": (
            "The client secret shown once when the credential is created. "
            "Create a new credential if you no longer have it."
        ),
        "token_url": "The 'M2M Token Endpoint' shown on the credential page.",
        "delegated_account_id": (
            "Only for third-party credentials: the account e-mail whose shared "
            "vehicles you want to read. Leave empty to use your own vehicles."
        ),
    }

    setup_description = (
        "Sign in at {portal_url} and open **Data Portal API → Credential** to "
        "create the credentials for this integration. Start from the portal "
        "home page rather than a country URL, because the address differs per "
        "market. Copy the four values from the credential page below."
    )

    return {
        "config": {
            "step": {
                "user": {
                    "title": "Polestar Data Portal credentials",
                    "description": setup_description,
                    "data": credential_fields,
                    "data_description": credential_descriptions,
                },
                "reauth_confirm": {
                    "title": "Update Polestar Data Portal credentials",
                    "description": (
                        "The stored credentials were rejected. Data Portal "
                        "credentials can expire or be revoked; sign in at "
                        "{portal_url}, open **Data Portal API → Credential** "
                        "and create a new credential, then enter it below."
                    ),
                    "data": credential_fields,
                    "data_description": credential_descriptions,
                },
            },
            "error": {
                "cannot_connect": (
                    "Could not reach the Data Portal. Check the M2M token "
                    "endpoint and your internet connection."
                ),
                "invalid_auth": (
                    "The Data Portal rejected these credentials. Check the App "
                    "client ID and client secret, and confirm the credential "
                    "has not expired."
                ),
                "invalid_token_url": "That does not look like a valid token endpoint.",
                "insecure_token_url": (
                    "The token endpoint must use https. Your client secret is "
                    "sent in the request body, so it would otherwise travel "
                    "over the network unencrypted."
                ),
                "no_vehicles": (
                    "The credentials work, but no vehicles are linked to this "
                    "account. Check that the vehicle is registered in the EU or "
                    "EEA and shared with this Data Portal account."
                ),
                "unknown": "Unexpected error.",
            },
            "abort": {
                "already_configured": "This Data Portal account is already set up.",
                "reauth_successful": "Credentials updated.",
            },
        },
        "options": {
            "step": {
                "init": {
                    "title": "Polestar Data Portal options",
                    "description": (
                        "Each poll spends one API request per data domain per "
                        "vehicle. Polestar allows roughly 10,000 requests per "
                        "day, so keep the interval high enough to stay within "
                        "your budget."
                    ),
                    "data": {"scan_interval_minutes": "Update interval (minutes)"},
                }
            }
        },
        "entity": {
            "binary_sensor": dict(sorted(binary_sensors.items())),
            "device_tracker": trackers,
            "sensor": dict(sorted(sensors.items())),
        },
    }


def main() -> int:
    """Write the generated translations."""
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(json.dumps(build(), indent=2, ensure_ascii=False) + "\n")
    print(f"Wrote {TARGET.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
