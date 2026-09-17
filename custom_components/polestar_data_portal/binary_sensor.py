"""Binary sensor platform for the Polestar Data Portal integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import PolestarConfigEntry
from .const import (
    DOMAIN_CHARGE_NOW,
    DOMAIN_EXTERIOR,
    DOMAIN_GLOBAL_CHARGE_TIMER,
    DOMAIN_HEALTH,
    DOMAIN_IS_AT_CHARGE_LOCATION,
    DOMAIN_PARKING_CLIMATIZATION,
    DOMAIN_PRE_CLEANING,
)
from .coordinator import PolestarVehicleCoordinator
from .entity import PolestarEntity
from .enums import (
    ALARM_STATUS,
    BRAKE_FLUID_LEVEL_WARNING,
    ENGINE_COOLANT_LEVEL_WARNING,
    EXTERIOR_LIGHT_WARNING,
    LOCK_STATUS,
    LOW_VOLTAGE_BATTERY_WARNING,
    OIL_LEVEL_WARNING,
    OPEN_STATUS,
    TYRE_PRESSURE_WARNING,
    WASHER_FLUID_LEVEL_WARNING,
)
from .helpers import EnumSpec, nested

PARALLEL_UPDATES = 0

# Enum options that mean "nothing to report" for a problem sensor.
_HEALTHY_OPTIONS = frozenset({"no_warning"})

# Open-status options that should read as "on" for an opening sensor. AJAR is
# included because a door left ajar is not closed; the precise value stays
# available as a state attribute.
_OPEN_OPTIONS = frozenset({"open", "ajar"})


@dataclass(frozen=True, kw_only=True)
class PolestarBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describe a Polestar Data Portal binary sensor."""

    api_domain: str
    is_on_fn: Callable[[dict[str, Any]], bool | None]
    attributes_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None


def _raw_state_attribute(
    spec: EnumSpec, *keys: str
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Expose the underlying enum option alongside the on/off state."""

    def attributes(data: dict[str, Any]) -> dict[str, Any]:
        option = spec.to_option(nested(data, *keys))
        return {"state": option} if option is not None else {}

    return attributes


def _opening(
    key: str, api_key: str, device_class: BinarySensorDeviceClass
) -> PolestarBinarySensorEntityDescription:
    """Build a door/window/hatch sensor from an OPEN_STATUS field."""

    def is_on(data: dict[str, Any]) -> bool | None:
        option = OPEN_STATUS.to_option(nested(data, api_key))
        return None if option is None else option in _OPEN_OPTIONS

    return PolestarBinarySensorEntityDescription(
        key=key,
        translation_key=key,
        api_domain=DOMAIN_EXTERIOR,
        device_class=device_class,
        is_on_fn=is_on,
        attributes_fn=_raw_state_attribute(OPEN_STATUS, api_key),
    )


def _lock(key: str, api_key: str) -> PolestarBinarySensorEntityDescription:
    """Build a lock sensor. Home Assistant treats "on" as unlocked."""

    def is_on(data: dict[str, Any]) -> bool | None:
        option = LOCK_STATUS.to_option(nested(data, api_key))
        return None if option is None else option == "unlocked"

    return PolestarBinarySensorEntityDescription(
        key=key,
        translation_key=key,
        api_domain=DOMAIN_EXTERIOR,
        device_class=BinarySensorDeviceClass.LOCK,
        is_on_fn=is_on,
    )


def _problem(
    *,
    key: str,
    api_domain: str,
    spec: EnumSpec,
    keys: tuple[str, ...],
    entity_category: EntityCategory | None = None,
    enabled: bool = True,
) -> PolestarBinarySensorEntityDescription:
    """Build a problem sensor from a warning enum."""

    def is_on(data: dict[str, Any]) -> bool | None:
        option = spec.to_option(nested(data, *keys))
        return None if option is None else option not in _HEALTHY_OPTIONS

    return PolestarBinarySensorEntityDescription(
        key=key,
        translation_key=key,
        api_domain=api_domain,
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=entity_category,
        entity_registry_enabled_default=enabled,
        is_on_fn=is_on,
        attributes_fn=_raw_state_attribute(spec, *keys),
    )


def _non_empty_list(
    *,
    key: str,
    api_domain: str,
    api_key: str,
    attribute: str,
) -> PolestarBinarySensorEntityDescription:
    """Build a problem sensor backed by an array of error/warning codes."""

    def is_on(data: dict[str, Any]) -> bool | None:
        values = nested(data, api_key)
        if not isinstance(values, list):
            return None
        return bool(_clean_codes(values))

    def attributes(data: dict[str, Any]) -> dict[str, Any]:
        values = nested(data, api_key)
        if not isinstance(values, list):
            return {}
        return {attribute: _clean_codes(values)}

    return PolestarBinarySensorEntityDescription(
        key=key,
        translation_key=key,
        api_domain=api_domain,
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=is_on,
        attributes_fn=attributes,
    )


def _clean_codes(values: list[Any]) -> list[str]:
    """Lowercase error/warning codes, dropping the placeholder members."""
    return [
        value.lower()
        for value in values
        if isinstance(value, str) and not value.endswith("UNSPECIFIED")
    ]


# Every individual exterior light the API can report a failure for. There are
# 40 of them, so they are diagnostic and disabled by default; the aggregate
# "light failure" sensor below covers the common case.
LIGHT_WARNING_FIELDS: tuple[tuple[str, str], ...] = (
    ("turn_indicator_front_left", "turnIndicatorFrontLeft"),
    ("turn_indicator_front_right", "turnIndicatorFrontRight"),
    ("turn_indicator_rear_left", "turnIndicatorRearLeft"),
    ("turn_indicator_rear_right", "turnIndicatorRearRight"),
    ("turn_indicator_left", "turnIndicatorLeft"),
    ("turn_indicator_right", "turnIndicatorRight"),
    ("turn_indicator_side_left", "turnIndicatorSideLeft"),
    ("turn_indicator_side_right", "turnIndicatorSideRight"),
    ("low_beam_left", "lowBeamLeft"),
    ("low_beam_right", "lowBeamRight"),
    ("low_beam_any", "lowBeamAny"),
    ("high_beam_left", "highBeamLeft"),
    ("high_beam_right", "highBeamRight"),
    ("high_beam_any", "highBeamAny"),
    ("fog_light_front", "fogLightFront"),
    ("fog_light_rear", "fogLightRear"),
    ("fog_light_rear_left", "fogLightRearLeft"),
    ("fog_light_rear_right", "fogLightRearRight"),
    ("brake_light_left", "brakeLightLeft"),
    ("brake_light_right", "brakeLightRight"),
    ("brake_light_center", "brakeLightCenter"),
    ("brake_light_any", "brakeLightAny"),
    ("position_light_front_left", "positionLightFrontLeft"),
    ("position_light_front_right", "positionLightFrontRight"),
    ("position_light_rear_left", "positionLightRearLeft"),
    ("position_light_rear_right", "positionLightRearRight"),
    ("position_light_front", "positionLightFront"),
    ("position_light_rear", "positionLightRear"),
    ("daytime_running_light_left", "daytimeRunningLightLeft"),
    ("daytime_running_light_right", "daytimeRunningLightRight"),
    ("daytime_running_light_any", "daytimeRunningLightAny"),
    ("registration_plate_light", "registrationPlateLight"),
    ("side_marker_light_left", "sideMarkerLightLeft"),
    ("side_marker_light_right", "sideMarkerLightRight"),
    ("side_marker_light_any", "sideMarkerLightAny"),
    ("reverse_light_left", "reverseLightLeft"),
    ("reverse_light_right", "reverseLightRight"),
    ("reverse_light_any", "reverseLightAny"),
    ("cornering_light_left", "corneringLightLeft"),
    ("cornering_light_right", "corneringLightRight"),
)


def _light_warnings() -> tuple[PolestarBinarySensorEntityDescription, ...]:
    """Build the per-light problem sensors."""
    return tuple(
        _problem(
            key=f"light_{key}",
            api_domain=DOMAIN_HEALTH,
            spec=EXTERIOR_LIGHT_WARNING,
            keys=("lightWarnings", api_key),
            entity_category=EntityCategory.DIAGNOSTIC,
            enabled=False,
        )
        for key, api_key in LIGHT_WARNING_FIELDS
    )


def _any_light_failure(data: dict[str, Any]) -> bool | None:
    """Return True when any exterior light reports a failure."""
    warnings = nested(data, "lightWarnings")
    if not isinstance(warnings, dict):
        return None

    options = [
        option
        for _, api_key in LIGHT_WARNING_FIELDS
        if (option := EXTERIOR_LIGHT_WARNING.to_option(warnings.get(api_key)))
        is not None
    ]
    if not options:
        return None
    return any(option != "no_warning" for option in options)


def _failed_lights(data: dict[str, Any]) -> dict[str, Any]:
    """List the lights currently reporting a failure."""
    warnings = nested(data, "lightWarnings")
    if not isinstance(warnings, dict):
        return {}
    return {
        "failed_lights": [
            key
            for key, api_key in LIGHT_WARNING_FIELDS
            if EXTERIOR_LIGHT_WARNING.to_option(warnings.get(api_key)) == "failure"
        ]
    }


BINARY_SENSOR_DESCRIPTIONS: tuple[PolestarBinarySensorEntityDescription, ...] = (
    # --- exterior: openings ------------------------------------------------
    _opening("front_left_door", "frontLeftDoor", BinarySensorDeviceClass.DOOR),
    _opening("front_right_door", "frontRightDoor", BinarySensorDeviceClass.DOOR),
    _opening("rear_left_door", "rearLeftDoor", BinarySensorDeviceClass.DOOR),
    _opening("rear_right_door", "rearRightDoor", BinarySensorDeviceClass.DOOR),
    _opening("front_left_window", "frontLeftWindow", BinarySensorDeviceClass.WINDOW),
    _opening("front_right_window", "frontRightWindow", BinarySensorDeviceClass.WINDOW),
    _opening("rear_left_window", "rearLeftWindow", BinarySensorDeviceClass.WINDOW),
    _opening("rear_right_window", "rearRightWindow", BinarySensorDeviceClass.WINDOW),
    _opening("sunroof", "sunroof", BinarySensorDeviceClass.WINDOW),
    _opening("hood", "hood", BinarySensorDeviceClass.OPENING),
    _opening("tailgate", "tailgate", BinarySensorDeviceClass.OPENING),
    _opening("charge_port", "tankLid", BinarySensorDeviceClass.OPENING),
    # --- exterior: locks and alarm ----------------------------------------
    _lock("central_lock", "centralLock"),
    _lock("tailgate_lock", "tailgateLock"),
    PolestarBinarySensorEntityDescription(
        key="alarm",
        translation_key="alarm",
        api_domain=DOMAIN_EXTERIOR,
        device_class=BinarySensorDeviceClass.SAFETY,
        is_on_fn=lambda data: (
            None
            if (option := ALARM_STATUS.to_option(nested(data, "alarm"))) is None
            else option == "triggered"
        ),
    ),
    # --- health: fluid and battery warnings --------------------------------
    _problem(
        key="brake_fluid_warning",
        api_domain=DOMAIN_HEALTH,
        spec=BRAKE_FLUID_LEVEL_WARNING,
        keys=("brakeFluidLevelWarning",),
    ),
    _problem(
        key="engine_coolant_warning",
        api_domain=DOMAIN_HEALTH,
        spec=ENGINE_COOLANT_LEVEL_WARNING,
        keys=("engineCoolantLevelWarning",),
    ),
    _problem(
        key="oil_level_warning",
        api_domain=DOMAIN_HEALTH,
        spec=OIL_LEVEL_WARNING,
        keys=("oilLevelWarning",),
        enabled=False,
    ),
    _problem(
        key="washer_fluid_warning",
        api_domain=DOMAIN_HEALTH,
        spec=WASHER_FLUID_LEVEL_WARNING,
        keys=("washerFluidLevelWarning",),
    ),
    _problem(
        key="low_voltage_battery_warning",
        api_domain=DOMAIN_HEALTH,
        spec=LOW_VOLTAGE_BATTERY_WARNING,
        keys=("lowVoltageBatteryWarning",),
    ),
    # --- health: tyre pressure warnings ------------------------------------
    _problem(
        key="tyre_pressure_warning_front_left",
        api_domain=DOMAIN_HEALTH,
        spec=TYRE_PRESSURE_WARNING,
        keys=("frontLeftTyrePressureWarning",),
        enabled=False,
    ),
    _problem(
        key="tyre_pressure_warning_front_right",
        api_domain=DOMAIN_HEALTH,
        spec=TYRE_PRESSURE_WARNING,
        keys=("frontRightTyrePressureWarning",),
        enabled=False,
    ),
    _problem(
        key="tyre_pressure_warning_rear_left",
        api_domain=DOMAIN_HEALTH,
        spec=TYRE_PRESSURE_WARNING,
        keys=("rearLeftTyrePressureWarning",),
        enabled=False,
    ),
    _problem(
        key="tyre_pressure_warning_rear_right",
        api_domain=DOMAIN_HEALTH,
        spec=TYRE_PRESSURE_WARNING,
        keys=("rearRightTyrePressureWarning",),
        enabled=False,
    ),
    # --- health: lights ----------------------------------------------------
    PolestarBinarySensorEntityDescription(
        key="light_failure",
        translation_key="light_failure",
        api_domain=DOMAIN_HEALTH,
        device_class=BinarySensorDeviceClass.PROBLEM,
        is_on_fn=_any_light_failure,
        attributes_fn=_failed_lights,
    ),
    *_light_warnings(),
    # --- parking climatization --------------------------------------------
    _non_empty_list(
        key="climatization_error",
        api_domain=DOMAIN_PARKING_CLIMATIZATION,
        api_key="errors",
        attribute="errors",
    ),
    _non_empty_list(
        key="climatization_warning",
        api_domain=DOMAIN_PARKING_CLIMATIZATION,
        api_key="warnings",
        attribute="warnings",
    ),
    # --- pre-cleaning ------------------------------------------------------
    PolestarBinarySensorEntityDescription(
        key="pre_cleaning_last_cycle_valid",
        translation_key="pre_cleaning_last_cycle_valid",
        api_domain=DOMAIN_PRE_CLEANING,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=lambda data: nested(data, "lastCycleValid"),
    ),
    # --- charging ----------------------------------------------------------
    PolestarBinarySensorEntityDescription(
        key="charge_now",
        translation_key="charge_now",
        api_domain=DOMAIN_CHARGE_NOW,
        is_on_fn=lambda data: nested(data, "syncedOverrideChargeTimer", "override"),
    ),
    PolestarBinarySensorEntityDescription(
        key="pending_charge_now",
        translation_key="pending_charge_now",
        api_domain=DOMAIN_CHARGE_NOW,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        is_on_fn=lambda data: nested(data, "pendingOverrideChargeTimer", "override"),
    ),
    PolestarBinarySensorEntityDescription(
        key="charge_timer_activated",
        translation_key="charge_timer_activated",
        api_domain=DOMAIN_GLOBAL_CHARGE_TIMER,
        is_on_fn=lambda data: nested(data, "globalChargeTimer", "activated"),
    ),
    PolestarBinarySensorEntityDescription(
        key="at_charge_location",
        translation_key="at_charge_location",
        api_domain=DOMAIN_IS_AT_CHARGE_LOCATION,
        is_on_fn=lambda data: bool(nested(data, "locationId")),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PolestarConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Polestar binary sensors for every vehicle on the account."""
    async_add_entities(
        PolestarBinarySensor(coordinator, description)
        for coordinator in entry.runtime_data.coordinators
        for description in BINARY_SENSOR_DESCRIPTIONS
        if description.api_domain in coordinator.supported_domains
    )


class PolestarBinarySensor(PolestarEntity, BinarySensorEntity):
    """A boolean state read from the Polestar Data Portal."""

    entity_description: PolestarBinarySensorEntityDescription

    def __init__(
        self,
        coordinator: PolestarVehicleCoordinator,
        description: PolestarBinarySensorEntityDescription,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, description, description.api_domain)

    @property
    def is_on(self) -> bool | None:
        """Return the current state."""
        return self.entity_description.is_on_fn(self.domain_data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the underlying enum value or code list, where relevant."""
        if (attributes_fn := self.entity_description.attributes_fn) is None:
            return None
        return attributes_fn(self.domain_data)
