"""The Dew Point integration."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
import logging
from typing import Any

from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT,
    CONF_NAME,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.helper_integration import async_handle_source_entity_changes

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
    CONFIG_ENTRY_MINOR_VERSION,
    CONFIG_ENTRY_VERSION,
    DEFAULT_CONDENSATION_THRESHOLD,
    DEFAULT_DECIMAL_PLACES,
    DEFAULT_HYSTERESIS,
    DEFAULT_NAME,
    DEW_POINT_UNIQUE_ID_SUFFIX,
    DOMAIN,
    OUTPUT_UNIT_AUTO,
    OUTPUT_UNIT_CELSIUS,
    OUTPUT_UNIT_FAHRENHEIT,
    PLATFORMS,
    SOURCE_TYPE_SENSORS,
)
from .repairs import async_clear_source_issues
from .runtime import DewPointRuntime

_LOGGER = logging.getLogger(__name__)

_SOURCE_KEYS = (
    CONF_WEATHER_ENTITY,
    CONF_TEMPERATURE_SENSOR,
    CONF_HUMIDITY_SENSOR,
    CONF_SURFACE_TEMPERATURE_SENSOR,
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Dew Point from a config entry."""
    runtime = DewPointRuntime(hass, entry)
    entry.runtime_data = runtime
    runtime.async_start()
    entry.async_on_unload(runtime.async_stop)

    sources: dict[str, list[str]] = {}
    for source_key in _SOURCE_KEYS:
        if source_entity_id := entry.options.get(source_key):
            sources.setdefault(source_entity_id, []).append(source_key)

    for source_entity_id, source_keys in sources.items():
        entry.async_on_unload(
            async_handle_source_entity_changes(
                hass,
                helper_config_entry_id=entry.entry_id,
                set_source_entity_id_or_uuid=_source_entity_updater(
                    hass, entry, tuple(source_keys)
                ),
                source_device_id=None,
                source_entity_id_or_uuid=source_entity_id,
                source_entity_removed=_source_entity_removed_handler(
                    hass, entry, tuple(source_keys), source_entity_id
                ),
            )
        )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Dew Point config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Clear persistent source issues when a helper is deleted."""
    for source_key in _SOURCE_KEYS:
        async_clear_source_issues(hass, entry.entry_id, source_key)


def _source_entity_updater(
    hass: HomeAssistant, entry: ConfigEntry, source_keys: tuple[str, ...]
) -> Callable[[str], None]:
    """Return a callback which persists a renamed source entity."""

    @callback
    def async_update_source_entity(source_entity_id: str) -> None:
        new_options = dict(entry.options)
        for source_key in source_keys:
            new_options[source_key] = source_entity_id
        hass.config_entries.async_update_entry(entry, options=new_options)
        hass.config_entries.async_schedule_reload(entry.entry_id)

    return async_update_source_entity


def _source_entity_removed_handler(
    hass: HomeAssistant,
    entry: ConfigEntry,
    source_keys: tuple[str, ...],
    source_entity_id: str,
) -> Callable[[], Coroutine[Any, Any, None]]:
    """Return a coroutine callback which reports a removed source entity."""

    async def async_source_entity_removed() -> None:
        from .repairs import SourceIssueType, async_update_source_issue

        for source_key in source_keys:
            async_update_source_issue(
                hass,
                entry,
                source_key,
                SourceIssueType.MISSING,
                entity_id=source_entity_id,
            )

    return async_source_entity_removed


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate a legacy Dew Point config entry to canonical options."""
    _LOGGER.debug(
        "Migrating configuration from version %s.%s",
        entry.version,
        entry.minor_version,
    )

    if entry.version > CONFIG_ENTRY_VERSION:
        _LOGGER.error(
            "Cannot migrate configuration from future version %s.%s",
            entry.version,
            entry.minor_version,
        )
        return False

    if entry.version != CONFIG_ENTRY_VERSION:
        _LOGGER.error("Unsupported configuration version %s", entry.version)
        return False

    if entry.minor_version >= CONFIG_ENTRY_MINOR_VERSION:
        return True

    if entry.minor_version == 2:
        options = dict(entry.options)
        if not all(
            isinstance(options.get(key), str) and options[key]
            for key in (CONF_TEMPERATURE_SENSOR, CONF_HUMIDITY_SENSOR)
        ):
            _LOGGER.error("Cannot migrate configuration with missing source entities")
            return False
        options[CONF_SOURCE_TYPE] = SOURCE_TYPE_SENSORS
        hass.config_entries.async_update_entry(
            entry,
            options=options,
            version=CONFIG_ENTRY_VERSION,
            minor_version=CONFIG_ENTRY_MINOR_VERSION,
        )
        _LOGGER.debug(
            "Migration to configuration version %s.%s successful",
            entry.version,
            entry.minor_version,
        )
        return True

    legacy = {**entry.data, **entry.options}
    if not all(
        isinstance(legacy.get(key), str) and legacy[key]
        for key in (CONF_TEMPERATURE_SENSOR, CONF_HUMIDITY_SENSOR)
    ):
        _LOGGER.error("Cannot migrate configuration with missing source entities")
        return False

    legacy_display_precision = _legacy_display_precision(legacy)
    legacy_output_unit = legacy.get(CONF_OUTPUT_UNIT, OUTPUT_UNIT_AUTO)
    if legacy_output_unit not in (
        OUTPUT_UNIT_AUTO,
        OUTPUT_UNIT_CELSIUS,
        OUTPUT_UNIT_FAHRENHEIT,
    ):
        legacy_output_unit = OUTPUT_UNIT_AUTO

    new_options: dict[str, Any] = {
        CONF_NAME: str(legacy.get(CONF_NAME) or entry.title or DEFAULT_NAME),
        CONF_SOURCE_TYPE: SOURCE_TYPE_SENSORS,
        CONF_TEMPERATURE_SENSOR: legacy[CONF_TEMPERATURE_SENSOR],
        CONF_HUMIDITY_SENSOR: legacy[CONF_HUMIDITY_SENSOR],
        CONF_CONDENSATION_THRESHOLD: _finite_float_or_default(
            legacy.get(CONF_CONDENSATION_THRESHOLD),
            DEFAULT_CONDENSATION_THRESHOLD,
        ),
        CONF_HYSTERESIS: _finite_float_or_default(
            legacy.get(CONF_HYSTERESIS), DEFAULT_HYSTERESIS
        ),
        # Hidden compatibility values retained during attribute deprecation.
        CONF_DECIMAL_PLACES: legacy_display_precision,
        CONF_OUTPUT_UNIT: legacy_output_unit,
    }
    if surface_sensor := legacy.get(CONF_SURFACE_TEMPERATURE_SENSOR):
        new_options[CONF_SURFACE_TEMPERATURE_SENSOR] = surface_sensor

    _migrate_legacy_entity_registry_settings(hass, entry, legacy)

    hass.config_entries.async_update_entry(
        entry,
        data={},
        options=new_options,
        title=new_options[CONF_NAME],
        version=CONFIG_ENTRY_VERSION,
        minor_version=CONFIG_ENTRY_MINOR_VERSION,
    )
    _LOGGER.debug(
        "Migration to configuration version %s.%s successful",
        entry.version,
        entry.minor_version,
    )
    return True


def _finite_float_or_default(value: Any, default: float) -> float:
    """Return a finite float or a safe default."""
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if result != result or result in (float("inf"), float("-inf")):
        return default
    return result


def _legacy_display_precision(legacy: dict[str, Any]) -> int:
    """Return a safe legacy display precision."""
    try:
        display_precision = int(legacy.get(CONF_DECIMAL_PLACES, DEFAULT_DECIMAL_PLACES))
    except (TypeError, ValueError):
        display_precision = DEFAULT_DECIMAL_PLACES
    return max(0, min(15, display_precision))


@callback
def _migrate_legacy_entity_registry_settings(
    hass: HomeAssistant, entry: ConfigEntry, legacy: dict[str, Any]
) -> None:
    """Preserve legacy display settings while stabilizing the unique ID."""
    registry = er.async_get(hass)
    target_unique_id = f"{entry.entry_id}_{DEW_POINT_UNIQUE_ID_SUFFIX}"
    legacy_unique_id_prefix = f"{entry.entry_id}_dewpoint_"

    display_precision = _legacy_display_precision(legacy)
    legacy_unit = _legacy_display_unit(hass, registry, legacy)

    target_exists = registry.async_get_entity_id(
        SENSOR_DOMAIN, DOMAIN, target_unique_id
    )
    for entity_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        if entity_entry.domain != SENSOR_DOMAIN or not (
            entity_entry.unique_id.startswith(legacy_unique_id_prefix)
            or entity_entry.unique_id == target_unique_id
        ):
            continue

        sensor_options = dict(entity_entry.options.get(SENSOR_DOMAIN, {}))
        if "display_precision" not in sensor_options:
            sensor_options["display_precision"] = display_precision
            registry.async_update_entity_options(
                entity_entry.entity_id, SENSOR_DOMAIN, sensor_options
            )

        updates: dict[str, Any] = {}
        if legacy_unit is not None and entity_entry.unit_of_measurement is None:
            updates["unit_of_measurement"] = legacy_unit
        if entity_entry.unique_id != target_unique_id and target_exists in (
            None,
            entity_entry.entity_id,
        ):
            updates["new_unique_id"] = target_unique_id
            target_exists = entity_entry.entity_id
        if updates:
            registry.async_update_entity(entity_entry.entity_id, **updates)


def _legacy_display_unit(
    hass: HomeAssistant,
    registry: er.EntityRegistry,
    legacy: dict[str, Any],
) -> UnitOfTemperature:
    """Resolve the temperature unit shown before migration."""
    output_unit = legacy.get(CONF_OUTPUT_UNIT, OUTPUT_UNIT_AUTO)
    if output_unit == OUTPUT_UNIT_FAHRENHEIT:
        return UnitOfTemperature.FAHRENHEIT
    if output_unit == OUTPUT_UNIT_CELSIUS:
        return UnitOfTemperature.CELSIUS

    source = legacy.get(CONF_TEMPERATURE_SENSOR)
    if isinstance(source, str):
        entity_id = er.async_resolve_entity_id(registry, source) or source
        state = hass.states.get(entity_id)
        source_unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT) if state else None
        if (
            source_unit is None
            and (source_entry := registry.async_get(entity_id)) is not None
        ):
            source_unit = source_entry.unit_of_measurement
        if source_unit == UnitOfTemperature.FAHRENHEIT:
            return UnitOfTemperature.FAHRENHEIT
    return UnitOfTemperature.CELSIUS
