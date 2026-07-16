"""Tests for Dew Point sensor entities."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT,
    CONF_NAME,
    PERCENTAGE,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dew_point.const import (
    CONF_DECIMAL_PLACES,
    CONF_HUMIDITY_SENSOR,
    CONF_OUTPUT_UNIT,
    CONF_SURFACE_TEMPERATURE_SENSOR,
    CONF_TEMPERATURE_SENSOR,
    DOMAIN,
    OUTPUT_UNIT_CELSIUS,
)
from custom_components.dew_point.runtime import DewPointRuntime
from custom_components.dew_point.sensor import (
    ATTR_HUMIDITY,
    ATTR_HUMIDITY_ENTITY_ID,
    ATTR_OUTPUT_UNIT,
    ATTR_TEMPERATURE,
    ATTR_TEMPERATURE_ENTITY_ID,
    DewPointSensor,
    async_setup_entry,
)


def _runtime(
    hass: HomeAssistant, *, surface: bool, legacy: bool = False
) -> tuple[MockConfigEntry, DewPointRuntime]:
    """Create a calculated runtime for entity tests."""
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
            "10",
            {ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS},
        )
        options[CONF_SURFACE_TEMPERATURE_SENSOR] = "sensor.surface"
    if legacy:
        options[CONF_DECIMAL_PLACES] = 2
        options[CONF_OUTPUT_UNIT] = OUTPUT_UNIT_CELSIUS
    entry = MockConfigEntry(domain=DOMAIN, title="Cellar", options=options)
    entry.add_to_hass(hass)
    runtime = DewPointRuntime(hass, entry)
    with patch("custom_components.dew_point.runtime.async_update_source_issue"):
        runtime.async_refresh()
    entry.runtime_data = runtime
    return entry, runtime


async def test_setup_adds_all_applicable_sensors(hass: HomeAssistant) -> None:
    """Surface-only metrics are only created when a surface source is configured."""
    entry, _runtime_without_surface = _runtime(hass, surface=False)
    entities: list[DewPointSensor] = []

    await async_setup_entry(hass, entry, entities.extend)

    assert len(entities) == 7
    assert {entity.entity_description.key for entity in entities} == {
        "dew_point",
        "dew_point_spread",
        "absolute_humidity",
        "vapor_pressure",
        "saturation_vapor_pressure",
        "vapor_pressure_deficit",
        "frost_point",
    }

    surface_entry, _surface_runtime = _runtime(hass, surface=True)
    surface_entities: list[DewPointSensor] = []
    await async_setup_entry(hass, surface_entry, surface_entities.extend)
    assert len(surface_entities) == 8
    assert "surface_dew_point_margin" in {
        entity.entity_description.key for entity in surface_entities
    }


async def test_sensor_values_identity_and_static_attributes(
    hass: HomeAssistant,
) -> None:
    """Canonical sensors expose stable identity, precision, and static source IDs."""
    entry, runtime = _runtime(hass, surface=True)
    entities: list[DewPointSensor] = []
    await async_setup_entry(hass, entry, entities.extend)
    dew_point = next(
        entity for entity in entities if entity.entity_description.key == "dew_point"
    )
    margin = next(
        entity
        for entity in entities
        if entity.entity_description.key == "surface_dew_point_margin"
    )

    assert dew_point.unique_id == f"{entry.entry_id}_dew_point"
    assert dew_point.native_value == pytest.approx(9.27, abs=0.02)
    assert dew_point.available is True
    assert margin.native_value == pytest.approx(0.73, abs=0.03)
    assert margin.available is True
    assert margin.extra_state_attributes is None

    attributes = dew_point.extra_state_attributes
    assert attributes is not None
    assert attributes == {
        ATTR_TEMPERATURE_ENTITY_ID: runtime.temperature_entity_id,
        ATTR_HUMIDITY_ENTITY_ID: runtime.humidity_entity_id,
    }


async def test_legacy_entry_preserves_deprecated_dynamic_attributes(
    hass: HomeAssistant,
) -> None:
    """Migrated entries retain their deprecated dynamic compatibility attributes."""
    entry, runtime = _runtime(hass, surface=False, legacy=True)
    entities: list[DewPointSensor] = []
    await async_setup_entry(hass, entry, entities.extend)
    dew_point = next(
        entity for entity in entities if entity.entity_description.key == "dew_point"
    )

    attributes = dew_point.extra_state_attributes
    assert attributes is not None
    assert attributes[ATTR_TEMPERATURE] == 20
    assert attributes[ATTR_HUMIDITY] == 50
    assert attributes[ATTR_TEMPERATURE_ENTITY_ID] == runtime.temperature_entity_id
    assert attributes[ATTR_HUMIDITY_ENTITY_ID] == runtime.humidity_entity_id
    assert attributes[ATTR_OUTPUT_UNIT] == UnitOfTemperature.CELSIUS

    runtime.legacy_output_unit = "fahrenheit"
    assert dew_point._legacy_output_unit == UnitOfTemperature.FAHRENHEIT  # noqa: SLF001
    runtime.legacy_output_unit = "auto"
    runtime.data = runtime.data.__class__(temperature_native_unit="invalid")
    assert dew_point._legacy_output_unit == UnitOfTemperature.CELSIUS  # noqa: SLF001


async def test_sensor_subscribes_and_unsubscribes(hass: HomeAssistant) -> None:
    """An added entity writes updates and removes its runtime listener on removal."""
    entry, runtime = _runtime(hass, surface=False)
    entities: list[DewPointSensor] = []
    await async_setup_entry(hass, entry, entities.extend)
    entity = entities[0]
    entity.hass = hass

    with patch.object(entity, "async_write_ha_state") as write_state:
        await entity.async_added_to_hass()
        for listener in tuple(runtime._listeners):  # noqa: SLF001
            listener()
        write_state.assert_called_once()
        entity._call_on_remove_callbacks()  # noqa: SLF001

    assert not runtime._listeners  # noqa: SLF001
