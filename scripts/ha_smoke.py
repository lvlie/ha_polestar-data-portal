#!/usr/bin/env python3
"""Run the integration inside a real Home Assistant container.

The container talks to a Prism mock server driven by ``resources/openapi.json``
rather than to Polestar, so the run exercises the actual component against the
published contract: Prism rejects a request that does not match the spec, which
means a missing ``x-client-id`` header or a malformed token body fails here.

    python3 scripts/ha_smoke.py --start [--ha-version stable]
    python3 scripts/ha_smoke.py --verify
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO / "ha_config"
LOG_FILE = CONFIG_DIR / "home-assistant.log"
CONTAINER = "homeassistant"
DOMAIN = "polestar_data_portal"

MOCK_BASE = "http://127.0.0.1:4010"
ENTRY_ID = "01JQPOLESTARDATAPORTALSMOKE0"

# Entities that must exist for the run to count as a success. These span three
# platforms and four API domains, so a regression in any of them is caught.
# Checked by unique ID rather than entity ID: unique IDs are built from the
# VIN and an entity key, so they do not move when the device naming changes.
# Each of these also covers a different platform and API domain.
REQUIRED_UNIQUE_ID_SUFFIXES = (
    "_battery_charge_level",
    "_odometer",
    "_front_left_door",
    "_location",
)

# The spec's example account lists two vehicles.
EXPECTED_DEVICES = 2

# One vehicle contributes roughly a hundred enabled entities; a much smaller
# number means platforms silently failed to load.
MINIMUM_ENTITIES = 150

CONFIGURATION_YAML = """
default_config:

logger:
  default: warning
  logs:
    custom_components.polestar_data_portal: debug
"""


def write_config(ha_version: str) -> None:
    """Lay out a Home Assistant config directory with the entry pre-seeded."""
    if CONFIG_DIR.exists():
        shutil.rmtree(CONFIG_DIR)

    (CONFIG_DIR / "custom_components").mkdir(parents=True)
    (CONFIG_DIR / ".storage").mkdir()

    shutil.copytree(
        REPO / "custom_components" / DOMAIN,
        CONFIG_DIR / "custom_components" / DOMAIN,
    )
    (CONFIG_DIR / "configuration.yaml").write_text(CONFIGURATION_YAML)

    # Seeding the config entry avoids driving the UI just to reach the state
    # this test is about: that setup, discovery and the platforms all work.
    entries = {
        "version": 1,
        "minor_version": 1,
        "key": "core.config_entries",
        "data": {
            "entries": [
                {
                    "entry_id": ENTRY_ID,
                    "version": 1,
                    "minor_version": 1,
                    "domain": DOMAIN,
                    "title": "Polestar Data Portal",
                    "data": {
                        "client_id": "client_12345",
                        "client_secret": "secret_67890",
                        "account_id": "cf50b789-4e95-4636-977d-4ffb10164d11",
                        "token_url": f"{MOCK_BASE}/token",
                    },
                    "options": {},
                    "pref_disable_new_entities": False,
                    "pref_disable_polling": False,
                    "source": "user",
                    "unique_id": "cf50b789-4e95-4636-977d-4ffb10164d11",
                    "disabled_by": None,
                    "created_at": "2026-01-01T00:00:00.000000+00:00",
                    "modified_at": "2026-01-01T00:00:00.000000+00:00",
                    "discovery_keys": {},
                    "subentries": [],
                }
            ]
        },
    }
    (CONFIG_DIR / ".storage" / "core.config_entries").write_text(
        json.dumps(entries, indent=2)
    )
    print(f"Prepared {CONFIG_DIR} for Home Assistant {ha_version}")


def start_container(ha_version: str) -> None:
    """Start Home Assistant and wait for it to come up."""
    subprocess.run(["docker", "rm", "-f", CONTAINER], capture_output=True, check=False)
    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            CONTAINER,
            "--network",
            "host",
            "-v",
            f"{CONFIG_DIR}:/config",
            f"ghcr.io/home-assistant/home-assistant:{ha_version}",
        ],
        check=True,
    )

    print("Waiting for Home Assistant to start...")
    for _ in range(60):
        result = subprocess.run(
            ["curl", "-sf", "-o", "/dev/null", "http://127.0.0.1:8123/"],
            capture_output=True,
            check=False,
        )
        if result.returncode == 0:
            print("Home Assistant is up")
            return
        time.sleep(5)

    raise SystemExit("Home Assistant did not become reachable")


def read_log() -> str:
    """Return the Home Assistant log, falling back to the container's stdout."""
    if LOG_FILE.exists():
        return LOG_FILE.read_text(errors="replace")
    result = subprocess.run(
        ["docker", "logs", CONTAINER], capture_output=True, text=True, check=False
    )
    return result.stdout + result.stderr


def read_registry(name: str) -> dict:
    """Return one of Home Assistant's .storage registries, or {} if unwritten."""
    path = CONFIG_DIR / ".storage" / name
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        # Home Assistant may be mid-write; the caller retries.
        return {}


def verify() -> int:
    """Check that the integration set up and registered its entities.

    The entity registry on disk is the source of truth here. Grepping the log
    for entity IDs does not work: Home Assistant only logs registrations at
    a log level the container does not use by default.
    """
    deadline = time.time() + 240
    entities: list[dict] = []
    devices: list[dict] = []
    log = ""

    while time.time() < deadline:
        log = read_log()

        if "Error setting up entry Polestar Data Portal" in log:
            print("FAILED: the config entry did not set up", file=sys.stderr)
            break

        entities = [
            entity
            for entity in read_registry("core.entity_registry")
            .get("data", {})
            .get("entities", [])
            if entity.get("platform") == DOMAIN
        ]
        devices = [
            device
            for device in read_registry("core.device_registry")
            .get("data", {})
            .get("devices", [])
            if any(item[0] == DOMAIN for item in device.get("identifiers", []))
        ]

        if len(entities) >= MINIMUM_ENTITIES and devices:
            return _report(entities, devices, log)

        time.sleep(5)

    print(
        f"FAILED: only {len(entities)} entities and {len(devices)} devices "
        f"were registered after waiting",
        file=sys.stderr,
    )
    print("\n----- log tail -----", file=sys.stderr)
    print("\n".join(log.splitlines()[-120:]), file=sys.stderr)
    return 1


def _report(entities: list[dict], devices: list[dict], log: str) -> int:
    """Check the registered entities against what the run must produce."""
    unique_ids = [entity.get("unique_id", "") for entity in entities]
    missing = [
        suffix
        for suffix in REQUIRED_UNIQUE_ID_SUFFIXES
        if not any(unique_id.endswith(suffix) for unique_id in unique_ids)
    ]

    print(f"devices registered : {len(devices)}")
    for device in devices:
        print(f"  - {device.get('name')}")
    print(f"entities registered: {len(entities)}")

    failures: list[str] = []
    if missing:
        failures.append(f"missing entities with unique IDs ending: {missing}")
    if len(devices) != EXPECTED_DEVICES:
        failures.append(f"expected {EXPECTED_DEVICES} devices, found {len(devices)}")
    if errors := _integration_errors(log):
        failures.append("integration errors in the log:\n  " + "\n  ".join(errors))

    if failures:
        print("\nFAILED:", file=sys.stderr)
        for failure in failures:
            print(f"  {failure}", file=sys.stderr)
        return 1

    print("\nSUCCESS: the integration set up and all checked entities exist")
    return 0


def _integration_errors(log: str) -> list[str]:
    """Return ERROR lines raised by this integration."""
    return [line for line in log.splitlines() if "ERROR" in line and DOMAIN in line]


def main() -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", action="store_true", help="start the container")
    parser.add_argument("--verify", action="store_true", help="check the result")
    parser.add_argument("--ha-version", default="stable")
    args = parser.parse_args()

    if args.start:
        write_config(args.ha_version)
        start_container(args.ha_version)
        return 0

    if args.verify:
        return verify()

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
