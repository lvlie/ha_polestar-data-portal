"""Device tracker platform for the Polestar Data Portal integration."""

from __future__ import annotations

from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import PolestarConfigEntry
from .const import DOMAIN_LOCATION
from .coordinator import PolestarVehicleCoordinator
from .entity import PolestarEntity
from .helpers import nested, to_float

PARALLEL_UPDATES = 0

TRACKER_DESCRIPTION = EntityDescription(
    key="location",
    translation_key="location",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PolestarConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up a device tracker for every vehicle that reports its location."""
    async_add_entities(
        PolestarDeviceTracker(coordinator)
        for coordinator in entry.runtime_data.coordinators
        if DOMAIN_LOCATION in coordinator.supported_domains
    )


class PolestarDeviceTracker(PolestarEntity, TrackerEntity):
    """Report the vehicle's last known GPS position."""

    def __init__(self, coordinator: PolestarVehicleCoordinator) -> None:
        """Initialize the device tracker."""
        super().__init__(coordinator, TRACKER_DESCRIPTION, DOMAIN_LOCATION)

    @property
    def source_type(self) -> SourceType:
        """Return that this tracker is GPS based."""
        return SourceType.GPS

    @property
    def latitude(self) -> float | None:
        """Return the latest latitude."""
        return to_float(nested(self.domain_data, "coordinate", "latitude"))

    @property
    def longitude(self) -> float | None:
        """Return the latest longitude."""
        return to_float(nested(self.domain_data, "coordinate", "longitude"))
