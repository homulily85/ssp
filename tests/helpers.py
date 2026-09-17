from __future__ import annotations

from itertools import combinations, permutations
from pathlib import Path

from src.ktns import ktns
from src.model import SSPInstance


def make_instance(
    requirements: list[set[int]], m: int, c: int, name: str = "test"
) -> SSPInstance:
    n = len(requirements)
    matrix = tuple(
        tuple(tool in requirements[job] for job in range(n)) for tool in range(m)
    )
    return SSPInstance(
        name=name,
        n=n,
        m=m,
        c=c,
        matrix=matrix,
        requirements=tuple(frozenset(required) for required in requirements),
        source=Path(name),
        problem_id=1,
    )


def brute_force_optimum(instance: SSPInstance) -> tuple[int, tuple[int, ...]]:
    best: tuple[int, tuple[int, ...]] | None = None
    for sequence in permutations(range(instance.n)):
        cost, _ = ktns(sequence, instance.requirements, instance.m, instance.c)
        candidate = (cost, sequence)
        if best is None or candidate < best:
            best = candidate
    assert best is not None
    return best


def brute_force_magazine_cost(instance: SSPInstance, sequence: tuple[int, ...]) -> int:
    configurations = [
        frozenset(config) for config in combinations(range(instance.m), instance.c)
    ]
    feasible = [
        [config for config in configurations if instance.requirements[job] <= config]
        for job in sequence
    ]
    costs = {config: instance.c for config in feasible[0]}
    for position in range(1, len(sequence)):
        updated = {}
        for current in feasible[position]:
            updated[current] = min(
                previous_cost + len(current - previous)
                for previous, previous_cost in costs.items()
            )
        costs = updated
    return min(costs.values())
