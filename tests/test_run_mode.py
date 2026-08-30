from __future__ import annotations

import pytest

from coding_agent.run_mode import RunMode


def test_run_mode_has_exact_wire_values() -> None:
    assert tuple(RunMode) == (RunMode.MODIFY, RunMode.READ_ONLY)
    assert RunMode.MODIFY.value == "modify"
    assert RunMode.READ_ONLY.value == "read_only"


def test_run_mode_rejects_unknown_value() -> None:
    with pytest.raises(ValueError):
        RunMode("auto")
