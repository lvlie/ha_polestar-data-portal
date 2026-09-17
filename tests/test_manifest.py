"""Manifest checks mirroring the rules hassfest enforces in CI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

MANIFEST = (
    Path(__file__).resolve().parent.parent
    / "custom_components"
    / "polestar_data_portal"
    / "manifest.json"
)


@pytest.fixture(scope="module")
def manifest() -> dict:
    """Return the parsed manifest."""
    return json.loads(MANIFEST.read_text())


def test_keys_are_sorted_the_way_hassfest_wants(manifest: dict) -> None:
    """Hassfest requires domain, then name, then alphabetical order.

    Getting this wrong fails CI with a message that is easy to miss, so it is
    asserted here where it shows up in a local test run first.
    """
    keys = list(manifest)
    assert keys[:2] == ["domain", "name"]
    assert keys[2:] == sorted(keys[2:])


def test_required_keys_are_present(manifest: dict) -> None:
    """The keys HACS and Home Assistant both need are set."""
    required = {
        "codeowners",
        "config_flow",
        "documentation",
        "domain",
        "iot_class",
        "name",
        "version",  # HACS requires a version on custom integrations
    }
    assert required <= set(manifest)


def test_domain_matches_the_directory(manifest: dict) -> None:
    """The domain has to match the folder it lives in."""
    assert manifest["domain"] == MANIFEST.parent.name


def test_no_core_only_keys(manifest: dict) -> None:
    """quality_scale belongs to core integrations; hassfest rejects it here."""
    assert "quality_scale" not in manifest


def test_iot_class_is_valid(manifest: dict) -> None:
    """The iot_class is one of the values Home Assistant accepts."""
    assert manifest["iot_class"] in {
        "assumed_state",
        "calculated",
        "cloud_polling",
        "cloud_push",
        "local_polling",
        "local_push",
    }


def test_integration_type_is_valid(manifest: dict) -> None:
    """The integration_type is one Home Assistant knows."""
    assert manifest["integration_type"] in {
        "device",
        "entity",
        "hardware",
        "helper",
        "hub",
        "service",
        "system",
    }


def test_version_is_semver_like(manifest: dict) -> None:
    """HACS expects a parseable version."""
    parts = manifest["version"].split(".")
    assert len(parts) == 3
    assert all(part.isdigit() for part in parts)
