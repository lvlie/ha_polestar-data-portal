"""Sensor platform for the Polestar Data Portal integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    DEGREE,
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfLength,
    UnitOfPower,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import PolestarConfigEntry
from .const import (
    DOMAIN_AMP_LIMIT,
    DOMAIN_AVAILABILITY,
    DOMAIN_BATTERY,
    DOMAIN_CHARGE_LOCATIONS,
    DOMAIN_GLOBAL_CHARGE_TIMER,
    DOMAIN_HEALTH,
    DOMAIN_IS_AT_CHARGE_LOCATION,
    DOMAIN_LOCATION,
    DOMAIN_ODOMETER,
    DOMAIN_PARKING_CLIMATE_TIMER,
    DOMAIN_PARKING_CLIMATIZATION,
    DOMAIN_PRE_CLEANING,
    DOMAIN_TARGET_SOC,
)
from .coordinator import PolestarVehicleCoordinator
from .entity import PolestarEntity
from .enums import (
    AVAILABILITY_STATUS,
    BATTERY_PRECONDITIONING,
    CHARGE_TARGET_LEVEL_SETTING_TYPE,
    CHARGER_CONNECTION_STATUS,
    CHARGER_POWER_STATUS,
    CHARGING_STATUS,
    CHARGING_STATUS_V2,
    CHARGING_TYPE,
    ERROR_TYPE,
    HEATING_INTENSITY,
    HEATING_LEVEL,
    MAIN_CLIMATE_RUNNING_STATUS,
    MANUAL_PRECONDITIONING_STATUS,
    MANUAL_PRECONDITIONING_UNAVAILABLE_REASON,
    RUNNING_STATUS,
    SERVICE_WARNING,
    START_REASON,
    SYNC_STATUS,
    UNAVAILABLE_REASON,
    USAGE_MODE,
    VENTILATION,
)
from .helpers import (
    EnumSpec,
    daily_time_to_string,
    iso_to_datetime,
    nested,
    timestamp_to_datetime,
    to_float,
)

try:  # Home Assistant 2026.3 and later
    from homeassistant.const import UnitOfDensity

    MICROGRAMS_PER_CUBIC_METER = UnitOfDensity.MICROGRAMS_PER_CUBIC_METER
except ImportError:  # deprecated alias, same value, removed in Core 2027.8
    from homeassistant.const import (
        CONCENTRATION_MICROGRAMS_PER_CUBIC_METER as MICROGRAMS_PER_CUBIC_METER,
    )

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class PolestarSensorEntityDescription(SensorEntityDescription):
    """Describe a Polestar Data Portal sensor."""

    api_domain: str
    value_fn: Callable[[dict[str, Any]], Any]
    attributes_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None


# --- description helpers ---------------------------------------------------


def _plain(*keys: str) -> Callable[[dict[str, Any]], Any]:
    """Read a (possibly nested) value unchanged."""
    return lambda data: nested(data, *keys)


def _number(*keys: str) -> Callable[[dict[str, Any]], Any]:
    """Read a numeric value, tolerating string encodings."""
    return lambda data: to_float(nested(data, *keys))


def _scaled(factor: float, *keys: str) -> Callable[[dict[str, Any]], Any]:
    """Read a numeric value and scale it (used to turn metres into km)."""

    def value(data: dict[str, Any]) -> float | None:
        raw = to_float(nested(data, *keys))
        return None if raw is None else raw * factor

    return value


def _enum(spec: EnumSpec, *keys: str) -> Callable[[dict[str, Any]], Any]:
    """Read an enum value and map it onto its Home Assistant option."""
    return lambda data: spec.to_option(nested(data, *keys))


def _timestamp(*keys: str) -> Callable[[dict[str, Any]], Any]:
    """Read a TelemetryTimestamp object as a datetime."""
    return lambda data: timestamp_to_datetime(nested(data, *keys))


def _iso(*keys: str) -> Callable[[dict[str, Any]], Any]:
    """Read an ISO 8601 string as a datetime."""
    return lambda data: iso_to_datetime(nested(data, *keys))


def _daily_time(*keys: str) -> Callable[[dict[str, Any]], Any]:
    """Read a DailyTime object as an HH:MM string."""
    return lambda data: daily_time_to_string(nested(data, *keys))


def _count(*keys: str) -> Callable[[dict[str, Any]], Any]:
    """Return the length of a list field."""

    def value(data: dict[str, Any]) -> int | None:
        raw = nested(data, *keys)
        return len(raw) if isinstance(raw, list) else None

    return value


def _enum_sensor(
    *,
    key: str,
    api_domain: str,
    spec: EnumSpec,
    keys: tuple[str, ...],
    entity_category: EntityCategory | None = None,
    enabled: bool = True,
) -> PolestarSensorEntityDescription:
    """Build an enum sensor description."""
    return PolestarSensorEntityDescription(
        key=key,
        translation_key=key,
        api_domain=api_domain,
        device_class=SensorDeviceClass.ENUM,
        options=spec.options,
        entity_category=entity_category,
        entity_registry_enabled_default=enabled,
        value_fn=_enum(spec, *keys),
    )


def _duration(
    *,
    key: str,
    api_domain: str,
    keys: tuple[str, ...],
    unit: str = UnitOfTime.MINUTES,
    entity_category: EntityCategory | None = None,
    enabled: bool = True,
) -> PolestarSensorEntityDescription:
    """Build a duration sensor description."""
    return PolestarSensorEntityDescription(
        key=key,
        translation_key=key,
        api_domain=api_domain,
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=unit,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=entity_category,
        entity_registry_enabled_default=enabled,
        value_fn=_number(*keys),
    )


def _updated_at(
    key: str, api_domain: str, *keys: str
) -> PolestarSensorEntityDescription:
    """Build a diagnostic 'last updated' timestamp sensor."""
    return PolestarSensorEntityDescription(
        key=key,
        translation_key=key,
        api_domain=api_domain,
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_timestamp(*keys),
    )


def _energy_breakdown() -> tuple[PolestarSensorEntityDescription, ...]:
    """Build the per-category energy consumption sensors.

    The battery domain reports "other/driving/climate/battery" splits three
    times over: for the manual trip meter, the automatic trip meter and the
    period since the last charge. That is 24 sensors, so all of them are
    diagnostic and off by default; users who want a consumption breakdown can
    enable exactly the ones they need.
    """
    descriptions: list[PolestarSensorEntityDescription] = []
    variants = (
        ("manual", "Manual"),
        ("automatic", "Automatic"),
        ("since_charge", "SinceCharge"),
    )
    categories = ("other", "driving", "climate", "battery")

    for suffix, api_suffix in variants:
        for category in categories:
            descriptions.append(
                PolestarSensorEntityDescription(
                    key=f"energy_consumption_percentage_{suffix}_{category}",
                    translation_key=f"energy_consumption_percentage_{suffix}_{category}",
                    api_domain=DOMAIN_BATTERY,
                    native_unit_of_measurement=PERCENTAGE,
                    state_class=SensorStateClass.MEASUREMENT,
                    entity_category=EntityCategory.DIAGNOSTIC,
                    entity_registry_enabled_default=False,
                    value_fn=_number(
                        f"energyConsumptionPercentage{api_suffix}", category
                    ),
                )
            )
            descriptions.append(
                PolestarSensorEntityDescription(
                    key=f"energy_consumption_{suffix}_{category}",
                    translation_key=f"energy_consumption_{suffix}_{category}",
                    api_domain=DOMAIN_BATTERY,
                    device_class=SensorDeviceClass.ENERGY,
                    native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
                    state_class=SensorStateClass.TOTAL_INCREASING,
                    entity_category=EntityCategory.DIAGNOSTIC,
                    entity_registry_enabled_default=False,
                    value_fn=_number(f"energyConsumptionWh{api_suffix}", category),
                )
            )

    return tuple(descriptions)


def _seat_heating() -> tuple[PolestarSensorEntityDescription, ...]:
    """Build the requested seat/steering-wheel heating sensors."""
    seats = (
        ("front_left", "requestedFrontLeftSeat"),
        ("front_right", "requestedFrontRightSeat"),
        ("rear_left", "requestedRearLeftSeat"),
        ("rear_right", "requestedRearRightSeat"),
    )
    descriptions = [
        _enum_sensor(
            key=f"requested_seat_heating_{name}",
            api_domain=DOMAIN_PARKING_CLIMATIZATION,
            spec=HEATING_INTENSITY,
            keys=(api_key,),
            entity_category=EntityCategory.DIAGNOSTIC,
            enabled=False,
        )
        for name, api_key in seats
    ]
    descriptions.append(
        _enum_sensor(
            key="requested_steering_wheel_heating",
            api_domain=DOMAIN_PARKING_CLIMATIZATION,
            spec=HEATING_INTENSITY,
            keys=("requestedSteeringWheelHeating",),
            entity_category=EntityCategory.DIAGNOSTIC,
            enabled=False,
        )
    )
    return tuple(descriptions)


def _timer_seat_heating() -> tuple[PolestarSensorEntityDescription, ...]:
    """Build the parking-climate-timer seat heating sensors."""
    seats = (
        ("front_left", "frontRowLeftSeat"),
        ("front_right", "frontRowRightSeat"),
        ("rear_left", "rearRowLeftSeat"),
        ("rear_right", "rearRowRightSeat"),
    )
    return tuple(
        _enum_sensor(
            key=f"timer_seat_heating_{name}",
            api_domain=DOMAIN_PARKING_CLIMATE_TIMER,
            spec=HEATING_LEVEL,
            keys=("timerSettings", "seatHeatingIntensity", api_key),
            entity_category=EntityCategory.DIAGNOSTIC,
            enabled=False,
        )
        for name, api_key in seats
    )


def _tyre_pressures() -> tuple[PolestarSensorEntityDescription, ...]:
    """Build the four measured tyre pressure sensors plus the references."""
    corners = (
        ("front_left", "frontLeftTyrePressureKpa"),
        ("front_right", "frontRightTyrePressureKpa"),
        ("rear_left", "rearLeftTyrePressureKpa"),
        ("rear_right", "rearRightTyrePressureKpa"),
    )
    descriptions = [
        PolestarSensorEntityDescription(
            key=f"tyre_pressure_{name}",
            translation_key=f"tyre_pressure_{name}",
            api_domain=DOMAIN_HEALTH,
            device_class=SensorDeviceClass.PRESSURE,
            native_unit_of_measurement=UnitOfPressure.KPA,
            state_class=SensorStateClass.MEASUREMENT,
            value_fn=_number(api_key),
        )
        for name, api_key in corners
    ]
    descriptions.extend(
        PolestarSensorEntityDescription(
            key=f"tyre_reference_pressure_{axle}",
            translation_key=f"tyre_reference_pressure_{axle}",
            api_domain=DOMAIN_HEALTH,
            device_class=SensorDeviceClass.PRESSURE,
            native_unit_of_measurement=UnitOfPressure.KPA,
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
            entity_registry_enabled_default=False,
            value_fn=_number(api_key),
        )
        for axle, api_key in (
            ("front", "frontTyresReferencePressureKpa"),
            ("rear", "rearTyresReferencePressureKpa"),
        )
    )
    return tuple(descriptions)


SENSOR_DESCRIPTIONS: tuple[PolestarSensorEntityDescription, ...] = (
    # --- availability ------------------------------------------------------
    _enum_sensor(
        key="availability_status",
        api_domain=DOMAIN_AVAILABILITY,
        spec=AVAILABILITY_STATUS,
        keys=("availabilityStatus",),
    ),
    _enum_sensor(
        key="unavailable_reason",
        api_domain=DOMAIN_AVAILABILITY,
        spec=UNAVAILABLE_REASON,
        keys=("unavailableReason",),
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    _enum_sensor(
        key="usage_mode",
        api_domain=DOMAIN_AVAILABILITY,
        spec=USAGE_MODE,
        keys=("usageMode",),
    ),
    _updated_at("availability_updated_at", DOMAIN_AVAILABILITY, "timestamp"),
    # --- battery -----------------------------------------------------------
    PolestarSensorEntityDescription(
        key="battery_charge_level",
        translation_key="battery_charge_level",
        api_domain=DOMAIN_BATTERY,
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=_number("batteryChargeLevelPercentage"),
    ),
    _enum_sensor(
        key="charger_connection_status",
        api_domain=DOMAIN_BATTERY,
        spec=CHARGER_CONNECTION_STATUS,
        keys=("chargerConnectionStatus",),
    ),
    _enum_sensor(
        key="charger_power_status",
        api_domain=DOMAIN_BATTERY,
        spec=CHARGER_POWER_STATUS,
        keys=("chargerPowerStatus",),
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    _enum_sensor(
        key="charging_status",
        api_domain=DOMAIN_BATTERY,
        spec=CHARGING_STATUS_V2,
        keys=("chargingStatusV2",),
    ),
    # Deprecated upstream in favour of chargingStatusV2, kept for continuity.
    _enum_sensor(
        key="charging_status_legacy",
        api_domain=DOMAIN_BATTERY,
        spec=CHARGING_STATUS,
        keys=("chargingStatus",),
        entity_category=EntityCategory.DIAGNOSTIC,
        enabled=False,
    ),
    _enum_sensor(
        key="charging_type",
        api_domain=DOMAIN_BATTERY,
        spec=CHARGING_TYPE,
        keys=("chargingType",),
    ),
    PolestarSensorEntityDescription(
        key="charging_current",
        translation_key="charging_current",
        api_domain=DOMAIN_BATTERY,
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_number("chargingCurrentAmps"),
    ),
    PolestarSensorEntityDescription(
        key="charging_power",
        translation_key="charging_power",
        api_domain=DOMAIN_BATTERY,
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_number("chargingPowerWatts"),
    ),
    PolestarSensorEntityDescription(
        key="charging_voltage",
        translation_key="charging_voltage",
        api_domain=DOMAIN_BATTERY,
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_number("chargingVoltageVolts"),
    ),
    _duration(
        key="charging_time_to_full",
        api_domain=DOMAIN_BATTERY,
        keys=("estimatedChargingTimeToFullMinutes",),
    ),
    _duration(
        key="charging_time_to_target_distance",
        api_domain=DOMAIN_BATTERY,
        keys=("estimatedChargingTimeMinutesToTargetDistance",),
        entity_category=EntityCategory.DIAGNOSTIC,
        enabled=False,
    ),
    _duration(
        key="charging_time_to_minimum_soc",
        api_domain=DOMAIN_BATTERY,
        keys=("estimatedChargingTimeMinutesToMinimumSoc",),
        entity_category=EntityCategory.DIAGNOSTIC,
        enabled=False,
    ),
    PolestarSensorEntityDescription(
        key="range",
        translation_key="range",
        api_domain=DOMAIN_BATTERY,
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=_number("estimatedDistanceToEmptyKm"),
    ),
    # Duplicate of `range` in miles. Home Assistant converts units itself, so
    # this is only useful when comparing against the car's own display.
    PolestarSensorEntityDescription(
        key="range_miles",
        translation_key="range_miles",
        api_domain=DOMAIN_BATTERY,
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.MILES,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_number("estimatedDistanceToEmptyMiles"),
    ),
    PolestarSensorEntityDescription(
        key="average_energy_consumption",
        translation_key="average_energy_consumption",
        api_domain=DOMAIN_BATTERY,
        native_unit_of_measurement="kWh/100 km",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=_number("averageEnergyConsumptionKwhPer100Km"),
    ),
    PolestarSensorEntityDescription(
        key="average_energy_consumption_automatic",
        translation_key="average_energy_consumption_automatic",
        api_domain=DOMAIN_BATTERY,
        native_unit_of_measurement="kWh/100 km",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_number("averageEnergyConsumptionKwhPer100KmAutomatic"),
    ),
    PolestarSensorEntityDescription(
        key="average_energy_consumption_since_charge",
        translation_key="average_energy_consumption_since_charge",
        api_domain=DOMAIN_BATTERY,
        native_unit_of_measurement="kWh/100 km",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=_number("averageEnergyConsumptionKwhPer100KmSinceCharge"),
    ),
    PolestarSensorEntityDescription(
        key="total_energy_consumption",
        translation_key="total_energy_consumption",
        api_domain=DOMAIN_BATTERY,
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=_number("totalEnergyConsumptionWh"),
    ),
    PolestarSensorEntityDescription(
        key="total_energy_consumption_automatic",
        translation_key="total_energy_consumption_automatic",
        api_domain=DOMAIN_BATTERY,
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_number("totalEnergyConsumptionWhAutomatic"),
    ),
    PolestarSensorEntityDescription(
        key="total_energy_consumption_since_charge",
        translation_key="total_energy_consumption_since_charge",
        api_domain=DOMAIN_BATTERY,
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=_number("totalEnergyConsumptionWhSinceCharge"),
    ),
    # The spec gives no unit for the discharge (V2L/V2H) figures, so they are
    # reported unitless rather than guessed at.
    PolestarSensorEntityDescription(
        key="discharge_energy_available",
        translation_key="discharge_energy_available",
        api_domain=DOMAIN_BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_number("dischargeInfo", "energyAvailable"),
    ),
    PolestarSensorEntityDescription(
        key="discharge_energy_available_increase",
        translation_key="discharge_energy_available_increase",
        api_domain=DOMAIN_BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_number("dischargeInfo", "energyAvailableIncrease"),
    ),
    PolestarSensorEntityDescription(
        key="discharge_power_limit",
        translation_key="discharge_power_limit",
        api_domain=DOMAIN_BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_number("dischargeInfo", "powerLimit"),
    ),
    _enum_sensor(
        key="preconditioning_status",
        api_domain=DOMAIN_BATTERY,
        spec=MANUAL_PRECONDITIONING_STATUS,
        keys=("manualPreconditioning", "preconditioningStatus"),
    ),
    _enum_sensor(
        key="preconditioning_unavailable_reason",
        api_domain=DOMAIN_BATTERY,
        spec=MANUAL_PRECONDITIONING_UNAVAILABLE_REASON,
        keys=("manualPreconditioning", "unavailableReason"),
        entity_category=EntityCategory.DIAGNOSTIC,
        enabled=False,
    ),
    PolestarSensorEntityDescription(
        key="preconditioning_started_at",
        translation_key="preconditioning_started_at",
        api_domain=DOMAIN_BATTERY,
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_timestamp("manualPreconditioning", "startedAt"),
    ),
    PolestarSensorEntityDescription(
        key="preconditioning_ending_at",
        translation_key="preconditioning_ending_at",
        api_domain=DOMAIN_BATTERY,
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_timestamp("manualPreconditioning", "endingAt"),
    ),
    _updated_at("battery_updated_at", DOMAIN_BATTERY, "timestamp"),
    *_energy_breakdown(),
    # --- health ------------------------------------------------------------
    _enum_sensor(
        key="service_warning",
        api_domain=DOMAIN_HEALTH,
        spec=SERVICE_WARNING,
        keys=("serviceWarning",),
    ),
    PolestarSensorEntityDescription(
        key="distance_to_service",
        translation_key="distance_to_service",
        api_domain=DOMAIN_HEALTH,
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=_number("distanceToServiceKm"),
    ),
    _duration(
        key="days_to_service",
        api_domain=DOMAIN_HEALTH,
        keys=("daysToService",),
        unit=UnitOfTime.DAYS,
    ),
    _duration(
        key="engine_hours_to_service",
        api_domain=DOMAIN_HEALTH,
        keys=("engineHoursToService",),
        unit=UnitOfTime.HOURS,
        entity_category=EntityCategory.DIAGNOSTIC,
        enabled=False,
    ),
    *_tyre_pressures(),
    # --- location ----------------------------------------------------------
    PolestarSensorEntityDescription(
        key="speed",
        translation_key="speed",
        api_domain=DOMAIN_LOCATION,
        device_class=SensorDeviceClass.SPEED,
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=_number("speed"),
    ),
    PolestarSensorEntityDescription(
        key="heading",
        translation_key="heading",
        api_domain=DOMAIN_LOCATION,
        native_unit_of_measurement=DEGREE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=_number("heading"),
    ),
    PolestarSensorEntityDescription(
        key="altitude",
        translation_key="altitude",
        api_domain=DOMAIN_LOCATION,
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.METERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_number("altitude"),
    ),
    _updated_at("location_updated_at", DOMAIN_LOCATION, "timestamp"),
    # --- odometer ----------------------------------------------------------
    PolestarSensorEntityDescription(
        key="odometer",
        translation_key="odometer",
        api_domain=DOMAIN_ODOMETER,
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=0,
        value_fn=_scaled(0.001, "odometerMeters"),
    ),
    PolestarSensorEntityDescription(
        key="trip_meter_manual",
        translation_key="trip_meter_manual",
        api_domain=DOMAIN_ODOMETER,
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=1,
        value_fn=_number("tripMeterManualKm"),
    ),
    PolestarSensorEntityDescription(
        key="trip_meter_automatic",
        translation_key="trip_meter_automatic",
        api_domain=DOMAIN_ODOMETER,
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=1,
        value_fn=_number("tripMeterAutomaticKm"),
    ),
    PolestarSensorEntityDescription(
        key="trip_meter_since_charge",
        translation_key="trip_meter_since_charge",
        api_domain=DOMAIN_ODOMETER,
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=1,
        value_fn=_number("tripMeterSinceChargeKm"),
    ),
    PolestarSensorEntityDescription(
        key="average_speed_manual",
        translation_key="average_speed_manual",
        api_domain=DOMAIN_ODOMETER,
        device_class=SensorDeviceClass.SPEED,
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=_number("averageSpeedKmPerHour"),
    ),
    PolestarSensorEntityDescription(
        key="average_speed_automatic",
        translation_key="average_speed_automatic",
        api_domain=DOMAIN_ODOMETER,
        device_class=SensorDeviceClass.SPEED,
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_number("averageSpeedKmPerHourAutomatic"),
    ),
    PolestarSensorEntityDescription(
        key="average_speed_since_charge",
        translation_key="average_speed_since_charge",
        api_domain=DOMAIN_ODOMETER,
        device_class=SensorDeviceClass.SPEED,
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=_number("averageSpeedKmPerHourSinceCharge"),
    ),
    _updated_at("odometer_updated_at", DOMAIN_ODOMETER, "timestamp"),
)


def _charge_location_attributes(data: dict[str, Any]) -> dict[str, Any]:
    """Summarise the configured charge locations as state attributes."""
    locations = nested(data, "chargeLocations")
    if not isinstance(locations, list):
        return {}
    return {
        "locations": [
            {
                "alias": location.get("locationAlias"),
                "location_id": location.get("locationId"),
                "latitude": nested(location, "coordinate", "latitude"),
                "longitude": nested(location, "coordinate", "longitude"),
                "amp_limit": to_float(location.get("ampLimit")),
                "minimum_soc": to_float(location.get("minimumSoc")),
                "optimized_charging": location.get("isOptimizedChargingEnabled"),
                "bidirectional_charging": location.get(
                    "isBidirectionalChargingEnabled"
                ),
                "charge_timers": len(location.get("chargeTimers") or []),
                "departure_times": len(location.get("departureTimes") or []),
            }
            for location in locations
            if isinstance(location, dict)
        ]
    }


def _climate_timer_attributes(data: dict[str, Any]) -> dict[str, Any]:
    """Summarise the parking climate timers as state attributes."""
    timers = nested(data, "parkingClimateTimers")
    if not isinstance(timers, list):
        return {}
    return {
        "timers": [
            {
                "timer_id": timer.get("timerId"),
                "activated": timer.get("activated"),
                "ready_at": daily_time_to_string(timer.get("readyAt")),
                "repeat": timer.get("repeat"),
                "weekdays": [
                    day.lower()
                    for day in (timer.get("weekdays") or [])
                    if isinstance(day, str) and day != "UNSPECIFIED"
                ],
            }
            for timer in timers
            if isinstance(timer, dict)
        ]
    }


CHARGING_SENSOR_DESCRIPTIONS: tuple[PolestarSensorEntityDescription, ...] = (
    # --- parking climatization --------------------------------------------
    _enum_sensor(
        key="climatization_status",
        api_domain=DOMAIN_PARKING_CLIMATIZATION,
        spec=RUNNING_STATUS,
        keys=("runningStatus",),
    ),
    _enum_sensor(
        key="main_climate_status",
        api_domain=DOMAIN_PARKING_CLIMATIZATION,
        spec=MAIN_CLIMATE_RUNNING_STATUS,
        keys=("mainClimateRunningStatus",),
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    _enum_sensor(
        key="ventilation",
        api_domain=DOMAIN_PARKING_CLIMATIZATION,
        spec=VENTILATION,
        keys=("ventilation",),
    ),
    _enum_sensor(
        key="climatization_start_reason",
        api_domain=DOMAIN_PARKING_CLIMATIZATION,
        spec=START_REASON,
        keys=("startReason",),
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    PolestarSensorEntityDescription(
        key="cabin_temperature",
        translation_key="cabin_temperature",
        api_domain=DOMAIN_PARKING_CLIMATIZATION,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=_number("currentCompartmentTemperatureCelsius"),
    ),
    PolestarSensorEntityDescription(
        key="requested_cabin_temperature",
        translation_key="requested_cabin_temperature",
        api_domain=DOMAIN_PARKING_CLIMATIZATION,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=_number("requestedCompartmentTemperatureCelsius"),
    ),
    # Deprecated upstream in favour of startedAt/endingAt.
    _duration(
        key="climatization_runtime_left",
        api_domain=DOMAIN_PARKING_CLIMATIZATION,
        keys=("runtimeLeftMinutes",),
        entity_category=EntityCategory.DIAGNOSTIC,
        enabled=False,
    ),
    PolestarSensorEntityDescription(
        key="climatization_started_at",
        translation_key="climatization_started_at",
        api_domain=DOMAIN_PARKING_CLIMATIZATION,
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_timestamp("startedAt"),
    ),
    PolestarSensorEntityDescription(
        key="climatization_ending_at",
        translation_key="climatization_ending_at",
        api_domain=DOMAIN_PARKING_CLIMATIZATION,
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_timestamp("endingAt"),
    ),
    *_seat_heating(),
    # --- pre-cleaning ------------------------------------------------------
    _enum_sensor(
        key="pre_cleaning_status",
        api_domain=DOMAIN_PRE_CLEANING,
        spec=RUNNING_STATUS,
        keys=("runningStatus",),
    ),
    _enum_sensor(
        key="pre_cleaning_start_reason",
        api_domain=DOMAIN_PRE_CLEANING,
        spec=START_REASON,
        keys=("startReason",),
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    _enum_sensor(
        key="pre_cleaning_error",
        api_domain=DOMAIN_PRE_CLEANING,
        spec=ERROR_TYPE,
        keys=("error",),
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    PolestarSensorEntityDescription(
        key="cabin_air_quality_index",
        translation_key="cabin_air_quality_index",
        api_domain=DOMAIN_PRE_CLEANING,
        device_class=SensorDeviceClass.AQI,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_number("measuredAirQualityIndex"),
    ),
    PolestarSensorEntityDescription(
        key="cabin_particulate_matter",
        translation_key="cabin_particulate_matter",
        api_domain=DOMAIN_PRE_CLEANING,
        device_class=SensorDeviceClass.PM25,
        native_unit_of_measurement=MICROGRAMS_PER_CUBIC_METER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_number("measuredParticulateMatter25"),
    ),
    _duration(
        key="pre_cleaning_runtime_left",
        api_domain=DOMAIN_PRE_CLEANING,
        keys=("runtimeLeftMinutes",),
    ),
    PolestarSensorEntityDescription(
        key="pre_cleaning_last_cycle_completed",
        translation_key="pre_cleaning_last_cycle_completed",
        api_domain=DOMAIN_PRE_CLEANING,
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_timestamp("lastCycleCompleted"),
    ),
    PolestarSensorEntityDescription(
        key="pre_cleaning_measured_at",
        translation_key="pre_cleaning_measured_at",
        api_domain=DOMAIN_PRE_CLEANING,
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_timestamp("measurementDate"),
    ),
    # --- amp limit ---------------------------------------------------------
    PolestarSensorEntityDescription(
        key="amp_limit",
        translation_key="amp_limit",
        api_domain=DOMAIN_AMP_LIMIT,
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_number("ampLimit", "ampLimit"),
    ),
    PolestarSensorEntityDescription(
        key="pending_amp_limit",
        translation_key="pending_amp_limit",
        api_domain=DOMAIN_AMP_LIMIT,
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_number("pendingAmpLimit", "ampLimit"),
    ),
    PolestarSensorEntityDescription(
        key="amp_limit_updated_at",
        translation_key="amp_limit_updated_at",
        api_domain=DOMAIN_AMP_LIMIT,
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_iso("updatedAt"),
    ),
    # --- charge locations --------------------------------------------------
    PolestarSensorEntityDescription(
        key="charge_locations",
        translation_key="charge_locations",
        api_domain=DOMAIN_CHARGE_LOCATIONS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_count("chargeLocations"),
        attributes_fn=_charge_location_attributes,
    ),
    # --- global charge timer ----------------------------------------------
    PolestarSensorEntityDescription(
        key="charge_timer_start",
        translation_key="charge_timer_start",
        api_domain=DOMAIN_GLOBAL_CHARGE_TIMER,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_daily_time("globalChargeTimer", "start"),
    ),
    PolestarSensorEntityDescription(
        key="charge_timer_stop",
        translation_key="charge_timer_stop",
        api_domain=DOMAIN_GLOBAL_CHARGE_TIMER,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_daily_time("globalChargeTimer", "stop"),
    ),
    _enum_sensor(
        key="charge_timer_sync_status",
        api_domain=DOMAIN_GLOBAL_CHARGE_TIMER,
        spec=SYNC_STATUS,
        keys=("globalChargeTimer", "metadata", "syncStatus", "value"),
        entity_category=EntityCategory.DIAGNOSTIC,
        enabled=False,
    ),
    # --- is at charge location --------------------------------------------
    PolestarSensorEntityDescription(
        key="current_charge_location",
        translation_key="current_charge_location",
        api_domain=DOMAIN_IS_AT_CHARGE_LOCATION,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_plain("locationId"),
    ),
    PolestarSensorEntityDescription(
        key="charge_location_arrived_at",
        translation_key="charge_location_arrived_at",
        api_domain=DOMAIN_IS_AT_CHARGE_LOCATION,
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_iso("arrivedAt"),
    ),
    # --- parking climate timer --------------------------------------------
    PolestarSensorEntityDescription(
        key="parking_climate_timers",
        translation_key="parking_climate_timers",
        api_domain=DOMAIN_PARKING_CLIMATE_TIMER,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_count("parkingClimateTimers"),
        attributes_fn=_climate_timer_attributes,
    ),
    PolestarSensorEntityDescription(
        key="timer_requested_cabin_temperature",
        translation_key="timer_requested_cabin_temperature",
        api_domain=DOMAIN_PARKING_CLIMATE_TIMER,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_number("timerSettings", "requestedCompartmentTemperatureCelsius"),
    ),
    _enum_sensor(
        key="timer_steering_wheel_heating",
        api_domain=DOMAIN_PARKING_CLIMATE_TIMER,
        spec=HEATING_LEVEL,
        keys=("timerSettings", "steeringWheelHeatingIntensity"),
        entity_category=EntityCategory.DIAGNOSTIC,
        enabled=False,
    ),
    _enum_sensor(
        key="timer_battery_preconditioning",
        api_domain=DOMAIN_PARKING_CLIMATE_TIMER,
        spec=BATTERY_PRECONDITIONING,
        keys=("timerSettings", "batteryPreconditioning"),
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    *_timer_seat_heating(),
    # --- target SoC --------------------------------------------------------
    PolestarSensorEntityDescription(
        key="target_battery_charge_level",
        translation_key="target_battery_charge_level",
        api_domain=DOMAIN_TARGET_SOC,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=_number("targetSoc", "batteryChargeTargetLevel"),
    ),
    PolestarSensorEntityDescription(
        key="pending_target_battery_charge_level",
        translation_key="pending_target_battery_charge_level",
        api_domain=DOMAIN_TARGET_SOC,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_number("pendingTargetSoc", "batteryChargeTargetLevel"),
    ),
    _enum_sensor(
        key="target_soc_setting_type",
        api_domain=DOMAIN_TARGET_SOC,
        spec=CHARGE_TARGET_LEVEL_SETTING_TYPE,
        keys=("targetSoc", "chargeTargetLevelSettingType"),
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    _updated_at("target_soc_updated_at", DOMAIN_TARGET_SOC, "timestamp"),
)

ALL_SENSOR_DESCRIPTIONS = SENSOR_DESCRIPTIONS + CHARGING_SENSOR_DESCRIPTIONS


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PolestarConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Polestar sensors for every vehicle on the account."""
    async_add_entities(
        PolestarSensor(coordinator, description)
        for coordinator in entry.runtime_data.coordinators
        for description in ALL_SENSOR_DESCRIPTIONS
        if description.api_domain in coordinator.supported_domains
    )


class PolestarSensor(PolestarEntity, SensorEntity):
    """A single value read from the Polestar Data Portal."""

    entity_description: PolestarSensorEntityDescription

    def __init__(
        self,
        coordinator: PolestarVehicleCoordinator,
        description: PolestarSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, description, description.api_domain)

    @property
    def native_value(self) -> Any:
        """Return the current value."""
        return self.entity_description.value_fn(self.domain_data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra attributes for the list-valued sensors."""
        if (attributes_fn := self.entity_description.attributes_fn) is None:
            return None
        return attributes_fn(self.domain_data)
