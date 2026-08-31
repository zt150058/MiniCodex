from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math
from types import MappingProxyType
from typing import Final


class BudgetProfile(StrEnum):
    STANDARD = "standard"
    DEEP = "deep"


def _positive_integer(value: object, name: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _nonnegative_integer(value: object, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _positive_finite_number(value: object, name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ValueError(f"{name} must be a positive finite number")
    return float(value)


@dataclass(frozen=True, slots=True)
class BudgetProfileLimits:
    max_main_logical_calls: int
    max_summary_logical_calls: int
    max_provider_attempts: int
    max_summary_provider_attempts: int
    max_tool_calls: int
    max_runtime_seconds: float
    verification_tool_reserve: int

    def __post_init__(self) -> None:
        for name in (
            "max_main_logical_calls",
            "max_summary_logical_calls",
            "max_provider_attempts",
            "max_summary_provider_attempts",
            "max_tool_calls",
        ):
            object.__setattr__(
                self,
                name,
                _positive_integer(getattr(self, name), name),
            )
        object.__setattr__(
            self,
            "max_runtime_seconds",
            _positive_finite_number(
                self.max_runtime_seconds,
                "max_runtime_seconds",
            ),
        )
        object.__setattr__(
            self,
            "verification_tool_reserve",
            _nonnegative_integer(
                self.verification_tool_reserve,
                "verification_tool_reserve",
            ),
        )


_PROFILE_LIMITS: Final = MappingProxyType(
    {
        BudgetProfile.STANDARD: BudgetProfileLimits(
            24,
            4,
            48,
            8,
            80,
            1200.0,
            1,
        ),
        BudgetProfile.DEEP: BudgetProfileLimits(
            40,
            6,
            80,
            12,
            140,
            1800.0,
            1,
        ),
    }
)


def limits_for_profile(profile: BudgetProfile) -> BudgetProfileLimits:
    if type(profile) is not BudgetProfile:
        raise TypeError("profile must be BudgetProfile")
    return _PROFILE_LIMITS[profile]
