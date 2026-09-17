"""Build example API payloads straight from ``resources/openapi.json``.

Hand-written fixtures drift from the contract as soon as the spec is updated.
Every response used in the tests is instead derived from the schema the API
actually publishes, so a field that changes shape upstream surfaces as a test
failure rather than as a silent regression.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

SPEC_PATH = Path(__file__).resolve().parent.parent / "resources" / "openapi.json"

# Enum members that carry no information; sampling picks a real value instead.
PLACEHOLDER_SUFFIXES = ("UNSPECIFIED", "UNDEFINED", "UNKNOWN")


@lru_cache(maxsize=1)
def load_spec() -> dict[str, Any]:
    """Return the parsed OpenAPI document."""
    return json.loads(SPEC_PATH.read_text())


def _resolve(spec: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
    """Follow a local ``$ref`` one level."""
    ref = node.get("$ref")
    if not ref:
        return node
    target: Any = spec
    for part in ref.lstrip("#/").split("/"):
        target = target[part]
    return target


def sample(node: dict[str, Any], spec: dict[str, Any] | None = None) -> Any:
    """Build a representative value for one schema node."""
    spec = spec or load_spec()
    node = _resolve(spec, node)

    if (example := node.get("example")) is not None:
        return example

    if (enum := node.get("enum")) is not None:
        for value in enum:
            if not str(value).endswith(PLACEHOLDER_SUFFIXES):
                return value
        return enum[0]

    node_type = node.get("type")

    if node_type == "object":
        return {
            name: sample(child, spec)
            for name, child in (node.get("properties") or {}).items()
        }
    if node_type == "array":
        items = node.get("items")
        return [sample(items, spec)] if items else []
    if node_type in ("number", "integer"):
        return 42
    if node_type == "boolean":
        return True
    if node_type == "string":
        return "sample"
    return None


def response_for(path: str, method: str = "get", status: str = "200") -> Any:
    """Return an example success body for one documented operation."""
    spec = load_spec()
    operation = spec["paths"][path][method]
    schema = operation["responses"][status]["content"]["application/json"]["schema"]
    return sample(schema, spec)


def telemetry_payload(path_suffix: str, vin: str = "YV1CZ0000000000000") -> Any:
    """Return an example body for a ``/v1/vehicles/{vin}/...`` endpoint."""
    body = response_for(f"/v1/vehicles/{{vin}}/{path_suffix}")
    if isinstance(body, dict) and isinstance(body.get("data"), dict):
        body["data"]["vin"] = vin
    return body


def documented_paths() -> list[str]:
    """Return every documented vehicle path, with ``{vin}`` still templated."""
    return [
        path for path in load_spec()["paths"] if path.startswith("/v1/vehicles/{vin}/")
    ]
