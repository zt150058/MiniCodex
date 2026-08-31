from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from coding_agent.engine.budget import (
    BudgetProfile,
    BudgetProfileLimits,
    limits_for_profile,
)


def test_budget_profiles_have_exact_wire_values() -> None:
    assert tuple(BudgetProfile) == (
        BudgetProfile.STANDARD,
        BudgetProfile.DEEP,
    )
    assert BudgetProfile.STANDARD.value == "standard"
    assert BudgetProfile.DEEP.value == "deep"


@pytest.mark.parametrize(
    ("profile", "expected"),
    [
        (
            BudgetProfile.STANDARD,
            BudgetProfileLimits(24, 4, 48, 8, 80, 1200.0, 1),
        ),
        (
            BudgetProfile.DEEP,
            BudgetProfileLimits(40, 6, 80, 12, 140, 1800.0, 1),
        ),
    ],
)
def test_profile_limits_are_exact_and_immutable(
    profile: BudgetProfile,
    expected: BudgetProfileLimits,
) -> None:
    actual = limits_for_profile(profile)

    assert actual == expected
    with pytest.raises(FrozenInstanceError):
        actual.max_tool_calls = 999  # type: ignore[misc]


def test_profile_lookup_rejects_non_enum_values() -> None:
    with pytest.raises(TypeError, match="profile must be BudgetProfile"):
        limits_for_profile("deep")  # type: ignore[arg-type]
