from __future__ import annotations

import pytest

from benchmarks import compute


def test_threaded_trigonometry_accumulates_results() -> None:
    value = compute.threaded_trigonometry(3, 1000)
    assert isinstance(value, int)
    assert value != 0


def test_threaded_trigonometry_validates_inputs() -> None:
    with pytest.raises(ValueError):
        compute.threaded_trigonometry(0, 100)
    with pytest.raises(ValueError):
        compute.threaded_trigonometry(2, 0)
