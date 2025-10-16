"""Benchmark workloads and orchestration utilities."""

from __future__ import annotations

from .compute import fibonacci, parse_and_serialize_json, prime_sieve

__all__ = [
    "fibonacci",
    "parse_and_serialize_json",
    "prime_sieve",
    "run_benchmarks",
    "main",
    "run_concurrency_benchmarks",
]


def __getattr__(name: str):
    if name in {"run_benchmarks", "main"}:
        from . import benchmark as _benchmark

        return getattr(_benchmark, name)
    if name == "run_concurrency_benchmarks":
        from . import concurrency as _concurrency

        return getattr(_concurrency, name)
    raise AttributeError(name)
