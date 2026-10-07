from __future__ import annotations

from .dominance import reconstruct_sequence
from .ktns import ktns
from .model import (
    DominanceResult,
    SSPInstance,
    TSPBuildResult,
    DirectBuildResult,
    ValidationResult,
)
from .subtour import decode_hamiltonian_sequence, decode_successor, find_cycles


def _validate_solution(
    original: SSPInstance,
    dominance: DominanceResult,
    build: TSPBuildResult,
    model: tuple[int, ...] | list[int],
    k: int,
) -> ValidationResult:
    """Independently verify permutation, magazine transitions and insertion cost."""
    reduced = dominance.reduced
    positive = {literal for literal in model if literal > 0}
    if isinstance(build, DirectBuildResult):
        decoded: list[int] = []
        for pos in range(reduced.n):
            selected = [job for job in range(reduced.n)
                        if build.vars_x[job, pos] in positive]
            if len(selected) != 1:
                raise AssertionError(f"position {pos} does not select exactly one job")
            decoded.append(selected[0])
        local_sequence = tuple(decoded)
        if set(local_sequence) != set(range(reduced.n)):
            raise AssertionError("direct model is not a permutation")
        if local_sequence.index(build.anchor_job) >= (reduced.n + 1) // 2:
            raise AssertionError("direct model violates reversal symmetry breaking")
        vertices = tuple(range(reduced.n))
    else:
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
    encoded_sat_cost = 0
    for position, (vertex, local_job) in enumerate(zip(vertices, local_sequence)):
        encoded_magazine = {
            tool for tool in range(reduced.m) if build.vars_z[tool, vertex] in positive
        }
        required = reduced.requirements[local_job]
        if len(encoded_magazine) > reduced.c:
            raise AssertionError(
                f"SAT magazine for vertex {vertex} has {len(encoded_magazine)} tools, maximum {reduced.c}"
            )
        if not required <= encoded_magazine:
            raise AssertionError(f"SAT magazine for vertex {vertex} misses required tools")

        expected_inserted = (
            encoded_magazine if position == 0 else encoded_magazine - previous
        )
        actual_inserted = {
            tool for tool in range(reduced.m) if build.vars_t[tool, vertex] in positive
        }
        if actual_inserted != expected_inserted:
            raise AssertionError(
                f"incorrect insertion set for vertex {vertex}: "
                f"{sorted(actual_inserted)} != {sorted(expected_inserted)}"
            )
        original_magazine = frozenset(
            reduced.tool_to_original[tool] for tool in encoded_magazine
        )
        original_inserted = frozenset(
            reduced.tool_to_original[tool] for tool in actual_inserted
        )
        magazines.append(original_magazine)
        inserted.append(original_inserted)
        encoded_sat_cost += len(actual_inserted)
        previous = encoded_magazine

    sat_cost = encoded_sat_cost
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


def validate_tsp_solution(
    original: SSPInstance, dominance: DominanceResult, build: TSPBuildResult,
    model: tuple[int, ...] | list[int], k: int,
) -> ValidationResult:
    if isinstance(build, DirectBuildResult):
        raise TypeError("expected a TSP build")
    return _validate_solution(original, dominance, build, model, k)


def validate_direct_solution(
    original: SSPInstance, dominance: DominanceResult, build: DirectBuildResult,
    model: tuple[int, ...] | list[int], k: int,
) -> ValidationResult:
    if not isinstance(build, DirectBuildResult):
        raise TypeError("expected a direct build")
    return _validate_solution(original, dominance, build, model, k)
