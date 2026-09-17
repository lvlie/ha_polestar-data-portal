#!/usr/bin/env python3
"""Regenerate ``custom_components/polestar_data_portal/enums.py`` from the spec.

Run this after replacing ``resources/openapi.json`` with a newer copy from
https://data-portal.polestar.com/<market>/api-credentials/docs/openapi so the
enum options Home Assistant validates against stay in sync with the API.

    python3 scripts/generate_enums.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SPEC = REPO / "resources" / "openapi.json"
TARGET = REPO / "custom_components" / "polestar_data_portal" / "enums.py"

# Enums whose generated name would be unhelpful, keyed by their value tuple's
# first member. Anything not listed is named after its protobuf prefix.
EXPLICIT_NAMES = {
    "UNSPECIFIED": "WEEKDAY",
    "UNAVAILABLE": "AVAILABLE_OPTIMIZED_CHARGING",
    "SYNC_STATUS_UNKNOWN": "SYNC_STATUS",
    "I_UNDEFINED": "HEATING_LEVEL",
    "BP_UNDEFINED": "BATTERY_PRECONDITIONING",
}


def common_prefix(values: list[str]) -> str:
    """Return the shared protobuf prefix, trimmed to an underscore boundary."""
    if len(values) < 2:
        return ""
    prefix = os.path.commonprefix(values)
    return prefix[: prefix.rfind("_") + 1] if "_" in prefix else ""


def collect(node: object, found: dict[tuple[str, ...], str], path: str = "") -> None:
    """Walk the spec collecting every distinct string enum."""
    if isinstance(node, dict):
        enum = node.get("enum")
        if isinstance(enum, list) and all(isinstance(value, str) for value in enum):
            key = tuple(enum)
            found.setdefault(key, path)
        for name, child in node.items():
            collect(child, found, name if name != "items" else path)
    elif isinstance(node, list):
        for child in node:
            collect(child, found, path)


def name_for(values: tuple[str, ...], path: str) -> str:
    """Derive a stable constant name for one enum."""
    if (explicit := EXPLICIT_NAMES.get(values[0])) is not None:
        return explicit
    if prefix := common_prefix(list(values)):
        return prefix.rstrip("_")
    # Fall back to the property the enum was first seen on.
    return "".join(
        f"_{char}" if char.isupper() else char.upper() for char in path
    ).lstrip("_")


def main() -> int:
    """Write the generated module."""
    spec = json.loads(SPEC.read_text())
    found: dict[tuple[str, ...], str] = {}
    collect(spec.get("components", {}).get("schemas", {}), found)

    lines = [
        '"""Enum definitions generated from ``resources/openapi.json``.',
        "",
        "Do not edit by hand: run ``python3 scripts/generate_enums.py`` after",
        "updating the spec.",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "from .helpers import EnumSpec",
        "",
    ]

    for values, path in sorted(found.items(), key=lambda item: name_for(*item)):
        constant = name_for(values, path)
        prefix = common_prefix(list(values))
        lines.append(f"{constant} = EnumSpec(")
        lines.append(f"    prefix={json.dumps(prefix)},")
        lines.append("    values=(")
        lines.extend(f"        {json.dumps(value)}," for value in values)
        lines.append("    ),")
        lines.append(")")
        lines.append("")

    TARGET.write_text("\n".join(lines))
    print(f"Wrote {len(found)} enums to {TARGET.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
