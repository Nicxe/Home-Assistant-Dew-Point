"""Regression tests for issue 55."""

from __future__ import annotations

import json
from pathlib import Path

from homeassistant.const import CONF_NAME
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dew_point import DOMAIN, repairs
from custom_components.dew_point.const import (
    CONF_CONDENSATION_THRESHOLD,
    CONF_HUMIDITY_SENSOR,
    CONF_HYSTERESIS,
    CONF_SOURCE_TYPE,
    CONF_TEMPERATURE_SENSOR,
    DEFAULT_CONDENSATION_THRESHOLD,
    DEFAULT_HYSTERESIS,
    SOURCE_TYPE_SENSORS,
)


def _sensor_options() -> dict[str, str | float]:
    """Return canonical options for a sensor-based helper."""
    return {
        CONF_NAME: "Bedroom",
        CONF_SOURCE_TYPE: SOURCE_TYPE_SENSORS,
        CONF_TEMPERATURE_SENSOR: "sensor.bedroom_temperature",
        CONF_HUMIDITY_SENSOR: "sensor.bedroom_humidity",
        CONF_CONDENSATION_THRESHOLD: DEFAULT_CONDENSATION_THRESHOLD,
        CONF_HYSTERESIS: DEFAULT_HYSTERESIS,
    }


async def test_repair_flow_init_ignores_issue_data(hass) -> None:
    """Issue metadata must not be treated as replacement form input."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Bedroom",
        options=_sensor_options(),
    )
    entry.add_to_hass(hass)
    issue_data = {
        "entry_id": entry.entry_id,
        "source_key": CONF_TEMPERATURE_SENSOR,
        "issue_type": repairs.SourceIssueType.UNAVAILABLE.value,
    }
    issue_id = repairs.source_issue_id(
        entry.entry_id,
        CONF_TEMPERATURE_SENSOR,
        repairs.SourceIssueType.UNAVAILABLE,
    )
    flow = await repairs.async_create_fix_flow(hass, issue_id, issue_data)
    flow.hass = hass

    result = await flow.async_step_init(issue_data)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "replace_source"
    assert result["errors"] == {}
    assert result["description_placeholders"] == {
        "current_entity_id": "sensor.bedroom_temperature",
        "helper_name": "Bedroom",
    }


async def test_options_flow_provides_title_placeholder(hass) -> None:
    """The options title receives the helper name required by its translation."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Bedroom",
        options=_sensor_options(),
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    assert result["description_placeholders"] == {"name": "Bedroom"}


def test_english_options_translations_are_resolved() -> None:
    """English options forms must not expose unresolved translation references."""
    translation_path = Path(__file__).parents[1] / "translations" / "en.json"
    translations = json.loads(translation_path.read_text(encoding="utf-8"))

    assert translations["options"]["step"]["sensors"]["title"] == (
        "Select sensor sources"
    )
    assert (
        translations["options"]["step"]["sensors"]["data"]["temperature_sensor"]
        == "Temperature source"
    )
    assert translations["options"]["step"]["weather"]["title"] == (
        "Select a weather source"
    )
