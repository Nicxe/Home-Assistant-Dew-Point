"""GUI-baserad konfiguration för Dew Point-integrationen."""
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
    """Hanterar första installationen av Dew Point."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Konfigurationssteg när användaren installerar integrationen första gången."""
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
                    EntitySelectorConfig(domain="sensor")
                ),
                vol.Required(CONF_HUMIDITY_SENSOR): EntitySelector(
                    EntitySelectorConfig(domain="sensor")
                ),
                vol.Required(CONF_DECIMAL_PLACES, default=1): NumberSelector(
                    NumberSelectorConfig(
                        min=0,
                        max=15,
                        step=1,  # Endast heltal
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
        """Aktivera 'Konfigurera'-knappen och peka på vår OptionsFlow-klass."""
        return DewpointOptionsFlowHandler(config_entry)


class DewpointOptionsFlowHandler(OptionsFlowWithConfigEntry):
    """
    Options flow för en befintlig Dew Point-instans.
    Ärver från OptionsFlowWithConfigEntry för att slippa explicit self.config_entry.
    """

    async def async_step_init(self, user_input=None):
        """Visas när användaren trycker på 'Konfigurera' för en redan installerad integration."""
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

        # Nu når vi config_entry via self._config_entry
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
                    EntitySelectorConfig(domain="sensor")
                ),
                vol.Required(CONF_HUMIDITY_SENSOR, default=humidity_sensor): EntitySelector(
                    EntitySelectorConfig(domain="sensor")
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