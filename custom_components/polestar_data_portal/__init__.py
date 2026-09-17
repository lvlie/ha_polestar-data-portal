"""The Polestar Data Portal integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_CLIENT_ID, CONF_CLIENT_SECRET, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import PolestarApiError, PolestarAuthError, PolestarDataPortalApi
from .const import (
    CONF_ACCOUNT_ID,
    CONF_DELEGATED_ACCOUNT_ID,
    CONF_SCAN_INTERVAL_MINUTES,
    CONF_TOKEN_URL,
    DAILY_REQUEST_BUDGET,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    estimated_daily_requests,
    recommended_scan_interval_minutes,
)
from .coordinator import PolestarVehicleCoordinator
from .discovery import DiscoveryCache
from .helpers import build_device_names, mask_vin

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.DEVICE_TRACKER,
    Platform.SENSOR,
]


@dataclass
class PolestarRuntimeData:
    """Runtime data for a configured Data Portal account."""

    api: PolestarDataPortalApi
    coordinators: list[PolestarVehicleCoordinator]


PolestarConfigEntry = ConfigEntry[PolestarRuntimeData]


def build_api(hass: HomeAssistant, data: dict[str, object]) -> PolestarDataPortalApi:
    """Create an API client from config entry data."""
    return PolestarDataPortalApi(
        async_get_clientsession(hass),
        client_id=str(data[CONF_CLIENT_ID]),
        client_secret=str(data[CONF_CLIENT_SECRET]),
        account_id=str(data[CONF_ACCOUNT_ID]),
        token_url=str(data[CONF_TOKEN_URL]),
        delegated_account_id=(
            str(value) if (value := data.get(CONF_DELEGATED_ACCOUNT_ID)) else None
        ),
    )


async def async_setup_entry(hass: HomeAssistant, entry: PolestarConfigEntry) -> bool:
    """Set up a Polestar Data Portal account from a config entry."""
    api = build_api(hass, dict(entry.data))

    cache = DiscoveryCache(hass)
    cached = await cache.async_get(entry.entry_id)

    if cached:
        # Reuse the previous discovery so a restart costs one request per
        # known domain instead of one per documented endpoint.
        _LOGGER.debug("Using cached discovery for %d vehicle(s)", len(cached))
        vehicles = {vin: set(domains) for vin, domains in cached.items()}
    else:
        try:
            vins = await api.async_get_vehicles()
        except PolestarAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except PolestarApiError as err:
            raise ConfigEntryNotReady(
                f"Could not reach the Polestar Data Portal: {err}"
            ) from err

        if not vins:
            raise ConfigEntryNotReady(
                "The Data Portal returned no vehicles for this account"
            )
        vehicles = dict.fromkeys(vins)

    # The first refresh runs at the configured interval; it is corrected below
    # once the real per-poll request cost is known.
    interval = timedelta(
        minutes=entry.options.get(
            CONF_SCAN_INTERVAL_MINUTES, DEFAULT_SCAN_INTERVAL_MINUTES
        )
    )

    # Named from every VIN on the account, including any that fail to set up
    # below, so a vehicle that temporarily loses a scope cannot rename the
    # others.
    device_names = build_device_names(list(vehicles))

    coordinators: list[PolestarVehicleCoordinator] = []
    for vin, known_domains in vehicles.items():
        coordinator = PolestarVehicleCoordinator(
            hass,
            entry,
            api,
            vin,
            interval,
            known_domains,
            device_names[vin],
        )
        try:
            await coordinator.async_config_entry_first_refresh()
        except ConfigEntryNotReady as err:
            # One car without readable telemetry must not block the others,
            # for example a vehicle shared with the account but not covered by
            # the credential's scopes.
            _LOGGER.warning("Skipping vehicle %s: %s", mask_vin(vin), err)
            continue
        coordinators.append(coordinator)

    if not coordinators:
        # A stale cache can point at vehicles that are no longer readable.
        # Drop it so the next attempt rediscovers from scratch.
        await cache.async_invalidate(entry.entry_id)
        raise ConfigEntryNotReady(
            "No vehicle on this account returned any Data Portal telemetry"
        )

    await cache.async_set(
        entry.entry_id,
        {
            coordinator.vin: sorted(coordinator.supported_domains)
            for coordinator in coordinators
        },
    )

    interval = _resolve_interval(entry, coordinators)
    for coordinator in coordinators:
        coordinator.update_interval = interval

    entry.runtime_data = PolestarRuntimeData(api=api, coordinators=coordinators)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


def _resolve_interval(
    entry: PolestarConfigEntry, coordinators: list[PolestarVehicleCoordinator]
) -> timedelta:
    """Pick the polling interval, keeping the default inside the daily budget.

    An explicit user choice is always honoured; it is only logged about when
    it would exceed the documented allowance. When no choice has been made the
    default is raised as needed so that an account with many vehicles does not
    silently overrun the budget.
    """
    requests_per_poll = sum(
        len(coordinator.supported_domains) for coordinator in coordinators
    )
    safe_minutes = recommended_scan_interval_minutes(requests_per_poll)
    configured = entry.options.get(CONF_SCAN_INTERVAL_MINUTES)

    if configured is None:
        minutes = max(DEFAULT_SCAN_INTERVAL_MINUTES, safe_minutes)
    else:
        minutes = int(configured)

    estimate = estimated_daily_requests(requests_per_poll, minutes)
    if estimate > DAILY_REQUEST_BUDGET:
        _LOGGER.warning(
            "Polling %d vehicle(s) every %d minutes costs about %d API requests "
            "per day, above the documented %d per day allowance. Increase the "
            "update interval in the integration options to at least %d minutes.",
            len(coordinators),
            minutes,
            estimate,
            DAILY_REQUEST_BUDGET,
            safe_minutes,
        )
    else:
        _LOGGER.debug(
            "Polling %d vehicle(s) every %d minutes, about %d requests per day",
            len(coordinators),
            minutes,
            estimate,
        )

    return timedelta(minutes=minutes)


async def async_unload_entry(hass: HomeAssistant, entry: PolestarConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: PolestarConfigEntry) -> None:
    """Drop the cached discovery when the entry is deleted.

    Nothing reads it again once the entry is gone, so leaving it behind would
    only grow Home Assistant's storage with dead account data.
    """
    await DiscoveryCache(hass).async_invalidate(entry.entry_id)


async def async_reload_entry(hass: HomeAssistant, entry: PolestarConfigEntry) -> None:
    """Reload the entry when its options change.

    Changing the options is also the supported way to pick up a newly added
    vehicle or a freshly granted scope, so the discovery cache is dropped here.
    """
    await DiscoveryCache(hass).async_invalidate(entry.entry_id)
    await hass.config_entries.async_reload(entry.entry_id)
