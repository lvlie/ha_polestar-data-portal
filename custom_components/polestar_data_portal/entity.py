"""Shared entity base for the Polestar Data Portal integration."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import PolestarVehicleCoordinator


class PolestarEntity(CoordinatorEntity[PolestarVehicleCoordinator]):
    """Base entity bound to one vehicle and one API domain."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: PolestarVehicleCoordinator,
        description: EntityDescription,
        api_domain: str,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self.api_domain = api_domain
        self._attr_unique_id = f"{coordinator.vin}_{description.key}"
        self._attr_device_info = coordinator.device_info

    @property
    def domain_data(self) -> dict[str, Any]:
        """Return the latest payload for this entity's API domain."""
        return (self.coordinator.data or {}).get(self.api_domain) or {}

    @property
    def available(self) -> bool:
        """Return True when the coordinator holds data for this domain."""
        return super().available and self.api_domain in (self.coordinator.data or {})
