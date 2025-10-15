"""CPU-bound workloads used for cross-version performance measurements."""

from __future__ import annotations

import json
import math
import random
from typing import List


def fibonacci(n: int) -> int:
    """Compute the nth Fibonacci number using an iterative algorithm."""
    if n < 2:
        return n

    a, b = 0, 1
    for _ in range(2, n + 1):
        a, b = b, a + b
    return b

def fibonacci2(n: int) -> int:
    """Compute the nth Fibonacci number using an recurcive algorithm."""
    if n <= 1:
        return n
    else:
        return fibonacci2(n-1) + fibonacci2(n-2)


def prime_sieve(limit: int) -> List[int]:
    """Return all prime numbers below *limit* using the Sieve of Eratosthenes."""
    if limit < 2:
        return []

    sieve = [True] * limit
    sieve[0] = sieve[1] = False

    for number in range(2, int(math.sqrt(limit)) + 1):
        if sieve[number]:
            step = number
            start = number * number
            sieve[start:limit:step] = [False] * len(range(start, limit, step))

    return [index for index, is_prime in enumerate(sieve) if is_prime]


def parse_and_serialize_json(payload_size: int) -> int:
    """Serialize and parse randomly generated JSON data."""
    if payload_size <= 0:
        raise ValueError("payload_size must be positive")

    payload = {
        "numbers": [random.random() for _ in range(payload_size)],
        "nested": {"a": "value", "b": list(range(payload_size))},
        "flag": True,
    }

    serialized = json.dumps(payload)
    decoded = json.loads(serialized)
    return len(decoded["nested"]["b"])


__all__ = ["fibonacci", "prime_sieve", "parse_and_serialize_json", "fibonacci2"]
