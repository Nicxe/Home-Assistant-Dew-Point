"""Live configuration preview for the Dew Point integration."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import math
from typing import Any

from homeassistant.components import websocket_api
from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT,
    PERCENTAGE,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfTemperature,
)
from homeassistant.core import (
    Event,
    EventStateChangedData,
    HomeAssistant,
    callback,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util.unit_conversion import TemperatureConverter
import voluptuous as vol

from .calculation import calculate_moist_air_properties
from .const import (
    CONF_CONDENSATION_THRESHOLD,
    CONF_HUMIDITY_SENSOR,
    CONF_SURFACE_TEMPERATURE_SENSOR,
    CONF_TEMPERATURE_SENSOR,
    DEFAULT_CONDENSATION_THRESHOLD,
    DOMAIN,
)

ATTR_ABSOLUTE_HUMIDITY = "absolute_humidity"
ATTR_AVAILABLE = "available"
ATTR_CONDENSATION_RISK = "condensation_risk"
ATTR_CONDENSATION_THRESHOLD = "condensation_threshold"
ATTR_DEW_POINT_SPREAD = "dew_point_spread"
ATTR_FROST_POINT = "frost_point"
ATTR_HUMIDITY = "humidity"
ATTR_HUMIDITY_ENTITY_ID = "humidity_entity_id"
ATTR_SATURATION_VAPOR_PRESSURE = "saturation_vapor_pressure"
ATTR_SURFACE_DEW_POINT_MARGIN = "surface_dew_point_margin"
ATTR_SURFACE_TEMPERATURE_ENTITY_ID = "surface_temperature_entity_id"
ATTR_TEMPERATURE = "temperature"
ATTR_TEMPERATURE_ENTITY_ID = "temperature_entity_id"
ATTR_VAPOR_PRESSURE = "vapor_pressure"
ATTR_VAPOR_PRESSURE_DEFICIT = "vapor_pressure_deficit"

type PreviewCallback = Callable[[str, Mapping[str, Any]], None]


async def async_setup_preview(hass: HomeAssistant) -> None:
    """Register the configuration-preview WebSocket command."""
    websocket_api.async_register_command(hass, ws_start_preview)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/start_preview",
        vol.Required("flow_id"): str,
        vol.Required("flow_type"): vol.Any("config_flow", "options_flow"),
        vol.Required("user_input"): dict,
    }
)
@callback
def ws_start_preview(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Start a live dew-point preview for a config or options flow."""
    options = _flow_options(hass, msg)

    @callback
    def async_preview_updated(state: str, attributes: Mapping[str, Any]) -> None:
        connection.send_message(
            websocket_api.event_message(
                msg["id"], {"attributes": attributes, "state": state}
            )
        )

    preview = DewPointPreview(hass, options, async_preview_updated)
    connection.send_result(msg["id"])
    connection.subscriptions[msg["id"]] = preview.async_start()


def _flow_options(hass: HomeAssistant, msg: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve the effective settings represented by a flow preview request."""
    user_input = dict(msg["user_input"])
    if msg["flow_type"] == "config_flow":
        hass.config_entries.flow.async_get(msg["flow_id"])
        return user_input

    flow_status = hass.config_entries.options.async_get(msg["flow_id"])
    config_entry = hass.config_entries.async_get_entry(flow_status["handler"])
    if config_entry is None:
        raise HomeAssistantError("Config entry not found")
    options = {**config_entry.options, **user_input}
    if CONF_SURFACE_TEMPERATURE_SENSOR not in user_input:
        options.pop(CONF_SURFACE_TEMPERATURE_SENSOR, None)
    return options


class DewPointPreview:
    """Calculate a side-effect-free preview and follow its source states."""

    def __init__(
        self,
        hass: HomeAssistant,
        options: Mapping[str, Any],
        update_callback: PreviewCallback,
    ) -> None:
        """Initialize a preview from partially completed form input."""
        self.hass = hass
        self.update_callback = update_callback
        self.temperature_entity_id = self._resolve_source(
            options.get(CONF_TEMPERATURE_SENSOR)
        )
        self.humidity_entity_id = self._resolve_source(
            options.get(CONF_HUMIDITY_SENSOR)
        )
        self.surface_temperature_entity_id = self._resolve_source(
            options.get(CONF_SURFACE_TEMPERATURE_SENSOR)
        )
        self.condensation_threshold = _finite_float(
            options.get(CONF_CONDENSATION_THRESHOLD)
        )
        if self.condensation_threshold is None:
            self.condensation_threshold = DEFAULT_CONDENSATION_THRESHOLD

    @callback
    def async_start(self) -> Callable[[], None]:
        """Publish the initial preview and subscribe to source-state changes."""
        self.async_refresh()
        sources = tuple(
            entity_id
            for entity_id in (
                self.temperature_entity_id,
                self.humidity_entity_id,
                self.surface_temperature_entity_id,
            )
            if entity_id is not None
        )
        if not sources:
            return lambda: None
        return async_track_state_change_event(
            self.hass, tuple(dict.fromkeys(sources)), self._async_source_changed
        )

    @callback
    def _async_source_changed(self, _event: Event[EventStateChangedData]) -> None:
        """Recalculate when a selected source changes."""
        self.async_refresh()

    @callback
    def async_refresh(self) -> None:
        """Publish one consistent preview snapshot."""
        temperature = self._temperature(self.temperature_entity_id)
        humidity = self._humidity(self.humidity_entity_id)
        surface_temperature = self._temperature(self.surface_temperature_entity_id)

        properties = None
        if temperature is not None and humidity is not None:
            properties = calculate_moist_air_properties(temperature, humidity)

        margin = None
        if (
            properties is not None
            and properties.dew_point_c is not None
            and surface_temperature is not None
        ):
            margin = surface_temperature - properties.dew_point_c

        attributes: dict[str, Any] = {
            ATTR_AVAILABLE: properties is not None,
            ATTR_CONDENSATION_THRESHOLD: self.condensation_threshold,
            ATTR_CONDENSATION_RISK: (
                margin <= self.condensation_threshold if margin is not None else None
            ),
            ATTR_TEMPERATURE_ENTITY_ID: self.temperature_entity_id,
            ATTR_HUMIDITY_ENTITY_ID: self.humidity_entity_id,
            ATTR_SURFACE_TEMPERATURE_ENTITY_ID: self.surface_temperature_entity_id,
            ATTR_TEMPERATURE: temperature,
            ATTR_HUMIDITY: humidity,
            ATTR_DEW_POINT_SPREAD: None,
            ATTR_ABSOLUTE_HUMIDITY: None,
            ATTR_VAPOR_PRESSURE: None,
            ATTR_SATURATION_VAPOR_PRESSURE: None,
            ATTR_VAPOR_PRESSURE_DEFICIT: None,
            ATTR_FROST_POINT: None,
            ATTR_SURFACE_DEW_POINT_MARGIN: margin,
        }
        if properties is None:
            mandatory_sources_selected = (
                self.temperature_entity_id is not None
                and self.humidity_entity_id is not None
            )
            self.update_callback(
                STATE_UNAVAILABLE if mandatory_sources_selected else STATE_UNKNOWN,
                attributes,
            )
            return

        attributes.update(
            {
                ATTR_DEW_POINT_SPREAD: properties.dew_point_spread_c,
                ATTR_ABSOLUTE_HUMIDITY: properties.absolute_humidity_g_m3,
                ATTR_VAPOR_PRESSURE: properties.actual_vapor_pressure_kpa,
                ATTR_SATURATION_VAPOR_PRESSURE: (
                    properties.saturation_vapor_pressure_kpa
                ),
                ATTR_VAPOR_PRESSURE_DEFICIT: (properties.vapor_pressure_deficit_kpa),
                ATTR_FROST_POINT: properties.frost_point_c,
            }
        )
        state = (
            str(properties.dew_point_c)
            if properties.dew_point_c is not None
            else STATE_UNKNOWN
        )
        self.update_callback(state, attributes)

    def _resolve_source(self, source: Any) -> str | None:
        """Resolve either an entity ID or registry UUID without raising."""
        if not isinstance(source, str):
            return None
        try:
            return er.async_validate_entity_id(er.async_get(self.hass), source)
        except vol.Invalid:
            return None

    def _temperature(self, entity_id: str | None) -> float | None:
        """Read a finite selected temperature and normalize it to Celsius."""
        if entity_id is None or (state := self.hass.states.get(entity_id)) is None:
            return None
        if state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return None
        unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
        value = _finite_float(state.state)
        if value is None or unit not in TemperatureConverter.VALID_UNITS:
            return None
        try:
            celsius = TemperatureConverter.convert(
                value, unit, UnitOfTemperature.CELSIUS
            )
        except (TypeError, ValueError):
            return None
        return celsius if math.isfinite(celsius) else None

    def _humidity(self, entity_id: str | None) -> float | None:
        """Read a finite relative-humidity percentage."""
        if entity_id is None or (state := self.hass.states.get(entity_id)) is None:
            return None
        if (
            state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE)
            or state.attributes.get(ATTR_UNIT_OF_MEASUREMENT) != PERCENTAGE
        ):
            return None
        value = _finite_float(state.state)
        return value if value is not None and 0 <= value <= 100 else None


def _finite_float(value: object) -> float | None:
    """Convert a state to a finite float."""
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None
