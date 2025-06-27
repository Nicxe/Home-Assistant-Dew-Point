"""
Sensor part for the Dew Point integration.
Arden Buck equation, dynamic decimals, and support for options flow.
"""
import logging
import math

from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT,
    UnitOfTemperature,
)
from homeassistant.util import slugify, convert
from homeassistant.util.unit_conversion import TemperatureConverter

from . import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    """Create sensor from config entry and its options."""
    # Prioritize entry.options, fallback to entry.data
    name = entry.data["name"]

    temperature_sensor = entry.options.get(
        "temperature_sensor", entry.data["temperature_sensor"]
    )
    humidity_sensor = entry.options.get(
        "humidity_sensor", entry.data["humidity_sensor"]
    )

    # decimal_places = options, otherwise data, otherwise 1
    decimal_places = entry.options.get(
        "decimal_places", entry.data.get("decimal_places", 1)
    )
    decimal_places = int(decimal_places)  # ensure integer

    async_add_entities(
        [
            DewPointSensor(
                hass,
                entry.entry_id,
                name,
                temperature_sensor,
                humidity_sensor,
                decimal_places
            )
        ],
        update_before_add=True  # Run an update immediately
    )


def _calculate_dew_point_arden_buck(temp_c: float, rel_hum: float) -> float | None:
    """Calculate dew point (°C) according to Arden Buck's equation."""
    es = 0.61121 * math.exp(
        (18.678 - (temp_c / 234.5)) * (temp_c / (257.14 + temp_c))
    )
    e = rel_hum * es
    if e <= 0:
        return None

    alpha = math.log(e / 0.61121)
    denominator = 18.678 - alpha
    if abs(denominator) < 1e-10:
        return None

    return (257.14 * alpha) / denominator


class DewPointSensor(SensorEntity):
    """Sensor for dew point with Arden Buck's equation, dynamic number of decimals, and options flow."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_icon = "mdi:water-thermometer-outline"
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(self, hass, entry_id, name, entity_dry_temp, entity_rel_hum, decimal_places: int):
        """Initialize the sensor."""
        self.hass = hass
        self._attr_name = name
        self._attr_unique_id = f"{entry_id}_dewpoint_{slugify(name)}"

        self._entity_dry_temp = entity_dry_temp
        self._entity_rel_hum = entity_rel_hum
        self._decimal_places = decimal_places

        self._unsub_listener = None
        self._startup_handle = None

        self._dry_temp_value = None  # °C
        self._rel_hum_value = None   # 0–1

        self._attr_native_value = None

        # Delay to give sensors time to become available
        self.delay_seconds = 10

    async def async_added_to_hass(self):
        """When the sensor is added to HA."""
        @callback
        def sensor_state_listener(event):
            """Listen to state_changed event and update the dew point."""
            self.async_schedule_update_ha_state(True)

        @callback
        def sensor_startup(_event):
            """Set up event listeners and wait a while before the first update."""
            self._unsub_listener = async_track_state_change_event(
                self.hass,
                [self._entity_dry_temp, self._entity_rel_hum],
                sensor_state_listener,
            )
            self._startup_handle = self.hass.loop.call_later(
                self.delay_seconds,
                lambda: self.async_schedule_update_ha_state(True),
            )

        self.hass.bus.async_listen_once("homeassistant_started", sensor_startup)

    async def async_will_remove_from_hass(self) -> None:
        """Clean up listeners when entity is removed."""
        if self._unsub_listener is not None:
            self._unsub_listener()
            self._unsub_listener = None
        if self._startup_handle is not None:
            self._startup_handle.cancel()
            self._startup_handle = None

    @property
    def extra_state_attributes(self):
        """Show current temp/humidity and number of decimals as attributes."""
        return {
            "temperature": self._dry_temp_value,
            "humidity": (
                round(self._rel_hum_value * 100, 1) 
                if self._rel_hum_value is not None 
                else None
            ),
            "decimal_places": self._decimal_places
        }

    async def async_update(self):
        """Fetch values and calculate the dew point."""
        dry_temp = self._get_dry_temp(self._entity_dry_temp)
        rel_hum = self._get_rel_hum(self._entity_rel_hum)

        self._dry_temp_value = dry_temp
        self._rel_hum_value = rel_hum

        if dry_temp is not None and rel_hum is not None:
            dew_point = _calculate_dew_point_arden_buck(dry_temp, rel_hum)
            if dew_point is not None:
                self._attr_native_value = round(dew_point, self._decimal_places)
            else:
                self._attr_native_value = None
        else:
            self._attr_native_value = None

    @callback
    def _get_dry_temp(self, entity_id):
        """Read and convert temperature from sensor in °C."""
        state = self.hass.states.get(entity_id)
        if not state or state.state in [None, "unknown", "unavailable"]:
            _LOGGER.debug("Temperature sensor %s is unavailable.", entity_id)
            return None

        unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
        value_str = state.state
        value_float = convert(value_str, float)

        if value_float is None:
            _LOGGER.error("Cannot interpret temperature value (%s) from %s.", value_str, entity_id)
            return None

        # If the unit is °F, convert to °C. Otherwise, if already °C, keep.
        if unit in (UnitOfTemperature.FAHRENHEIT, UnitOfTemperature.CELSIUS):
            try:
                return TemperatureConverter.convert(
                    value_float, unit, UnitOfTemperature.CELSIUS
                )
            except ValueError as ex:
                _LOGGER.error("Error in temperature conversion: %s", ex)
                return None

        _LOGGER.error("Sensor %s has unit measure %s, not supported (only °C/°F).", entity_id, unit)
        return None

    @callback
    def _get_rel_hum(self, entity_id):
        """Read and convert relative humidity (0–1) from sensor."""
        state = self.hass.states.get(entity_id)
        if not state or state.state in [None, "unknown", "unavailable"]:
            _LOGGER.debug("Humidity sensor %s is unavailable.", entity_id)
            return None

        value_str = state.state
        value_float = convert(value_str, float)
        unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)

        if value_float is None:
            _LOGGER.error("Cannot interpret humidity value (%s) from %s.", value_str, entity_id)
            return None

        if unit != "%":
            _LOGGER.error("Sensor %s has unit measure %s, not supported (only %%).", entity_id, unit)
            return None

        if not (0 <= value_float <= 100):
            _LOGGER.error("Humidity sensor %s reports value outside 0–100%%: %s", entity_id, value_float)
            return None

        return value_float / 100.0
