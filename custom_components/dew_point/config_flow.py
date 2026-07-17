"""Config flow for the Dew Point integration."""

from __future__ import annotations

from collections.abc import Mapping
import math
from typing import Any, cast

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.components.weather import (
    ATTR_WEATHER_HUMIDITY,
    ATTR_WEATHER_TEMPERATURE,
    ATTR_WEATHER_TEMPERATURE_UNIT,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_DEVICE_CLASS,
    ATTR_UNIT_OF_MEASUREMENT,
    CONF_NAME,
    PERCENTAGE,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    Platform,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import AbortFlow
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.schema_config_entry_flow import (
    SchemaCommonFlowHandler,
    SchemaConfigFlowHandler,
    SchemaFlowError,
    SchemaFlowFormStep,
    SchemaOptionsFlowHandler,
    entity_selector_without_own_entities,
)
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
)
from homeassistant.util.unit_conversion import TemperatureConverter
import voluptuous as vol

from .calculation import MAX_WATER_TEMPERATURE_C, MIN_BUCK_TEMPERATURE_C
from .const import (
    CONF_CONDENSATION_THRESHOLD,
    CONF_HUMIDITY_SENSOR,
    CONF_HYSTERESIS,
    CONF_SOURCE_TYPE,
    CONF_SURFACE_TEMPERATURE_SENSOR,
    CONF_TEMPERATURE_SENSOR,
    CONF_WEATHER_ENTITY,
    CONFIG_ENTRY_MINOR_VERSION,
    CONFIG_ENTRY_VERSION,
    DEFAULT_CONDENSATION_THRESHOLD,
    DEFAULT_HYSTERESIS,
    DEFAULT_NAME,
    DOMAIN,
    MAX_CONDENSATION_THRESHOLD,
    MAX_HYSTERESIS,
    MIN_CONDENSATION_THRESHOLD,
    MIN_HYSTERESIS,
    SOURCE_TYPE_SENSORS,
    SOURCE_TYPE_WEATHER,
)
from .preview import async_setup_preview as async_setup_preview_api

_TEMPERATURE_SELECTOR_CONFIG = EntitySelectorConfig(
    domain=Platform.SENSOR,
    device_class=SensorDeviceClass.TEMPERATURE,
)
_HUMIDITY_SELECTOR_CONFIG = EntitySelectorConfig(
    domain=Platform.SENSOR,
    device_class=SensorDeviceClass.HUMIDITY,
)
_WEATHER_SELECTOR_CONFIG = EntitySelectorConfig(domain=Platform.WEATHER)


def _source_type_schema() -> vol.Schema:
    """Return the common first-step schema."""
    return vol.Schema(
        {
            vol.Required(CONF_NAME, default=DEFAULT_NAME): TextSelector(),
            vol.Required(CONF_SOURCE_TYPE, default=SOURCE_TYPE_SENSORS): SelectSelector(
                SelectSelectorConfig(
                    options=[SOURCE_TYPE_SENSORS, SOURCE_TYPE_WEATHER],
                    translation_key=CONF_SOURCE_TYPE,
                )
            ),
        }
    )


def _measurement_settings(
    temperature_selector: EntitySelector,
) -> dict[vol.Marker, Any]:
    """Return fields shared by both measurement-source modes."""
    return {
        vol.Optional(CONF_SURFACE_TEMPERATURE_SENSOR): temperature_selector,
        vol.Required(
            CONF_CONDENSATION_THRESHOLD,
            default=DEFAULT_CONDENSATION_THRESHOLD,
        ): NumberSelector(
            NumberSelectorConfig(
                min=MIN_CONDENSATION_THRESHOLD,
                max=MAX_CONDENSATION_THRESHOLD,
                step="any",
                mode=NumberSelectorMode.BOX,
                unit_of_measurement=UnitOfTemperature.CELSIUS,
                translation_key=CONF_CONDENSATION_THRESHOLD,
            )
        ),
        vol.Required(CONF_HYSTERESIS, default=DEFAULT_HYSTERESIS): NumberSelector(
            NumberSelectorConfig(
                min=MIN_HYSTERESIS,
                max=MAX_HYSTERESIS,
                step="any",
                mode=NumberSelectorMode.BOX,
                unit_of_measurement=UnitOfTemperature.CELSIUS,
                translation_key=CONF_HYSTERESIS,
            )
        ),
    }


def _sensors_schema() -> vol.Schema:
    """Return the separate temperature and humidity sensor schema."""
    temperature_selector = EntitySelector(
        EntitySelectorConfig(_TEMPERATURE_SELECTOR_CONFIG)
    )
    humidity_selector = EntitySelector(EntitySelectorConfig(_HUMIDITY_SELECTOR_CONFIG))
    return vol.Schema(
        {
            vol.Required(CONF_TEMPERATURE_SENSOR): temperature_selector,
            vol.Required(CONF_HUMIDITY_SENSOR): humidity_selector,
            **_measurement_settings(temperature_selector),
        }
    )


def _weather_schema() -> vol.Schema:
    """Return the weather entity schema."""
    temperature_selector = EntitySelector(
        EntitySelectorConfig(_TEMPERATURE_SELECTOR_CONFIG)
    )
    return vol.Schema(
        {
            vol.Required(CONF_WEATHER_ENTITY): EntitySelector(
                EntitySelectorConfig(_WEATHER_SELECTOR_CONFIG)
            ),
            **_measurement_settings(temperature_selector),
        }
    )


CONFIG_SCHEMA = _source_type_schema()
SENSORS_SCHEMA = _sensors_schema()
WEATHER_SCHEMA = _weather_schema()


async def _options_sensors_schema(handler: SchemaCommonFlowHandler) -> vol.Schema:
    """Return the sensor-mode options schema without this helper's own entities."""
    parent = cast(SchemaOptionsFlowHandler, handler.parent_handler)
    temperature_selector = entity_selector_without_own_entities(
        parent, _TEMPERATURE_SELECTOR_CONFIG
    )
    humidity_selector = entity_selector_without_own_entities(
        parent, _HUMIDITY_SELECTOR_CONFIG
    )
    return vol.Schema(
        {
            vol.Required(CONF_TEMPERATURE_SENSOR): temperature_selector,
            vol.Required(CONF_HUMIDITY_SENSOR): humidity_selector,
            **_measurement_settings(temperature_selector),
        }
    )


async def _options_weather_schema(handler: SchemaCommonFlowHandler) -> vol.Schema:
    """Return the weather-mode options schema without this helper's own entities."""
    parent = cast(SchemaOptionsFlowHandler, handler.parent_handler)
    temperature_selector = entity_selector_without_own_entities(
        parent, _TEMPERATURE_SELECTOR_CONFIG
    )
    return vol.Schema(
        {
            vol.Required(CONF_WEATHER_ENTITY): EntitySelector(
                EntitySelectorConfig(_WEATHER_SELECTOR_CONFIG)
            ),
            **_measurement_settings(temperature_selector),
        }
    )


async def _next_source_step(options: dict[str, Any]) -> str:
    """Continue to the form for the selected source type."""
    return cast(str, options[CONF_SOURCE_TYPE])


async def _validate_source_type(
    _handler: SchemaCommonFlowHandler, user_input: dict[str, Any]
) -> dict[str, Any]:
    """Validate and normalize the helper name and source type."""
    name = str(user_input.get(CONF_NAME, "")).strip()
    if not name or len(name) > 100:
        raise SchemaFlowError("invalid_name")
    source_type = user_input.get(CONF_SOURCE_TYPE)
    if source_type not in (SOURCE_TYPE_SENSORS, SOURCE_TYPE_WEATHER):
        raise SchemaFlowError("invalid_source_type")
    return {CONF_NAME: name, CONF_SOURCE_TYPE: source_type}


async def _validate_input(
    handler: SchemaCommonFlowHandler, user_input: dict[str, Any]
) -> dict[str, Any]:
    """Validate and normalize source entities and thresholds."""
    options = {**handler.options, **user_input}
    if CONF_SURFACE_TEMPERATURE_SENSOR not in user_input:
        options.pop(CONF_SURFACE_TEMPERATURE_SENSOR, None)
    name = str(options.get(CONF_NAME, "")).strip()
    if not name or len(name) > 100:
        raise SchemaFlowError("invalid_name")
    options[CONF_NAME] = name

    source_type = options.get(CONF_SOURCE_TYPE, SOURCE_TYPE_SENSORS)
    options[CONF_SOURCE_TYPE] = source_type
    stale_source_keys: tuple[str, ...]
    if source_type == SOURCE_TYPE_WEATHER:
        options[CONF_WEATHER_ENTITY] = _validate_weather_source(
            handler, options[CONF_WEATHER_ENTITY]
        )
        stale_source_keys = (CONF_TEMPERATURE_SENSOR, CONF_HUMIDITY_SENSOR)
    elif source_type == SOURCE_TYPE_SENSORS:
        options[CONF_TEMPERATURE_SENSOR] = _validate_temperature_source(
            handler,
            options[CONF_TEMPERATURE_SENSOR],
            "invalid_temperature_sensor",
            enforce_calculation_range=True,
        )
        options[CONF_HUMIDITY_SENSOR] = _validate_humidity_source(
            handler, options[CONF_HUMIDITY_SENSOR]
        )
        stale_source_keys = (CONF_WEATHER_ENTITY,)
    else:
        raise SchemaFlowError("invalid_source_type")

    for source_key in stale_source_keys:
        options.pop(source_key, None)
    if surface_source := options.get(CONF_SURFACE_TEMPERATURE_SENSOR):
        options[CONF_SURFACE_TEMPERATURE_SENSOR] = _validate_temperature_source(
            handler,
            surface_source,
            "invalid_surface_temperature_sensor",
            enforce_calculation_range=False,
        )
    else:
        options.pop(CONF_SURFACE_TEMPERATURE_SENSOR, None)

    threshold = _validate_finite_range(
        options[CONF_CONDENSATION_THRESHOLD],
        MIN_CONDENSATION_THRESHOLD,
        MAX_CONDENSATION_THRESHOLD,
        "invalid_condensation_threshold",
    )
    hysteresis = _validate_finite_range(
        options[CONF_HYSTERESIS],
        MIN_HYSTERESIS,
        MAX_HYSTERESIS,
        "invalid_hysteresis",
    )
    options[CONF_CONDENSATION_THRESHOLD] = threshold
    options[CONF_HYSTERESIS] = hysteresis

    _abort_on_duplicate(handler, options)
    for source_key in stale_source_keys:
        handler.options.pop(source_key, None)
    return options


def _validate_weather_source(handler: SchemaCommonFlowHandler, source: str) -> str:
    """Validate weather temperature and humidity attributes."""
    error_key = "invalid_weather_entity"
    entity_id, state, _registry_entry = _resolve_source(
        handler, source, error_key, domain=Platform.WEATHER
    )
    if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
        return entity_id

    temperature = _finite_value(
        state.attributes.get(ATTR_WEATHER_TEMPERATURE), error_key
    )
    unit = state.attributes.get(ATTR_WEATHER_TEMPERATURE_UNIT)
    humidity = _finite_value(state.attributes.get(ATTR_WEATHER_HUMIDITY), error_key)
    if unit not in TemperatureConverter.VALID_UNITS or not 0 <= humidity <= 100:
        raise SchemaFlowError(error_key)
    try:
        temperature_c = TemperatureConverter.convert(
            temperature, unit, UnitOfTemperature.CELSIUS
        )
    except (TypeError, ValueError) as err:
        raise SchemaFlowError(error_key) from err
    if not MIN_BUCK_TEMPERATURE_C <= temperature_c <= MAX_WATER_TEMPERATURE_C:
        raise SchemaFlowError(error_key)
    return entity_id


def _finite_value(value: Any, error_key: str) -> float:
    """Return a finite float or raise a schema-flow error."""
    try:
        result = float(value)
    except (TypeError, ValueError) as err:
        raise SchemaFlowError(error_key) from err
    if not math.isfinite(result):
        raise SchemaFlowError(error_key)
    return result


def _validate_temperature_source(
    handler: SchemaCommonFlowHandler,
    source: str,
    error_key: str,
    *,
    enforce_calculation_range: bool,
) -> str:
    """Validate a temperature source, including legacy unit-only sensors."""
    entity_id, state, registry_entry = _resolve_source(handler, source, error_key)
    device_class, unit = _source_metadata(state, registry_entry)
    if device_class not in (None, SensorDeviceClass.TEMPERATURE):
        raise SchemaFlowError(error_key)
    if unit is not None and unit not in TemperatureConverter.VALID_UNITS:
        raise SchemaFlowError(error_key)
    if device_class is None and unit is None:
        raise SchemaFlowError(error_key)
    if state is not None and state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
        try:
            value = float(state.state)
        except (TypeError, ValueError) as err:
            raise SchemaFlowError(error_key) from err
        if not math.isfinite(value) or unit is None:
            raise SchemaFlowError(error_key)
        try:
            value_c = TemperatureConverter.convert(
                value, unit, UnitOfTemperature.CELSIUS
            )
        except (TypeError, ValueError) as err:
            raise SchemaFlowError(error_key) from err
        if enforce_calculation_range and not (
            MIN_BUCK_TEMPERATURE_C <= value_c <= MAX_WATER_TEMPERATURE_C
        ):
            raise SchemaFlowError(error_key)
    return entity_id


def _validate_humidity_source(handler: SchemaCommonFlowHandler, source: str) -> str:
    """Validate a relative-humidity source, including legacy unit-only sensors."""
    error_key = "invalid_humidity_sensor"
    entity_id, state, registry_entry = _resolve_source(handler, source, error_key)
    device_class, unit = _source_metadata(state, registry_entry)
    if device_class not in (None, SensorDeviceClass.HUMIDITY):
        raise SchemaFlowError(error_key)
    if unit is not None and unit != PERCENTAGE:
        raise SchemaFlowError(error_key)
    if device_class is None and unit != PERCENTAGE:
        raise SchemaFlowError(error_key)
    if state is not None and state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
        try:
            value = float(state.state)
        except (TypeError, ValueError) as err:
            raise SchemaFlowError(error_key) from err
        if not math.isfinite(value) or unit != PERCENTAGE or not 0 <= value <= 100:
            raise SchemaFlowError(error_key)
    return entity_id


def _resolve_source(
    handler: SchemaCommonFlowHandler,
    source: str,
    error_key: str,
    *,
    domain: Platform = Platform.SENSOR,
) -> tuple[str, Any, er.RegistryEntry | None]:
    """Resolve an entity ID or registry UUID and ensure the source exists."""
    registry = er.async_get(handler.parent_handler.hass)
    try:
        entity_id = er.async_validate_entity_id(registry, source)
    except vol.Invalid as err:
        raise SchemaFlowError(error_key) from err
    if not entity_id.startswith(f"{domain}."):
        raise SchemaFlowError(error_key)
    state = handler.parent_handler.hass.states.get(entity_id)
    registry_entry = registry.async_get(entity_id)
    if state is None and registry_entry is None:
        raise SchemaFlowError(error_key)
    return entity_id, state, registry_entry


def _source_metadata(
    state: Any, registry_entry: er.RegistryEntry | None
) -> tuple[str | None, str | None]:
    """Return effective device class and unit for a source entity."""
    device_class = state.attributes.get(ATTR_DEVICE_CLASS) if state else None
    unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT) if state else None
    if registry_entry is not None:
        device_class = (
            device_class
            or registry_entry.device_class
            or registry_entry.original_device_class
        )
        unit = unit or registry_entry.unit_of_measurement
    return device_class, unit


def _validate_finite_range(
    value: Any, minimum: float, maximum: float, error_key: str
) -> float:
    """Validate a finite numeric setting within an inclusive range."""
    try:
        result = float(value)
    except (TypeError, ValueError) as err:
        raise SchemaFlowError(error_key) from err
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise SchemaFlowError(error_key)
    return result


def _abort_on_duplicate(
    handler: SchemaCommonFlowHandler, options: Mapping[str, Any]
) -> None:
    """Abort when another entry uses the exact same source combination."""
    parent = handler.parent_handler
    registry = er.async_get(parent.hass)
    signature = _source_signature(registry, options)
    current_entry: ConfigEntry | None = getattr(parent, "config_entry", None)
    for entry in parent.hass.config_entries.async_entries(DOMAIN):
        if current_entry is not None and entry.entry_id == current_entry.entry_id:
            continue
        if _source_signature(registry, {**entry.data, **entry.options}) == signature:
            raise AbortFlow("already_configured")


def _source_signature(
    registry: er.EntityRegistry, options: Mapping[str, Any]
) -> tuple[str | None, ...]:
    """Return the source fields which define an exact duplicate."""
    source_type = cast(str, options.get(CONF_SOURCE_TYPE, SOURCE_TYPE_SENSORS))

    def _resolve(source_key: str) -> str | None:
        source = options.get(source_key)
        if not isinstance(source, str):
            return None
        return er.async_resolve_entity_id(registry, source) or source

    if source_type == SOURCE_TYPE_WEATHER:
        return (
            source_type,
            _resolve(CONF_WEATHER_ENTITY),
            None,
            _resolve(CONF_SURFACE_TEMPERATURE_SENSOR),
        )
    return (
        SOURCE_TYPE_SENSORS,
        _resolve(CONF_TEMPERATURE_SENSOR),
        _resolve(CONF_HUMIDITY_SENSOR),
        _resolve(CONF_SURFACE_TEMPERATURE_SENSOR),
    )


CONFIG_FLOW = {
    "user": SchemaFlowFormStep(
        schema=CONFIG_SCHEMA,
        validate_user_input=_validate_source_type,
        next_step=_next_source_step,
    ),
    SOURCE_TYPE_SENSORS: SchemaFlowFormStep(
        schema=SENSORS_SCHEMA,
        validate_user_input=_validate_input,
        preview=DOMAIN,
    ),
    SOURCE_TYPE_WEATHER: SchemaFlowFormStep(
        schema=WEATHER_SCHEMA,
        validate_user_input=_validate_input,
        preview=DOMAIN,
    ),
}

OPTIONS_FLOW = {
    "init": SchemaFlowFormStep(
        schema=CONFIG_SCHEMA,
        validate_user_input=_validate_source_type,
        next_step=_next_source_step,
    ),
    SOURCE_TYPE_SENSORS: SchemaFlowFormStep(
        schema=_options_sensors_schema,
        validate_user_input=_validate_input,
        preview=DOMAIN,
    ),
    SOURCE_TYPE_WEATHER: SchemaFlowFormStep(
        schema=_options_weather_schema,
        validate_user_input=_validate_input,
        preview=DOMAIN,
    ),
}


class DewpointConfigFlow(SchemaConfigFlowHandler, domain=DOMAIN):
    """Handle Dew Point config and options flows."""

    VERSION = CONFIG_ENTRY_VERSION
    MINOR_VERSION = CONFIG_ENTRY_MINOR_VERSION

    config_flow = CONFIG_FLOW
    options_flow = OPTIONS_FLOW
    options_flow_reloads = True

    @staticmethod
    async def async_setup_preview(hass: HomeAssistant) -> None:
        """Set up the live configuration preview API."""
        await async_setup_preview_api(hass)

    def async_config_entry_title(self, options: Mapping[str, Any]) -> str:
        """Return the config entry title."""
        return cast(str, options[CONF_NAME])
