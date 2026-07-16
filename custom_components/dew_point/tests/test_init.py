"""Tests for Dew Point config-entry lifecycle and migration."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant.components.binary_sensor import DOMAIN as BINARY_SENSOR_DOMAIN
from homeassistant.components.sensor import (
    DOMAIN as SENSOR_DOMAIN,
    SensorDeviceClass,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    ATTR_DEVICE_CLASS,
    ATTR_UNIT_OF_MEASUREMENT,
    CONF_NAME,
    PERCENTAGE,
    STATE_UNAVAILABLE,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er, issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dew_point import (
    async_migrate_entry,
    async_remove_entry,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.dew_point.const import (
    CONF_CONDENSATION_THRESHOLD,
    CONF_DECIMAL_PLACES,
    CONF_HUMIDITY_SENSOR,
    CONF_HYSTERESIS,
    CONF_OUTPUT_UNIT,
    CONF_TEMPERATURE_SENSOR,
    CONFIG_ENTRY_MINOR_VERSION,
    DEFAULT_CONDENSATION_THRESHOLD,
    DEFAULT_HYSTERESIS,
    DOMAIN,
    OUTPUT_UNIT_AUTO,
    OUTPUT_UNIT_FAHRENHEIT,
    PLATFORMS,
)
from custom_components.dew_point.repairs import (
    SourceIssueType,
    async_update_source_issue,
    source_issue_id,
)


def _canonical_entry() -> MockConfigEntry:
    """Return a canonical config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Room",
        data={},
        options={
            CONF_NAME: "Room",
            CONF_TEMPERATURE_SENSOR: "sensor.temperature",
            CONF_HUMIDITY_SENSOR: "sensor.humidity",
            CONF_CONDENSATION_THRESHOLD: DEFAULT_CONDENSATION_THRESHOLD,
            CONF_HYSTERESIS: DEFAULT_HYSTERESIS,
        },
        version=1,
        minor_version=CONFIG_ENTRY_MINOR_VERSION,
    )


async def test_setup_is_awaited_and_unload_uses_all_platforms(
    hass: HomeAssistant,
) -> None:
    """Platform setup and unload use the current config-entry APIs."""
    entry = _canonical_entry()
    forward = AsyncMock()
    unload = AsyncMock(return_value=True)

    with (
        patch.object(hass.config_entries, "async_forward_entry_setups", forward),
        patch.object(hass.config_entries, "async_unload_platforms", unload),
    ):
        assert await async_setup_entry(hass, entry) is True
        assert forward.await_count == 1
        forward.assert_awaited_once_with(entry, PLATFORMS)
        assert await async_unload_entry(hass, entry) is True

    unload.assert_awaited_once_with(entry, PLATFORMS)


async def test_full_setup_updates_and_unloads_entities(hass: HomeAssistant) -> None:
    """The real platforms share runtime data, react to events, and unload cleanly."""
    hass.states.async_set(
        "sensor.temperature",
        "20",
        {
            ATTR_DEVICE_CLASS: SensorDeviceClass.TEMPERATURE,
            ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS,
        },
    )
    hass.states.async_set(
        "sensor.humidity",
        "100",
        {
            ATTR_DEVICE_CLASS: SensorDeviceClass.HUMIDITY,
            ATTR_UNIT_OF_MEASUREMENT: PERCENTAGE,
        },
    )
    hass.states.async_set(
        "sensor.surface",
        "19",
        {
            ATTR_DEVICE_CLASS: SensorDeviceClass.TEMPERATURE,
            ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS,
        },
    )
    entry = _canonical_entry()
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        entry,
        options={
            **entry.options,
            "surface_temperature_sensor": "sensor.surface",
        },
    )

    assert await hass.config_entries.async_setup(entry.entry_id) is True
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    dew_point_entity_id = registry.async_get_entity_id(
        SENSOR_DOMAIN, DOMAIN, f"{entry.entry_id}_dew_point"
    )
    risk_entity_id = registry.async_get_entity_id(
        BINARY_SENSOR_DOMAIN,
        DOMAIN,
        f"{entry.entry_id}_condensation_risk",
    )
    assert dew_point_entity_id is not None
    assert risk_entity_id is not None
    dew_point_state = hass.states.get(dew_point_entity_id)
    risk_state = hass.states.get(risk_entity_id)
    assert dew_point_state is not None
    assert risk_state is not None
    assert float(dew_point_state.state) == 20.0
    assert risk_state.state == "on"

    hass.states.async_set(
        "sensor.humidity",
        "50",
        {
            ATTR_DEVICE_CLASS: SensorDeviceClass.HUMIDITY,
            ATTR_UNIT_OF_MEASUREMENT: PERCENTAGE,
        },
    )
    await hass.async_block_till_done()
    dew_point_state = hass.states.get(dew_point_entity_id)
    risk_state = hass.states.get(risk_entity_id)
    assert dew_point_state is not None
    assert risk_state is not None
    assert float(dew_point_state.state) < 10.0
    assert risk_state.state == "off"

    assert await hass.config_entries.async_unload(entry.entry_id) is True
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert hass.states.get(dew_point_entity_id).state == STATE_UNAVAILABLE
    assert hass.states.get(risk_entity_id).state == STATE_UNAVAILABLE


async def test_source_entity_rename_updates_options_and_reloads(
    hass: HomeAssistant,
) -> None:
    """A registry rename follows the source without losing other options."""
    entry = _canonical_entry()
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    registry.async_get_or_create(
        SENSOR_DOMAIN,
        "test",
        "temperature",
        suggested_object_id="temperature",
    )
    registry.async_get_or_create(
        SENSOR_DOMAIN,
        "test",
        "humidity",
        suggested_object_id="humidity",
    )

    with (
        patch.object(
            hass.config_entries,
            "async_forward_entry_setups",
            AsyncMock(),
        ),
        patch.object(hass.config_entries, "async_schedule_reload") as reload_mock,
    ):
        await async_setup_entry(hass, entry)
        registry.async_update_entity(
            "sensor.temperature", new_entity_id="sensor.renamed_temperature"
        )
        await hass.async_block_till_done()

    assert entry.options[CONF_TEMPERATURE_SENSOR] == "sensor.renamed_temperature"
    assert entry.options[CONF_HUMIDITY_SENSOR] == "sensor.humidity"
    reload_mock.assert_called_once_with(entry.entry_id)


async def test_source_entity_removal_creates_actionable_issue(
    hass: HomeAssistant,
) -> None:
    """Removing a registered source creates a repair issue for that source."""
    entry = _canonical_entry()
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    registry.async_get_or_create(
        SENSOR_DOMAIN,
        "test",
        "temperature",
        suggested_object_id="temperature",
    )
    registry.async_get_or_create(
        SENSOR_DOMAIN,
        "test",
        "humidity",
        suggested_object_id="humidity",
    )

    with patch.object(
        hass.config_entries,
        "async_forward_entry_setups",
        AsyncMock(),
    ):
        await async_setup_entry(hass, entry)
        registry.async_remove("sensor.temperature")
        await hass.async_block_till_done()

    issue = ir.async_get(hass).async_get_issue(
        DOMAIN,
        source_issue_id(
            entry.entry_id, CONF_TEMPERATURE_SENSOR, SourceIssueType.MISSING
        ),
    )
    assert issue is not None


async def test_v1_migration_canonicalizes_and_preserves_registry_settings(
    hass: HomeAssistant,
) -> None:
    """Legacy data and options migrate without replacing the entity registry row."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Legacy room",
        data={
            CONF_NAME: "Legacy room",
            CONF_TEMPERATURE_SENSOR: "sensor.temperature",
            CONF_HUMIDITY_SENSOR: "sensor.old_humidity",
            CONF_DECIMAL_PLACES: 2,
            CONF_OUTPUT_UNIT: OUTPUT_UNIT_FAHRENHEIT,
        },
        options={CONF_HUMIDITY_SENSOR: "sensor.humidity"},
        entry_id="legacy_entry",
        version=1,
        minor_version=1,
    )
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    entity_entry = registry.async_get_or_create(
        SENSOR_DOMAIN,
        DOMAIN,
        "legacy_entry_dewpoint_legacy_room",
        config_entry=entry,
        suggested_object_id="legacy_room",
    )
    original_entity_id = entity_entry.entity_id

    assert await async_migrate_entry(hass, entry) is True

    assert entry.data == {}
    assert entry.options == {
        CONF_NAME: "Legacy room",
        CONF_TEMPERATURE_SENSOR: "sensor.temperature",
        CONF_HUMIDITY_SENSOR: "sensor.humidity",
        CONF_CONDENSATION_THRESHOLD: DEFAULT_CONDENSATION_THRESHOLD,
        CONF_HYSTERESIS: DEFAULT_HYSTERESIS,
        CONF_DECIMAL_PLACES: 2,
        CONF_OUTPUT_UNIT: OUTPUT_UNIT_FAHRENHEIT,
    }
    assert entry.version == 1
    assert entry.minor_version == CONFIG_ENTRY_MINOR_VERSION
    migrated_entity = registry.async_get(original_entity_id)
    assert migrated_entity is not None
    assert migrated_entity.unique_id == "legacy_entry_dew_point"
    assert migrated_entity.unit_of_measurement == UnitOfTemperature.FAHRENHEIT
    assert migrated_entity.options[SENSOR_DOMAIN]["display_precision"] == 2


async def test_v1_migration_preserves_existing_registry_overrides(
    hass: HomeAssistant,
) -> None:
    """Migration never replaces explicit unit or precision overrides."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Legacy room",
        data={
            CONF_NAME: "Legacy room",
            CONF_TEMPERATURE_SENSOR: "sensor.temperature",
            CONF_HUMIDITY_SENSOR: "sensor.humidity",
            CONF_DECIMAL_PLACES: 2,
            CONF_OUTPUT_UNIT: OUTPUT_UNIT_FAHRENHEIT,
        },
        entry_id="override_entry",
        version=1,
        minor_version=1,
    )
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    entity_entry = registry.async_get_or_create(
        SENSOR_DOMAIN,
        DOMAIN,
        "override_entry_dewpoint_legacy_room",
        config_entry=entry,
        suggested_object_id="legacy_override",
    )
    registry.async_update_entity_options(
        entity_entry.entity_id, SENSOR_DOMAIN, {"display_precision": 4}
    )
    registry.async_update_entity(
        entity_entry.entity_id,
        unit_of_measurement=UnitOfTemperature.CELSIUS,
    )

    assert await async_migrate_entry(hass, entry) is True

    migrated_entity = registry.async_get(entity_entry.entity_id)
    assert migrated_entity is not None
    assert migrated_entity.unit_of_measurement == UnitOfTemperature.CELSIUS
    assert migrated_entity.options[SENSOR_DOMAIN]["display_precision"] == 4


async def test_v1_auto_unit_preserves_fahrenheit_source_display(
    hass: HomeAssistant,
) -> None:
    """Legacy auto output keeps Fahrenheit when the configured source uses it."""
    hass.states.async_set(
        "sensor.temperature",
        "68",
        {ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.FAHRENHEIT},
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Legacy auto",
        data={
            CONF_NAME: "Legacy auto",
            CONF_TEMPERATURE_SENSOR: "sensor.temperature",
            CONF_HUMIDITY_SENSOR: "sensor.humidity",
            CONF_DECIMAL_PLACES: 1,
            CONF_OUTPUT_UNIT: OUTPUT_UNIT_AUTO,
        },
        entry_id="auto_entry",
        version=1,
        minor_version=1,
    )
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    entity_entry = registry.async_get_or_create(
        SENSOR_DOMAIN,
        DOMAIN,
        "auto_entry_dewpoint_legacy_auto",
        config_entry=entry,
        suggested_object_id="legacy_auto",
    )

    assert await async_migrate_entry(hass, entry) is True

    migrated_entity = registry.async_get(entity_entry.entity_id)
    assert migrated_entity is not None
    assert migrated_entity.unit_of_measurement == UnitOfTemperature.FAHRENHEIT
    assert entry.options[CONF_OUTPUT_UNIT] == OUTPUT_UNIT_AUTO


async def test_future_major_version_is_rejected(hass: HomeAssistant) -> None:
    """A downgrade from an unknown future major schema fails clearly."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Future",
        data={},
        options={},
        version=2,
        minor_version=1,
    )

    assert await async_migrate_entry(hass, entry) is False


async def test_remove_entry_clears_persistent_source_issues(
    hass: HomeAssistant,
) -> None:
    """Deleting a helper leaves no orphaned source repair issues."""
    entry = _canonical_entry()
    entry.add_to_hass(hass)
    async_update_source_issue(
        hass,
        entry,
        CONF_TEMPERATURE_SENSOR,
        SourceIssueType.MISSING,
        entity_id="sensor.temperature",
    )
    issue_registry = ir.async_get(hass)
    issue_id = source_issue_id(
        entry.entry_id, CONF_TEMPERATURE_SENSOR, SourceIssueType.MISSING
    )
    assert issue_registry.async_get_issue(DOMAIN, issue_id) is not None

    await async_remove_entry(hass, entry)

    assert issue_registry.async_get_issue(DOMAIN, issue_id) is None
