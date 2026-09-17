"""Persistent cache of the vehicles and API domains found for an account.

Discovering what a credential can read costs one request per documented
endpoint. Doing that on every Home Assistant restart is what turns a restart
loop into a rate-limit problem, so the result is cached between runs and only
re-probed when it is missing, stale, or explicitly invalidated.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DISCOVERY_CACHE_TTL_DAYS, STORAGE_KEY, STORAGE_VERSION

_LOGGER = logging.getLogger(__name__)


class DiscoveryCache:
    """Store the discovered vehicles and domains for each account."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the cache."""
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)

    async def async_get(self, account_id: str) -> dict[str, list[str]] | None:
        """Return the cached vehicles for an account, or None when unusable."""
        data = await self._store.async_load() or {}
        entry = data.get(account_id)
        if not isinstance(entry, dict):
            return None

        try:
            discovered_at = datetime.fromisoformat(entry["discovered_at"])
        except (KeyError, TypeError, ValueError):
            return None

        if datetime.now(UTC) - discovered_at > timedelta(days=DISCOVERY_CACHE_TTL_DAYS):
            _LOGGER.debug("Discovery cache for this account expired; re-probing")
            return None

        vehicles = entry.get("vehicles")
        if not isinstance(vehicles, dict) or not vehicles:
            return None

        return {
            vin: list(domains)
            for vin, domains in vehicles.items()
            if isinstance(domains, list) and domains
        }

    async def async_set(self, account_id: str, vehicles: dict[str, list[str]]) -> None:
        """Replace the cached discovery for one account."""
        data = await self._store.async_load() or {}
        data[account_id] = {
            "discovered_at": datetime.now(UTC).isoformat(),
            "vehicles": {vin: sorted(domains) for vin, domains in vehicles.items()},
        }
        await self._store.async_save(data)

    async def async_invalidate(self, account_id: str) -> None:
        """Drop the cached discovery so the next setup probes again."""
        data = await self._store.async_load() or {}
        if data.pop(account_id, None) is not None:
            await self._store.async_save(data)
