"""Tests for the condensation-risk binary sensor."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT,
    CONF_NAME,
    PERCENTAGE,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dew_point.binary_sensor import (
    DewPointCondensationRiskSensor,
    async_setup_entry,
)
from custom_components.dew_point.const import (
    CONF_HUMIDITY_SENSOR,
    CONF_SURFACE_TEMPERATURE_SENSOR,
    CONF_TEMPERATURE_SENSOR,
    DOMAIN,
)
from custom_components.dew_point.runtime import DewPointRuntime


def _entry_runtime(
    hass: HomeAssistant, *, surface: bool
) -> tuple[MockConfigEntry, DewPointRuntime]:
    """Create a runtime with an active condensation risk."""
    hass.states.async_set(
        "sensor.temperature",
        "20",
        {ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS},
    )
    hass.states.async_set(
        "sensor.humidity", "50", {ATTR_UNIT_OF_MEASUREMENT: PERCENTAGE}
    )
    options = {
        CONF_NAME: "Cellar",
        CONF_TEMPERATURE_SENSOR: "sensor.temperature",
        CONF_HUMIDITY_SENSOR: "sensor.humidity",
    }
    if surface:
        hass.states.async_set(
            "sensor.surface",
            "9",
            {ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS},
        )
        options[CONF_SURFACE_TEMPERATURE_SENSOR] = "sensor.surface"
    entry = MockConfigEntry(domain=DOMAIN, title="Cellar", options=options)
    entry.add_to_hass(hass)
    runtime = DewPointRuntime(hass, entry)
    with patch("custom_components.dew_point.runtime.async_update_source_issue"):
        runtime.async_refresh()
    entry.runtime_data = runtime
    return entry, runtime


async def test_binary_sensor_requires_surface_source(hass: HomeAssistant) -> None:
    """No binary sensor is created without an explicit surface source."""
    entry, _runtime = _entry_runtime(hass, surface=False)
    entities: list[DewPointCondensationRiskSensor] = []

    await async_setup_entry(hass, entry, entities.extend)

    assert entities == []


async def test_binary_sensor_reports_risk_and_updates(hass: HomeAssistant) -> None:
    """The binary sensor exposes shared runtime risk and update notifications."""
    entry, runtime = _entry_runtime(hass, surface=True)
    entities: list[DewPointCondensationRiskSensor] = []
    await async_setup_entry(hass, entry, entities.extend)
    entity = entities[0]

    assert entity.unique_id == f"{entry.entry_id}_condensation_risk"
    assert entity.available is True
    assert entity.is_on is True

    entity.hass = hass
    with patch.object(entity, "async_write_ha_state") as write_state:
        await entity.async_added_to_hass()
        for listener in tuple(runtime._listeners):  # noqa: SLF001
            listener()
        write_state.assert_called_once()
        entity._call_on_remove_callbacks()  # noqa: SLF001

    assert not runtime._listeners  # noqa: SLF001
