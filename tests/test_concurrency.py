"""Tests for the concurrency-focused benchmarks module."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from benchmarks import concurrency as concurrency_module
from benchmarks.concurrency import (
    WorkloadSpec,
    main as concurrency_main,
    run_concurrency_benchmarks,
)


def _noop(_: object) -> None:
    return None


def test_run_concurrency_benchmarks_structure() -> None:
    data = run_concurrency_benchmarks(tasks=6, workers=2)

    metadata = data["metadata"]
    assert metadata["tasks"] == 6
    assert metadata["workers"] == 2
    assert "gil_disabled" in metadata
    assert metadata["gil_disabled"] in (True, False, None)

    workloads = {workload["name"]: workload for workload in data["workloads"]}
    assert {
        "cpu_bound_fibonacci",
        "io_bound_sleep",
    }.issubset(workloads)

    for workload in workloads.values():
        strategies = {entry["name"]: entry for entry in workload["strategies"]}
        sequential = strategies["sequential"]
        assert sequential["supported"] is True
        assert sequential["duration"] is not None
        if sequential["duration"] and sequential["duration"] > 0:
            assert math.isclose(sequential["speedup_vs_sequential"], 1.0)

        for name in ("threading", "process"):
            entry = strategies[name]
            assert entry["supported"] is True
            assert entry["duration"] is not None

        subinterp = strategies["subinterpreters"]
        assert subinterp["duration"] is None or subinterp["duration"] >= 0
        assert subinterp["supported"] in (True, False)
        if not subinterp["supported"]:
            assert isinstance(subinterp["reason"], str)


def test_run_concurrency_benchmarks_custom_workload() -> None:
    workload = WorkloadSpec(
        name="custom",
        category="misc",
        description="Custom workload for testing.",
        function=_noop,
        argument=None,
        supports_threads=False,
        supports_processes=False,
        supports_subinterpreters=False,
    )

    data = run_concurrency_benchmarks(tasks=4, workers=2, workloads=[workload])
    [workload_result] = data["workloads"]
    strategies = {entry["name"]: entry for entry in workload_result["strategies"]}

    assert strategies["threading"]["supported"] is False
    assert strategies["process"]["supported"] is False
    assert strategies["subinterpreters"]["supported"] is False


def test_run_concurrency_benchmarks_validation() -> None:
    with pytest.raises(ValueError):
        run_concurrency_benchmarks(tasks=0)
    with pytest.raises(ValueError):
        run_concurrency_benchmarks(workers=0)
    with pytest.raises(ValueError):
        run_concurrency_benchmarks(workloads=[])


def test_main_writes_output(tmp_path: Path) -> None:
    output_path = tmp_path / "results" / "concurrency.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    exit_code = concurrency_main(
        ["--tasks", "3", "--workers", "2", "--output", str(output_path)]
    )

    assert exit_code == 0
    payload = json.loads(output_path.read_text())
    assert payload["metadata"]["tasks"] == 3
    assert payload["metadata"]["workers"] == 2
    assert "gil_disabled" in payload["metadata"]


def test_run_concurrency_benchmarks_reports_disabled_gil(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(concurrency_module, "_detect_gil_disabled", lambda: True)
    data = concurrency_module.run_concurrency_benchmarks(tasks=2, workers=1)
    assert data["metadata"]["gil_disabled"] is True

