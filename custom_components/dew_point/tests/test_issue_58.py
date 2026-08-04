"""Regression tests for issue 58."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import (
    ATTR_DEVICE_CLASS,
    ATTR_UNIT_OF_MEASUREMENT,
    CONF_NAME,
    PERCENTAGE,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfTemperature,
)
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

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
from custom_components.dew_point.runtime import DewPointRuntime, SourceStatus


def _entry() -> MockConfigEntry:
    """Return a configured sensor-based helper."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Bedroom",
        options={
            CONF_NAME: "Bedroom",
            CONF_SOURCE_TYPE: SOURCE_TYPE_SENSORS,
            CONF_TEMPERATURE_SENSOR: "sensor.bedroom_temperature",
            CONF_HUMIDITY_SENSOR: "sensor.bedroom_humidity",
            CONF_CONDENSATION_THRESHOLD: DEFAULT_CONDENSATION_THRESHOLD,
            CONF_HYSTERESIS: DEFAULT_HYSTERESIS,
        },
    )


def _set_sensor_states(hass, state: str) -> None:
    """Set both configured source sensors to one state."""
    hass.states.async_set(
        "sensor.bedroom_temperature",
        state,
        {
            ATTR_DEVICE_CLASS: SensorDeviceClass.TEMPERATURE,
            ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS,
        },
    )
    hass.states.async_set(
        "sensor.bedroom_humidity",
        state,
        {
            ATTR_DEVICE_CLASS: SensorDeviceClass.HUMIDITY,
            ATTR_UNIT_OF_MEASUREMENT: PERCENTAGE,
        },
    )


def _unavailable_issue(hass, entry: MockConfigEntry, source_key: str):
    """Return the legacy unavailable Repair for a source, if present."""
    return ir.async_get(hass).async_get_issue(
        DOMAIN,
        repairs.source_issue_id(
            entry.entry_id,
            source_key,
            repairs.SourceIssueType.UNAVAILABLE,
        ),
    )


@pytest.mark.parametrize("state", [STATE_UNAVAILABLE, STATE_UNKNOWN])
async def test_unavailable_sources_do_not_create_repairs(hass, state: str) -> None:
    """Unavailable and unknown sources stay quiet and recover automatically."""
    entry = _entry()
    entry.add_to_hass(hass)
    _set_sensor_states(hass, state)
    runtime = DewPointRuntime(hass, entry)

    runtime.async_start()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=6))
    await hass.async_block_till_done()

    assert runtime.data.available is False
    assert runtime.source_statuses == {
        CONF_TEMPERATURE_SENSOR: SourceStatus.UNAVAILABLE,
        CONF_HUMIDITY_SENSOR: SourceStatus.UNAVAILABLE,
    }
    assert _unavailable_issue(hass, entry, CONF_TEMPERATURE_SENSOR) is None
    assert _unavailable_issue(hass, entry, CONF_HUMIDITY_SENSOR) is None

    hass.states.async_set(
        "sensor.bedroom_temperature",
        "20",
        {
            ATTR_DEVICE_CLASS: SensorDeviceClass.TEMPERATURE,
            ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS,
        },
    )
    hass.states.async_set(
        "sensor.bedroom_humidity",
        "50",
        {
            ATTR_DEVICE_CLASS: SensorDeviceClass.HUMIDITY,
            ATTR_UNIT_OF_MEASUREMENT: PERCENTAGE,
        },
    )
    await hass.async_block_till_done()

    assert runtime.data.available is True
    runtime.async_stop()


async def test_existing_unavailable_repairs_are_cleared(hass) -> None:
    """Runtime startup removes unavailable Repairs created by older releases."""
    entry = _entry()
    entry.add_to_hass(hass)
    _set_sensor_states(hass, STATE_UNAVAILABLE)
    issue_id = repairs.source_issue_id(
        entry.entry_id,
        CONF_TEMPERATURE_SENSOR,
        repairs.SourceIssueType.UNAVAILABLE,
    )
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=True,
        is_persistent=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key="temperature_source_unavailable",
        translation_placeholders={
            "entity_id": "sensor.bedroom_temperature",
            "helper_name": "Bedroom",
        },
    )
    assert _unavailable_issue(hass, entry, CONF_TEMPERATURE_SENSOR) is not None

    runtime = DewPointRuntime(hass, entry)
    runtime.async_start()

    assert _unavailable_issue(hass, entry, CONF_TEMPERATURE_SENSOR) is None
    runtime.async_stop()


async def test_actionable_source_failures_still_create_repairs(hass) -> None:
    """Missing and incompatible sources remain actionable Repairs."""
    entry = _entry()
    entry.add_to_hass(hass)
    hass.states.async_set(
        "sensor.bedroom_temperature",
        "100",
        {
            ATTR_DEVICE_CLASS: SensorDeviceClass.POWER,
            ATTR_UNIT_OF_MEASUREMENT: "W",
        },
    )
    runtime = DewPointRuntime(hass, entry)

    runtime.async_start()

    registry = ir.async_get(hass)
    assert (
        registry.async_get_issue(
            DOMAIN,
            repairs.source_issue_id(
                entry.entry_id,
                CONF_TEMPERATURE_SENSOR,
                repairs.SourceIssueType.INCOMPATIBLE,
            ),
        )
        is not None
    )
    assert (
        registry.async_get_issue(
            DOMAIN,
            repairs.source_issue_id(
                entry.entry_id,
                CONF_HUMIDITY_SENSOR,
                repairs.SourceIssueType.MISSING,
            ),
        )
        is not None
    )
    runtime.async_stop()
