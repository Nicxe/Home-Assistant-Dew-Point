"""Tests for the Dew Point config flow."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.components.weather import (
    ATTR_WEATHER_HUMIDITY,
    ATTR_WEATHER_TEMPERATURE,
    ATTR_WEATHER_TEMPERATURE_UNIT,
)
from homeassistant.const import (
    ATTR_DEVICE_CLASS,
    ATTR_UNIT_OF_MEASUREMENT,
    PERCENTAGE,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.schema_config_entry_flow import SchemaFlowError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dew_point.config_flow import (
    _resolve_source,
    _validate_finite_range,
)
from custom_components.dew_point.const import (
    CONF_CONDENSATION_THRESHOLD,
    CONF_HUMIDITY_SENSOR,
    CONF_HYSTERESIS,
    CONF_SOURCE_TYPE,
    CONF_SURFACE_TEMPERATURE_SENSOR,
    CONF_TEMPERATURE_SENSOR,
    CONF_WEATHER_ENTITY,
    DEFAULT_CONDENSATION_THRESHOLD,
    DEFAULT_HYSTERESIS,
    DOMAIN,
    SOURCE_TYPE_SENSORS,
    SOURCE_TYPE_WEATHER,
)


def _set_sources(hass: HomeAssistant) -> None:
    """Add compatible source states."""
    hass.states.async_set(
        "sensor.air_temperature",
        "20.5",
        {
            ATTR_DEVICE_CLASS: SensorDeviceClass.TEMPERATURE,
            ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS,
        },
    )
    hass.states.async_set(
        "sensor.humidity",
        "52",
        {
            ATTR_DEVICE_CLASS: SensorDeviceClass.HUMIDITY,
            ATTR_UNIT_OF_MEASUREMENT: PERCENTAGE,
        },
    )
    hass.states.async_set(
        "sensor.surface_temperature",
        "16.2",
        {
            ATTR_DEVICE_CLASS: SensorDeviceClass.TEMPERATURE,
            ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS,
        },
    )


def _sensor_input() -> dict[str, str | float]:
    """Return valid separate-sensor step input."""
    return {
        CONF_TEMPERATURE_SENSOR: "sensor.air_temperature",
        CONF_HUMIDITY_SENSOR: "sensor.humidity",
        CONF_SURFACE_TEMPERATURE_SENSOR: "sensor.surface_temperature",
        CONF_CONDENSATION_THRESHOLD: 1.0,
        CONF_HYSTERESIS: 0.5,
    }


def _sensor_options() -> dict[str, str | float]:
    """Return canonical options for a separate-sensor entry."""
    return {
        "name": "Basement climate",
        CONF_SOURCE_TYPE: SOURCE_TYPE_SENSORS,
        **_sensor_input(),
    }


async def _start_sensor_flow(
    hass: HomeAssistant, *, name: str = "Basement climate"
) -> dict[str, object]:
    """Start a config flow and select separate sensors."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"name": name, CONF_SOURCE_TYPE: SOURCE_TYPE_SENSORS},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == SOURCE_TYPE_SENSORS
    return result


async def test_user_flow_creates_canonical_options(hass: HomeAssistant) -> None:
    """The user flow stores all helper settings in entry options."""
    _set_sources(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    schema_keys = {str(key) for key in result["data_schema"].schema}
    assert schema_keys == {"name", CONF_SOURCE_TYPE}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"name": "Basement climate", CONF_SOURCE_TYPE: SOURCE_TYPE_SENSORS},
    )
    assert result["step_id"] == SOURCE_TYPE_SENSORS
    schema_keys = {str(key) for key in result["data_schema"].schema}
    assert schema_keys == {
        CONF_TEMPERATURE_SENSOR,
        CONF_HUMIDITY_SENSOR,
        CONF_SURFACE_TEMPERATURE_SENSOR,
        CONF_CONDENSATION_THRESHOLD,
        CONF_HYSTERESIS,
    }

    with patch("custom_components.dew_point.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], _sensor_input()
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Basement climate"
    assert result["data"] == {}
    assert result["options"] == _sensor_options()


async def test_user_flow_creates_weather_options(hass: HomeAssistant) -> None:
    """The weather flow stores one entity for both atmospheric measurements."""
    hass.states.async_set(
        "weather.home",
        "sunny",
        {
            ATTR_WEATHER_TEMPERATURE: 68,
            ATTR_WEATHER_TEMPERATURE_UNIT: UnitOfTemperature.FAHRENHEIT,
            ATTR_WEATHER_HUMIDITY: 50,
        },
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"name": "Home weather", CONF_SOURCE_TYPE: SOURCE_TYPE_WEATHER},
    )

    assert result["step_id"] == SOURCE_TYPE_WEATHER
    assert {str(key) for key in result["data_schema"].schema} == {
        CONF_WEATHER_ENTITY,
        CONF_SURFACE_TEMPERATURE_SENSOR,
        CONF_CONDENSATION_THRESHOLD,
        CONF_HYSTERESIS,
    }

    with patch("custom_components.dew_point.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_WEATHER_ENTITY: "weather.home",
                CONF_CONDENSATION_THRESHOLD: 0.0,
                CONF_HYSTERESIS: 0.5,
            },
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"] == {
        "name": "Home weather",
        CONF_SOURCE_TYPE: SOURCE_TYPE_WEATHER,
        CONF_WEATHER_ENTITY: "weather.home",
        CONF_CONDENSATION_THRESHOLD: 0.0,
        CONF_HYSTERESIS: 0.5,
    }


@pytest.mark.parametrize(
    "attributes",
    [
        {
            ATTR_WEATHER_TEMPERATURE: 20,
            ATTR_WEATHER_TEMPERATURE_UNIT: UnitOfTemperature.CELSIUS,
        },
        {
            ATTR_WEATHER_TEMPERATURE: 20,
            ATTR_WEATHER_TEMPERATURE_UNIT: UnitOfTemperature.CELSIUS,
            ATTR_WEATHER_HUMIDITY: 101,
        },
        {
            ATTR_WEATHER_TEMPERATURE: "invalid",
            ATTR_WEATHER_TEMPERATURE_UNIT: UnitOfTemperature.CELSIUS,
            ATTR_WEATHER_HUMIDITY: 50,
        },
    ],
)
async def test_user_flow_rejects_invalid_weather_attributes(
    hass: HomeAssistant, attributes: dict[str, str | int]
) -> None:
    """A weather source must expose compatible current measurement attributes."""
    hass.states.async_set("weather.home", "sunny", attributes)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"name": "Weather", CONF_SOURCE_TYPE: SOURCE_TYPE_WEATHER},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_WEATHER_ENTITY: "weather.home",
            CONF_CONDENSATION_THRESHOLD: 0.0,
            CONF_HYSTERESIS: 0.5,
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_weather_entity"}


async def test_user_flow_accepts_registered_unavailable_weather_entity(
    hass: HomeAssistant,
) -> None:
    """A registry-only weather source can be configured before attributes load."""
    er.async_get(hass).async_get_or_create(
        "weather",
        "test",
        "home",
        suggested_object_id="home",
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"name": "Weather", CONF_SOURCE_TYPE: SOURCE_TYPE_WEATHER},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_WEATHER_ENTITY: "weather.home",
            CONF_CONDENSATION_THRESHOLD: 0.0,
            CONF_HYSTERESIS: 0.5,
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_accepts_compatible_legacy_sources(
    hass: HomeAssistant,
) -> None:
    """Unit-only legacy sensors remain supported when their units are compatible."""
    hass.states.async_set(
        "sensor.legacy_temperature",
        "293.15",
        {ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.KELVIN},
    )
    hass.states.async_set(
        "sensor.legacy_humidity",
        "45",
        {ATTR_UNIT_OF_MEASUREMENT: PERCENTAGE},
    )

    result = await _start_sensor_flow(hass, name="Legacy")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_TEMPERATURE_SENSOR: "sensor.legacy_temperature",
            CONF_HUMIDITY_SENSOR: "sensor.legacy_humidity",
            CONF_CONDENSATION_THRESHOLD: DEFAULT_CONDENSATION_THRESHOLD,
            CONF_HYSTERESIS: DEFAULT_HYSTERESIS,
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_rejects_incompatible_temperature(
    hass: HomeAssistant,
) -> None:
    """An incompatible source is rejected before an entry is created."""
    _set_sources(hass)
    hass.states.async_set(
        "sensor.power",
        "100",
        {
            ATTR_DEVICE_CLASS: SensorDeviceClass.POWER,
            ATTR_UNIT_OF_MEASUREMENT: "W",
        },
    )

    result = await _start_sensor_flow(hass)
    user_input = _sensor_input()
    user_input[CONF_TEMPERATURE_SENSOR] = "sensor.power"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_temperature_sensor"}


async def test_user_flow_rejects_invalid_humidity_value(
    hass: HomeAssistant,
) -> None:
    """Out-of-range relative humidity is rejected."""
    _set_sources(hass)
    hass.states.async_set(
        "sensor.humidity",
        "101",
        {
            ATTR_DEVICE_CLASS: SensorDeviceClass.HUMIDITY,
            ATTR_UNIT_OF_MEASUREMENT: PERCENTAGE,
        },
    )

    result = await _start_sensor_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _sensor_input()
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_humidity_sensor"}


async def test_user_flow_aborts_exact_duplicate(hass: HomeAssistant) -> None:
    """An exact duplicate source combination is not created."""
    _set_sources(hass)
    existing = MockConfigEntry(
        domain=DOMAIN,
        title="Existing",
        data={},
        options=_sensor_options(),
    )
    existing.add_to_hass(hass)

    result = await _start_sensor_flow(hass, name="Another name")
    duplicate = _sensor_input()
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], duplicate
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_user_flow_starts_while_existing_entry_has_missing_source(
    hass: HomeAssistant,
) -> None:
    """A broken existing helper never prevents creation of another helper."""
    _set_sources(hass)
    existing = MockConfigEntry(
        domain=DOMAIN,
        title="Broken helper",
        data={},
        options={
            "name": "Broken helper",
            CONF_SOURCE_TYPE: SOURCE_TYPE_SENSORS,
            CONF_TEMPERATURE_SENSOR: "sensor.old_temperature",
            CONF_HUMIDITY_SENSOR: "sensor.missing_humidity",
            CONF_CONDENSATION_THRESHOLD: DEFAULT_CONDENSATION_THRESHOLD,
            CONF_HYSTERESIS: DEFAULT_HYSTERESIS,
        },
    )
    existing.add_to_hass(hass)

    result = await _start_sensor_flow(hass, name="Working helper")
    with patch("custom_components.dew_point.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], _sensor_input()
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Working helper"


async def test_user_flow_shows_unknown_error_for_unexpected_validation_failure(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """Unexpected source validation errors stay inside the config flow."""
    _set_sources(hass)
    result = await _start_sensor_flow(hass)

    with patch(
        "custom_components.dew_point.config_flow._validate_humidity_source",
        side_effect=RuntimeError("unexpected validation failure"),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], _sensor_input()
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "unknown"}
    assert "Unexpected error validating configuration" in caplog.text


async def test_options_flow_updates_and_schedules_reload(
    hass: HomeAssistant,
) -> None:
    """Saving changed options schedules exactly one config-entry reload."""
    _set_sources(hass)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Basement climate",
        data={},
        options=_sensor_options(),
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"name": "Basement climate", CONF_SOURCE_TYPE: SOURCE_TYPE_SENSORS},
    )
    assert result["step_id"] == SOURCE_TYPE_SENSORS

    updated = {
        CONF_TEMPERATURE_SENSOR: "sensor.air_temperature",
        CONF_HUMIDITY_SENSOR: "sensor.humidity",
        CONF_SURFACE_TEMPERATURE_SENSOR: "sensor.surface_temperature",
        CONF_CONDENSATION_THRESHOLD: 1.5,
        CONF_HYSTERESIS: 0.75,
    }
    with patch.object(hass.config_entries, "async_schedule_reload") as reload_mock:
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], updated
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {
        "name": "Basement climate",
        CONF_SOURCE_TYPE: SOURCE_TYPE_SENSORS,
        **updated,
    }
    reload_mock.assert_called_once_with(entry.entry_id)


async def test_options_flow_can_remove_optional_surface_source(
    hass: HomeAssistant,
) -> None:
    """Leaving the optional surface field empty removes it from saved options."""
    _set_sources(hass)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Basement climate",
        data={},
        options=_sensor_options(),
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"name": "Basement climate", CONF_SOURCE_TYPE: SOURCE_TYPE_SENSORS},
    )

    updated = {
        CONF_TEMPERATURE_SENSOR: "sensor.air_temperature",
        CONF_HUMIDITY_SENSOR: "sensor.humidity",
        CONF_CONDENSATION_THRESHOLD: 1.0,
        CONF_HYSTERESIS: 0.5,
    }
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], updated
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert CONF_SURFACE_TEMPERATURE_SENSOR not in entry.options


async def test_options_flow_switches_to_weather_and_removes_sensor_sources(
    hass: HomeAssistant,
) -> None:
    """Changing source type removes fields belonging to the previous mode."""
    _set_sources(hass)
    hass.states.async_set(
        "weather.home",
        "cloudy",
        {
            ATTR_WEATHER_TEMPERATURE: 20,
            ATTR_WEATHER_TEMPERATURE_UNIT: UnitOfTemperature.CELSIUS,
            ATTR_WEATHER_HUMIDITY: 50,
        },
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Basement climate",
        options=_sensor_options(),
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"name": "Basement climate", CONF_SOURCE_TYPE: SOURCE_TYPE_WEATHER},
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_WEATHER_ENTITY: "weather.home",
            CONF_CONDENSATION_THRESHOLD: 0.0,
            CONF_HYSTERESIS: 0.5,
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_SOURCE_TYPE] == SOURCE_TYPE_WEATHER
    assert entry.options[CONF_WEATHER_ENTITY] == "weather.home"
    assert CONF_TEMPERATURE_SENSOR not in entry.options
    assert CONF_HUMIDITY_SENSOR not in entry.options


async def test_user_flow_rejects_air_temperature_outside_calculation_range(
    hass: HomeAssistant,
) -> None:
    """An air temperature outside the documented Buck range is rejected."""
    _set_sources(hass)
    hass.states.async_set(
        "sensor.air_temperature",
        "51",
        {
            ATTR_DEVICE_CLASS: SensorDeviceClass.TEMPERATURE,
            ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS,
        },
    )
    result = await _start_sensor_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _sensor_input()
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_temperature_sensor"}


@pytest.mark.parametrize(
    ("source_key", "entity_id", "state", "attributes", "error"),
    [
        (
            CONF_TEMPERATURE_SENSOR,
            "sensor.temperature_without_metadata",
            "20",
            {},
            "invalid_temperature_sensor",
        ),
        (
            CONF_TEMPERATURE_SENSOR,
            "sensor.non_numeric_temperature",
            "not-a-number",
            {
                ATTR_DEVICE_CLASS: SensorDeviceClass.TEMPERATURE,
                ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS,
            },
            "invalid_temperature_sensor",
        ),
        (
            CONF_TEMPERATURE_SENSOR,
            "sensor.non_finite_temperature",
            "nan",
            {
                ATTR_DEVICE_CLASS: SensorDeviceClass.TEMPERATURE,
                ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS,
            },
            "invalid_temperature_sensor",
        ),
        (
            CONF_HUMIDITY_SENSOR,
            "sensor.power_as_humidity",
            "50",
            {
                ATTR_DEVICE_CLASS: SensorDeviceClass.POWER,
                ATTR_UNIT_OF_MEASUREMENT: PERCENTAGE,
            },
            "invalid_humidity_sensor",
        ),
        (
            CONF_HUMIDITY_SENSOR,
            "sensor.humidity_wrong_unit",
            "50",
            {
                ATTR_DEVICE_CLASS: SensorDeviceClass.HUMIDITY,
                ATTR_UNIT_OF_MEASUREMENT: "g/m³",
            },
            "invalid_humidity_sensor",
        ),
        (
            CONF_HUMIDITY_SENSOR,
            "sensor.humidity_without_metadata",
            "50",
            {},
            "invalid_humidity_sensor",
        ),
        (
            CONF_HUMIDITY_SENSOR,
            "sensor.non_numeric_humidity",
            "not-a-number",
            {
                ATTR_DEVICE_CLASS: SensorDeviceClass.HUMIDITY,
                ATTR_UNIT_OF_MEASUREMENT: PERCENTAGE,
            },
            "invalid_humidity_sensor",
        ),
        (
            CONF_SURFACE_TEMPERATURE_SENSOR,
            "sensor.invalid_surface",
            "20",
            {ATTR_UNIT_OF_MEASUREMENT: "W"},
            "invalid_surface_temperature_sensor",
        ),
    ],
)
async def test_user_flow_rejects_source_metadata_and_value_errors(
    hass: HomeAssistant,
    source_key: str,
    entity_id: str,
    state: str,
    attributes: dict[str, str],
    error: str,
) -> None:
    """Each source field reports a concrete compatibility error."""
    _set_sources(hass)
    hass.states.async_set(entity_id, state, attributes)
    user_input = _sensor_input()
    user_input[source_key] = entity_id
    result = await _start_sensor_flow(hass)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}


async def test_user_flow_rejects_invalid_missing_and_non_sensor_sources(
    hass: HomeAssistant,
) -> None:
    """An entity ID with no state or registry row is rejected."""
    _set_sources(hass)
    user_input = _sensor_input()
    user_input[CONF_TEMPERATURE_SENSOR] = "sensor.missing"
    result = await _start_sensor_flow(hass)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_temperature_sensor"}


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("name", "", "invalid_name"),
        ("name", "x" * 101, "invalid_name"),
    ],
)
async def test_user_flow_rejects_invalid_settings(
    hass: HomeAssistant, field: str, value: str | float, error: str
) -> None:
    """Name, threshold, and hysteresis validation is finite and bounded."""
    _set_sources(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {field: value, CONF_SOURCE_TYPE: SOURCE_TYPE_SENSORS},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}


def test_internal_validation_contains_schema_bypass_values(hass: HomeAssistant) -> None:
    """Defensive validation still rejects malformed values if selectors are bypassed."""
    handler = SimpleNamespace(parent_handler=SimpleNamespace(hass=hass))
    hass.states.async_set(
        "input_number.temperature",
        "20",
        {ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS},
    )

    with pytest.raises(SchemaFlowError):
        _resolve_source(handler, "not-an-entity", "invalid_temperature_sensor")
    with pytest.raises(SchemaFlowError):
        _resolve_source(
            handler, "input_number.temperature", "invalid_temperature_sensor"
        )
    with pytest.raises(SchemaFlowError):
        _validate_finite_range(
            "not-a-number", -20, 20, "invalid_condensation_threshold"
        )
    with pytest.raises(SchemaFlowError):
        _validate_finite_range(21, -20, 20, "invalid_condensation_threshold")
    with pytest.raises(SchemaFlowError):
        _validate_finite_range(float("inf"), 0, 20, "invalid_hysteresis")


async def test_user_flow_contains_temperature_conversion_errors(
    hass: HomeAssistant,
) -> None:
    """A conversion failure becomes a form error instead of escaping the flow."""
    _set_sources(hass)
    result = await _start_sensor_flow(hass)

    with patch(
        "custom_components.dew_point.config_flow.TemperatureConverter.convert",
        side_effect=ValueError,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], _sensor_input()
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_temperature_sensor"}


async def test_user_flow_accepts_registered_unavailable_sources(
    hass: HomeAssistant,
) -> None:
    """Compatible registry metadata allows setup before source states load."""
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "sensor",
        "test",
        "temperature",
        suggested_object_id="registered_temperature",
        original_device_class=SensorDeviceClass.TEMPERATURE,
        unit_of_measurement=UnitOfTemperature.KELVIN,
    )
    registry.async_get_or_create(
        "sensor",
        "test",
        "humidity",
        suggested_object_id="registered_humidity",
        original_device_class=SensorDeviceClass.HUMIDITY,
        unit_of_measurement=PERCENTAGE,
    )
    result = await _start_sensor_flow(hass, name="Registered sources")
    user_input = {
        CONF_TEMPERATURE_SENSOR: "sensor.registered_temperature",
        CONF_HUMIDITY_SENSOR: "sensor.registered_humidity",
        CONF_CONDENSATION_THRESHOLD: DEFAULT_CONDENSATION_THRESHOLD,
        CONF_HYSTERESIS: DEFAULT_HYSTERESIS,
    }

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
