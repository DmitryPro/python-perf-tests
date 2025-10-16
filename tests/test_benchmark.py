from __future__ import annotations

import json
from pathlib import Path

import pytest

import benchmarks.benchmark as benchmark


def test_run_benchmarks_structure(tmp_path: Path) -> None:
    payload = benchmark.run_benchmarks(iterations=1, repeat=2)

    assert payload["iterations"] == 1
    assert payload["repeat"] == 2
    assert isinstance(payload["python_implementation"], str)
    assert isinstance(payload["python_version"], str)
    assert len(payload["cases"]) == 6

    case_names = {case["name"] for case in payload["cases"]}
    assert {
        "fibonacci_40",
        "fibonacci_rec_32",
        "prime_sieve_5000",
        "json_roundtrip_500",
        "bubble_sort_10000",
        "threaded_trig_4x20000",
    } == case_names

    for case in payload["cases"]:
        assert set(case.keys()) == {
            "name",
            "runs",
            "mean",
            "stdev",
            "per_iteration_mean",
            "per_iteration_stdev",
        }
        assert len(case["runs"]) == 2
        assert all(run >= 0 for run in case["runs"])
        assert case["mean"] >= 0
        assert case["per_iteration_mean"] >= 0

    output_file = tmp_path / "result.json"
    exit_code = benchmark.main(["--iterations", "1", "--repeat", "1", "--output", str(output_file)])
    assert exit_code == 0
    stored = json.loads(output_file.read_text())
    assert stored["iterations"] == 1
    assert "python_implementation" in stored


def test_invalid_arguments() -> None:
    with pytest.raises(ValueError):
        benchmark.run_benchmarks(iterations=0)
    with pytest.raises(ValueError):
        benchmark.run_benchmarks(repeat=0)
