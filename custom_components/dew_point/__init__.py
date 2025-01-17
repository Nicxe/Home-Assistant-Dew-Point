"""Init-fil för Dew Point-integrationen."""
from homeassistant.config_entries import ConfigEntry, OptionsFlow
from homeassistant.core import HomeAssistant

DOMAIN = "dew_point"
PLATFORMS = ["sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Ladda denna integration från en config entry."""
    hass.async_create_task(
        hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Avlasta denna integration."""
    return await hass.config_entries.async_forward_entry_unload(entry, PLATFORMS)


async def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
    """Skapa och returnera en options flow för denna konfigurationsentry."""
    from .config_flow import DewpointOptionsFlowHandler
    return DewpointOptionsFlowHandler(config_entry)