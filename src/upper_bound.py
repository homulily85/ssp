from __future__ import annotations

from dataclasses import dataclass

from .dominance import reconstruct_sequence
from .ktns import ktns
from .model import DominanceResult, SSPInstance


@dataclass(frozen=True, slots=True)
class UpperBoundResult:
    cost: int
    reduced_sequence: tuple[int, ...]
    full_sequence: tuple[int, ...]
    magazine_configs: tuple[frozenset[int], ...]


def greedy_sequence(
    start: int,
    requirements: tuple[frozenset[int], ...],
    distances: tuple[tuple[int, ...], ...],
    local_to_original: tuple[int, ...],
) -> tuple[int, ...]:
    remaining = set(range(len(requirements)))
    remaining.remove(start)
    sequence = [start]
    while remaining:
        current = sequence[-1]
        chosen = min(
            remaining,
            key=lambda job: (
                distances[current][job],
                -len(requirements[current] & requirements[job]),
                local_to_original[job],
            ),
        )
        sequence.append(chosen)
        remaining.remove(chosen)
    return tuple(sequence)


def construct_upper_bound(
    original: SSPInstance,
    dominance: DominanceResult,
    distances: tuple[tuple[int, ...], ...],
) -> UpperBoundResult:
    reduced = dominance.reduced
    best: UpperBoundResult | None = None
    for start in range(reduced.n):
        local_sequence = greedy_sequence(
            start, reduced.requirements, distances, reduced.local_to_original
        )
        representative_sequence = tuple(reduced.local_to_original[job] for job in local_sequence)
        full_sequence = reconstruct_sequence(representative_sequence, dominance)
        cost, configs = ktns(full_sequence, original.requirements, original.m, original.c)
        candidate = UpperBoundResult(cost, representative_sequence, full_sequence, configs)
        if best is None or (candidate.cost, candidate.full_sequence) < (best.cost, best.full_sequence):
            best = candidate
    assert best is not None
    return best
