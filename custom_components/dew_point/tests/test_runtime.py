"""Tests for the shared event-driven Dew Point runtime."""

from __future__ import annotations

import logging
from unittest.mock import Mock, call, patch

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.components.weather import (
    ATTR_WEATHER_HUMIDITY,
    ATTR_WEATHER_TEMPERATURE,
    ATTR_WEATHER_TEMPERATURE_UNIT,
)
from homeassistant.const import (
    ATTR_DEVICE_CLASS,
    ATTR_UNIT_OF_MEASUREMENT,
    CONF_NAME,
    PERCENTAGE,
    STATE_UNAVAILABLE,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dew_point import runtime as runtime_module
from custom_components.dew_point.const import (
    CONF_CONDENSATION_THRESHOLD,
    CONF_HUMIDITY_SENSOR,
    CONF_HYSTERESIS,
    CONF_SOURCE_TYPE,
    CONF_SURFACE_TEMPERATURE_SENSOR,
    CONF_TEMPERATURE_SENSOR,
    CONF_WEATHER_ENTITY,
    DOMAIN,
    SOURCE_TYPE_WEATHER,
)
from custom_components.dew_point.repairs import SourceIssueType
from custom_components.dew_point.runtime import DewPointRuntime, SourceStatus


def _entry(*, surface: bool = True) -> MockConfigEntry:
    """Return a runtime config entry."""
    options: dict[str, str | float] = {
        CONF_NAME: "Cellar",
        CONF_TEMPERATURE_SENSOR: "sensor.temperature",
        CONF_HUMIDITY_SENSOR: "sensor.humidity",
        CONF_CONDENSATION_THRESHOLD: 0.0,
        CONF_HYSTERESIS: 0.5,
    }
    if surface:
        options[CONF_SURFACE_TEMPERATURE_SENSOR] = "sensor.surface"
    return MockConfigEntry(domain=DOMAIN, title="Cellar", options=options)


def _set_temperature(
    hass: HomeAssistant,
    entity_id: str,
    value: str | float,
    unit: str = UnitOfTemperature.CELSIUS,
) -> None:
    """Set a compatible temperature source."""
    hass.states.async_set(
        entity_id,
        str(value),
        {
            ATTR_DEVICE_CLASS: SensorDeviceClass.TEMPERATURE,
            ATTR_UNIT_OF_MEASUREMENT: unit,
        },
    )


def _set_humidity(hass: HomeAssistant, value: str | float) -> None:
    """Set a compatible humidity source."""
    hass.states.async_set(
        "sensor.humidity",
        str(value),
        {
            ATTR_DEVICE_CLASS: SensorDeviceClass.HUMIDITY,
            ATTR_UNIT_OF_MEASUREMENT: PERCENTAGE,
        },
    )


async def test_runtime_calculates_once_and_tracks_sources(
    hass: HomeAssistant,
) -> None:
    """Source events update one shared snapshot and notify listeners."""
    _set_temperature(hass, "sensor.temperature", 20)
    _set_humidity(hass, 50)
    _set_temperature(hass, "sensor.surface", 10)
    entry = _entry()
    entry.add_to_hass(hass)
    listener = Mock()

    with patch("custom_components.dew_point.runtime.async_update_source_issue"):
        runtime = DewPointRuntime(hass, entry)
        runtime.async_add_listener(listener)
        runtime.async_start()

        assert runtime.data.available is True
        assert runtime.data.surface_available is True
        assert runtime.data.properties is not None
        assert runtime.data.properties.dew_point_c == pytest.approx(9.27, abs=0.02)
        assert runtime.data.surface_dew_point_margin_c == pytest.approx(0.73, abs=0.03)
        assert runtime.data.condensation_risk is False
        assert set(runtime.source_entity_ids) == {
            "sensor.temperature",
            "sensor.humidity",
            "sensor.surface",
        }

        _set_humidity(hass, 60)
        await hass.async_block_till_done()

        assert listener.call_count == 2
        assert runtime.data.properties is not None
        assert runtime.data.properties.dew_point_c > 11

        runtime.async_stop()
        _set_humidity(hass, 65)
        await hass.async_block_till_done()
        assert listener.call_count == 2


async def test_runtime_calculates_from_weather_attributes(
    hass: HomeAssistant,
) -> None:
    """One weather entity supplies both measurements and triggers updates."""
    hass.states.async_set(
        "weather.home",
        "sunny",
        {
            ATTR_WEATHER_TEMPERATURE: 68,
            ATTR_WEATHER_TEMPERATURE_UNIT: UnitOfTemperature.FAHRENHEIT,
            ATTR_WEATHER_HUMIDITY: 50,
        },
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Home",
        options={
            CONF_NAME: "Home",
            CONF_SOURCE_TYPE: SOURCE_TYPE_WEATHER,
            CONF_WEATHER_ENTITY: "weather.home",
        },
    )
    entry.add_to_hass(hass)
    listener = Mock()

    with patch("custom_components.dew_point.runtime.async_update_source_issue"):
        runtime = DewPointRuntime(hass, entry)
        runtime.async_add_listener(listener)
        runtime.async_start()

        assert runtime.source_entity_ids == ("weather.home",)
        assert runtime.temperature_entity_id == "weather.home"
        assert runtime.humidity_entity_id == "weather.home"
        assert runtime.data.available is True
        assert runtime.data.properties is not None
        assert runtime.data.properties.dew_point_c == pytest.approx(9.27, abs=0.02)

        hass.states.async_set(
            "weather.home",
            "cloudy",
            {
                ATTR_WEATHER_TEMPERATURE: 68,
                ATTR_WEATHER_TEMPERATURE_UNIT: UnitOfTemperature.FAHRENHEIT,
                ATTR_WEATHER_HUMIDITY: 60,
            },
        )
        await hass.async_block_till_done()

        assert listener.call_count == 2
        assert runtime.data.properties is not None
        assert runtime.data.properties.dew_point_c > 11


async def test_runtime_marks_invalid_weather_attributes_incompatible(
    hass: HomeAssistant,
) -> None:
    """Missing weather measurements create one actionable weather-source issue."""
    hass.states.async_set(
        "weather.home",
        "sunny",
        {
            ATTR_WEATHER_TEMPERATURE: 20,
            ATTR_WEATHER_TEMPERATURE_UNIT: UnitOfTemperature.CELSIUS,
        },
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Home",
        options={
            CONF_NAME: "Home",
            CONF_SOURCE_TYPE: SOURCE_TYPE_WEATHER,
            CONF_WEATHER_ENTITY: "weather.home",
        },
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.dew_point.runtime.async_update_source_issue"
    ) as update_issue:
        runtime = DewPointRuntime(hass, entry)
        runtime.async_refresh()

    assert runtime.data.available is False
    assert runtime.source_statuses[CONF_WEATHER_ENTITY] is SourceStatus.INCOMPATIBLE
    assert (
        call(
            hass,
            entry,
            CONF_WEATHER_ENTITY,
            SourceIssueType.INCOMPATIBLE,
            entity_id="weather.home",
        )
        in update_issue.call_args_list
    )


async def test_runtime_hysteresis(hass: HomeAssistant) -> None:
    """Condensation risk does not chatter around its configured threshold."""
    _set_temperature(hass, "sensor.temperature", 20)
    _set_humidity(hass, 50)
    _set_temperature(hass, "sensor.surface", 9)
    entry = _entry()
    entry.add_to_hass(hass)

    with patch("custom_components.dew_point.runtime.async_update_source_issue"):
        runtime = DewPointRuntime(hass, entry)
        runtime.async_start()
        assert runtime.data.condensation_risk is True

        _set_temperature(hass, "sensor.surface", 9.5)
        await hass.async_block_till_done()
        assert runtime.data.surface_dew_point_margin_c == pytest.approx(0.23, abs=0.03)
        assert runtime.data.condensation_risk is True

        _set_temperature(hass, "sensor.surface", 10)
        await hass.async_block_till_done()
        assert runtime.data.condensation_risk is False


async def test_runtime_marks_unavailable_and_actionable_problems(
    hass: HomeAssistant,
) -> None:
    """Transient unavailability is distinct from missing and incompatible sources."""
    _set_temperature(hass, "sensor.temperature", 20)
    _set_humidity(hass, 50)
    entry = _entry(surface=False)
    entry.add_to_hass(hass)

    with patch(
        "custom_components.dew_point.runtime.async_update_source_issue"
    ) as update_issue:
        runtime = DewPointRuntime(hass, entry)
        runtime.async_start()
        update_issue.reset_mock()

        hass.states.async_set(
            "sensor.humidity",
            STATE_UNAVAILABLE,
            {
                ATTR_DEVICE_CLASS: SensorDeviceClass.HUMIDITY,
                ATTR_UNIT_OF_MEASUREMENT: PERCENTAGE,
            },
        )
        await hass.async_block_till_done()
        assert runtime.source_statuses[CONF_HUMIDITY_SENSOR] is SourceStatus.UNAVAILABLE
        assert runtime.data.available is False
        update_issue.assert_not_called()

        hass.states.async_remove("sensor.humidity")
        await hass.async_block_till_done()
        assert runtime.source_statuses[CONF_HUMIDITY_SENSOR] is SourceStatus.MISSING
        update_issue.assert_called_once_with(
            hass,
            entry,
            CONF_HUMIDITY_SENSOR,
            SourceIssueType.MISSING,
            entity_id="sensor.humidity",
        )

        update_issue.reset_mock()
        hass.states.async_set(
            "sensor.humidity",
            "50",
            {ATTR_UNIT_OF_MEASUREMENT: "not-percent"},
        )
        await hass.async_block_till_done()
        assert (
            runtime.source_statuses[CONF_HUMIDITY_SENSOR] is SourceStatus.INCOMPATIBLE
        )
        update_issue.assert_called_once_with(
            hass,
            entry,
            CONF_HUMIDITY_SENSOR,
            SourceIssueType.INCOMPATIBLE,
            entity_id="sensor.humidity",
        )


async def test_runtime_uses_registry_metadata_and_converts_units(
    hass: HomeAssistant,
) -> None:
    """Registry device classes and non-Celsius temperature units are supported."""
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "sensor",
        "test",
        "temperature",
        suggested_object_id="temperature",
        original_device_class=SensorDeviceClass.TEMPERATURE,
    )
    registry.async_get_or_create(
        "sensor",
        "test",
        "humidity",
        suggested_object_id="humidity",
        original_device_class=SensorDeviceClass.HUMIDITY,
    )
    hass.states.async_set(
        "sensor.temperature",
        "68",
        {ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.FAHRENHEIT},
    )
    hass.states.async_set(
        "sensor.humidity", "50", {ATTR_UNIT_OF_MEASUREMENT: PERCENTAGE}
    )
    entry = _entry(surface=False)
    entry.add_to_hass(hass)

    with patch("custom_components.dew_point.runtime.async_update_source_issue"):
        runtime = DewPointRuntime(hass, entry)
        runtime.async_refresh()

    assert runtime.data.temperature_native_value == 68
    assert runtime.data.temperature_native_unit == UnitOfTemperature.FAHRENHEIT
    assert runtime.data.properties is not None
    assert runtime.data.properties.air_temperature_c == pytest.approx(20)


async def test_registered_but_unloaded_source_is_transient(
    hass: HomeAssistant,
) -> None:
    """A source retained in the entity registry is unavailable rather than missing."""
    er.async_get(hass).async_get_or_create(
        "sensor",
        "test",
        "temperature",
        suggested_object_id="temperature",
        original_device_class=SensorDeviceClass.TEMPERATURE,
    )
    _set_humidity(hass, 50)
    entry = _entry(surface=False)
    entry.add_to_hass(hass)

    with patch(
        "custom_components.dew_point.runtime.async_update_source_issue"
    ) as update_issue:
        runtime = DewPointRuntime(hass, entry)
        runtime.async_refresh()

    assert runtime.source_statuses[CONF_TEMPERATURE_SENSOR] is SourceStatus.UNAVAILABLE
    assert (
        call(
            hass,
            entry,
            CONF_TEMPERATURE_SENSOR,
            None,
            entity_id="sensor.temperature",
        )
        in update_issue.call_args_list
    )


async def test_runtime_logs_problem_and_recovery_once(
    hass: HomeAssistant, caplog
) -> None:
    """Changing failure details does not spam logs before full recovery."""
    _set_temperature(hass, "sensor.temperature", 20)
    _set_humidity(hass, 50)
    entry = _entry(surface=False)
    entry.add_to_hass(hass)
    caplog.set_level(logging.INFO, logger="custom_components.dew_point.runtime")

    with patch("custom_components.dew_point.runtime.async_update_source_issue"):
        runtime = DewPointRuntime(hass, entry)
        runtime.async_start()
        hass.states.async_set(
            "sensor.humidity",
            STATE_UNAVAILABLE,
            {
                ATTR_DEVICE_CLASS: SensorDeviceClass.HUMIDITY,
                ATTR_UNIT_OF_MEASUREMENT: PERCENTAGE,
            },
        )
        await hass.async_block_till_done()
        hass.states.async_remove("sensor.humidity")
        await hass.async_block_till_done()
        _set_humidity(hass, 50)
        await hass.async_block_till_done()

    messages = [record.getMessage() for record in caplog.records]
    assert (
        sum(message.startswith("Source validation failed") for message in messages) == 1
    )
    assert sum(message.startswith("Sources recovered") for message in messages) == 1


async def test_runtime_refresh_is_idempotent_and_out_of_range_is_incompatible(
    hass: HomeAssistant,
) -> None:
    """Identical snapshots do not notify and unsupported calculation input is rejected."""
    _set_temperature(hass, "sensor.temperature", 20)
    _set_humidity(hass, 50)
    entry = _entry(surface=False)
    entry.add_to_hass(hass)
    listener = Mock()

    with patch("custom_components.dew_point.runtime.async_update_source_issue"):
        runtime = DewPointRuntime(hass, entry)
        runtime.async_add_listener(listener)
        runtime.async_refresh()
        runtime.async_refresh()
        assert listener.call_count == 1

        with patch(
            "custom_components.dew_point.runtime.calculate_moist_air_properties",
            return_value=None,
        ):
            runtime.async_refresh()

    assert runtime.source_statuses[CONF_TEMPERATURE_SENSOR] is SourceStatus.INCOMPATIBLE


async def test_runtime_temperature_and_humidity_validation_branches(
    hass: HomeAssistant,
) -> None:
    """Malformed source-state forms are normalized to explicit statuses."""
    entry = _entry(surface=False)
    entry.add_to_hass(hass)
    runtime = DewPointRuntime(hass, entry)

    _set_temperature(hass, "sensor.temperature", STATE_UNAVAILABLE)
    assert (
        runtime._read_temperature(CONF_TEMPERATURE_SENSOR, "sensor.temperature").status  # noqa: SLF001
        is SourceStatus.UNAVAILABLE
    )
    hass.states.async_set(
        "sensor.temperature",
        "20",
        {
            ATTR_DEVICE_CLASS: SensorDeviceClass.POWER,
            ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS,
        },
    )
    assert (
        runtime._read_temperature(CONF_TEMPERATURE_SENSOR, "sensor.temperature").status  # noqa: SLF001
        is SourceStatus.INCOMPATIBLE
    )
    hass.states.async_set(
        "sensor.temperature",
        "not-a-number",
        {ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS},
    )
    assert (
        runtime._read_temperature(CONF_TEMPERATURE_SENSOR, "sensor.temperature").status  # noqa: SLF001
        is SourceStatus.INCOMPATIBLE
    )
    _set_temperature(hass, "sensor.temperature", 20)
    with patch.object(
        runtime_module.TemperatureConverter, "convert", side_effect=ValueError
    ):
        assert (
            runtime._read_temperature(  # noqa: SLF001
                CONF_TEMPERATURE_SENSOR, "sensor.temperature"
            ).status
            is SourceStatus.INCOMPATIBLE
        )

    hass.states.async_set(
        "sensor.humidity",
        "50",
        {
            ATTR_DEVICE_CLASS: SensorDeviceClass.POWER,
            ATTR_UNIT_OF_MEASUREMENT: PERCENTAGE,
        },
    )
    assert (
        runtime._read_humidity("sensor.humidity").status  # noqa: SLF001
        is SourceStatus.INCOMPATIBLE
    )
    _set_humidity(hass, "nan")
    assert (
        runtime._read_humidity("sensor.humidity").status  # noqa: SLF001
        is SourceStatus.INCOMPATIBLE
    )


async def test_runtime_start_is_idempotent_and_logs_recovery(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """Starting twice creates one subscription and status logs occur on transitions."""
    entry = _entry(surface=False)
    entry.add_to_hass(hass)
    runtime = DewPointRuntime(hass, entry)

    with patch("custom_components.dew_point.runtime.async_update_source_issue"):
        runtime.async_start()
        subscription = runtime._unsub_state_listener  # noqa: SLF001
        runtime.async_start()
        assert runtime._unsub_state_listener is subscription  # noqa: SLF001

        _set_temperature(hass, "sensor.temperature", 20)
        _set_humidity(hass, 50)
        await hass.async_block_till_done()

    assert "Sources recovered for Cellar" in caplog.text
    runtime.async_stop()
    runtime.async_stop()


def test_runtime_numeric_fallback_helpers() -> None:
    """Legacy numeric parsing remains bounded and exception-safe."""
    assert runtime_module._finite_float(object()) is None  # noqa: SLF001
    assert runtime_module._bounded_int(None, 1, 0, 15) == 1  # noqa: SLF001
    assert runtime_module._bounded_int("bad", 1, 0, 15) == 1  # noqa: SLF001
    assert runtime_module._bounded_int(99, 1, 0, 15) == 15  # noqa: SLF001
