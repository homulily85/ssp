from __future__ import annotations

from dataclasses import dataclass

from .dominance import reconstruct_sequence
from .model import DominanceResult, SSPInstance


@dataclass(frozen=True, slots=True)
class UpperBoundResult:
    cost: int
    reduced_sequence: tuple[int, ...]
    full_sequence: tuple[int, ...]
    magazine_configs: tuple[frozenset[int], ...]


def construct_upper_bound(
    original: SSPInstance,
    dominance: DominanceResult,
) -> UpperBoundResult:
    reduced = dominance.reduced
    frequencies = [sum(tool in required for required in reduced.requirements)
                   for tool in range(reduced.m)]
    local_sequence = sorted(range(reduced.n), key=lambda job: (
        -sum(frequencies[tool] for tool in reduced.requirements[job]),
        reduced.local_to_original[job],
    ))
    magazine: set[int] = set()
    cost = 0
    configs: list[frozenset[int]] = []
    representatives = tuple(reduced.local_to_original[job] for job in local_sequence)
    for job, representative in zip(local_sequence, representatives):
        required = reduced.requirements[job]
        missing = required - magazine
        cost += len(missing)
        magazine.update(missing)
        removable = sorted(magazine - required,
                           key=lambda tool: reduced.tool_to_original[tool], reverse=True)
        for tool in removable[:max(0, len(magazine) - reduced.c)]:
            magazine.remove(tool)
        config = frozenset(reduced.tool_to_original[tool] for tool in magazine)
        configs.extend([config] * (1 + len(dominance.dominated_by[representative])))
    full = reconstruct_sequence(representatives, dominance)
    previous = frozenset()
    verified = 0
    for job, config in zip(full, configs):
        assert original.requirements[job] <= config and len(config) <= original.c
        verified += len(config - previous)
        previous = config
    assert verified == cost
    return UpperBoundResult(cost, representatives, full, tuple(configs))
