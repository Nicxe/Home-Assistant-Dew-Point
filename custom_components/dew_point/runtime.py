"""Shared event-driven runtime for the Dew Point integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
import logging
import math

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_DEVICE_CLASS,
    ATTR_UNIT_OF_MEASUREMENT,
    CONF_NAME,
    PERCENTAGE,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfTemperature,
)
from homeassistant.core import (
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util.unit_conversion import TemperatureConverter

from .calculation import MoistAirProperties, calculate_moist_air_properties
from .const import (
    CONF_CONDENSATION_THRESHOLD,
    CONF_DECIMAL_PLACES,
    CONF_HUMIDITY_SENSOR,
    CONF_HYSTERESIS,
    CONF_OUTPUT_UNIT,
    CONF_SURFACE_TEMPERATURE_SENSOR,
    CONF_TEMPERATURE_SENSOR,
    DEFAULT_CONDENSATION_THRESHOLD,
    DEFAULT_DECIMAL_PLACES,
    DEFAULT_HYSTERESIS,
    OUTPUT_UNIT_AUTO,
    OUTPUT_UNIT_CELSIUS,
    OUTPUT_UNIT_FAHRENHEIT,
)
from .repairs import SourceIssueType, async_update_source_issue

_LOGGER = logging.getLogger(__name__)

type RuntimeListener = Callable[[], None]


class SourceStatus(StrEnum):
    """Current validation status for a configured source."""

    OK = "ok"
    UNAVAILABLE = "unavailable"
    MISSING = "missing"
    INCOMPATIBLE = "incompatible"


@dataclass(frozen=True, slots=True)
class SourceReading:
    """Normalized reading and metadata for one source."""

    status: SourceStatus
    value: float | None = None
    native_value: float | None = None
    native_unit: str | None = None


@dataclass(frozen=True, slots=True)
class DewPointRuntimeData:
    """One internally consistent snapshot shared by all entities."""

    properties: MoistAirProperties | None = None
    temperature_native_value: float | None = None
    temperature_native_unit: str | None = None
    humidity_percent: float | None = None
    surface_temperature_c: float | None = None
    surface_dew_point_margin_c: float | None = None
    condensation_risk: bool | None = None
    available: bool = False
    surface_available: bool = False


class DewPointRuntime:
    """Validate source states and calculate all derived values once per update."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the runtime from canonical config-entry options."""
        self.hass = hass
        self.entry = entry
        self.name = str(entry.options.get(CONF_NAME, entry.title))
        self.temperature_entity_id = str(entry.options[CONF_TEMPERATURE_SENSOR])
        self.humidity_entity_id = str(entry.options[CONF_HUMIDITY_SENSOR])
        surface = entry.options.get(CONF_SURFACE_TEMPERATURE_SENSOR)
        self.surface_temperature_entity_id = str(surface) if surface else None
        self.condensation_threshold = float(
            entry.options.get(
                CONF_CONDENSATION_THRESHOLD, DEFAULT_CONDENSATION_THRESHOLD
            )
        )
        self.hysteresis = float(entry.options.get(CONF_HYSTERESIS, DEFAULT_HYSTERESIS))
        self.legacy_compatibility = any(
            key in entry.options for key in (CONF_DECIMAL_PLACES, CONF_OUTPUT_UNIT)
        )
        self.legacy_decimal_places = _bounded_int(
            entry.options.get(CONF_DECIMAL_PLACES), DEFAULT_DECIMAL_PLACES, 0, 15
        )
        configured_output_unit = entry.options.get(CONF_OUTPUT_UNIT, OUTPUT_UNIT_AUTO)
        self.legacy_output_unit = (
            configured_output_unit
            if configured_output_unit
            in (OUTPUT_UNIT_AUTO, OUTPUT_UNIT_CELSIUS, OUTPUT_UNIT_FAHRENHEIT)
            else OUTPUT_UNIT_AUTO
        )

        self.data = DewPointRuntimeData()
        self.source_statuses: dict[str, SourceStatus] = {}
        self._listeners: set[RuntimeListener] = set()
        self._unsub_state_listener: Callable[[], None] | None = None
        self._active_issues: dict[str, SourceIssueType | None] = {}
        self._logged_problem_signature: tuple[tuple[str, SourceStatus], ...] = ()

    @callback
    def async_start(self) -> None:
        """Subscribe to source changes and publish the initial snapshot."""
        if self._unsub_state_listener is not None:
            return

        self._unsub_state_listener = async_track_state_change_event(
            self.hass,
            self.source_entity_ids,
            self._async_source_state_changed,
        )
        self.async_refresh()

    @callback
    def async_stop(self) -> None:
        """Unsubscribe from source events."""
        if self._unsub_state_listener is not None:
            self._unsub_state_listener()
            self._unsub_state_listener = None
        self._listeners.clear()

    @property
    def source_entity_ids(self) -> tuple[str, ...]:
        """Return configured source entity IDs."""
        sources = [self.temperature_entity_id, self.humidity_entity_id]
        if self.surface_temperature_entity_id is not None:
            sources.append(self.surface_temperature_entity_id)
        return tuple(dict.fromkeys(sources))

    @callback
    def async_add_listener(self, listener: RuntimeListener) -> Callable[[], None]:
        """Register an entity listener and return its unsubscribe callback."""
        self._listeners.add(listener)

        @callback
        def async_remove_listener() -> None:
            self._listeners.discard(listener)

        return async_remove_listener

    @callback
    def _async_source_state_changed(self, _event: Event[EventStateChangedData]) -> None:
        """Refresh all calculations after a source state change."""
        self.async_refresh()

    @callback
    def async_refresh(self) -> None:
        """Read source states, update Repairs, and notify entities on change."""
        temperature = self._read_temperature(
            CONF_TEMPERATURE_SENSOR, self.temperature_entity_id
        )
        humidity = self._read_humidity(self.humidity_entity_id)
        readings: dict[str, SourceReading] = {
            CONF_TEMPERATURE_SENSOR: temperature,
            CONF_HUMIDITY_SENSOR: humidity,
        }

        surface = SourceReading(SourceStatus.UNAVAILABLE)
        if self.surface_temperature_entity_id is not None:
            surface = self._read_temperature(
                CONF_SURFACE_TEMPERATURE_SENSOR,
                self.surface_temperature_entity_id,
            )
            readings[CONF_SURFACE_TEMPERATURE_SENSOR] = surface

        properties: MoistAirProperties | None = None
        if (
            temperature.status is SourceStatus.OK
            and temperature.value is not None
            and humidity.status is SourceStatus.OK
            and humidity.value is not None
        ):
            properties = calculate_moist_air_properties(
                temperature.value, humidity.value
            )
            if properties is None:
                temperature = SourceReading(
                    SourceStatus.INCOMPATIBLE,
                    native_value=temperature.native_value,
                    native_unit=temperature.native_unit,
                )
                readings[CONF_TEMPERATURE_SENSOR] = temperature

        margin: float | None = None
        if (
            properties is not None
            and properties.dew_point_c is not None
            and surface.status is SourceStatus.OK
            and surface.value is not None
        ):
            candidate_margin = surface.value - properties.dew_point_c
            if math.isfinite(candidate_margin):
                margin = candidate_margin

        condensation_risk = self._condensation_risk(margin)
        new_data = DewPointRuntimeData(
            properties=properties,
            temperature_native_value=temperature.native_value,
            temperature_native_unit=temperature.native_unit,
            humidity_percent=humidity.value,
            surface_temperature_c=surface.value,
            surface_dew_point_margin_c=margin,
            condensation_risk=condensation_risk,
            available=properties is not None,
            surface_available=(
                self.surface_temperature_entity_id is not None
                and surface.status is SourceStatus.OK
                and properties is not None
            ),
        )
        new_statuses = {key: reading.status for key, reading in readings.items()}

        self._update_source_issues(readings)
        self._log_status_transition(new_statuses)

        if new_data == self.data and new_statuses == self.source_statuses:
            return
        self.data = new_data
        self.source_statuses = new_statuses
        for listener in tuple(self._listeners):
            listener()

    def _read_temperature(self, source_key: str, entity_id: str) -> SourceReading:
        """Read and normalize one temperature source to Celsius."""
        state = self.hass.states.get(entity_id)
        if state is None:
            return SourceReading(self._missing_or_unavailable(entity_id))
        if state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return SourceReading(SourceStatus.UNAVAILABLE)
        if not self._has_expected_device_class(state, SensorDeviceClass.TEMPERATURE):
            return SourceReading(SourceStatus.INCOMPATIBLE)

        native_value = _finite_float(state.state)
        unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
        if native_value is None or unit not in TemperatureConverter.VALID_UNITS:
            return SourceReading(SourceStatus.INCOMPATIBLE)
        try:
            value_c = TemperatureConverter.convert(
                native_value, unit, UnitOfTemperature.CELSIUS
            )
        except (TypeError, ValueError):
            return SourceReading(SourceStatus.INCOMPATIBLE)
        if not math.isfinite(value_c):
            return SourceReading(SourceStatus.INCOMPATIBLE)
        return SourceReading(
            SourceStatus.OK,
            value=value_c,
            native_value=native_value,
            native_unit=unit,
        )

    def _read_humidity(self, entity_id: str) -> SourceReading:
        """Read and validate a relative-humidity source in percent."""
        state = self.hass.states.get(entity_id)
        if state is None:
            return SourceReading(self._missing_or_unavailable(entity_id))
        if state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return SourceReading(SourceStatus.UNAVAILABLE)
        if not self._has_expected_device_class(state, SensorDeviceClass.HUMIDITY):
            return SourceReading(SourceStatus.INCOMPATIBLE)
        if state.attributes.get(ATTR_UNIT_OF_MEASUREMENT) != PERCENTAGE:
            return SourceReading(SourceStatus.INCOMPATIBLE)

        value = _finite_float(state.state)
        if value is None or not 0.0 <= value <= 100.0:
            return SourceReading(SourceStatus.INCOMPATIBLE)
        return SourceReading(
            SourceStatus.OK,
            value=value,
            native_value=value,
            native_unit=PERCENTAGE,
        )

    def _has_expected_device_class(
        self, state: State, expected: SensorDeviceClass
    ) -> bool:
        """Return whether state/registry metadata is compatible."""
        device_class = state.attributes.get(ATTR_DEVICE_CLASS)
        if device_class is None:
            registry_entry = er.async_get(self.hass).async_get(state.entity_id)
            if registry_entry is not None:
                device_class = (
                    registry_entry.device_class or registry_entry.original_device_class
                )
        return device_class in (None, expected)

    def _missing_or_unavailable(self, entity_id: str) -> SourceStatus:
        """Distinguish a removed source from a registered source not loaded yet."""
        return (
            SourceStatus.UNAVAILABLE
            if er.async_get(self.hass).async_get(entity_id) is not None
            else SourceStatus.MISSING
        )

    def _condensation_risk(self, margin: float | None) -> bool | None:
        """Apply threshold and hysteresis to the optional surface margin."""
        if margin is None:
            return None
        previous = self.data.condensation_risk
        if previous is True:
            return margin < self.condensation_threshold + self.hysteresis
        return margin <= self.condensation_threshold

    @callback
    def _update_source_issues(self, readings: dict[str, SourceReading]) -> None:
        """Create only persistent, user-actionable source issues."""
        source_ids = {
            CONF_TEMPERATURE_SENSOR: self.temperature_entity_id,
            CONF_HUMIDITY_SENSOR: self.humidity_entity_id,
            CONF_SURFACE_TEMPERATURE_SENSOR: self.surface_temperature_entity_id,
        }
        for source_key, reading in readings.items():
            issue_type = {
                SourceStatus.MISSING: SourceIssueType.MISSING,
                SourceStatus.INCOMPATIBLE: SourceIssueType.INCOMPATIBLE,
            }.get(reading.status)
            if (
                source_key in self._active_issues
                and self._active_issues[source_key] is issue_type
            ):
                continue
            async_update_source_issue(
                self.hass,
                self.entry,
                source_key,
                issue_type,
                entity_id=source_ids[source_key],
            )
            self._active_issues[source_key] = issue_type

    def _log_status_transition(self, statuses: dict[str, SourceStatus]) -> None:
        """Log source problems once and recovery once."""
        problem_signature = tuple(
            sorted(
                (source_key, status)
                for source_key, status in statuses.items()
                if status is not SourceStatus.OK
            )
        )
        if problem_signature == self._logged_problem_signature:
            return
        if problem_signature and not self._logged_problem_signature:
            _LOGGER.warning(
                "Source validation failed for %s: %s",
                self.entry.title,
                ", ".join(
                    f"{source_key}={status.value}"
                    for source_key, status in problem_signature
                ),
            )
        elif not problem_signature and self._logged_problem_signature:
            _LOGGER.info("Sources recovered for %s", self.entry.title)
        self._logged_problem_signature = problem_signature


def _finite_float(value: object) -> float | None:
    """Return a finite float or None."""
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _bounded_int(value: object, default: int, minimum: int, maximum: int) -> int:
    """Return an integer constrained to the legacy compatibility range."""
    if not isinstance(value, (str, int, float)):
        return default
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return max(minimum, min(maximum, result))
