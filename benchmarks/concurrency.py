"""Concurrency-focused benchmarks tailored for Python 3.14 experiments.

The module exposes :func:`run_concurrency_benchmarks` which coordinates four
execution strategies across a couple of representative workloads:

``sequential``
    Baseline single-threaded execution used as a reference point.

``threading``
    Uses :class:`concurrent.futures.ThreadPoolExecutor` to highlight the impact
    of the GIL on CPU bound tasks and the strengths of threading for blocking
    workloads.

``process``
    Employs :class:`concurrent.futures.ProcessPoolExecutor` to demonstrate when
    sidestepping the GIL with multiple processes pays off.

``subinterpreters``
    Targets the "interpreters" module that becomes broadly available in Python
    3.14.  When the module is not present (e.g. on older runtimes) the strategy
    is reported as unsupported together with an explanatory reason.

Each workload is executed with identical parameters across the strategies so
that callers can compare total execution time, derived throughput, and speed-up
relative to the sequential baseline.
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import dataclass
import os
import platform
import sys
import time
from time import perf_counter
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Sequence

from .compute import fibonacci


class UnsupportedStrategyError(RuntimeError):
    """Raised when a workload cannot be executed with a given strategy."""


@dataclass(frozen=True)
class WorkloadSpec:
    """Container describing a concurrency benchmark workload."""

    name: str
    category: str
    description: str
    function: Callable[[object], object | None]
    argument: object
    supports_threads: bool = True
    supports_processes: bool = True
    supports_subinterpreters: bool = True


def _cpu_bound_fibonacci(size: int) -> None:
    fibonacci(size)


def _io_bound_sleep(duration: float) -> None:
    time.sleep(duration)


_WORKLOADS: Sequence[WorkloadSpec] = (
    WorkloadSpec(
        name="cpu_bound_fibonacci",
        category="cpu",
        description=(
            "Iterative Fibonacci computation that keeps the CPU busy and "
            "illustrates the limitations of threads under the GIL."
        ),
        function=_cpu_bound_fibonacci,
        argument=30,
    ),
    WorkloadSpec(
        name="io_bound_sleep",
        category="io",
        description=(
            "Repeated short sleeps that mimic I/O waits, highlighting the "
            "benefits of threads for blocking workloads."
        ),
        function=_io_bound_sleep,
        argument=0.002,
    ),
)


def _ensure_positive(name: str, value: int) -> None:
    if value <= 0:
        raise ValueError(f"{name} must be positive, got {value!r}")


def _run_sequential(workload: WorkloadSpec, tasks: int) -> float:
    start = perf_counter()
    for _ in range(tasks):
        workload.function(workload.argument)
    return perf_counter() - start


def _run_threads(workload: WorkloadSpec, tasks: int, workers: int) -> float:
    if not workload.supports_threads:
        raise UnsupportedStrategyError("workload does not support threads")

    start = perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as executor:
        list(executor.map(workload.function, (workload.argument,) * tasks))
    return perf_counter() - start


def _run_processes(workload: WorkloadSpec, tasks: int, workers: int) -> float:
    if not workload.supports_processes:
        raise UnsupportedStrategyError("workload does not support processes")

    start = perf_counter()
    with ProcessPoolExecutor(max_workers=workers) as executor:
        list(executor.map(workload.function, (workload.argument,) * tasks))
    return perf_counter() - start


def _split_work(amount: int, parts: int) -> List[int]:
    base = amount // parts
    remainder = amount % parts
    return [base + (1 if index < remainder else 0) for index in range(parts)]


def _run_subinterpreters(workload: WorkloadSpec, tasks: int, workers: int) -> float:
    if not workload.supports_subinterpreters:
        raise UnsupportedStrategyError("workload does not support subinterpreters")

    try:
        import interpreters  # type: ignore[attr-defined]
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on runtime
        raise UnsupportedStrategyError("interpreters module is unavailable") from exc

    if not hasattr(interpreters, "create"):
        raise UnsupportedStrategyError("interpreters module lacks create()")

    work_splits = _split_work(tasks, workers)
    interpreters_pool = [interpreters.create() for _ in range(workers)]

    module_name = workload.function.__module__
    function_name = workload.function.__name__
    argument_repr = repr(workload.argument)

    start = perf_counter()
    try:
        for interp, count in zip(interpreters_pool, work_splits):
            if count == 0:
                continue
            source = (
                f"from {module_name} import {function_name} as _func\n"
                f"for _ in range({count}):\n"
                f"    _func({argument_repr})\n"
            )
            interp.run(source)
    finally:  # pragma: no cover - clean-up depends on runtime support
        for interp in interpreters_pool:
            close = getattr(interp, "close", None)
            if callable(close):
                close()

    return perf_counter() - start


def _detect_gil_disabled() -> bool | None:
    """Return ``True`` when the interpreter runs with the GIL disabled."""

    env_flag = os.environ.get("PYTHON_GIL")
    if env_flag is not None:
        if env_flag == "0":
            return True
        if env_flag == "1":
            return False

    for attribute in ("is_gil_enabled", "_is_gil_enabled"):
        probe = getattr(sys, attribute, None)
        if callable(probe):
            try:
                return not bool(probe())
            except Exception:  # pragma: no cover - defensive fallback
                continue
    return None


def _format_result(
    *,
    name: str,
    supported: bool,
    duration: float | None,
    baseline: float,
    total_tasks: int,
    reason: str | None = None,
) -> Dict[str, object]:
    tasks_per_second = None
    speedup = None
    if supported and duration is not None and duration > 0:
        tasks_per_second = total_tasks / duration
        speedup = baseline / duration if baseline > 0 else None

    return {
        "name": name,
        "supported": supported,
        "duration": duration,
        "tasks_per_second": tasks_per_second,
        "speedup_vs_sequential": speedup,
        "reason": reason,
    }


def _runner_mapping() -> Dict[str, Callable[[WorkloadSpec, int, int], float]]:
    return {
        "threading": _run_threads,
        "process": _run_processes,
        "subinterpreters": _run_subinterpreters,
    }


def run_concurrency_benchmarks(
    *,
    tasks: int = 24,
    workers: int = 4,
    workloads: Iterable[WorkloadSpec] | None = None,
) -> Dict[str, object]:
    """Measure concurrency strategies for multiple workloads.

    Parameters
    ----------
    tasks:
        Total number of workload invocations per strategy.
    workers:
        Size of the worker pool for the parallel strategies.
    workloads:
        Optional custom workload list.  When omitted the default CPU and I/O
        workloads defined in this module are executed.
    """

    _ensure_positive("tasks", tasks)
    _ensure_positive("workers", workers)

    selected_workloads = tuple(_WORKLOADS if workloads is None else workloads)
    if not selected_workloads:
        raise ValueError("at least one workload must be specified")

    metadata = {
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "tasks": tasks,
        "workers": workers,
        "gil_disabled": not sys._is_gil_enabled(),
    }

    runner_map = _runner_mapping()
    results: List[Dict[str, object]] = []

    for workload in selected_workloads:
        sequential_duration = _run_sequential(workload, tasks)
        strategies: List[Dict[str, object]] = [
            _format_result(
                name="sequential",
                supported=True,
                duration=sequential_duration,
                baseline=sequential_duration,
                total_tasks=tasks,
            )
        ]

        for name, runner in runner_map.items():
            try:
                duration = runner(workload, tasks, workers)
            except UnsupportedStrategyError as exc:
                strategies.append(
                    _format_result(
                        name=name,
                        supported=False,
                        duration=None,
                        baseline=sequential_duration,
                        total_tasks=tasks,
                        reason=str(exc),
                    )
                )
            else:
                strategies.append(
                    _format_result(
                        name=name,
                        supported=True,
                        duration=duration,
                        baseline=sequential_duration,
                        total_tasks=tasks,
                    )
                )

        results.append(
            {
                "name": workload.name,
                "category": workload.category,
                "description": workload.description,
                "strategies": strategies,
            }
        )

    return {"metadata": metadata, "workloads": results}


__all__ = ["run_concurrency_benchmarks", "WorkloadSpec", "UnsupportedStrategyError"]


def _default_output_path(metadata: Dict[str, object]) -> Path:
    implementation = str(metadata.get("python_implementation", "unknown")).lower()
    version = str(metadata.get("python_version", "unknown"))
    gil_suffix = "-nogil" if metadata.get("gil_disabled") is True else ""
    return Path("results") / f"concurrency-{implementation}-{version}{gil_suffix}.json"


def main(args: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tasks", type=int, default=24, help="Total workload invocations per strategy"
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Number of worker threads/processes/subinterpreters",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional file to store benchmark results as JSON",
    )

    parsed = parser.parse_args(args=args)

    payload = run_concurrency_benchmarks(tasks=parsed.tasks, workers=parsed.workers)
    metadata = payload.get("metadata", {}) if isinstance(payload, dict) else {}

    if parsed.output is None:
        output_path = _default_output_path(metadata)
    else:
        output_path = parsed.output

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())

