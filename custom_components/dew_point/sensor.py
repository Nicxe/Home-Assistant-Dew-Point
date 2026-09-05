"""Sensor entities for the Dew Point integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    UnitOfPressure,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from .const import (
    OUTPUT_UNIT_CELSIUS,
    OUTPUT_UNIT_FAHRENHEIT,
)
from .runtime import DewPointRuntime, DewPointRuntimeData

try:
    from homeassistant.const import UnitOfDensity
except ImportError:  # Home Assistant < 2026.8
    from homeassistant.const import (
        CONCENTRATION_GRAMS_PER_CUBIC_METER as GRAMS_PER_CUBIC_METER,
    )
else:
    GRAMS_PER_CUBIC_METER = UnitOfDensity.GRAMS_PER_CUBIC_METER

ATTR_TEMPERATURE = "temperature"
ATTR_TEMPERATURE_UNIT = "temperature_unit"
ATTR_TEMPERATURE_ENTITY_ID = "temperature_entity_id"
ATTR_HUMIDITY = "humidity"
ATTR_HUMIDITY_ENTITY_ID = "humidity_entity_id"
ATTR_DECIMAL_PLACES = "decimal_places"
ATTR_OUTPUT_UNIT = "output_unit"


@dataclass(frozen=True, kw_only=True)
class DewPointSensorEntityDescription(SensorEntityDescription):
    """Describe one derived Dew Point sensor."""

    value_fn: Callable[[DewPointRuntimeData], StateType]
    requires_surface: bool = False
    legacy_attributes: bool = False


SENSOR_DESCRIPTIONS: tuple[DewPointSensorEntityDescription, ...] = (
    DewPointSensorEntityDescription(
        key="dew_point",
        translation_key="dew_point",
        icon="mdi:water-thermometer-outline",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda data: (
            data.properties.dew_point_c if data.properties is not None else None
        ),
        legacy_attributes=True,
    ),
    DewPointSensorEntityDescription(
        key="dew_point_spread",
        translation_key="dew_point_spread",
        icon="mdi:thermometer-chevron-down",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE_DELTA,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda data: (
            data.properties.dew_point_spread_c if data.properties is not None else None
        ),
    ),
    DewPointSensorEntityDescription(
        key="absolute_humidity",
        translation_key="absolute_humidity",
        icon="mdi:water-percent",
        native_unit_of_measurement=GRAMS_PER_CUBIC_METER,
        device_class=SensorDeviceClass.ABSOLUTE_HUMIDITY,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda data: (
            data.properties.absolute_humidity_g_m3
            if data.properties is not None
            else None
        ),
    ),
    DewPointSensorEntityDescription(
        key="vapor_pressure",
        translation_key="vapor_pressure",
        icon="mdi:gauge-low",
        native_unit_of_measurement=UnitOfPressure.KPA,
        device_class=SensorDeviceClass.PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        entity_registry_enabled_default=False,
        value_fn=lambda data: (
            data.properties.actual_vapor_pressure_kpa
            if data.properties is not None
            else None
        ),
    ),
    DewPointSensorEntityDescription(
        key="saturation_vapor_pressure",
        translation_key="saturation_vapor_pressure",
        icon="mdi:gauge-full",
        native_unit_of_measurement=UnitOfPressure.KPA,
        device_class=SensorDeviceClass.PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        entity_registry_enabled_default=False,
        value_fn=lambda data: (
            data.properties.saturation_vapor_pressure_kpa
            if data.properties is not None
            else None
        ),
    ),
    DewPointSensorEntityDescription(
        key="vapor_pressure_deficit",
        translation_key="vapor_pressure_deficit",
        icon="mdi:leaf",
        native_unit_of_measurement=UnitOfPressure.KPA,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        entity_registry_enabled_default=False,
        value_fn=lambda data: (
            data.properties.vapor_pressure_deficit_kpa
            if data.properties is not None
            else None
        ),
    ),
    DewPointSensorEntityDescription(
        key="frost_point",
        translation_key="frost_point",
        icon="mdi:snowflake-thermometer",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        entity_registry_enabled_default=False,
        value_fn=lambda data: (
            data.properties.frost_point_c if data.properties is not None else None
        ),
    ),
    DewPointSensorEntityDescription(
        key="surface_dew_point_margin",
        translation_key="surface_dew_point_margin",
        icon="mdi:home-thermometer-outline",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE_DELTA,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        requires_surface=True,
        value_fn=lambda data: data.surface_dew_point_margin_c,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up all calculated sensor entities for a config entry."""
    runtime: DewPointRuntime = entry.runtime_data
    async_add_entities(
        DewPointSensor(runtime, entry.entry_id, description)
        for description in SENSOR_DESCRIPTIONS
        if not description.requires_surface
        or runtime.surface_temperature_entity_id is not None
    )


class DewPointSensor(SensorEntity):
    """Represent one value from the shared Dew Point runtime."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _unrecorded_attributes = frozenset(
        {
            ATTR_TEMPERATURE,
            ATTR_TEMPERATURE_UNIT,
            ATTR_HUMIDITY,
            ATTR_DECIMAL_PLACES,
            ATTR_OUTPUT_UNIT,
        }
    )

    entity_description: DewPointSensorEntityDescription

    def __init__(
        self,
        runtime: DewPointRuntime,
        entry_id: str,
        description: DewPointSensorEntityDescription,
    ) -> None:
        """Initialize a calculated sensor."""
        self.runtime = runtime
        self.entity_description = description
        self._attr_unique_id = f"{entry_id}_{description.key}"
        self._attr_translation_placeholders = {"name": runtime.name}

    @property
    def available(self) -> bool:
        """Return whether required source data is available."""
        if self.entity_description.requires_surface:
            return self.runtime.data.surface_available
        return self.runtime.data.available

    @property
    def native_value(self) -> StateType:
        """Return the calculated native value from memory."""
        return self.entity_description.value_fn(self.runtime.data)

    @property
    def extra_state_attributes(self) -> dict[str, StateType] | None:
        """Preserve legacy attributes without recording changing source values."""
        if not self.entity_description.legacy_attributes:
            return None
        data = self.runtime.data
        attributes: dict[str, StateType] = {
            ATTR_TEMPERATURE_ENTITY_ID: self.runtime.temperature_entity_id,
            ATTR_HUMIDITY_ENTITY_ID: self.runtime.humidity_entity_id,
        }
        if self.runtime.legacy_compatibility:
            attributes.update(
                {
                    ATTR_TEMPERATURE: data.temperature_native_value,
                    ATTR_TEMPERATURE_UNIT: data.temperature_native_unit,
                    ATTR_HUMIDITY: data.humidity_percent,
                    ATTR_DECIMAL_PLACES: self.runtime.legacy_decimal_places,
                    ATTR_OUTPUT_UNIT: self._legacy_output_unit,
                }
            )
        return attributes

    @property
    def _legacy_output_unit(self) -> str:
        """Resolve the unit shown by the deprecated legacy attribute."""
        if self.runtime.legacy_output_unit == OUTPUT_UNIT_FAHRENHEIT:
            return UnitOfTemperature.FAHRENHEIT
        if self.runtime.legacy_output_unit == OUTPUT_UNIT_CELSIUS:
            return UnitOfTemperature.CELSIUS
        if self.runtime.data.temperature_native_unit in (
            UnitOfTemperature.CELSIUS,
            UnitOfTemperature.FAHRENHEIT,
        ):
            return self.runtime.data.temperature_native_unit
        return UnitOfTemperature.CELSIUS

    async def async_added_to_hass(self) -> None:
        """Subscribe to the shared runtime after entity registration."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.runtime.async_add_listener(self._async_runtime_updated)
        )

    @callback
    def _async_runtime_updated(self) -> None:
        """Write the latest in-memory value to Home Assistant."""
        self.async_write_ha_state()
