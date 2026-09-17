"""Diagnostics support for the Polestar Data Portal integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_CLIENT_ID, CONF_CLIENT_SECRET
from homeassistant.core import HomeAssistant

from . import PolestarConfigEntry
from .const import (
    API_DOMAIN_SCOPES,
    CONF_ACCOUNT_ID,
    CONF_DELEGATED_ACCOUNT_ID,
)

# Credentials and anything that identifies the owner or the car.
TO_REDACT = {
    CONF_ACCOUNT_ID,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_DELEGATED_ACCOUNT_ID,
    "arrivedAt",
    "coordinate",
    "latitude",
    "locationAlias",
    "locationId",
    "longitude",
    "metaEventId",
    "vin",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: PolestarConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "vehicles": [
            {
                # The VIN itself is sensitive, so vehicles are only
                # distinguished by position in this dump.
                "supported_domains": sorted(coordinator.supported_domains),
                "required_scopes": sorted(
                    API_DOMAIN_SCOPES[domain]
                    for domain in coordinator.supported_domains
                ),
                "last_update_success": coordinator.last_update_success,
                "data": async_redact_data(coordinator.data or {}, TO_REDACT),
            }
            for coordinator in entry.runtime_data.coordinators
        ],
    }
