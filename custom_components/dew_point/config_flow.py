"""Config flow for the Dew Point integration."""

from __future__ import annotations

from collections.abc import Mapping
import math
from typing import Any, cast

from homeassistant.components.sensor import SensorDeviceClass
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
    TextSelector,
)
from homeassistant.util.unit_conversion import TemperatureConverter
import voluptuous as vol

from .calculation import MAX_WATER_TEMPERATURE_C, MIN_BUCK_TEMPERATURE_C
from .const import (
    CONF_CONDENSATION_THRESHOLD,
    CONF_HUMIDITY_SENSOR,
    CONF_HYSTERESIS,
    CONF_SURFACE_TEMPERATURE_SENSOR,
    CONF_TEMPERATURE_SENSOR,
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


def _schema() -> vol.Schema:
    """Return the configuration schema."""
    temperature_config = EntitySelectorConfig(_TEMPERATURE_SELECTOR_CONFIG)
    humidity_config = EntitySelectorConfig(_HUMIDITY_SELECTOR_CONFIG)

    return vol.Schema(
        {
            vol.Required(CONF_NAME, default=DEFAULT_NAME): TextSelector(),
            vol.Required(CONF_TEMPERATURE_SENSOR): EntitySelector(temperature_config),
            vol.Required(CONF_HUMIDITY_SENSOR): EntitySelector(humidity_config),
            vol.Optional(CONF_SURFACE_TEMPERATURE_SENSOR): EntitySelector(
                temperature_config
            ),
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
    )


CONFIG_SCHEMA = _schema()


async def _options_schema(handler: SchemaCommonFlowHandler) -> vol.Schema:
    """Return an options schema which excludes this helper's own entities."""
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
    )


async def _validate_input(
    handler: SchemaCommonFlowHandler, user_input: dict[str, Any]
) -> dict[str, Any]:
    """Validate and normalize source entities and thresholds."""
    options = {**handler.options, **user_input}
    if (
        isinstance(handler.parent_handler, SchemaOptionsFlowHandler)
        and CONF_SURFACE_TEMPERATURE_SENSOR not in user_input
    ):
        options.pop(CONF_SURFACE_TEMPERATURE_SENSOR, None)
    name = str(options.get(CONF_NAME, "")).strip()
    if not name or len(name) > 100:
        raise SchemaFlowError("invalid_name")
    options[CONF_NAME] = name

    options[CONF_TEMPERATURE_SENSOR] = _validate_temperature_source(
        handler,
        options[CONF_TEMPERATURE_SENSOR],
        "invalid_temperature_sensor",
        enforce_calculation_range=True,
    )
    options[CONF_HUMIDITY_SENSOR] = _validate_humidity_source(
        handler, options[CONF_HUMIDITY_SENSOR]
    )
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
    return options


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
    handler: SchemaCommonFlowHandler, source: str, error_key: str
) -> tuple[str, Any, er.RegistryEntry | None]:
    """Resolve an entity ID or registry UUID and ensure the source exists."""
    registry = er.async_get(handler.parent_handler.hass)
    try:
        entity_id = er.async_validate_entity_id(registry, source)
    except vol.Invalid as err:
        raise SchemaFlowError(error_key) from err
    if not entity_id.startswith(f"{Platform.SENSOR}."):
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
    return tuple(
        er.async_resolve_entity_id(registry, source) or source
        if isinstance(source := options.get(source_key), str)
        else None
        for source_key in (
            CONF_TEMPERATURE_SENSOR,
            CONF_HUMIDITY_SENSOR,
            CONF_SURFACE_TEMPERATURE_SENSOR,
        )
    )


CONFIG_FLOW = {
    "user": SchemaFlowFormStep(
        schema=CONFIG_SCHEMA,
        validate_user_input=_validate_input,
        preview=DOMAIN,
    )
}

OPTIONS_FLOW = {
    "init": SchemaFlowFormStep(
        schema=_options_schema,
        validate_user_input=_validate_input,
        preview=DOMAIN,
    )
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
