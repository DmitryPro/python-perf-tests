"""Benchmark workloads and orchestration utilities."""

from __future__ import annotations

from .compute import fibonacci, parse_and_serialize_json, prime_sieve

__all__ = [
    "fibonacci",
    "parse_and_serialize_json",
    "prime_sieve",
    "run_benchmarks",
    "main",
]


def __getattr__(name: str):
    if name in {"run_benchmarks", "main"}:
        from . import benchmark as _benchmark

        return getattr(_benchmark, name)
    raise AttributeError(name)
