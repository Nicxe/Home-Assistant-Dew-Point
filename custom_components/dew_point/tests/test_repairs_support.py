"""Tests for Dew Point Repairs support."""

from __future__ import annotations

from unittest.mock import AsyncMock

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import UnitOfTemperature
from homeassistant.helpers import entity_registry as er, issue_registry as ir
from pytest import raises
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dew_point import DOMAIN, repairs


async def test_source_issue_lifecycle_is_limited_to_persistent_errors(hass) -> None:
    """Only missing and incompatible sources can become repair issues."""
    entry = MockConfigEntry(domain=DOMAIN, title="Bedroom")
    entry.add_to_hass(hass)

    repairs.async_update_source_issue(
        hass,
        entry,
        repairs.CONF_TEMPERATURE_SENSOR,
        repairs.SourceIssueType.MISSING,
        entity_id="sensor.old_temperature",
    )
    issue_id = repairs.source_issue_id(
        entry.entry_id,
        repairs.CONF_TEMPERATURE_SENSOR,
        repairs.SourceIssueType.MISSING,
    )
    issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)

    assert issue is not None
    assert issue.is_fixable is True
    assert issue.is_persistent is True
    assert issue.translation_key == "temperature_source_missing"

    repairs.async_update_source_issue(
        hass,
        entry,
        repairs.CONF_TEMPERATURE_SENSOR,
        None,
    )
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None
    with raises(ValueError):
        repairs.SourceIssueType("unavailable")


async def test_repair_flow_replaces_source_and_reloads(hass) -> None:
    """A compatible replacement is saved and the helper is reloaded."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Bedroom",
        data={"temperature_sensor": "sensor.old_temperature"},
        options={"humidity_sensor": "sensor.humidity"},
    )
    entry.add_to_hass(hass)
    hass.states.async_set(
        "sensor.new_temperature",
        "20.0",
        {
            "device_class": SensorDeviceClass.TEMPERATURE,
            "unit_of_measurement": UnitOfTemperature.KELVIN,
        },
    )
    repairs.async_update_source_issue(
        hass,
        entry,
        repairs.CONF_TEMPERATURE_SENSOR,
        repairs.SourceIssueType.MISSING,
        entity_id="sensor.old_temperature",
    )
    issue_id = repairs.source_issue_id(
        entry.entry_id,
        repairs.CONF_TEMPERATURE_SENSOR,
        repairs.SourceIssueType.MISSING,
    )
    hass.config_entries.async_reload = AsyncMock(return_value=True)

    flow = await repairs.async_create_fix_flow(
        hass,
        issue_id,
        {
            "entry_id": entry.entry_id,
            "source_key": repairs.CONF_TEMPERATURE_SENSOR,
            "issue_type": repairs.SourceIssueType.MISSING.value,
        },
    )
    flow.hass = hass
    result = await flow.async_step_replace_source(
        {repairs.CONF_REPLACEMENT_ENTITY: "sensor.new_temperature"}
    )

    assert result["type"] == "create_entry"
    assert entry.options[repairs.CONF_TEMPERATURE_SENSOR] == ("sensor.new_temperature")
    hass.config_entries.async_reload.assert_awaited_once_with(entry.entry_id)
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


async def test_repair_flow_rejects_incompatible_replacement(hass) -> None:
    """The repair cannot save a source with incompatible metadata."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Bedroom",
        options={"humidity_sensor": "sensor.old_humidity"},
    )
    entry.add_to_hass(hass)
    hass.states.async_set(
        "sensor.power",
        "50",
        {"device_class": SensorDeviceClass.POWER, "unit_of_measurement": "W"},
    )
    issue_id = repairs.source_issue_id(
        entry.entry_id,
        repairs.CONF_HUMIDITY_SENSOR,
        repairs.SourceIssueType.INCOMPATIBLE,
    )
    hass.config_entries.async_reload = AsyncMock(return_value=True)

    flow = await repairs.async_create_fix_flow(
        hass,
        issue_id,
        {
            "entry_id": entry.entry_id,
            "source_key": repairs.CONF_HUMIDITY_SENSOR,
            "issue_type": repairs.SourceIssueType.INCOMPATIBLE.value,
        },
    )
    flow.hass = hass
    result = await flow.async_step_replace_source(
        {repairs.CONF_REPLACEMENT_ENTITY: "sensor.power"}
    )

    assert result["type"] == "form"
    assert result["errors"] == {
        repairs.CONF_REPLACEMENT_ENTITY: "replacement_incompatible"
    }
    assert entry.options[repairs.CONF_HUMIDITY_SENSOR] == "sensor.old_humidity"
    hass.config_entries.async_reload.assert_not_awaited()


async def test_repair_flow_accepts_registered_unavailable_replacement(hass) -> None:
    """A compatible registry-only source can repair a helper before it loads."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Bedroom",
        options={"temperature_sensor": "sensor.old_temperature"},
    )
    entry.add_to_hass(hass)
    er.async_get(hass).async_get_or_create(
        "sensor",
        "test",
        "temperature",
        suggested_object_id="replacement_temperature",
        original_device_class=SensorDeviceClass.TEMPERATURE,
        unit_of_measurement=UnitOfTemperature.CELSIUS,
    )
    replacement_entity_id = "sensor.replacement_temperature"
    issue_id = repairs.source_issue_id(
        entry.entry_id,
        repairs.CONF_TEMPERATURE_SENSOR,
        repairs.SourceIssueType.MISSING,
    )
    hass.config_entries.async_reload = AsyncMock(return_value=True)

    flow = await repairs.async_create_fix_flow(
        hass,
        issue_id,
        {
            "entry_id": entry.entry_id,
            "source_key": repairs.CONF_TEMPERATURE_SENSOR,
            "issue_type": repairs.SourceIssueType.MISSING.value,
        },
    )
    flow.hass = hass
    result = await flow.async_step_replace_source(
        {repairs.CONF_REPLACEMENT_ENTITY: replacement_entity_id}
    )

    assert result["type"] == "create_entry"
    assert entry.options[repairs.CONF_TEMPERATURE_SENSOR] == replacement_entity_id
    hass.config_entries.async_reload.assert_awaited_once_with(entry.entry_id)
