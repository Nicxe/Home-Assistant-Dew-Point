"""Init file for the Dew Point integration."""
from homeassistant.config_entries import ConfigEntry, OptionsFlow
from homeassistant.core import HomeAssistant
from homeassistant.const import Platform

DOMAIN = "dew_point"
PLATFORMS = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Load this integration from a config entry."""
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload this integration."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
    """Create and return an options flow for this config entry."""
    from .config_flow import DewpointOptionsFlowHandler
    return DewpointOptionsFlowHandler(config_entry)
