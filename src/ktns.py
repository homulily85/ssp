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
    magazine: set[int] = set()
    cost = 0
    configs: list[frozenset[int]] = []
    for position in range(len(sequence)):
        required = set(requirements[sequence[position]])
        missing = required - magazine
        candidates = magazine - required
        # Larger next-use is evicted first. On ties, evict the larger tool ID,
        # preserving a deterministic lexicographically smaller configuration.
        evicted = sorted(
            candidates,
            key=lambda tool: (next_use[position][tool], tool),
            reverse=True,
        )[: max(0, len(magazine) + len(missing) - c)]
        magazine.difference_update(evicted)
        magazine.update(missing)
        cost += len(missing)
        assert len(magazine) <= c
        assert required <= magazine
        configs.append(frozenset(magazine))
    return cost, tuple(configs)


def ktns_switches(
    sequence: Sequence[int],
    requirements: Sequence[frozenset[int] | set[int]],
    m: int,
    c: int,
) -> tuple[int, tuple[frozenset[int], ...]]:
    """Exact tooling cost when the first magazine is preloaded for free.

    The free initial magazine is filled with up to ``c`` distinct tools used
    by the sequence (in first-use order).  KTNS then evicts the tool whose
    next use is farthest away, charging only additions after position zero.
    This realizes legacy KTNS cost minus the free initial load size.
    """
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
    distinct: list[int] = []
    seen: set[int] = set()
    for job in sequence:
        for tool in sorted(requirements[job]):
            if tool not in seen:
                distinct.append(tool)
                seen.add(tool)
    magazine = set(distinct[:c])
    cost = 0
    configs: list[frozenset[int]] = []
    for position, job in enumerate(sequence):
        required = set(requirements[job])
        missing = required - magazine
        candidates = magazine - required
        evicted = sorted(
            candidates,
            key=lambda tool: (next_use[position][tool], tool),
            reverse=True,
        )[: max(0, len(magazine) + len(missing) - c)]
        magazine.difference_update(evicted)
        magazine.update(missing)
        if position > 0:
            cost += len(missing)
        assert len(magazine) <= c and required <= magazine
        configs.append(frozenset(magazine))
    return cost, tuple(configs)
