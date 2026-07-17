"""Tests for Dew Point diagnostics."""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import UnitOfTemperature
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dew_point import DOMAIN
from custom_components.dew_point.diagnostics import (
    async_get_config_entry_diagnostics,
)


async def test_diagnostics_exposes_source_health_without_measurements(hass) -> None:
    """Diagnostics contain useful metadata but no source values or extra attributes."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Bathroom",
        data={
            "name": "Bathroom",
            "temperature_sensor": "sensor.bathroom_temperature",
            "humidity_sensor": "sensor.bathroom_humidity",
            "surface_temperature_sensor": "sensor.window_temperature",
        },
        options={
            "condensation_threshold": 0.0,
            "hysteresis": 0.5,
        },
    )
    entry.add_to_hass(hass)
    hass.states.async_set(
        "sensor.bathroom_temperature",
        "21.7",
        {
            "device_class": SensorDeviceClass.TEMPERATURE,
            "unit_of_measurement": UnitOfTemperature.CELSIUS,
            "private_attribute": "must-not-leak",
        },
    )
    hass.states.async_set(
        "sensor.bathroom_humidity",
        "47.3",
        {
            "device_class": SensorDeviceClass.HUMIDITY,
            "unit_of_measurement": "%",
            "raw_payload": {"secret": "must-not-leak"},
        },
    )

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert diagnostics["config_entry"]["configuration"] == {
        "name": "Bathroom",
        "temperature_sensor": "sensor.bathroom_temperature",
        "humidity_sensor": "sensor.bathroom_humidity",
        "surface_temperature_sensor": "sensor.window_temperature",
        "condensation_threshold": 0.0,
        "hysteresis": 0.5,
    }
    assert diagnostics["sources"]["temperature_sensor"] == {
        "entity_id": "sensor.bathroom_temperature",
        "state_status": "present",
        "device_class": SensorDeviceClass.TEMPERATURE,
        "unit_of_measurement": UnitOfTemperature.CELSIUS,
    }
    assert diagnostics["sources"]["humidity_sensor"] == {
        "entity_id": "sensor.bathroom_humidity",
        "state_status": "present",
        "device_class": SensorDeviceClass.HUMIDITY,
        "unit_of_measurement": "%",
    }
    assert diagnostics["sources"]["surface_temperature_sensor"] == {
        "entity_id": "sensor.window_temperature",
        "state_status": "missing",
    }
    serialized = str(diagnostics)
    assert "21.7" not in serialized
    assert "47.3" not in serialized
    assert "must-not-leak" not in serialized
    assert "private_attribute" not in serialized
    assert "raw_payload" not in serialized


async def test_diagnostics_only_categorizes_transient_unavailability(hass) -> None:
    """A temporarily unavailable source is reported without leaking old data."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "temperature_sensor": "sensor.temperature",
            "humidity_sensor": "sensor.humidity",
        },
    )
    entry.add_to_hass(hass)
    hass.states.async_set(
        "sensor.temperature",
        "unavailable",
        {
            "device_class": SensorDeviceClass.TEMPERATURE,
            "unit_of_measurement": UnitOfTemperature.CELSIUS,
        },
    )

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert diagnostics["sources"]["temperature_sensor"]["state_status"] == (
        "unavailable"
    )
    assert diagnostics["sources"]["humidity_sensor"] == {
        "entity_id": "sensor.humidity",
        "state_status": "missing",
    }


async def test_diagnostics_categorizes_registered_unloaded_source(hass) -> None:
    """A registry-only source is unavailable rather than incorrectly missing."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "temperature_sensor": "sensor.temperature",
            "humidity_sensor": "sensor.humidity",
        },
    )
    entry.add_to_hass(hass)
    er.async_get(hass).async_get_or_create(
        "sensor",
        "test",
        "temperature",
        suggested_object_id="temperature",
        original_device_class=SensorDeviceClass.TEMPERATURE,
        unit_of_measurement=UnitOfTemperature.KELVIN,
    )

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert diagnostics["sources"]["temperature_sensor"] == {
        "entity_id": "sensor.temperature",
        "state_status": "unavailable",
        "device_class": SensorDeviceClass.TEMPERATURE,
        "unit_of_measurement": UnitOfTemperature.KELVIN,
    }


async def test_diagnostics_reports_weather_health_without_attributes(hass) -> None:
    """Weather diagnostics expose source health without environmental readings."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        options={
            "name": "Home",
            "source_type": "weather",
            "weather_entity": "weather.home",
        },
    )
    entry.add_to_hass(hass)
    hass.states.async_set(
        "weather.home",
        "sunny",
        {
            "temperature": 21.5,
            "temperature_unit": UnitOfTemperature.CELSIUS,
            "humidity": 48,
        },
    )

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert diagnostics["config_entry"]["configuration"]["source_type"] == "weather"
    assert diagnostics["sources"]["weather_entity"] == {
        "entity_id": "weather.home",
        "state_status": "present",
        "device_class": None,
        "unit_of_measurement": None,
    }
    assert "21.5" not in str(diagnostics)
    assert "48" not in str(diagnostics)
