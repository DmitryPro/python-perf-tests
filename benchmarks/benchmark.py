"""Utility script for running deterministic micro-benchmarks across Python versions."""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import timeit
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Tuple

from .compute import fibonacci, parse_and_serialize_json, prime_sieve, fibonacci2

# Shared sink to ensure that benchmark results are observable and cannot be
# optimized away by the interpreter.
_SINK: List[int] = []

BenchmarkFunc = Callable[[], int]


def _consume(value: int) -> None:
    _SINK.append(value)
    if len(_SINK) > 1024:
        del _SINK[:512]


def _wrap(func: BenchmarkFunc) -> BenchmarkFunc:
    def runner() -> int:
        result = func()
        _consume(result)
        return result

    return runner


def _benchmark_cases() -> List[Tuple[str, BenchmarkFunc]]:
    return [
        ("fibonacci_40", lambda: fibonacci(40)),
        ("fibonacci_rec_32", lambda: fibonacci2(32)),
        ("prime_sieve_5000", lambda: len(prime_sieve(5000))),
        ("json_roundtrip_500", lambda: parse_and_serialize_json(500)),
    ]


def run_benchmarks(iterations: int = 10, repeat: int = 5) -> Dict[str, object]:
    if iterations <= 0:
        raise ValueError("iterations must be positive")
    if repeat <= 0:
        raise ValueError("repeat must be positive")

    results = []
    for name, func in _benchmark_cases():
        timer = timeit.Timer(_wrap(func))
        runs = timer.repeat(repeat, number=iterations)
        per_iteration = [duration / float(iterations) for duration in runs]
        mean = statistics.mean(runs)
        stdev = statistics.pstdev(runs) if len(runs) > 1 else 0.0
        per_iteration_mean = statistics.mean(per_iteration)
        per_iteration_stdev = (
            statistics.pstdev(per_iteration) if len(per_iteration) > 1 else 0.0
        )
        results.append(
            {
                "name": name,
                "runs": runs,
                "mean": mean,
                "stdev": stdev,
                "per_iteration_mean": per_iteration_mean,
                "per_iteration_stdev": per_iteration_stdev,
            }
        )

    return {
        "python_version": platform.python_version(),
        "iterations": iterations,
        "repeat": repeat,
        "cases": results,
    }


def _default_output_path() -> Path:
    return Path("results") / f"benchmarks-python-{platform.python_version()}.json"


def main(args: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=10, help="Iterations per repeat")
    parser.add_argument("--repeat", type=int, default=5, help="Number of repeats per benchmark")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional file to store benchmark results as JSON",
    )

    parsed = parser.parse_args(args=args)

    payload = run_benchmarks(iterations=parsed.iterations, repeat=parsed.repeat)

    if parsed.output is None:
        output_path = _default_output_path()
    else:
        output_path = parsed.output

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
