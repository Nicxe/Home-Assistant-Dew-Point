"""Init-fil för Dew Point-integrationen."""
import asyncio

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

DOMAIN = "dew_point"
PLATFORMS = ["sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Ladda denna integration från en config entry."""
    # För kompatibilitet med olika versioner av Home Assistant
    hass.async_create_task(
        hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Avlasta denna integration."""
    return await hass.config_entries.async_forward_entry_unload(entry, PLATFORMS)
