"""GUI-baserad konfiguration för Dew Point-integrationen."""
import logging
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
)
import homeassistant.helpers.config_validation as cv

from . import DOMAIN

_LOGGER = logging.getLogger(__name__)


class DewpointConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Hantera ett konfigurationsflöde för Dew Point."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Steg 1 i konfigurationsflödet."""
        errors = {}

        if user_input is not None:
            # Användaren klickar "Skicka"
            return self.async_create_entry(
                title=user_input["name"],
                data={
                    "name": user_input["name"],
                    "temperature_sensor": user_input["temperature_sensor"],
                    "humidity_sensor": user_input["humidity_sensor"],
                },
            )

        data_schema = vol.Schema(
            {
                vol.Required("name"): cv.string,
                vol.Required("temperature_sensor"): EntitySelector(
                    EntitySelectorConfig(domain="sensor")
                ),
                vol.Required("humidity_sensor"): EntitySelector(
                    EntitySelectorConfig(domain="sensor")
                ),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors
        )
