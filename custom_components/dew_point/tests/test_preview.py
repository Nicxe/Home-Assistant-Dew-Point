"""Tests for the live Dew Point configuration preview."""

from __future__ import annotations

from unittest.mock import Mock, patch

from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT,
    PERCENTAGE,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dew_point.config_flow import CONFIG_FLOW, OPTIONS_FLOW
from custom_components.dew_point.const import (
    CONF_CONDENSATION_THRESHOLD,
    CONF_HUMIDITY_SENSOR,
    CONF_SURFACE_TEMPERATURE_SENSOR,
    CONF_TEMPERATURE_SENSOR,
    DOMAIN,
)
from custom_components.dew_point.preview import (
    ATTR_ABSOLUTE_HUMIDITY,
    ATTR_AVAILABLE,
    ATTR_CONDENSATION_RISK,
    ATTR_CONDENSATION_THRESHOLD,
    ATTR_SURFACE_DEW_POINT_MARGIN,
    DewPointPreview,
    _flow_options,
    async_setup_preview,
    ws_start_preview,
)


def _set_sources(hass: HomeAssistant) -> None:
    """Set preview source states."""
    hass.states.async_set(
        "sensor.temperature",
        "68",
        {ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.FAHRENHEIT},
    )
    hass.states.async_set(
        "sensor.humidity",
        "50",
        {ATTR_UNIT_OF_MEASUREMENT: PERCENTAGE},
    )
    hass.states.async_set(
        "sensor.surface",
        "50",
        {ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.FAHRENHEIT},
    )


def _options() -> dict[str, str]:
    """Return preview source options."""
    return {
        CONF_TEMPERATURE_SENSOR: "sensor.temperature",
        CONF_HUMIDITY_SENSOR: "sensor.humidity",
        CONF_SURFACE_TEMPERATURE_SENSOR: "sensor.surface",
    }


async def test_preview_publishes_and_tracks_sources(hass: HomeAssistant) -> None:
    """The preview reports all derived values and follows live source updates."""
    _set_sources(hass)
    update = Mock()
    preview = DewPointPreview(hass, _options(), update)

    unsubscribe = preview.async_start()

    state, attributes = update.call_args.args
    assert float(state) == pytest.approx(9.27, abs=0.02)
    assert attributes[ATTR_AVAILABLE] is True
    assert attributes[ATTR_ABSOLUTE_HUMIDITY] == pytest.approx(8.64, abs=0.03)
    assert attributes[ATTR_SURFACE_DEW_POINT_MARGIN] == pytest.approx(0.73, abs=0.03)
    assert attributes[ATTR_CONDENSATION_THRESHOLD] == 0
    assert attributes[ATTR_CONDENSATION_RISK] is False

    hass.states.async_set(
        "sensor.humidity",
        "60",
        {ATTR_UNIT_OF_MEASUREMENT: PERCENTAGE},
    )
    await hass.async_block_till_done()

    assert update.call_count == 2
    assert float(update.call_args.args[0]) > float(state)

    unsubscribe()
    hass.states.async_set(
        "sensor.humidity",
        "65",
        {ATTR_UNIT_OF_MEASUREMENT: PERCENTAGE},
    )
    await hass.async_block_till_done()
    assert update.call_count == 2


async def test_preview_handles_partial_and_invalid_input(hass: HomeAssistant) -> None:
    """A partially completed form produces an unknown preview without errors."""
    update = Mock()
    preview = DewPointPreview(
        hass,
        {
            CONF_TEMPERATURE_SENSOR: "not-an-entity",
            CONF_HUMIDITY_SENSOR: "sensor.missing",
        },
        update,
    )

    unsubscribe = preview.async_start()

    assert update.call_args.args[0] == STATE_UNKNOWN
    assert update.call_args.args[1][ATTR_AVAILABLE] is False
    unsubscribe()

    no_source_update = Mock()
    no_source_unsubscribe = DewPointPreview(hass, {}, no_source_update).async_start()
    no_source_unsubscribe()
    assert no_source_update.call_args.args[0] == STATE_UNKNOWN


async def test_preview_rejects_invalid_live_values(hass: HomeAssistant) -> None:
    """Non-finite, out-of-range, and incompatible readings stay unknown."""
    hass.states.async_set(
        "sensor.temperature",
        "nan",
        {ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS},
    )
    hass.states.async_set(
        "sensor.humidity",
        "101",
        {ATTR_UNIT_OF_MEASUREMENT: PERCENTAGE},
    )
    update = Mock()

    DewPointPreview(hass, _options(), update).async_refresh()

    assert update.call_args.args[0] == STATE_UNAVAILABLE


async def test_preview_is_declared_and_registers_websocket(
    hass: HomeAssistant,
) -> None:
    """Both flow forms expose the integration's registered preview command."""
    assert CONFIG_FLOW["user"].preview == DOMAIN
    assert OPTIONS_FLOW["init"].preview == DOMAIN

    with patch(
        "custom_components.dew_point.preview.websocket_api.async_register_command"
    ) as register:
        await async_setup_preview(hass)

    register.assert_called_once()


async def test_websocket_preview_sends_result_event_and_cleanup(
    hass: HomeAssistant,
) -> None:
    """The WebSocket command delivers the current value and a live subscription."""
    _set_sources(hass)
    connection = Mock()
    connection.subscriptions = {}
    msg = {
        "id": 7,
        "type": f"{DOMAIN}/start_preview",
        "flow_id": "unused-by-patched-options",
        "flow_type": "config_flow",
        "user_input": _options(),
    }

    with patch(
        "custom_components.dew_point.preview._flow_options",
        return_value=_options(),
    ):
        ws_start_preview(hass, connection, msg)

    connection.send_result.assert_called_once_with(7)
    event = connection.send_message.call_args.args[0]
    assert event["id"] == 7
    assert float(event["event"]["state"]) == pytest.approx(9.27, abs=0.02)
    connection.subscriptions[7]()


async def test_flow_options_merges_only_options_flow_changes(
    hass: HomeAssistant,
) -> None:
    """Config previews use form data while options previews merge saved settings."""
    config_message = {
        "flow_id": "config-flow",
        "flow_type": "config_flow",
        "user_input": _options(),
    }
    with patch.object(hass.config_entries.flow, "async_get", return_value={}):
        assert _flow_options(hass, config_message) == _options()

    entry_options = {**_options(), "name": "Saved"}
    entry = MockConfigEntry(domain=DOMAIN, title="Saved", options=entry_options)
    entry.add_to_hass(hass)
    options_message = {
        "flow_id": "options-flow",
        "flow_type": "options_flow",
        "user_input": {CONF_HUMIDITY_SENSOR: "sensor.new_humidity"},
    }
    with patch.object(
        hass.config_entries.options,
        "async_get",
        return_value={"handler": entry.entry_id},
    ):
        merged = _flow_options(hass, options_message)

    assert merged[CONF_TEMPERATURE_SENSOR] == "sensor.temperature"
    assert merged[CONF_HUMIDITY_SENSOR] == "sensor.new_humidity"
    assert CONF_SURFACE_TEMPERATURE_SENSOR not in merged


async def test_preview_reader_error_branches(hass: HomeAssistant) -> None:
    """Preview readers safely ignore unavailable and unconvertible source states."""
    preview = DewPointPreview(hass, {}, Mock())
    hass.states.async_set(
        "sensor.temperature",
        STATE_UNKNOWN,
        {ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS},
    )
    hass.states.async_set(
        "sensor.humidity", STATE_UNKNOWN, {ATTR_UNIT_OF_MEASUREMENT: PERCENTAGE}
    )
    assert preview._temperature("sensor.temperature") is None  # noqa: SLF001
    assert preview._humidity("sensor.humidity") is None  # noqa: SLF001

    hass.states.async_set(
        "sensor.temperature",
        "20",
        {ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS},
    )
    with patch(
        "custom_components.dew_point.preview.TemperatureConverter.convert",
        side_effect=ValueError,
    ):
        assert preview._temperature("sensor.temperature") is None  # noqa: SLF001

    hass.states.async_set(
        "sensor.humidity", "not-a-number", {ATTR_UNIT_OF_MEASUREMENT: PERCENTAGE}
    )
    assert preview._humidity("sensor.humidity") is None  # noqa: SLF001


async def test_preview_uses_configured_condensation_threshold(
    hass: HomeAssistant,
) -> None:
    """The initial risk preview applies the form's current surface threshold."""
    _set_sources(hass)
    update = Mock()
    DewPointPreview(
        hass,
        {**_options(), CONF_CONDENSATION_THRESHOLD: 1.0},
        update,
    ).async_refresh()

    assert update.call_args.args[1][ATTR_CONDENSATION_RISK] is True
