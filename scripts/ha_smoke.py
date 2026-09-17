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
# The spec's example VIN is YV1CZ0000000000000; the device is named after its
# serial part, so entity IDs are prefixed polestar_000000.
REQUIRED_ENTITIES = (
    "sensor.polestar_000000_battery",
    "sensor.polestar_000000_odometer",
    "binary_sensor.polestar_000000_front_left_door",
    "device_tracker.polestar_000000_location",
)

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


def verify() -> int:
    """Check that the integration set up and registered its entities."""
    deadline = time.time() + 180
    log = ""

    while time.time() < deadline:
        log = read_log()

        if f"Error setting up entry Polestar Data Portal for {DOMAIN}" in log:
            print("FAILED: the config entry did not set up", file=sys.stderr)
            break

        found = [entity for entity in REQUIRED_ENTITIES if entity in log]
        if len(found) == len(REQUIRED_ENTITIES):
            print(f"SUCCESS: all {len(found)} expected entities were registered")
            for entity in found:
                print(f"  - {entity}")
            if failures := _integration_errors(log):
                print("\nBut the log contains integration errors:", file=sys.stderr)
                print("\n".join(failures), file=sys.stderr)
                return 1
            return 0

        time.sleep(5)

    print("FAILED: expected entities never appeared", file=sys.stderr)
    missing = [entity for entity in REQUIRED_ENTITIES if entity not in log]
    print(f"Missing: {missing}", file=sys.stderr)
    print("\n----- log tail -----", file=sys.stderr)
    print("\n".join(log.splitlines()[-120:]), file=sys.stderr)
    return 1


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
