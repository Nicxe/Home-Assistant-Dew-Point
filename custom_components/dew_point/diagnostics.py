"""Diagnostics support for the Dew Point integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_DEVICE_CLASS,
    ATTR_UNIT_OF_MEASUREMENT,
    CONF_NAME,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_CONDENSATION_THRESHOLD,
    CONF_DECIMAL_PLACES,
    CONF_HUMIDITY_SENSOR,
    CONF_HYSTERESIS,
    CONF_OUTPUT_UNIT,
    CONF_SOURCE_TYPE,
    CONF_SURFACE_TEMPERATURE_SENSOR,
    CONF_TEMPERATURE_SENSOR,
    CONF_WEATHER_ENTITY,
)

_CONFIGURATION_KEYS = (
    CONF_NAME,
    CONF_SOURCE_TYPE,
    CONF_WEATHER_ENTITY,
    CONF_TEMPERATURE_SENSOR,
    CONF_HUMIDITY_SENSOR,
    CONF_SURFACE_TEMPERATURE_SENSOR,
    CONF_CONDENSATION_THRESHOLD,
    CONF_HYSTERESIS,
    # Retained so diagnostics remain useful for entries created by older releases.
    CONF_DECIMAL_PLACES,
    CONF_OUTPUT_UNIT,
)
_SOURCE_KEYS = (
    CONF_WEATHER_ENTITY,
    CONF_TEMPERATURE_SENSOR,
    CONF_HUMIDITY_SENSOR,
    CONF_SURFACE_TEMPERATURE_SENSOR,
)
_TO_REDACT = {
    "access_token",
    "api_key",
    "password",
    "refresh_token",
    "token",
}


def _effective_configuration(entry: ConfigEntry) -> dict[str, Any]:
    """Return only settings owned by this integration."""
    return {
        key: entry.options.get(key, entry.data.get(key))
        for key in _CONFIGURATION_KEYS
        if key in entry.options or key in entry.data
    }


def _source_diagnostics(
    hass: HomeAssistant, configuration: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    """Return source health without exposing source measurements or attributes."""
    sources: dict[str, dict[str, Any]] = {}
    registry = er.async_get(hass)

    for source_key in _SOURCE_KEYS:
        entity_id = configuration.get(source_key)
        if not isinstance(entity_id, str) or not entity_id:
            continue

        state = hass.states.get(entity_id)
        if state is None:
            registry_entry = registry.async_get(entity_id)
            source = {
                "entity_id": entity_id,
                "state_status": (
                    STATE_UNAVAILABLE if registry_entry is not None else "missing"
                ),
            }
            if registry_entry is not None:
                source.update(
                    {
                        "device_class": (
                            registry_entry.device_class
                            or registry_entry.original_device_class
                        ),
                        "unit_of_measurement": registry_entry.unit_of_measurement,
                    }
                )
            sources[source_key] = source
            continue

        if state.state == STATE_UNAVAILABLE:
            state_status = STATE_UNAVAILABLE
        elif state.state == STATE_UNKNOWN:
            state_status = STATE_UNKNOWN
        else:
            # The actual source value can reveal sensitive environmental data and
            # is not needed to diagnose configuration or compatibility problems.
            state_status = "present"

        sources[source_key] = {
            "entity_id": entity_id,
            "state_status": state_status,
            "device_class": state.attributes.get(ATTR_DEVICE_CLASS),
            "unit_of_measurement": state.attributes.get(ATTR_UNIT_OF_MEASUREMENT),
        }

    return sources


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return privacy-conscious diagnostics for a config entry."""
    configuration = _effective_configuration(entry)
    payload = {
        "config_entry": {
            "entry_id": entry.entry_id,
            "version": entry.version,
            "minor_version": entry.minor_version,
            "configuration": configuration,
        },
        "sources": _source_diagnostics(hass, configuration),
    }
    return async_redact_data(payload, _TO_REDACT)
