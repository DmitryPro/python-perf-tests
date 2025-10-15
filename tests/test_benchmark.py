from __future__ import annotations

import json
from pathlib import Path

import pytest

import benchmarks.benchmark as benchmark


def test_run_benchmarks_structure(tmp_path: Path) -> None:
    payload = benchmark.run_benchmarks(iterations=1, repeat=2)

    assert payload["iterations"] == 1
    assert payload["repeat"] == 2
    assert isinstance(payload["python_version"], str)
    assert len(payload["cases"]) == 3

    for case in payload["cases"]:
        assert set(case.keys()) == {"name", "runs", "mean", "stdev"}
        assert len(case["runs"]) == 2
        assert all(run >= 0 for run in case["runs"])

    output_file = tmp_path / "result.json"
    exit_code = benchmark.main(["--iterations", "1", "--repeat", "1", "--output", str(output_file)])
    assert exit_code == 0
    stored = json.loads(output_file.read_text())
    assert stored["iterations"] == 1


def test_invalid_arguments() -> None:
    with pytest.raises(ValueError):
        benchmark.run_benchmarks(iterations=0)
    with pytest.raises(ValueError):
        benchmark.run_benchmarks(repeat=0)
