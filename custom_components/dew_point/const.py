"""Constants for the Dew Point integration."""

from __future__ import annotations

from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "dew_point"

PLATFORMS: Final = (Platform.SENSOR, Platform.BINARY_SENSOR)

CONFIG_ENTRY_VERSION: Final = 1
CONFIG_ENTRY_MINOR_VERSION: Final = 2

CONF_TEMPERATURE_SENSOR: Final = "temperature_sensor"
CONF_HUMIDITY_SENSOR: Final = "humidity_sensor"
CONF_SURFACE_TEMPERATURE_SENSOR: Final = "surface_temperature_sensor"
CONF_CONDENSATION_THRESHOLD: Final = "condensation_threshold"
CONF_HYSTERESIS: Final = "hysteresis"

DEFAULT_NAME: Final = "Dew Point"
DEFAULT_CONDENSATION_THRESHOLD: Final = 0.0
DEFAULT_HYSTERESIS: Final = 0.5

MIN_CONDENSATION_THRESHOLD: Final = -20.0
MAX_CONDENSATION_THRESHOLD: Final = 20.0
MIN_HYSTERESIS: Final = 0.0
MAX_HYSTERESIS: Final = 20.0

# Legacy version 1.1 keys retained only for config-entry migration.
CONF_DECIMAL_PLACES: Final = "decimal_places"
CONF_OUTPUT_UNIT: Final = "output_unit"
OUTPUT_UNIT_AUTO: Final = "auto"
OUTPUT_UNIT_CELSIUS: Final = "celsius"
OUTPUT_UNIT_FAHRENHEIT: Final = "fahrenheit"
DEFAULT_DECIMAL_PLACES: Final = 1

DEW_POINT_UNIQUE_ID_SUFFIX: Final = "dew_point"
