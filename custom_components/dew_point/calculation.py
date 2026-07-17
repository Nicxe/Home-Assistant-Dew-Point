"""Numerically robust psychrometric calculations based on Buck (1996).

All temperatures accepted and returned by this module are in degrees Celsius,
relative humidity is expressed in percent, vapor pressures are in kPa, and
absolute humidity is in g/m³.

The Buck equations are empirical approximations for a plane surface of pure
water or ice. This implementation deliberately limits them to the
meteorological range from -80 to 50 °C described by Buck. The ice relation is
further limited to -80 to 0 °C so that a frost point is never silently
presented as a liquid-water dew point. No pressure enhancement factor is
applied because the integration has no atmospheric-pressure input.

Reference: A. L. Buck, "New Equations for Computing Vapor Pressure and
Enhancement Factor", Journal of Applied Meteorology, 20 (1981), 1527-1532,
with the coefficient update published in the Buck Research CR-1A manual
(1996).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import math
from typing import Literal

type VaporPressureSurface = Literal["water", "ice"]

MIN_BUCK_TEMPERATURE_C = -80.0
MAX_WATER_TEMPERATURE_C = 50.0
MAX_ICE_TEMPERATURE_C = 0.0

_KELVIN_OFFSET = 273.15
_MOLAR_MASS_WATER_KG_PER_MOL = 0.01801528
_UNIVERSAL_GAS_CONSTANT_J_PER_MOL_K = 8.31446261815324
_INVERSION_ITERATIONS = 80


@dataclass(frozen=True, slots=True)
class MoistAirProperties:
    """Consistent set of properties derived from one input sample.

    ``frost_point_c`` is ``None`` when the vapor pressure has no root in the
    physically supported ice range. At zero relative humidity, dew point,
    frost point, and dew point spread are undefined and therefore ``None``;
    pressure and absolute humidity correctly remain zero.
    """

    air_temperature_c: float
    relative_humidity: float
    humidity_reference: VaporPressureSurface
    saturation_vapor_pressure_kpa: float
    actual_vapor_pressure_kpa: float
    vapor_pressure_deficit_kpa: float
    dew_point_c: float | None
    dew_point_spread_c: float | None
    absolute_humidity_g_m3: float
    frost_point_c: float | None


def saturation_vapor_pressure_water(temperature_c: float) -> float | None:
    """Return saturation vapor pressure over water in kPa.

    The liquid-water relation is valid from -80 through 50 °C. Below 0 °C,
    it describes a plane surface of supercooled liquid water, not ice.
    Non-finite or out-of-range input returns ``None``.
    """

    temperature = _finite_float(temperature_c)
    if temperature is None or not (
        MIN_BUCK_TEMPERATURE_C <= temperature <= MAX_WATER_TEMPERATURE_C
    ):
        return None

    exponent = (18.678 - temperature / 234.5) * (temperature / (257.14 + temperature))
    return _safe_exponential_pressure(0.61121, exponent)


def saturation_vapor_pressure_ice(temperature_c: float) -> float | None:
    """Return saturation vapor pressure over ice in kPa.

    The ice relation is valid from -80 through 0 °C. Values above freezing
    are rejected to keep frost-point semantics explicit. Non-finite or
    out-of-range input returns ``None``.
    """

    temperature = _finite_float(temperature_c)
    if temperature is None or not (
        MIN_BUCK_TEMPERATURE_C <= temperature <= MAX_ICE_TEMPERATURE_C
    ):
        return None

    exponent = (23.036 - temperature / 333.7) * (temperature / (279.82 + temperature))
    return _safe_exponential_pressure(0.61115, exponent)


def actual_vapor_pressure(
    temperature_c: float,
    relative_humidity: float,
    *,
    humidity_reference: VaporPressureSurface = "water",
) -> float | None:
    """Return actual vapor pressure in kPa.

    ``humidity_reference`` declares whether the supplied relative humidity is
    relative to saturation over liquid water or ice. Home humidity sensors
    normally use ``"water"``. Relative humidity must be between 0 and 100 %;
    0 % produces the physically meaningful pressure 0 kPa.
    """

    saturation = _saturation_pressure(temperature_c, humidity_reference)
    humidity_fraction = _humidity_fraction(relative_humidity)
    if saturation is None or humidity_fraction is None:
        return None

    pressure = saturation * humidity_fraction
    return pressure if math.isfinite(pressure) else None


def dew_point(
    temperature_c: float,
    relative_humidity: float,
    *,
    humidity_reference: VaporPressureSurface = "water",
) -> float | None:
    """Return the liquid-water dew point in °C.

    The result numerically inverts the same Buck water equation used to obtain
    vapor pressure, making it self-consistent. In particular, water-referenced
    100 % RH returns the air temperature exactly. A result below -80 °C, zero
    RH, invalid input, or a state outside Buck's valid range returns ``None``.
    """

    temperature = _finite_float(temperature_c)
    humidity_fraction = _humidity_fraction(relative_humidity)
    pressure = actual_vapor_pressure(
        temperature_c,
        relative_humidity,
        humidity_reference=humidity_reference,
    )
    if temperature is None or humidity_fraction is None or pressure is None:
        return None
    if pressure <= 0.0:
        return None
    if humidity_reference == "water" and humidity_fraction == 1.0:
        return temperature

    return _invert_saturation_pressure(
        pressure,
        saturation_vapor_pressure_water,
        MIN_BUCK_TEMPERATURE_C,
        MAX_WATER_TEMPERATURE_C,
    )


def frost_point(
    temperature_c: float,
    relative_humidity: float,
    *,
    humidity_reference: VaporPressureSurface = "water",
) -> float | None:
    """Return the frost point over ice in °C.

    The input RH reference is explicit and defaults to the liquid-water
    convention used by typical sensors. The result is restricted to -80
    through 0 °C. ``None`` means that no frost-point root exists in that
    range, not that a liquid-water dew point should be substituted.
    """

    temperature = _finite_float(temperature_c)
    humidity_fraction = _humidity_fraction(relative_humidity)
    pressure = actual_vapor_pressure(
        temperature_c,
        relative_humidity,
        humidity_reference=humidity_reference,
    )
    if temperature is None or humidity_fraction is None or pressure is None:
        return None
    if pressure <= 0.0:
        return None
    if humidity_reference == "ice" and humidity_fraction == 1.0:
        return temperature

    return _invert_saturation_pressure(
        pressure,
        saturation_vapor_pressure_ice,
        MIN_BUCK_TEMPERATURE_C,
        MAX_ICE_TEMPERATURE_C,
    )


def dew_point_spread(
    temperature_c: float,
    relative_humidity: float,
    *,
    humidity_reference: VaporPressureSurface = "water",
) -> float | None:
    """Return air temperature minus liquid-water dew point in °C.

    Zero humidity has no finite dew point and therefore no finite spread.
    """

    temperature = _finite_float(temperature_c)
    calculated_dew_point = dew_point(
        temperature_c,
        relative_humidity,
        humidity_reference=humidity_reference,
    )
    if temperature is None or calculated_dew_point is None:
        return None

    spread = temperature - calculated_dew_point
    if not math.isfinite(spread):
        return None
    if humidity_reference == "water" and spread < 0.0 and spread > -1e-12:
        return 0.0
    return spread


def absolute_humidity(
    temperature_c: float,
    relative_humidity: float,
    *,
    humidity_reference: VaporPressureSurface = "water",
) -> float | None:
    """Return absolute humidity in g/m³ using the ideal-gas relation.

    Buck supplies vapor pressure and the ideal-gas law converts water-vapor
    partial pressure to density. The supported temperature range is therefore
    inherited from the selected Buck surface. Zero RH returns 0 g/m³.
    """

    temperature = _finite_float(temperature_c)
    pressure_kpa = actual_vapor_pressure(
        temperature_c,
        relative_humidity,
        humidity_reference=humidity_reference,
    )
    if temperature is None or pressure_kpa is None:
        return None

    temperature_kelvin = temperature + _KELVIN_OFFSET
    if temperature_kelvin <= 0.0:
        return None

    density = (
        pressure_kpa
        * 1_000.0
        * _MOLAR_MASS_WATER_KG_PER_MOL
        / (_UNIVERSAL_GAS_CONSTANT_J_PER_MOL_K * temperature_kelvin)
        * 1_000.0
    )
    return density if math.isfinite(density) and density >= 0.0 else None


def vapor_pressure_deficit(
    temperature_c: float,
    relative_humidity: float,
    *,
    humidity_reference: VaporPressureSurface = "water",
) -> float | None:
    """Return vapor pressure deficit in kPa for the selected surface.

    This is saturation pressure minus actual vapor pressure at the air
    temperature. It is zero at 100 % RH and non-negative for valid input.
    """

    saturation = _saturation_pressure(temperature_c, humidity_reference)
    humidity_fraction = _humidity_fraction(relative_humidity)
    if saturation is None or humidity_fraction is None:
        return None

    deficit = saturation * (1.0 - humidity_fraction)
    return deficit if math.isfinite(deficit) and deficit >= 0.0 else None


def calculate_moist_air_properties(
    temperature_c: float,
    relative_humidity: float,
    *,
    humidity_reference: VaporPressureSurface = "water",
) -> MoistAirProperties | None:
    """Return all supported properties for one validated input sample.

    A single immutable result lets all Home Assistant entities publish values
    calculated from the same temperature and humidity snapshot. Invalid base
    input returns ``None``. Individually undefined dew/frost values remain
    ``None`` inside an otherwise valid result.
    """

    temperature = _finite_float(temperature_c)
    humidity = _finite_float(relative_humidity)
    saturation = _saturation_pressure(temperature_c, humidity_reference)
    pressure = actual_vapor_pressure(
        temperature_c,
        relative_humidity,
        humidity_reference=humidity_reference,
    )
    deficit = vapor_pressure_deficit(
        temperature_c,
        relative_humidity,
        humidity_reference=humidity_reference,
    )
    density = absolute_humidity(
        temperature_c,
        relative_humidity,
        humidity_reference=humidity_reference,
    )
    if (
        temperature is None
        or humidity is None
        or saturation is None
        or pressure is None
        or deficit is None
        or density is None
    ):
        return None

    calculated_dew_point = dew_point(
        temperature_c,
        relative_humidity,
        humidity_reference=humidity_reference,
    )
    return MoistAirProperties(
        air_temperature_c=temperature,
        relative_humidity=humidity,
        humidity_reference=humidity_reference,
        saturation_vapor_pressure_kpa=saturation,
        actual_vapor_pressure_kpa=pressure,
        vapor_pressure_deficit_kpa=deficit,
        dew_point_c=calculated_dew_point,
        dew_point_spread_c=(
            None if calculated_dew_point is None else temperature - calculated_dew_point
        ),
        absolute_humidity_g_m3=density,
        frost_point_c=frost_point(
            temperature_c,
            relative_humidity,
            humidity_reference=humidity_reference,
        ),
    )


def _finite_float(value: float) -> float | None:
    """Return a finite float without allowing malformed input to escape."""

    try:
        converted = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return converted if math.isfinite(converted) else None


def _humidity_fraction(relative_humidity: float) -> float | None:
    """Validate percent relative humidity and return a 0..1 fraction."""

    humidity = _finite_float(relative_humidity)
    if humidity is None or not 0.0 <= humidity <= 100.0:
        return None
    return humidity / 100.0


def _saturation_pressure(
    temperature_c: float,
    surface: VaporPressureSurface,
) -> float | None:
    """Route a saturation calculation to the explicitly selected surface."""

    if surface == "water":
        return saturation_vapor_pressure_water(temperature_c)
    if surface == "ice":
        return saturation_vapor_pressure_ice(temperature_c)
    return None


def _safe_exponential_pressure(coefficient: float, exponent: float) -> float | None:
    """Evaluate a Buck exponential while containing numerical failures."""

    if not math.isfinite(exponent):
        return None
    try:
        pressure = coefficient * math.exp(exponent)
    except OverflowError:
        return None
    return pressure if math.isfinite(pressure) and pressure > 0.0 else None


def _invert_saturation_pressure(
    target_pressure: float,
    pressure_function: Callable[[float], float | None],
    lower_temperature: float,
    upper_temperature: float,
) -> float | None:
    """Invert a monotonic saturation relation with bounded bisection."""

    target = _finite_float(target_pressure)
    lower_pressure = pressure_function(lower_temperature)
    upper_pressure = pressure_function(upper_temperature)
    if (
        target is None
        or target <= 0.0
        or lower_pressure is None
        or upper_pressure is None
        or target < lower_pressure
        or target > upper_pressure
    ):
        return None
    if target == lower_pressure:
        return lower_temperature
    if target == upper_pressure:
        return upper_temperature

    lower = lower_temperature
    upper = upper_temperature
    for _ in range(_INVERSION_ITERATIONS):
        midpoint = (lower + upper) / 2.0
        midpoint_pressure = pressure_function(midpoint)
        if midpoint_pressure is None:
            return None
        if midpoint_pressure < target:
            lower = midpoint
        else:
            upper = midpoint

    result = (lower + upper) / 2.0
    return result if math.isfinite(result) else None
