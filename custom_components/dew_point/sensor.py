"""
Sensor-del för Dew Point-integrationen.
Arden Buck-ekvation, dynamiska decimaler och stöd för options flow.
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
    """Skapa sensor utifrån config entry och dess options."""
    # Prioritera entry.options, fallback till entry.data
    name = entry.data["name"]

    temperature_sensor = entry.options.get(
        "temperature_sensor", entry.data["temperature_sensor"]
    )
    humidity_sensor = entry.options.get(
        "humidity_sensor", entry.data["humidity_sensor"]
    )

    # decimal_places = options, annars data, annars 1
    decimal_places = entry.options.get(
        "decimal_places", entry.data.get("decimal_places", 1)
    )
    decimal_places = int(decimal_places)  # säkerställ heltal

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
        update_before_add=True  # Kör en update direkt
    )


def _calculate_dew_point_arden_buck(temp_c: float, rel_hum: float) -> float | None:
    """Beräkna daggpunkt (°C) enligt Arden Bucks ekvation."""
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
    """Sensor för daggpunkt med Arden Bucks ekvation, dynamiskt antal decimaler och options flow."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_icon = "mdi:water-thermometer-outline"
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(self, hass, entry_id, name, entity_dry_temp, entity_rel_hum, decimal_places: int):
        """Initiera sensorn."""
        self.hass = hass
        self._attr_name = name
        self._attr_unique_id = f"{entry_id}_dewpoint_{slugify(name)}"

        self._entity_dry_temp = entity_dry_temp
        self._entity_rel_hum = entity_rel_hum
        self._decimal_places = decimal_places

        self._dry_temp_value = None  # °C
        self._rel_hum_value = None   # 0–1

        self._attr_native_value = None

        # Fördröjning för att ge sensorer tid att bli tillgängliga
        self.delay_seconds = 10

    async def async_added_to_hass(self):
        """När sensorn läggs till i HA."""
        @callback
        def sensor_state_listener(event):
            """Lyssna på state_changed-event och uppdatera daggpunkten."""
            self.async_schedule_update_ha_state(True)

        @callback
        def sensor_startup(_event):
            """Sätt upp eventlyssnare och vänta en stund innan första update."""
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
        """Visa aktuell temp/fukt och antal decimaler som attribut."""
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
        """Hämta värden och beräkna daggpunkten."""
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
        """Läs och konvertera temperatur från sensor i °C."""
        state = self.hass.states.get(entity_id)
        if not state or state.state in [None, "unknown", "unavailable"]:
            _LOGGER.debug("Temperatursensor %s är otillgänglig.", entity_id)
            return None

        unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
        value_str = state.state
        value_float = convert(value_str, float)

        if value_float is None:
            _LOGGER.error("Kan inte tolka temperaturvärde (%s) från %s.", value_str, entity_id)
            return None

        # Om enheten är °F, konvertera till °C. Annars om redan °C, behåll.
        if unit in (UnitOfTemperature.FAHRENHEIT, UnitOfTemperature.CELSIUS):
            try:
                return TemperatureConverter.convert(
                    value_float, unit, UnitOfTemperature.CELSIUS
                )
            except ValueError as ex:
                _LOGGER.error("Fel vid temperaturkonvertering: %s", ex)
                return None

        _LOGGER.error("Sensor %s har enhetsmått %s, stöds ej (endast °C/°F).", entity_id, unit)
        return None

    @callback
    def _get_rel_hum(self, entity_id):
        """Läs och omvandla relativ fukt (0–1) från sensor."""
        state = self.hass.states.get(entity_id)
        if not state or state.state in [None, "unknown", "unavailable"]:
            _LOGGER.debug("Fuktsensor %s är otillgänglig.", entity_id)
            return None

        value_str = state.state
        value_float = convert(value_str, float)
        unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)

        if value_float is None:
            _LOGGER.error("Kan inte tolka fuktvärde (%s) från %s.", value_str, entity_id)
            return None

        if unit != "%":
            _LOGGER.error("Sensor %s har enhetsmått %s, stöds ej (endast %%).", entity_id, unit)
            return None

        if not (0 <= value_float <= 100):
            _LOGGER.error("Fuktsensor %s rapporterar värde utanför 0–100%%: %s", entity_id, value_float)
            return None

        return value_float / 100.0