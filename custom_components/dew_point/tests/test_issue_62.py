"""Regression tests for issue 62."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any
from unittest.mock import AsyncMock, patch

from homeassistant import const as ha_const
from homeassistant.const import CONF_NAME
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components import dew_point
from custom_components.dew_point import sensor
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


def _entry() -> MockConfigEntry:
    """Return a configured sensor-based helper."""
    return MockConfigEntry(
        domain=dew_point.DOMAIN,
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


async def test_setup_uses_supported_source_change_api(hass) -> None:
    """Setup must not pass the source change argument removed in HA 2027.8."""
    entry = _entry()
    entry.add_to_hass(hass)

    def async_handle_source_entity_changes(
        _hass,
        *,
        helper_config_entry_id: str,
        set_source_entity_id_or_uuid: Callable[[str], None],
        source_device_id: str | None,
        source_entity_id_or_uuid: str,
        source_entity_removed: Callable[[], Coroutine[Any, Any, None]] | None = None,
    ) -> Callable[[], None]:
        """Model the Home Assistant 2027.8 source change API."""
        return lambda: None

    with (
        patch(
            "custom_components.dew_point.async_handle_source_entity_changes",
            side_effect=async_handle_source_entity_changes,
        ) as source_change_handler,
        patch.object(
            hass.config_entries,
            "async_forward_entry_setups",
            new=AsyncMock(),
        ),
    ):
        assert await dew_point.async_setup_entry(hass, entry) is True

    assert source_change_handler.call_count == 2
    entry.runtime_data.async_stop()


def test_absolute_humidity_uses_supported_density_unit() -> None:
    """The sensor module must not import the density constant removed in HA 2027.8."""
    description = next(
        description
        for description in sensor.SENSOR_DESCRIPTIONS
        if description.key == "absolute_humidity"
    )

    assert not hasattr(sensor, "CONCENTRATION_GRAMS_PER_CUBIC_METER")
    if unit_of_density := getattr(ha_const, "UnitOfDensity", None):
        assert (
            description.native_unit_of_measurement
            == unit_of_density.GRAMS_PER_CUBIC_METER
        )
    else:
        assert description.native_unit_of_measurement == "g/m³"
