from __future__ import annotations

from math import inf
from typing import Sequence


def _next_use_table(
    sequence: Sequence[int], requirements: Sequence[frozenset[int] | set[int]], m: int
) -> list[list[int | float]]:
    """Return the first use strictly after each position for every tool."""
    n = len(sequence)
    table: list[list[int | float]] = [[inf] * m for _ in range(n)]
    next_position: list[int | float] = [inf] * m
    for position in range(n - 1, -1, -1):
        table[position] = next_position.copy()
        for tool in requirements[sequence[position]]:
            next_position[tool] = position
    return table


def ktns(
    sequence: Sequence[int],
    requirements: Sequence[frozenset[int] | set[int]],
    m: int,
    c: int,
) -> tuple[int, tuple[frozenset[int], ...]]:
    if not sequence:
        raise ValueError("KTNS requires a non-empty job sequence")
    if not 1 <= c <= m:
        raise ValueError("capacity must satisfy 1 <= c <= m")
    if len(set(sequence)) != len(sequence):
        raise ValueError("job sequence contains duplicates")
    if any(job < 0 or job >= len(requirements) for job in sequence):
        raise ValueError("job sequence contains an invalid job ID")
    if any(len(requirements[job]) > c for job in sequence):
        raise ValueError("a job requires more tools than magazine capacity")

    next_use = _next_use_table(sequence, requirements, m)
    first_required = set(requirements[sequence[0]])
    fillers = sorted(
        (tool for tool in range(m) if tool not in first_required),
        key=lambda tool: (next_use[0][tool], tool),
    )
    magazine = first_required | set(fillers[: c - len(first_required)])
    cost = c
    configs: list[frozenset[int]] = [frozenset(magazine)]
    assert len(magazine) == c
    assert first_required <= magazine

    for position in range(1, len(sequence)):
        required = set(requirements[sequence[position]])
        missing = required - magazine
        candidates = magazine - required
        # Larger next-use is evicted first. On ties, evict the larger tool ID,
        # preserving a deterministic lexicographically smaller configuration.
        evicted = sorted(
            candidates,
            key=lambda tool: (next_use[position][tool], tool),
            reverse=True,
        )[: len(missing)]
        if len(evicted) != len(missing):
            raise AssertionError("insufficient evictable tools")
        magazine.difference_update(evicted)
        magazine.update(missing)
        cost += len(missing)
        assert len(magazine) == c
        assert required <= magazine
        configs.append(frozenset(magazine))
    return cost, tuple(configs)
