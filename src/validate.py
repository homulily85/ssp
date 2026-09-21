from __future__ import annotations

from .dominance import reconstruct_sequence
from .ktns import ktns
from .model import (
    DominanceResult,
    SSPInstance,
    TSPBuildResult,
    ValidationResult,
)
from .subtour import decode_hamiltonian_sequence, decode_successor, find_cycles


def validate_tsp_solution(
    original: SSPInstance,
    dominance: DominanceResult,
    build: TSPBuildResult,
    model: tuple[int, ...] | list[int],
    k: int,
) -> ValidationResult:
    """Independently verify a Hamiltonian TSP-SSP SAT model.

    This routine deliberately recomputes every magazine transition from z and
    x.  It never relies on clauses emitted by the encoder to justify a model.
    """
    reduced = dominance.reduced
    positive = {literal for literal in model if literal > 0}
    successor = decode_successor(model, build.vars_x, reduced.n)
    cycles = find_cycles(successor)
    if len(cycles) != 1 or len(cycles[0]) != reduced.n + 1 or 0 not in cycles[0]:
        raise AssertionError("SAT model is a cycle cover rather than a Hamiltonian cycle")

    vertices = decode_hamiltonian_sequence(successor, reduced.n)
    local_sequence = tuple(vertex - 1 for vertex in vertices)
    representative_sequence = tuple(
        reduced.local_to_original[local] for local in local_sequence
    )
    if set(local_sequence) != set(range(reduced.n)):
        raise AssertionError("decoded TSP sequence is not a reduced-job permutation")

    magazines: list[frozenset[int]] = []
    inserted: list[frozenset[int]] = []
    previous: set[int] = set()
    sat_cost = 0
    for position, (vertex, local_job) in enumerate(zip(vertices, local_sequence)):
        magazine = {
            tool for tool in range(reduced.m) if build.vars_z[tool, vertex] in positive
        }
        required = reduced.requirements[local_job]
        if len(magazine) != reduced.c:
            raise AssertionError(
                f"SAT magazine for vertex {vertex} has {len(magazine)} tools, expected {reduced.c}"
            )
        if not required <= magazine:
            raise AssertionError(f"SAT magazine for vertex {vertex} misses required tools")

        expected_inserted = magazine if position == 0 else magazine - previous
        actual_inserted = {
            tool for tool in range(reduced.m) if build.vars_t[tool, vertex] in positive
        }
        if actual_inserted != expected_inserted:
            raise AssertionError(
                f"incorrect insertion set for vertex {vertex}: "
                f"{sorted(actual_inserted)} != {sorted(expected_inserted)}"
            )
        magazines.append(frozenset(magazine))
        inserted.append(frozenset(actual_inserted))
        sat_cost += len(actual_inserted)
        previous = magazine

    if sat_cost > k:
        raise AssertionError(f"SAT insertion cost {sat_cost} exceeds bound {k}")

    full_sequence = reconstruct_sequence(representative_sequence, dominance)
    ktns_cost, ktns_magazines = ktns(
        full_sequence,
        original.requirements,
        original.m,
        original.c,
    )
    # A dominated job can reuse its representative's magazine.  KTNS on the
    # reconstructed full sequence therefore cannot be worse than the decoded
    # reduced SAT policy.
    if ktns_cost > sat_cost:
        raise AssertionError(
            f"reconstructed KTNS cost {ktns_cost} exceeds SAT cost {sat_cost}"
        )
    return ValidationResult(
        reduced_sequence=representative_sequence,
        full_sequence=full_sequence,
        sat_cost=sat_cost,
        ktns_cost=ktns_cost,
        magazine_configs=tuple(magazines),
        inserted_tools=tuple(inserted),
        ktns_magazine_configs=ktns_magazines,
    )
