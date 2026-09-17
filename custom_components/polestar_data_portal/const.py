"""Constants for the Polestar Data Portal integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "polestar_data_portal"

MANUFACTURER: Final = "Polestar"

# Config entry keys. CONF_CLIENT_ID / CONF_CLIENT_SECRET come from
# homeassistant.const; the remaining two are specific to this API.
CONF_ACCOUNT_ID: Final = "account_id"
CONF_TOKEN_URL: Final = "token_url"
CONF_DELEGATED_ACCOUNT_ID: Final = "delegated_account_id"
CONF_SCAN_INTERVAL_MINUTES: Final = "scan_interval_minutes"

# The portal publishes a single production token endpoint. It is still asked
# for during setup because the Data Portal shows a per-credential value that
# may differ per market.
DEFAULT_TOKEN_URL: Final = (
    "https://pc-api.polestar.com/eu-north-1/data-portal/m2m/token"
)

# Polestar documents 10.000 requests/day with a 100 requests/minute burst.
# Every poll spends one request per supported domain per vehicle, so the
# default is deliberately conservative.
DEFAULT_SCAN_INTERVAL_MINUTES: Final = 15
MIN_SCAN_INTERVAL_MINUTES: Final = 5
MAX_SCAN_INTERVAL_MINUTES: Final = 1440

# Daily request budget the polling interval is sized against.
DAILY_REQUEST_BUDGET: Final = 10_000

# Requests held back from that budget for things that are not steady-state
# polling: hourly token refreshes, retries, and the burst of requests each
# Home Assistant restart costs. 1000 covers roughly 60 restarts a day for a
# single vehicle on top of the hourly token refreshes.
RESTART_RESERVE_REQUESTS: Final = 1_000

# How long a discovered set of vehicles and domains stays usable. Caching it
# keeps a restart from re-probing all 15 endpoints, which is what makes a
# restart loop expensive.
DISCOVERY_CACHE_TTL_DAYS: Final = 7

STORAGE_VERSION: Final = 1
STORAGE_KEY: Final = f"{DOMAIN}.discovery"

# Refresh the access token this many seconds before it actually expires.
TOKEN_EXPIRY_MARGIN: Final = 60

# --- API domains -----------------------------------------------------------
# Keys are the internal domain names used throughout the integration; values
# are the path templates from resources/openapi.json.

DOMAIN_AVAILABILITY: Final = "availability"
DOMAIN_BATTERY: Final = "battery"
DOMAIN_EXTERIOR: Final = "exterior"
DOMAIN_HEALTH: Final = "health"
DOMAIN_LOCATION: Final = "location"
DOMAIN_ODOMETER: Final = "odometer"
DOMAIN_PARKING_CLIMATIZATION: Final = "parking_climatization"
DOMAIN_PRE_CLEANING: Final = "pre_cleaning"
DOMAIN_AMP_LIMIT: Final = "amp_limit"
DOMAIN_CHARGE_LOCATIONS: Final = "charge_locations"
DOMAIN_CHARGE_NOW: Final = "charge_now"
DOMAIN_GLOBAL_CHARGE_TIMER: Final = "global_charge_timer"
DOMAIN_IS_AT_CHARGE_LOCATION: Final = "is_at_charge_location"
DOMAIN_PARKING_CLIMATE_TIMER: Final = "parking_climate_timer"
DOMAIN_TARGET_SOC: Final = "target_soc"

API_DOMAIN_PATHS: Final[dict[str, str]] = {
    DOMAIN_AVAILABILITY: "/v1/vehicles/{vin}/telemetry/availability",
    DOMAIN_BATTERY: "/v1/vehicles/{vin}/telemetry/battery",
    DOMAIN_EXTERIOR: "/v1/vehicles/{vin}/telemetry/exterior",
    DOMAIN_HEALTH: "/v1/vehicles/{vin}/telemetry/health",
    DOMAIN_LOCATION: "/v1/vehicles/{vin}/telemetry/location",
    DOMAIN_ODOMETER: "/v1/vehicles/{vin}/telemetry/odometer",
    DOMAIN_PARKING_CLIMATIZATION: (
        "/v1/vehicles/{vin}/telemetry/parking-climatization"
    ),
    DOMAIN_PRE_CLEANING: "/v1/vehicles/{vin}/telemetry/pre-cleaning",
    DOMAIN_AMP_LIMIT: "/v1/vehicles/{vin}/charging/amp-limit",
    DOMAIN_CHARGE_LOCATIONS: "/v1/vehicles/{vin}/charging/charge-locations",
    DOMAIN_CHARGE_NOW: "/v1/vehicles/{vin}/charging/charge-now",
    DOMAIN_GLOBAL_CHARGE_TIMER: ("/v1/vehicles/{vin}/charging/global-charge-timer"),
    DOMAIN_IS_AT_CHARGE_LOCATION: ("/v1/vehicles/{vin}/charging/is-at-charge-location"),
    DOMAIN_PARKING_CLIMATE_TIMER: ("/v1/vehicles/{vin}/charging/parking-climate-timer"),
    DOMAIN_TARGET_SOC: "/v1/vehicles/{vin}/charging/target-soc",
}

# OAuth scope backing each domain, as listed in the M2MTokenRequest schema.
# Kept for documentation and for the diagnostics dump; the integration does
# not request scopes explicitly (see api.py).
API_DOMAIN_SCOPES: Final[dict[str, str]] = {
    DOMAIN_AVAILABILITY: "pdp-telemetry/availability",
    DOMAIN_BATTERY: "pdp-telemetry/battery",
    DOMAIN_EXTERIOR: "pdp-telemetry/exterior",
    DOMAIN_HEALTH: "pdp-telemetry/health",
    DOMAIN_LOCATION: "pdp-telemetry/location",
    DOMAIN_ODOMETER: "pdp-telemetry/odometer",
    DOMAIN_PARKING_CLIMATIZATION: "pdp-telemetry/parkingClimatization",
    DOMAIN_PRE_CLEANING: "pdp-telemetry/preCleaning",
    DOMAIN_AMP_LIMIT: "pdp-charging/ampLimit",
    DOMAIN_CHARGE_LOCATIONS: "pdp-charging/chargeLocations",
    DOMAIN_CHARGE_NOW: "pdp-charging/overrideChargeTimer",
    DOMAIN_GLOBAL_CHARGE_TIMER: "pdp-charging/globalChargeTimer",
    DOMAIN_IS_AT_CHARGE_LOCATION: "pdp-charging/isAtChargeLocation",
    DOMAIN_PARKING_CLIMATE_TIMER: "pdp-charging/parkingClimateTimer",
    DOMAIN_TARGET_SOC: "pdp-charging/targetSoc",
}

# --- Enum prefixes ---------------------------------------------------------
# The API returns protobuf-style enum values such as
# "CHARGING_STATUS_V2_CHARGING". Sensors strip the prefix and lowercase the
# remainder so the Home Assistant state becomes "charging".

ENUM_UNSPECIFIED_SUFFIX: Final = "UNSPECIFIED"

# Values that mean "there is nothing wrong", used by the problem sensors.
NO_WARNING_SUFFIX: Final = "NO_WARNING"


def recommended_scan_interval_minutes(requests_per_poll: int) -> int:
    """Return the smallest polling interval that respects the daily budget.

    ``requests_per_poll`` is the total number of API calls one refresh cycle
    costs across every vehicle on the account. The result is never below
    :data:`MIN_SCAN_INTERVAL_MINUTES`.
    """
    from math import ceil

    if requests_per_poll <= 0:
        return DEFAULT_SCAN_INTERVAL_MINUTES

    usable = DAILY_REQUEST_BUDGET - RESTART_RESERVE_REQUESTS
    polls_per_day = usable / requests_per_poll
    if polls_per_day <= 0:
        return MAX_SCAN_INTERVAL_MINUTES

    minutes = ceil(24 * 60 / polls_per_day)
    return min(max(minutes, MIN_SCAN_INTERVAL_MINUTES), MAX_SCAN_INTERVAL_MINUTES)


def estimated_daily_requests(requests_per_poll: int, interval_minutes: int) -> int:
    """Estimate the daily request count for a given poll cost and interval."""
    if interval_minutes <= 0:
        return DAILY_REQUEST_BUDGET
    polls_per_day = 24 * 60 / interval_minutes
    # One token refresh per hour on top of the polling itself.
    return int(polls_per_day * requests_per_poll) + 24
