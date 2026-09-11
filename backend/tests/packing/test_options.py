"""Limits reject ambiguous or unbounded configuration before search starts."""

from fractions import Fraction

import pytest

from app.packing.options import EngineOptions


def test_engine_options_defaults_are_bounded_and_support_is_exact() -> None:
    options = EngineOptions()
    assert options.min_support_ratio == Fraction(4, 5)
    assert options.max_candidate_points == 128
    assert options.max_strategies == 12
    assert options.max_alternatives == 3
    assert options.max_fill_passes == 3


@pytest.mark.parametrize("value", [Fraction(4, 5), 0.8, "0.8"])
def test_decimal_support_configuration_becomes_exact_fraction(value) -> None:
    options = EngineOptions(min_support_ratio=value)
    assert options.min_support_ratio == Fraction(4, 5)
    assert isinstance(options.min_support_ratio, Fraction)


@pytest.mark.parametrize("value", [Fraction(1, 10000), Fraction(2, 3), Fraction(1)])
def test_valid_support_thresholds_preserve_exact_value(value: Fraction) -> None:
    assert EngineOptions(min_support_ratio=value).min_support_ratio == value


@pytest.mark.parametrize("value", [-1, 0, 1.01, Fraction(101, 100), float("nan"), float("inf")])
def test_out_of_range_or_nonfinite_support_is_rejected(value) -> None:
    with pytest.raises(ValueError):
        EngineOptions(min_support_ratio=value)


@pytest.mark.parametrize(
    "field,lower,upper",
    [
        ("max_candidate_points", 1, 4096),
        ("max_strategies", 1, 12),
        ("max_alternatives", 0, 3),
        ("max_fill_passes", 1, 10),
    ],
)
def test_limit_endpoints_are_inclusive(field: str, lower: int, upper: int) -> None:
    assert getattr(EngineOptions(**{field: lower}), field) == lower
    assert getattr(EngineOptions(**{field: upper}), field) == upper
    for value in (lower - 1, upper + 1):
        with pytest.raises(ValueError, match=field):
            EngineOptions(**{field: value})


@pytest.mark.parametrize(
    "field", ["max_candidate_points", "max_strategies", "max_alternatives", "max_fill_passes"]
)
@pytest.mark.parametrize("value", [True, False, 1.0, "1", None])
def test_limits_require_integer_values_without_bool_coercion(field: str, value) -> None:
    with pytest.raises(ValueError, match=field):
        EngineOptions(**{field: value})
