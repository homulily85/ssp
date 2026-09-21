from __future__ import annotations

from .dominance import reconstruct_sequence
from .ktns import ktns
from .model import (
    CNFBuildResult,
    DominanceResult,
    SSPInstance,
    ValidationResult,
)


def decode_reduced_sequence(
    model: tuple[int, ...] | list[int],
    vars_x: dict[tuple[int, int], int],
    local_to_original: tuple[int, ...],
) -> tuple[int, ...]:
    positive = {literal for literal in model if literal > 0}
    n = len(local_to_original)
    local_sequence: list[int] = []
    for position in range(1, n + 1):
        jobs = [job for job in range(n) if vars_x[job, position] in positive]
        if len(jobs) != 1:
            raise AssertionError(
                f"position {position} has {len(jobs)} jobs in decoded SAT model"
            )
        local_sequence.append(jobs[0])
    if set(local_sequence) != set(range(n)):
        raise AssertionError("decoded reduced sequence is not a permutation")
    return tuple(local_to_original[job] for job in local_sequence)


def validate_sat_solution(
    original: SSPInstance,
    dominance: DominanceResult,
    build: CNFBuildResult,
    model: tuple[int, ...] | list[int],
    k: int,
) -> ValidationResult:
    positive = {literal for literal in model if literal > 0}
    representative_sequence = decode_reduced_sequence(
        model, build.vars_x, dominance.local_to_original
    )
    local_sequence = tuple(
        dominance.original_to_local[representative] for representative in representative_sequence
    )
    n, m, c = dominance.reduced.n, original.m, original.c
    previous = {tool for tool in range(m) if build.vars_z[tool, 0] in positive}
    if previous:
        raise AssertionError("SAT model does not have an empty initial magazine")
    sat_cost = 0
    for position, local_job in enumerate(local_sequence, 1):
        magazine = {
            tool for tool in range(m) if build.vars_z[tool, position] in positive
        }
        if len(magazine) != c:
            raise AssertionError(f"SAT magazine at position {position} has wrong capacity")
        required = dominance.reduced.requirements[local_job]
        if not required <= magazine:
            raise AssertionError(f"SAT magazine at position {position} misses required tools")
        for tool in range(m):
            expected_t = tool in magazine and tool not in previous
            if build.vars_t:
                actual_t = build.vars_t[tool, position] in positive
                if actual_t != expected_t:
                    raise AssertionError(
                        f"incorrect t[{tool},{position}] in SAT model: "
                        f"{actual_t} != {expected_t}"
                    )
            sat_cost += int(expected_t)
        previous = magazine
    if sat_cost > k:
        raise AssertionError(f"SAT cost {sat_cost} exceeds bound {k}")

    full_sequence = reconstruct_sequence(representative_sequence, dominance)
    full_cost, configs = ktns(
        full_sequence, original.requirements, original.m, original.c
    )
    if full_cost > k:
        raise AssertionError(f"reconstructed KTNS cost {full_cost} exceeds bound {k}")
    return ValidationResult(
        representative_sequence, full_sequence, sat_cost, full_cost, configs
    )
