"""Tests for dew point psychrometric calculations."""

from dataclasses import FrozenInstanceError
import math
from typing import Any

import pytest

from custom_components.dew_point import calculation
from custom_components.dew_point.calculation import (
    MAX_ICE_TEMPERATURE_C,
    MAX_WATER_TEMPERATURE_C,
    MIN_BUCK_TEMPERATURE_C,
    absolute_humidity,
    actual_vapor_pressure,
    calculate_moist_air_properties,
    dew_point,
    dew_point_spread,
    frost_point,
    saturation_vapor_pressure_ice,
    saturation_vapor_pressure_water,
    vapor_pressure_deficit,
)


@pytest.mark.parametrize(
    ("temperature", "expected_kpa"),
    [
        (-80.0, 0.000113722715),
        (-20.0, 0.125584089515),
        (0.0, 0.61121),
        (20.0, 2.338339978450),
        (50.0, 12.349403510283),
    ],
)
def test_saturation_vapor_pressure_water_reference_values(
    temperature: float, expected_kpa: float
) -> None:
    """Buck water results agree with published-coefficient reference values."""

    assert saturation_vapor_pressure_water(temperature) == pytest.approx(
        expected_kpa, rel=1e-10
    )


@pytest.mark.parametrize(
    ("temperature", "expected_kpa"),
    [
        (-80.0, 0.000054839809),
        (-40.0, 0.012847309535),
        (-20.0, 0.103285944485),
        (0.0, 0.61115),
    ],
)
def test_saturation_vapor_pressure_ice_reference_values(
    temperature: float, expected_kpa: float
) -> None:
    """Buck ice results agree with published-coefficient reference values."""

    assert saturation_vapor_pressure_ice(temperature) == pytest.approx(
        expected_kpa, rel=1e-10
    )


@pytest.mark.parametrize("temperature", [-80.0, -40.0, 0.0, 20.0, 50.0])
def test_water_dew_point_is_self_consistent_at_saturation(
    temperature: float,
) -> None:
    """At 100 % water-relative humidity, dew point equals air temperature."""

    assert dew_point(temperature, 100.0) == temperature
    assert dew_point_spread(temperature, 100.0) == 0.0


@pytest.mark.parametrize("temperature", [-80.0, -40.0, -20.0, 0.0])
def test_ice_frost_point_is_self_consistent_at_saturation(
    temperature: float,
) -> None:
    """At 100 % ice-relative humidity, frost point equals air temperature."""

    assert frost_point(temperature, 100.0, humidity_reference="ice") == pytest.approx(
        temperature, abs=1e-12
    )


@pytest.mark.parametrize("temperature", [-20.0, 0.0, 20.0, 50.0])
@pytest.mark.parametrize("humidity", [1.0, 10.0, 50.0, 99.0, 100.0])
def test_dew_point_does_not_exceed_air_temperature(
    temperature: float, humidity: float
) -> None:
    """Water-referenced dew point remains at or below air temperature."""

    calculated = dew_point(temperature, humidity)
    if calculated is not None:
        assert calculated <= temperature + 1e-12


def test_dew_point_is_monotonic_with_relative_humidity() -> None:
    """Dew point rises monotonically as humidity rises."""

    results = [dew_point(20.0, humidity) for humidity in (5, 20, 40, 60, 80, 100)]
    assert all(result is not None for result in results)
    finite_results = [result for result in results if result is not None]
    assert finite_results == sorted(finite_results)
    assert len(set(finite_results)) == len(finite_results)


@pytest.mark.parametrize(
    ("temperature", "humidity"),
    [(-40.0, 80.0), (-10.0, 40.0), (20.0, 50.0), (45.0, 95.0)],
)
def test_dew_point_inverts_the_same_water_pressure_curve(
    temperature: float, humidity: float
) -> None:
    """Forward pressure at the result reproduces actual vapor pressure."""

    calculated_dew_point = dew_point(temperature, humidity)
    pressure = actual_vapor_pressure(temperature, humidity)
    assert calculated_dew_point is not None
    assert pressure is not None
    assert saturation_vapor_pressure_water(calculated_dew_point) == pytest.approx(
        pressure, rel=1e-12
    )


def test_common_room_reference_values() -> None:
    """Derived values agree with independent psychrometric reference values."""

    assert dew_point(20.0, 50.0) == pytest.approx(9.271, abs=0.001)
    assert absolute_humidity(20.0, 50.0) == pytest.approx(8.6416, abs=0.0001)
    assert vapor_pressure_deficit(20.0, 50.0) == pytest.approx(1.16917, abs=0.00001)


def test_zero_humidity_keeps_defined_zero_quantities() -> None:
    """Zero vapor content is retained while point temperatures stay undefined."""

    assert actual_vapor_pressure(20.0, 0.0) == 0.0
    assert absolute_humidity(20.0, 0.0) == 0.0
    assert vapor_pressure_deficit(20.0, 0.0) == saturation_vapor_pressure_water(20.0)
    assert dew_point(20.0, 0.0) is None
    assert frost_point(20.0, 0.0) is None
    assert dew_point_spread(20.0, 0.0) is None


def test_frost_point_has_explicit_ice_range_semantics() -> None:
    """Frost point is returned only where the ice curve has a physical root."""

    calculated = frost_point(-20.0, 50.0, humidity_reference="ice")
    assert calculated is not None
    assert MIN_BUCK_TEMPERATURE_C <= calculated <= MAX_ICE_TEMPERATURE_C
    assert saturation_vapor_pressure_ice(calculated) == pytest.approx(
        actual_vapor_pressure(-20.0, 50.0, humidity_reference="ice"), rel=1e-12
    )

    assert frost_point(20.0, 50.0) is None


@pytest.mark.parametrize("invalid", [math.nan, math.inf, -math.inf, None, "bad"])
def test_malformed_temperature_never_escapes(invalid: Any) -> None:
    """Malformed and non-finite temperatures return None without exceptions."""

    assert saturation_vapor_pressure_water(invalid) is None
    assert saturation_vapor_pressure_ice(invalid) is None
    assert actual_vapor_pressure(invalid, 50.0) is None
    assert dew_point(invalid, 50.0) is None
    assert frost_point(invalid, 50.0) is None
    assert dew_point_spread(invalid, 50.0) is None
    assert absolute_humidity(invalid, 50.0) is None
    assert vapor_pressure_deficit(invalid, 50.0) is None
    assert calculate_moist_air_properties(invalid, 50.0) is None


@pytest.mark.parametrize(
    "invalid", [math.nan, math.inf, -math.inf, -0.0001, 100.0001, None, "bad"]
)
def test_malformed_humidity_never_escapes(invalid: Any) -> None:
    """Malformed, non-finite, and out-of-range humidity is rejected."""

    assert actual_vapor_pressure(20.0, invalid) is None
    assert dew_point(20.0, invalid) is None
    assert frost_point(20.0, invalid) is None
    assert dew_point_spread(20.0, invalid) is None
    assert absolute_humidity(20.0, invalid) is None
    assert vapor_pressure_deficit(20.0, invalid) is None
    assert calculate_moist_air_properties(20.0, invalid) is None


def test_temperature_validity_boundaries_are_enforced() -> None:
    """Extreme values and the analytical singularities stay outside the API."""

    assert saturation_vapor_pressure_water(MIN_BUCK_TEMPERATURE_C) is not None
    assert saturation_vapor_pressure_water(MAX_WATER_TEMPERATURE_C) is not None
    assert saturation_vapor_pressure_ice(MIN_BUCK_TEMPERATURE_C) is not None
    assert saturation_vapor_pressure_ice(MAX_ICE_TEMPERATURE_C) is not None
    assert saturation_vapor_pressure_water(-80.0001) is None
    assert saturation_vapor_pressure_water(50.0001) is None
    assert saturation_vapor_pressure_ice(-80.0001) is None
    assert saturation_vapor_pressure_ice(0.0001) is None
    assert saturation_vapor_pressure_water(-257.14) is None
    assert saturation_vapor_pressure_ice(-279.82) is None
    assert saturation_vapor_pressure_water(1e308) is None


def test_invalid_surface_is_rejected_without_an_exception() -> None:
    """Runtime misuse of the typed surface selector fails safely."""

    assert actual_vapor_pressure(20.0, 50.0, humidity_reference="steam") is None
    assert dew_point(20.0, 50.0, humidity_reference="steam") is None
    assert frost_point(20.0, 50.0, humidity_reference="steam") is None
    assert absolute_humidity(20.0, 50.0, humidity_reference="steam") is None
    assert vapor_pressure_deficit(20.0, 50.0, humidity_reference="steam") is None
    assert (
        calculate_moist_air_properties(20.0, 50.0, humidity_reference="steam") is None
    )


def test_immutable_properties_snapshot_is_internally_consistent() -> None:
    """The aggregate result exposes one consistent, immutable input snapshot."""

    properties = calculate_moist_air_properties(20.0, 50.0)
    assert properties is not None
    assert properties.air_temperature_c == 20.0
    assert properties.relative_humidity == 50.0
    assert properties.humidity_reference == "water"
    assert properties.saturation_vapor_pressure_kpa == pytest.approx(
        2 * properties.actual_vapor_pressure_kpa
    )
    assert properties.vapor_pressure_deficit_kpa == pytest.approx(
        properties.actual_vapor_pressure_kpa
    )
    assert properties.dew_point_c is not None
    assert properties.dew_point_spread_c == pytest.approx(
        properties.air_temperature_c - properties.dew_point_c
    )
    assert properties.absolute_humidity_g_m3 == pytest.approx(8.6416, abs=0.0001)

    with pytest.raises(FrozenInstanceError):
        properties.air_temperature_c = 21.0


def test_defensive_numeric_guards_contain_internal_failures(monkeypatch) -> None:
    """Defensive branches return None or a stable zero without leaking errors."""
    monkeypatch.setattr(calculation, "dew_point", lambda *_args, **_kwargs: math.inf)
    assert calculation.dew_point_spread(20.0, 50.0) is None

    monkeypatch.setattr(
        calculation,
        "dew_point",
        lambda *_args, **_kwargs: 20.0 + 5e-13,
    )
    assert calculation.dew_point_spread(20.0, 50.0) == 0.0

    monkeypatch.setattr(
        calculation,
        "actual_vapor_pressure",
        lambda *_args, **_kwargs: 1.0,
    )
    assert calculation.absolute_humidity(-273.15, 50.0) is None

    assert calculation._safe_exponential_pressure(1.0, math.nan) is None
    assert calculation._safe_exponential_pressure(1.0, 1_000.0) is None


def test_bounded_inversion_handles_endpoints_and_invalid_midpoint() -> None:
    """The numerical inverter handles exact boundaries and function failures."""

    def linear_pressure(temperature: float) -> float:
        return temperature

    assert calculation._invert_saturation_pressure(
        1.0, linear_pressure, 1.0, 3.0
    ) == pytest.approx(1.0)
    assert calculation._invert_saturation_pressure(
        3.0, linear_pressure, 1.0, 3.0
    ) == pytest.approx(3.0)

    def missing_midpoint_pressure(temperature: float) -> float | None:
        return None if temperature == 2.0 else temperature

    assert (
        calculation._invert_saturation_pressure(
            2.0, missing_midpoint_pressure, 1.0, 3.0
        )
        is None
    )
