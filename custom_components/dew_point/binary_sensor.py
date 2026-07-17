"""Binary sensor entities for the Dew Point integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .runtime import DewPointRuntime


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up condensation-risk binary sensor when a surface source exists."""
    runtime: DewPointRuntime = entry.runtime_data
    if runtime.surface_temperature_entity_id is None:
        return
    async_add_entities([DewPointCondensationRiskSensor(runtime, entry.entry_id)])


class DewPointCondensationRiskSensor(BinarySensorEntity):
    """Indicate whether the configured surface is at condensation risk."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_has_entity_name = True
    _attr_icon = "mdi:water-alert-outline"
    _attr_should_poll = False
    _attr_translation_key = "condensation_risk"

    def __init__(self, runtime: DewPointRuntime, entry_id: str) -> None:
        """Initialize the binary sensor."""
        self.runtime = runtime
        self._attr_unique_id = f"{entry_id}_condensation_risk"
        self._attr_translation_placeholders = {"name": runtime.name}

    @property
    def available(self) -> bool:
        """Return whether surface and atmospheric data are available."""
        return self.runtime.data.surface_available

    @property
    def is_on(self) -> bool | None:
        """Return the current hysteresis-controlled risk state."""
        return self.runtime.data.condensation_risk

    async def async_added_to_hass(self) -> None:
        """Subscribe to the shared runtime after entity registration."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.runtime.async_add_listener(self._async_runtime_updated)
        )

    @callback
    def _async_runtime_updated(self) -> None:
        """Write the latest in-memory value to Home Assistant."""
        self.async_write_ha_state()
