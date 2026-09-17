from __future__ import annotations

from time import perf_counter

from .distances import pairwise_distances
from .dominance import preprocess_dominance
from .encoding import adjacency_clauses, build_cnf, build_incremental_cnf
from .ktns import ktns
from .model import IterationResult, OptimizationResult, SSPInstance, SolverResult
from .solver import IncrementalSolverSession, solve_cnf
from .upper_bound import construct_upper_bound
from .validate import validate_sat_solution


def lower_bound(instance: SSPInstance) -> int:
    required_tools: set[int] = set()
    for required in instance.requirements:
        required_tools.update(required)
    return max(instance.c, len(required_tools))


def optimize_instance(
    instance: SSPInstance,
    time_limit: float = 600.0,
    *,
    incremental: bool = False,
) -> OptimizationResult:
    if time_limit <= 0:
        raise ValueError("time limit must be greater than zero")
    started = perf_counter()
    dominance = preprocess_dominance(instance)
    distances = pairwise_distances(dominance.reduced)
    upper = construct_upper_bound(instance, dominance, distances)
    lb = lower_bound(instance)

    best_cost = upper.cost
    best_reduced = upper.reduced_sequence
    best_full = upper.full_sequence
    iterations: list[IterationResult] = []
    status = "OPTIMAL"

    if best_cost > lb and not incremental:
        for k in range(upper.cost - 1, lb - 1, -1):
            remaining = time_limit - (perf_counter() - started)
            if remaining <= 0:
                iterations.append(
                    IterationResult(
                        k=k,
                        status="TIMEOUT",
                        primary_variables=0,
                        auxiliary_variables=0,
                        variables=0,
                        clauses=0,
                        solve_time=0.0,
                        stats={},
                    )
                )
                status = "TIMEOUT"
                break
            build = build_cnf(dominance.reduced, k, distances)
            remaining = time_limit - (perf_counter() - started)
            solved = (
                solve_cnf(build, time_limit=remaining)
                if remaining > 0
                else SolverResult("TIMEOUT", 0.0, None, {})
            )
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
            if solved.status == "TIMEOUT":
                status = "TIMEOUT"
                break
            if solved.status == "UNSAT":
                break
            if solved.model is None:
                raise AssertionError("SAT result did not contain a model")
            validated = validate_sat_solution(instance, dominance, build, solved.model, k)
            if (validated.ktns_cost, validated.full_sequence) < (best_cost, best_full):
                best_cost = validated.ktns_cost
                best_reduced = validated.reduced_sequence
                best_full = validated.full_sequence

    if best_cost > lb and incremental:
        first_k = upper.cost - 1
        remaining = time_limit - (perf_counter() - started)
        if remaining <= 0:
            iterations.append(
                IterationResult(
                    k=first_k,
                    status="TIMEOUT",
                    primary_variables=0,
                    auxiliary_variables=0,
                    variables=0,
                    clauses=0,
                    solve_time=0.0,
                    stats={},
                )
            )
            status = "TIMEOUT"
        else:
            build = build_incremental_cnf(dominance.reduced, first_k, distances)
            remaining = time_limit - (perf_counter() - started)
            if remaining <= 0:
                iterations.append(
                    IterationResult(
                        k=first_k,
                        status="TIMEOUT",
                        primary_variables=build.variable_counts["primary"],
                        auxiliary_variables=build.variable_counts["auxiliary"],
                        variables=build.variable_counts["total"],
                        clauses=len(build.cnf.clauses),
                        solve_time=0.0,
                        stats={},
                    )
                )
                status = "TIMEOUT"
            else:
                added_adjacency: set[tuple[int, ...]] = set()
                with IncrementalSolverSession(build.cnf.clauses) as session:
                    for k in range(first_k, lb - 1, -1):
                        remaining = time_limit - (perf_counter() - started)
                        if remaining <= 0:
                            iterations.append(
                                IterationResult(
                                    k=k,
                                    status="TIMEOUT",
                                    primary_variables=build.variable_counts["primary"],
                                    auxiliary_variables=build.variable_counts["auxiliary"],
                                    variables=build.variable_counts["total"],
                                    clauses=len(build.cnf.clauses) + len(added_adjacency),
                                    solve_time=0.0,
                                    stats={},
                                )
                            )
                            status = "TIMEOUT"
                            break

                        active_adjacency = adjacency_clauses(
                            dominance.reduced, distances, k, build.vars_x
                        )
                        new_adjacency = [
                            clause
                            for clause in active_adjacency
                            if tuple(clause) not in added_adjacency
                        ]
                        if k < build.t_literal_count and k >= len(build.totalizer_rhs):
                            raise AssertionError(f"ITotalizer has no output for bound {k}")
                        assumptions = (
                            [-build.totalizer_rhs[k]]
                            if k < build.t_literal_count
                            else []
                        )
                        remaining = time_limit - (perf_counter() - started)
                        if remaining <= 0:
                            iterations.append(
                                IterationResult(
                                    k=k,
                                    status="TIMEOUT",
                                    primary_variables=build.variable_counts["primary"],
                                    auxiliary_variables=build.variable_counts["auxiliary"],
                                    variables=build.variable_counts["total"],
                                    clauses=len(build.cnf.clauses) + len(added_adjacency),
                                    solve_time=0.0,
                                    stats={},
                                )
                            )
                            status = "TIMEOUT"
                            break
                        added_adjacency.update(map(tuple, new_adjacency))
                        solved = session.solve(
                            new_clauses=new_adjacency,
                            assumptions=assumptions,
                            time_limit=remaining,
                        )
                        iterations.append(
                            IterationResult(
                                k=k,
                                status=solved.status,
                                primary_variables=build.variable_counts["primary"],
                                auxiliary_variables=build.variable_counts["auxiliary"],
                                variables=build.variable_counts["total"],
                                clauses=len(build.cnf.clauses) + len(added_adjacency),
                                solve_time=solved.solve_time,
                                stats=solved.stats,
                            )
                        )
                        if solved.status == "TIMEOUT":
                            status = "TIMEOUT"
                            break
                        if solved.status == "UNSAT":
                            break
                        if solved.model is None:
                            raise AssertionError("SAT result did not contain a model")
                        validated = validate_sat_solution(
                            instance, dominance, build, solved.model, k
                        )
                        if (validated.ktns_cost, validated.full_sequence) < (
                            best_cost,
                            best_full,
                        ):
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
        mode="incremental" if incremental else "standard",
        status=status,
        lower_bound=lb,
        initial_upper_bound=upper.cost,
        initial_reduced_sequence=upper.reduced_sequence,
        initial_sequence=upper.full_sequence,
        best_cost=best_cost,
        optimum=best_cost if status == "OPTIMAL" else None,
        optimal_reduced_sequence=best_reduced,
        optimal_sequence=best_full,
        verification_cost=verification_cost,
        iterations=tuple(iterations),
        total_runtime=perf_counter() - started,
    )
