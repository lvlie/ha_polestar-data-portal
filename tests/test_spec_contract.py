"""Guard the integration against drift from the published OpenAPI spec."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from custom_components.polestar_data_portal.const import (
    API_DOMAIN_PATHS,
    API_DOMAIN_SCOPES,
    DEFAULT_TOKEN_URL,
)
from custom_components.polestar_data_portal.enums import (
    CHARGING_STATUS_V2,
    OPEN_STATUS,
    TYRE_PRESSURE_WARNING,
)

from .openapi import load_spec

REPO = Path(__file__).resolve().parent.parent
COMPONENT = REPO / "custom_components" / "polestar_data_portal"


def test_every_documented_vehicle_path_is_implemented() -> None:
    """No endpoint in the spec is silently left unread."""
    documented = {
        path for path in load_spec()["paths"] if path.startswith("/v1/vehicles/{vin}/")
    }
    assert set(API_DOMAIN_PATHS.values()) == documented


def test_no_undocumented_path_is_requested() -> None:
    """The integration never invents an endpoint the spec does not define."""
    documented = set(load_spec()["paths"])
    for path in API_DOMAIN_PATHS.values():
        assert path in documented


def test_every_domain_declares_its_scope() -> None:
    """Each domain maps to a scope the token endpoint documents."""
    scope_text = load_spec()["components"]["schemas"]["M2MTokenRequest"]["properties"][
        "scope"
    ]["description"]
    documented_scopes = {
        scope.strip().rstrip(",")
        for scope in scope_text.split("Supported scopes:")[1].split()
    }

    assert set(API_DOMAIN_SCOPES) == set(API_DOMAIN_PATHS)
    for scope in API_DOMAIN_SCOPES.values():
        assert scope in documented_scopes


def test_default_token_url_matches_spec_server() -> None:
    """The pre-filled token endpoint follows the server in the spec."""
    server = load_spec()["servers"][0]["url"].rstrip("/")
    assert f"{server}/token" == DEFAULT_TOKEN_URL


def test_token_response_fields_are_camel_case() -> None:
    """The client depends on the spec's non-standard token field names."""
    schema = load_spec()["paths"]["/token"]["post"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    assert set(schema["required"]) == {"accessToken", "expiresIn", "tokenType"}


def test_account_header_is_required_on_vehicle_requests() -> None:
    """Every vehicle endpoint requires the x-client-id header."""
    spec = load_spec()
    for path, operations in spec["paths"].items():
        if not path.startswith("/v1/vehicles"):
            continue
        for operation in operations.values():
            headers = {
                parameter["name"]
                for parameter in operation.get("parameters", [])
                if parameter["in"] == "header" and parameter.get("required")
            }
            assert "x-client-id" in headers, path


@pytest.mark.parametrize(
    ("spec_name", "enum"),
    [
        ("BatteryState.chargingStatusV2", CHARGING_STATUS_V2),
        ("ExteriorState.frontLeftDoor", OPEN_STATUS),
        ("HealthState.frontLeftTyrePressureWarning", TYRE_PRESSURE_WARNING),
    ],
)
def test_generated_enums_match_the_spec(spec_name: str, enum: object) -> None:
    """The generated enum values are exactly what the spec publishes."""
    schema_name, field = spec_name.split(".")
    published = load_spec()["components"]["schemas"][schema_name]["properties"][field][
        "enum"
    ]
    assert list(enum.values) == published


def test_enums_module_is_up_to_date() -> None:
    """``enums.py`` is regenerated whenever the spec changes.

    Fails when someone updates resources/openapi.json without re-running
    ``python3 scripts/generate_enums.py``.
    """
    import subprocess
    import sys

    target = COMPONENT / "enums.py"
    before = target.read_text()
    subprocess.run(
        [sys.executable, "scripts/generate_enums.py"],
        cwd=REPO,
        check=True,
        capture_output=True,
    )
    after = target.read_text()
    if before != after:
        target.write_text(before)
        pytest.fail(
            "enums.py is stale; run `python3 scripts/generate_enums.py` "
            "after updating resources/openapi.json"
        )


def test_spec_is_valid_json_and_openapi_3() -> None:
    """The bundled spec copy stays parseable and versioned."""
    spec = json.loads((REPO / "resources" / "openapi.json").read_text())
    assert spec["openapi"].startswith("3.")
    assert spec["paths"]


# Domains that legitimately have no freshness sensor, with the reason each one
# is exempt. Anything else must expose when its data was measured.
FRESHNESS_EXEMPT = {
    # The spec gives this domain no car-side timestamp at all: its only date is
    # metaReceivedAt, which is when Polestar's backend saw the event.
    "charge_locations",
    # Its arrivedAt is both the event time and the record time, and is already
    # exposed as "Arrived at charge location".
    "is_at_charge_location",
}


def test_every_domain_reports_when_its_data_was_measured() -> None:
    """A reading with no age is a reading you cannot trust.

    A poll returns whatever the car last uploaded, not a fresh measurement --
    against a real vehicle the exterior payload was 36 hours old and the health
    payload 58 -- so a domain without one of these leaves "locked" or "no
    warning" looking current when it is days stale.
    """
    from custom_components.polestar_data_portal.sensor import ALL_SENSOR_DESCRIPTIONS

    covered = {
        description.api_domain
        for description in ALL_SENSOR_DESCRIPTIONS
        if description.key.endswith("_updated_at")
    }
    missing = set(API_DOMAIN_PATHS) - covered - FRESHNESS_EXEMPT
    assert not missing, f"domains with no freshness sensor: {sorted(missing)}"


def test_no_freshness_sensor_is_exempted_without_cause() -> None:
    """The exemption list cannot quietly outlive its reason."""
    assert set(API_DOMAIN_PATHS) >= FRESHNESS_EXEMPT

    spec = load_spec()
    for domain in FRESHNESS_EXEMPT:
        schema = spec["paths"][API_DOMAIN_PATHS[domain]]["get"]["responses"]["200"]
        body = json.dumps(schema)
        assert "updatedAtTimestamp" not in body, (
            f"{domain} now publishes a timestamp and should have a freshness sensor"
        )
