from __future__ import annotations

from .model import ReducedInstance


def pairwise_distances(instance: ReducedInstance) -> tuple[tuple[int, ...], ...]:
    return tuple(
        tuple(
            0 if i == h else max(0, len(instance.requirements[i] | instance.requirements[h]) - instance.c)
            for h in range(instance.n)
        )
        for i in range(instance.n)
    )
