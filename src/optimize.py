from __future__ import annotations

from time import perf_counter

from .distances import pairwise_distances
from .dominance import preprocess_dominance
from .encoding import build_cnf
from .ktns import ktns
from .model import IterationResult, OptimizationResult, SSPInstance
from .solver import solve_cnf
from .upper_bound import construct_upper_bound
from .validate import validate_sat_solution


def lower_bound(instance: SSPInstance) -> int:
    required_tools: set[int] = set()
    for required in instance.requirements:
        required_tools.update(required)
    return max(instance.c, len(required_tools))


def optimize_instance(instance: SSPInstance) -> OptimizationResult:
    started = perf_counter()
    dominance = preprocess_dominance(instance)
    distances = pairwise_distances(dominance.reduced)
    upper = construct_upper_bound(instance, dominance, distances)
    lb = lower_bound(instance)

    best_cost = upper.cost
    best_reduced = upper.reduced_sequence
    best_full = upper.full_sequence
    iterations: list[IterationResult] = []

    if best_cost > lb:
        for k in range(upper.cost - 1, lb - 1, -1):
            build = build_cnf(dominance.reduced, k, distances)
            solved = solve_cnf(build)
            iterations.append(
                IterationResult(
                    k=k,
                    status=solved.status,
                    primary_variables=build.variable_counts["primary"],
                    auxiliary_variables=build.variable_counts["auxiliary"],
                    variables=build.variable_counts["total"],
                    clauses=len(build.cnf.clauses),
                    solve_time=solved.solve_time,
                    stats=solved.stats,
                )
            )
            if solved.status == "UNSAT":
                break
            if solved.model is None:
                raise AssertionError("SAT result did not contain a model")
            validated = validate_sat_solution(instance, dominance, build, solved.model, k)
            if (validated.ktns_cost, validated.full_sequence) < (best_cost, best_full):
                best_cost = validated.ktns_cost
                best_reduced = validated.reduced_sequence
                best_full = validated.full_sequence

    verification_cost, _ = ktns(best_full, instance.requirements, instance.m, instance.c)
    if verification_cost != best_cost:
        raise AssertionError(
            f"stored cost {best_cost} does not match final KTNS cost {verification_cost}"
        )
    return OptimizationResult(
        instance=instance,
        dominance=dominance,
        lower_bound=lb,
        initial_upper_bound=upper.cost,
        initial_reduced_sequence=upper.reduced_sequence,
        initial_sequence=upper.full_sequence,
        optimum=best_cost,
        optimal_reduced_sequence=best_reduced,
        optimal_sequence=best_full,
        verification_cost=verification_cost,
        iterations=tuple(iterations),
        total_runtime=perf_counter() - started,
    )
