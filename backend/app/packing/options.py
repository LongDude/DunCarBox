"""Engine-local knobs; the frozen v1 HTTP PackingOptions is unchanged."""

from dataclasses import dataclass
from fractions import Fraction


@dataclass(frozen=True, slots=True)
class EngineOptions:
    min_support_ratio: Fraction = Fraction(4, 5)
    max_candidate_points: int = 128
    max_strategies: int = 12
    max_alternatives: int = 3
    max_fill_passes: int = 3

    def __post_init__(self) -> None:
        # Decimal text avoids importing binary float error into geometric decisions.
        ratio = Fraction(str(self.min_support_ratio))
        if not 0 < ratio <= 1:
            raise ValueError("min_support_ratio must be in (0, 1]")
        object.__setattr__(self, "min_support_ratio", ratio)
        for field, upper in (
            ("max_candidate_points", 4096),
            ("max_strategies", 12),
            ("max_alternatives", 3),
            ("max_fill_passes", 10),
        ):
            value = getattr(self, field)
            lower = 0 if field == "max_alternatives" else 1
            if type(value) is not int or not lower <= value <= upper:
                raise ValueError(f"{field} must be an integer in [{lower}, {upper}]")
