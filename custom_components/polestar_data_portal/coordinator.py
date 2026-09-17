"""Data update coordinator for the Polestar Data Portal integration."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    PolestarApiError,
    PolestarAuthError,
    PolestarDataPortalApi,
    PolestarForbiddenError,
    PolestarNotFoundError,
    PolestarRateLimitError,
)
from .const import API_DOMAIN_PATHS, DOMAIN, MANUFACTURER
from .helpers import mask_vin, short_vin

_LOGGER = logging.getLogger(__name__)

# The API allows a 100 requests/minute burst. A poll spends one request per
# domain, so requests are capped to keep a single refresh well inside that.
MAX_CONCURRENT_REQUESTS = 5


class PolestarVehicleCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Poll every supported API domain for a single vehicle.

    Which domains a credential may read depends on the scopes granted in the
    Data Portal, and which domains a car answers depends on its equipment.
    Both are discovered once during setup so later polls only spend requests
    on endpoints that actually return data.
    """

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        api: PolestarDataPortalApi,
        vin: str,
        update_interval: timedelta,
        known_domains: set[str] | None = None,
    ) -> None:
        """Initialize the coordinator.

        ``known_domains`` is a previously discovered domain set. When given,
        setup reads only those endpoints instead of probing all of them.
        """
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=f"{DOMAIN} {mask_vin(vin)}",
            update_interval=update_interval,
        )
        self.api = api
        self.vin = vin
        self.supported_domains: set[str] = set()
        self._known_domains = known_domains
        self._initial_data: dict[str, dict[str, Any]] | None = None
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device registry entry for this vehicle."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.vin)},
            manufacturer=MANUFACTURER,
            name=f"Polestar {short_vin(self.vin)}",
            serial_number=self.vin,
        )

    async def _async_setup(self) -> None:
        """Establish which domains this vehicle and credential can read."""
        candidates = self._known_domains or set(API_DOMAIN_PATHS)
        results = await self._async_fetch_domains(candidates)

        # Only keep domains that returned an actual payload. Endpoints the
        # credential lacks a scope for, and endpoints the car does not report,
        # are dropped so no entities are created for permanently empty data.
        self.supported_domains = {
            domain for domain, payload in results.items() if payload
        }

        if not self.supported_domains:
            raise UpdateFailed(
                f"No Data Portal domain returned data for vehicle "
                f"{mask_vin(self.vin)}. Check that the credential has telemetry "
                "scopes granted in the Data Portal."
            )

        skipped = sorted(candidates - self.supported_domains)
        _LOGGER.debug(
            "Vehicle %s supports %s; no data for %s",
            mask_vin(self.vin),
            sorted(self.supported_domains),
            skipped or "none",
        )

        # Home Assistant runs the first refresh straight after this hook.
        # Hand it the payloads already fetched here rather than spending a
        # second full round of requests on the same data.
        self._initial_data = {
            domain: results[domain] for domain in self.supported_domains
        }

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        """Fetch the supported domains for this vehicle."""
        if self._initial_data is not None:
            initial, self._initial_data = self._initial_data, None
            return initial

        results = await self._async_fetch_domains(self.supported_domains)

        # A single flaky domain must not blank out every entity, so the
        # previous payload is kept for domains that failed this round. Only a
        # complete failure is reported as a failed update.
        previous = self.data or {}
        merged: dict[str, dict[str, Any]] = {}
        for domain in self.supported_domains:
            if domain in results:
                merged[domain] = results[domain]
            elif domain in previous:
                merged[domain] = previous[domain]

        if not results:
            raise UpdateFailed(f"No Data Portal domain could be read for {self.vin}")

        return merged

    async def _async_fetch_domains(
        self, domains: set[str]
    ) -> dict[str, dict[str, Any]]:
        """Fetch several domains concurrently, tolerating per-domain failures.

        Returns only the domains that answered. Authentication failures are
        re-raised because they affect every request, not just one endpoint.
        """

        async def fetch(domain: str) -> tuple[str, dict[str, Any] | None]:
            async with self._semaphore:
                try:
                    return domain, await self.api.async_get_domain(domain, self.vin)
                except PolestarAuthError:
                    # Affects every request, not just this endpoint.
                    raise
                except PolestarForbiddenError:
                    # No scope for this endpoint; stop polling it.
                    _LOGGER.debug(
                        "Domain %s is not accessible for %s (missing scope)",
                        domain,
                        mask_vin(self.vin),
                    )
                    self.supported_domains.discard(domain)
                    return domain, None
                except PolestarNotFoundError:
                    _LOGGER.debug(
                        "Domain %s reported no data for %s",
                        domain,
                        mask_vin(self.vin),
                    )
                    return domain, {}
                except PolestarRateLimitError as err:
                    _LOGGER.warning("Polestar Data Portal rate limit hit: %s", err)
                    return domain, None
                except PolestarApiError as err:
                    _LOGGER.debug(
                        "Domain %s failed for %s: %s",
                        domain,
                        mask_vin(self.vin),
                        err,
                    )
                    return domain, None

        if not domains:
            return {}

        try:
            gathered = await asyncio.gather(*(fetch(domain) for domain in domains))
        except PolestarAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err

        return {domain: payload for domain, payload in gathered if payload is not None}
