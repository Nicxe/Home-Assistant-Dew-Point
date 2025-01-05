"""
Sensor-del för Dew Point-integrationen.
Använder Arden Bucks ekvation för daggpunktsberäkning.
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
    """Skapa sensorer för en konfigurationsinstans."""
    name = entry.data["name"]
    temperature_sensor = entry.data["temperature_sensor"]
    humidity_sensor = entry.data["humidity_sensor"]

    async_add_entities([
        DewPointSensor(
            hass,
            entry.entry_id,
            name,
            temperature_sensor,
            humidity_sensor
        )
    ])


def _calculate_dew_point_arden_buck(temp_c: float, rel_hum: float) -> float | None:
    """
    Beräkna daggpunkt (°C) enligt Arden Bucks ekvation.

    temp_c  : aktuell temperatur i °C
    rel_hum : relativ fuktighet (0–1), ex. 0.45 = 45%
    Returnerar daggpunkten i °C, eller None om beräkning ej möjlig.
    """
    # Mättnadsånga (kPa)
    es = 0.61121 * math.exp(
        (18.678 - (temp_c / 234.5)) * (temp_c / (257.14 + temp_c))
    )
    # Aktuellt ångtryck (kPa)
    e = rel_hum * es
    if e <= 0:
        return None

    alpha = math.log(e / 0.61121)
    denominator = 18.678 - alpha
    if abs(denominator) < 1e-10:
        return None

    return (257.14 * alpha) / denominator


class DewPointSensor(SensorEntity):
    """Sensor för daggpunkt med Arden Bucks ekvation."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_icon = "mdi:water-thermometer-outline"
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(self, hass, entry_id, name, entity_dry_temp, entity_rel_hum):
        """Initiera sensorn."""
        self.hass = hass
        self._attr_name = name
        self._attr_unique_id = f"{entry_id}_dewpoint_{slugify(name)}"

        self._entity_dry_temp = entity_dry_temp
        self._entity_rel_hum = entity_rel_hum

        # Temperatur (°C) och fukt (0–1) för attribut
        self._dry_temp_value = None
        self._rel_hum_value = None

        # Värde för sensorn (daggpunkt i °C)
        self._attr_native_value = None

        # Tidsfördröjning innan första avläsning
        self.delay_seconds = 10

    async def async_added_to_hass(self):
        """Kallas när sensorn läggs till i Home Assistant."""
        @callback
        def sensor_state_listener(event):
            """Lyssna på state_changed-event och uppdatera daggpunkten."""
            self.async_schedule_update_ha_state(True)

        @callback
        def sensor_startup(_event):
            """Setup eventlyssnare och fördröj första uppdatering."""
            async_track_state_change_event(
                self.hass,
                [self._entity_dry_temp, self._entity_rel_hum],
                sensor_state_listener
            )
            self.hass.loop.call_later(
                self.delay_seconds,
                lambda: self.async_schedule_update_ha_state(True)
            )

        self.hass.bus.async_listen_once("homeassistant_started", sensor_startup)

    @property
    def extra_state_attributes(self):
        """Visa aktuell temperatur och fukt som attribut."""
        return {
            "temperature": self._dry_temp_value,
            "humidity": (
                round(self._rel_hum_value * 100, 1) 
                if self._rel_hum_value is not None else None
            ),
        }

    async def async_update(self):
        """Hämta värden och beräkna daggpunkten med Arden Bucks ekvation."""
        dry_temp = self._get_dry_temp(self._entity_dry_temp)
        rel_hum = self._get_rel_hum(self._entity_rel_hum)

        self._dry_temp_value = dry_temp
        self._rel_hum_value = rel_hum

        if dry_temp is not None and rel_hum is not None:
            dew_point = _calculate_dew_point_arden_buck(dry_temp, rel_hum)
            self._attr_native_value = round(dew_point, 1) if dew_point else None
        else:
            self._attr_native_value = None

    @callback
    def _get_dry_temp(self, entity_id):
        """Läs och konvertera temperatur från sensor i °C."""
        state_obj = self.hass.states.get(entity_id)
        if not state_obj or state_obj.state in [None, "unknown", "unavailable"]:
            _LOGGER.debug("Temp-sensor %s är inte redo (otillgänglig).", entity_id)
            return None

        unit = state_obj.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
        value_str = state_obj.state
        value_float = convert(value_str, float)

        if value_float is None:
            _LOGGER.error(
                "Kan inte tolka temperaturvärde (%s) från sensor %s.",
                value_str,
                entity_id
            )
            return None

        # Omvandla °F → °C om nödvändigt
        if unit in (UnitOfTemperature.FAHRENHEIT, UnitOfTemperature.CELSIUS):
            try:
                return TemperatureConverter.convert(
                    value_float, unit, UnitOfTemperature.CELSIUS
                )
            except ValueError as ex:
                _LOGGER.error("Fel vid temperaturkonvertering: %s", ex)
                return None

        _LOGGER.error(
            "Sensor %s har enhetsmått %s, stöds ej (endast °C/°F).",
            entity_id,
            unit
        )
        return None

    @callback
    def _get_rel_hum(self, entity_id):
        """Läs och omvandla relativ fukt (0–1) från sensor."""
        state_obj = self.hass.states.get(entity_id)
        if not state_obj or state_obj.state in [None, "unknown", "unavailable"]:
            _LOGGER.debug("Fuktsensor %s är inte redo (otillgänglig).", entity_id)
            return None

        value_str = state_obj.state
        value_float = convert(value_str, float)
        unit = state_obj.attributes.get(ATTR_UNIT_OF_MEASUREMENT)

        if value_float is None:
            _LOGGER.error(
                "Kan inte tolka fuktvärde (%s) från sensor %s.",
                value_str,
                entity_id
            )
            return None

        if unit != "%":
            _LOGGER.error(
                "Sensor %s har enhetsmått %s, stöds ej (endast %%).",
                entity_id,
                unit
            )
            return None

        if not (0 <= value_float <= 100):
            _LOGGER.error(
                "Fuktsensor %s rapporterar värde utanför 0–100%%: %s",
                entity_id,
                value_float
            )
            return None

        return value_float / 100.0
