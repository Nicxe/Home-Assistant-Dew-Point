"""Repairs support for the Dew Point integration."""

from __future__ import annotations

from enum import StrEnum
import math
from typing import Any

from homeassistant.components.repairs import ConfirmRepairFlow, RepairsFlow
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
    PERCENTAGE,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    Platform,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import entity_registry as er, issue_registry as ir
from homeassistant.helpers.selector import EntitySelector, EntitySelectorConfig
from homeassistant.util.unit_conversion import TemperatureConverter
import voluptuous as vol

from .calculation import MAX_WATER_TEMPERATURE_C, MIN_BUCK_TEMPERATURE_C
from .const import (
    CONF_HUMIDITY_SENSOR,
    CONF_SURFACE_TEMPERATURE_SENSOR,
    CONF_TEMPERATURE_SENSOR,
    CONF_WEATHER_ENTITY,
    DOMAIN,
)

CONF_REPLACEMENT_ENTITY = "replacement_entity"

_SOURCE_KINDS = {
    CONF_WEATHER_ENTITY: "weather",
    CONF_TEMPERATURE_SENSOR: "temperature",
    CONF_HUMIDITY_SENSOR: "humidity",
    CONF_SURFACE_TEMPERATURE_SENSOR: "surface_temperature",
}
_TEMPERATURE_SOURCE_KEYS = {
    CONF_TEMPERATURE_SENSOR,
    CONF_SURFACE_TEMPERATURE_SENSOR,
}


class SourceIssueType(StrEnum):
    """Persistent, user-actionable source failures."""

    MISSING = "missing"
    INCOMPATIBLE = "incompatible"
    UNAVAILABLE = "unavailable"


def source_issue_id(entry_id: str, source_key: str, issue_type: SourceIssueType) -> str:
    """Return a stable ID for a source issue."""
    if source_key not in _SOURCE_KINDS:
        raise ValueError(f"Unsupported source key: {source_key}")
    return f"{entry_id}_{source_key}_{issue_type}"


@callback
def async_clear_source_issues(
    hass: HomeAssistant, entry_id: str, source_key: str
) -> None:
    """Clear all actionable issues for one source."""
    for issue_type in SourceIssueType:
        ir.async_delete_issue(
            hass,
            DOMAIN,
            source_issue_id(entry_id, source_key, issue_type),
        )


@callback
def async_update_source_issue(
    hass: HomeAssistant,
    entry: ConfigEntry,
    source_key: str,
    issue_type: SourceIssueType | None,
    *,
    entity_id: str | None = None,
) -> None:
    """Create or clear a persistent source issue.

    ``UNAVAILABLE`` must only be passed after the source has remained unavailable
    beyond the runtime grace period, so normal startup ordering does not create
    transient issues.
    """
    if source_key not in _SOURCE_KINDS:
        raise ValueError(f"Unsupported source key: {source_key}")

    async_clear_source_issues(hass, entry.entry_id, source_key)
    if issue_type is None:
        return

    source_kind = _SOURCE_KINDS[source_key]
    ir.async_create_issue(
        hass,
        DOMAIN,
        source_issue_id(entry.entry_id, source_key, issue_type),
        data={
            "entry_id": entry.entry_id,
            "source_key": source_key,
            "issue_type": issue_type.value,
        },
        is_fixable=True,
        is_persistent=True,
        issue_domain=DOMAIN,
        severity=ir.IssueSeverity.WARNING,
        translation_key=f"{source_kind}_source_{issue_type.value}",
        translation_placeholders={
            "entity_id": entity_id or "unknown",
            "helper_name": entry.title,
        },
    )


def _selector_for_source(
    hass: HomeAssistant, entry: ConfigEntry, source_key: str
) -> EntitySelector:
    """Return a device-class filtered selector for a source."""
    own_entities = [
        entity.entity_id
        for entity in er.async_entries_for_config_entry(
            er.async_get(hass), entry.entry_id
        )
    ]
    if source_key == CONF_WEATHER_ENTITY:
        return EntitySelector(
            EntitySelectorConfig(
                domain=Platform.WEATHER,
                exclude_entities=own_entities,
            )
        )

    device_class = (
        SensorDeviceClass.TEMPERATURE
        if source_key in _TEMPERATURE_SOURCE_KEYS
        else SensorDeviceClass.HUMIDITY
    )
    return EntitySelector(
        EntitySelectorConfig(
            domain=Platform.SENSOR,
            device_class=device_class,
            exclude_entities=own_entities,
        )
    )


def _replacement_error(
    hass: HomeAssistant, source_key: str, entity_id: str
) -> str | None:
    """Validate a replacement, including registered unavailable sources."""
    registry = er.async_get(hass)
    try:
        resolved_entity_id = er.async_validate_entity_id(registry, entity_id)
    except vol.Invalid:
        return "replacement_missing"

    state = hass.states.get(resolved_entity_id)
    registry_entry = registry.async_get(resolved_entity_id)
    if state is None and registry_entry is None:
        return "replacement_missing"

    if source_key == CONF_WEATHER_ENTITY:
        if not resolved_entity_id.startswith(f"{Platform.WEATHER}."):
            return "replacement_incompatible"
        if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return None
        temperature = _finite_float(state.attributes.get(ATTR_WEATHER_TEMPERATURE))
        humidity = _finite_float(state.attributes.get(ATTR_WEATHER_HUMIDITY))
        unit = state.attributes.get(ATTR_WEATHER_TEMPERATURE_UNIT)
        if (
            temperature is None
            or humidity is None
            or unit not in TemperatureConverter.VALID_UNITS
            or not 0 <= humidity <= 100
        ):
            return "replacement_incompatible"
        try:
            temperature_c = TemperatureConverter.convert(
                temperature, unit, UnitOfTemperature.CELSIUS
            )
        except (TypeError, ValueError, OverflowError):
            return "replacement_incompatible"
        return (
            None
            if MIN_BUCK_TEMPERATURE_C <= temperature_c <= MAX_WATER_TEMPERATURE_C
            else "replacement_incompatible"
        )

    device_class = state.attributes.get(ATTR_DEVICE_CLASS) if state else None
    unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT) if state else None
    if registry_entry is not None:
        device_class = (
            device_class
            or registry_entry.device_class
            or registry_entry.original_device_class
        )
        unit = unit or registry_entry.unit_of_measurement
    if source_key in _TEMPERATURE_SOURCE_KEYS:
        if device_class not in (None, SensorDeviceClass.TEMPERATURE):
            return "replacement_incompatible"
        if unit not in TemperatureConverter.VALID_UNITS:
            return "replacement_incompatible"
        return None

    if device_class not in (None, SensorDeviceClass.HUMIDITY) or unit != PERCENTAGE:
        return "replacement_incompatible"
    return None


def _finite_float(value: object) -> float | None:
    """Return a finite float or None."""
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


class SourceRepairFlow(RepairsFlow):
    """Guide the user through replacing one invalid source."""

    def __init__(self, entry: ConfigEntry, source_key: str) -> None:
        """Initialize the repair flow."""
        super().__init__()
        self._entry = entry
        self._source_key = source_key

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Start the source replacement flow."""
        return await self.async_step_replace_source(user_input)

    async def async_step_replace_source(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Validate and save a replacement source."""
        errors: dict[str, str] = {}
        if user_input is not None:
            replacement = str(user_input[CONF_REPLACEMENT_ENTITY])
            if error := _replacement_error(self.hass, self._source_key, replacement):
                errors[CONF_REPLACEMENT_ENTITY] = error
            else:
                options = dict(self._entry.options)
                options[self._source_key] = replacement
                self.hass.config_entries.async_update_entry(
                    self._entry, options=options
                )
                async_clear_source_issues(
                    self.hass, self._entry.entry_id, self._source_key
                )
                await self.hass.config_entries.async_reload(self._entry.entry_id)
                return self.async_create_entry(title="", data={})

        current_source = self._entry.options.get(
            self._source_key, self._entry.data.get(self._source_key, "unknown")
        )
        return self.async_show_form(
            step_id="replace_source",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_REPLACEMENT_ENTITY): _selector_for_source(
                        self.hass, self._entry, self._source_key
                    )
                }
            ),
            errors=errors,
            description_placeholders={
                "current_entity_id": str(current_source),
                "helper_name": self._entry.title,
            },
        )


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """Create a source replacement repair flow."""
    if data is None:
        return ConfirmRepairFlow()

    entry_id = data.get("entry_id")
    source_key = data.get("source_key")
    issue_type_value = data.get("issue_type")
    if not isinstance(entry_id, str) or not isinstance(source_key, str):
        return ConfirmRepairFlow()
    if source_key not in _SOURCE_KINDS or not isinstance(issue_type_value, str):
        return ConfirmRepairFlow()

    try:
        issue_type = SourceIssueType(issue_type_value)
    except ValueError:
        return ConfirmRepairFlow()
    if issue_id != source_issue_id(entry_id, source_key, issue_type):
        return ConfirmRepairFlow()

    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None:
        return ConfirmRepairFlow()
    return SourceRepairFlow(entry, source_key)
