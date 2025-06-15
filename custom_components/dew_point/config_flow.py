"""GUI-based configuration for the Dew Point integration."""
import logging
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import OptionsFlowWithConfigEntry
from homeassistant.const import CONF_NAME
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
)

from . import DOMAIN

_LOGGER = logging.getLogger(__name__)

CONF_TEMPERATURE_SENSOR = "temperature_sensor"
CONF_HUMIDITY_SENSOR = "humidity_sensor"
CONF_DECIMAL_PLACES = "decimal_places"

DEFAULT_NAME = "Dew Point"


class DewpointConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handles the initial installation of Dew Point."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Configuration step when the user installs the integration for the first time."""
        errors = {}

        if user_input is not None:
            decimal_places = int(user_input[CONF_DECIMAL_PLACES])

            return self.async_create_entry(
                title=user_input.get(CONF_NAME, DEFAULT_NAME),
                data={
                    CONF_NAME: user_input.get(CONF_NAME, DEFAULT_NAME),
                    CONF_TEMPERATURE_SENSOR: user_input[CONF_TEMPERATURE_SENSOR],
                    CONF_HUMIDITY_SENSOR: user_input[CONF_HUMIDITY_SENSOR],
                    CONF_DECIMAL_PLACES: decimal_places,
                },
            )

        data_schema = vol.Schema(
            {
                vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
                vol.Required(CONF_TEMPERATURE_SENSOR): EntitySelector(
                    EntitySelectorConfig(domain="sensor", device_class="temperature")
                ),
                vol.Required(CONF_HUMIDITY_SENSOR): EntitySelector(
                    EntitySelectorConfig(domain="sensor", device_class="humidity")
                ),
                vol.Required(CONF_DECIMAL_PLACES, default=1): NumberSelector(
                    NumberSelectorConfig(
                        min=0,
                        max=15,
                        step=1,  # Only integers
                        mode="box",
                        unit_of_measurement="decimals"
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors
        )

    @staticmethod
    def async_get_options_flow(config_entry):
        """Enable the 'Configure' button and point to our OptionsFlow class."""
        return DewpointOptionsFlowHandler(config_entry)


class DewpointOptionsFlowHandler(OptionsFlowWithConfigEntry):
 
    async def async_step_init(self, user_input=None):
        """Displayed when the user presses 'Configure' for an already installed integration."""
        if user_input is not None:
            decimal_places = int(user_input[CONF_DECIMAL_PLACES])

            return self.async_create_entry(
                title="",
                data={
                    CONF_TEMPERATURE_SENSOR: user_input[CONF_TEMPERATURE_SENSOR],
                    CONF_HUMIDITY_SENSOR: user_input[CONF_HUMIDITY_SENSOR],
                    CONF_DECIMAL_PLACES: decimal_places,
                },
            )

        # Now we access config_entry via self._config_entry
        data = dict(self._config_entry.data)
        options = dict(self._config_entry.options)

        temperature_sensor = options.get(
            CONF_TEMPERATURE_SENSOR, data.get(CONF_TEMPERATURE_SENSOR)
        )
        humidity_sensor = options.get(
            CONF_HUMIDITY_SENSOR, data.get(CONF_HUMIDITY_SENSOR)
        )
        decimal_places = options.get(
            CONF_DECIMAL_PLACES, data.get(CONF_DECIMAL_PLACES, 1)
        )

        schema = vol.Schema(
            {
                vol.Required(CONF_TEMPERATURE_SENSOR, default=temperature_sensor): EntitySelector(
                    EntitySelectorConfig(domain="sensor", device_class="temperature")
                ),
                vol.Required(CONF_HUMIDITY_SENSOR, default=humidity_sensor): EntitySelector(
                    EntitySelectorConfig(domain="sensor",  device_class="humidity")
                ),
                vol.Required(CONF_DECIMAL_PLACES, default=decimal_places): NumberSelector(
                    NumberSelectorConfig(
                        min=0,
                        max=15,
                        step=1,
                        mode="box",
                        unit_of_measurement="decimals"
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            errors={},
        )
