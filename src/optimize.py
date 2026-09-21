from __future__ import annotations

from time import perf_counter

from .distances import pairwise_distances
from .dominance import preprocess_dominance
from .encoding import (
    adjacency_clauses,
    build_cnf,
    build_incremental_cnf,
    build_maxsat_no_t_wcnf,
    build_maxsat_wcnf,
)
from .ktns import ktns
from .model import (
    AdditionalConstraints,
    IterationResult,
    OPTIMIZATION_MODES,
    OptimizationMode,
    OptimizationResult,
    SSPInstance,
    SolverResult,
)
from .solver import (
    IncrementalSolverSession,
    solve_cnf,
    solve_maxsat,
    unavailable_solver_stats,
)
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
    mode: OptimizationMode = "standard",
    additional_constraints: AdditionalConstraints | None = None,
) -> OptimizationResult:
    if time_limit <= 0:
        raise ValueError("time limit must be greater than zero")
    if mode not in OPTIMIZATION_MODES:
        raise ValueError(f"unknown optimization mode: {mode}")
    started = perf_counter()
    constraints = (
        additional_constraints
        if additional_constraints is not None
        else AdditionalConstraints.all()
    )
    dominance = preprocess_dominance(instance)
    distances = pairwise_distances(dominance.reduced)
    upper = construct_upper_bound(instance, dominance, distances)
    lb = lower_bound(instance)

    best_cost = upper.cost
    best_reduced = upper.reduced_sequence
    best_full = upper.full_sequence
    iterations: list[IterationResult] = []
    status = "OPTIMAL"

    if best_cost > lb and mode in ("maxsat", "maxsat-no-t"):
        remaining = time_limit - (perf_counter() - started)
        if remaining <= 0:
            iterations.append(
                IterationResult(
                    k=None,
                    status="TIMEOUT",
                    primary_variables=0,
                    auxiliary_variables=0,
                    variables=0,
                    clauses=0,
                    solve_time=0.0,
                    stats=unavailable_solver_stats(),
                )
            )
            status = "TIMEOUT"
        else:
            builder = (
                build_maxsat_no_t_wcnf
                if mode == "maxsat-no-t"
                else build_maxsat_wcnf
            )
            maxsat_build = builder(
                dominance.reduced,
                upper.cost,
                distances,
                additional_constraints=constraints,
            )
            build = maxsat_build.core
            remaining = time_limit - (perf_counter() - started)
            solved = (
                solve_maxsat(maxsat_build, time_limit=remaining)
                if remaining > 0
                else SolverResult(
                    "TIMEOUT", 0.0, None, unavailable_solver_stats()
                )
            )
            objective = (
                solved.objective + instance.c
                if mode == "maxsat-no-t" and solved.objective is not None
                else solved.objective
            )
            iterations.append(
                IterationResult(
                    k=None,
                    status=solved.status,
                    primary_variables=build.variable_counts["primary"],
                    auxiliary_variables=build.variable_counts["auxiliary"],
                    variables=build.variable_counts["total"],
                    clauses=len(maxsat_build.wcnf.hard)
                    + len(maxsat_build.wcnf.soft),
                    solve_time=solved.solve_time,
                    stats=solved.stats,
                    objective=objective,
                )
            )
            if solved.status == "UNSAT":
                raise AssertionError("MaxSAT hard clauses are unexpectedly unsatisfiable")
            if solved.model is not None:
                if objective is None:
                    raise AssertionError("MaxSAT model did not contain an objective")
                validated = validate_sat_solution(
                    instance,
                    dominance,
                    build,
                    solved.model,
                    objective,
                )
                if validated.sat_cost != objective:
                    raise AssertionError(
                        "MaxSAT objective does not match magazine transitions: "
                        f"{objective} != {validated.sat_cost}"
                    )
                if solved.status == "OPTIMAL" and (
                    validated.ktns_cost != objective
                ):
                    raise AssertionError(
                        "optimal reduced MaxSAT cost does not match reconstructed "
                        f"KTNS cost: {objective} != {validated.ktns_cost}"
                    )
                if (validated.ktns_cost, validated.full_sequence) < (
                    best_cost,
                    best_full,
                ):
                    best_cost = validated.ktns_cost
                    best_reduced = validated.reduced_sequence
                    best_full = validated.full_sequence
            if solved.status == "TIMEOUT":
                status = "TIMEOUT"

    if best_cost > lb and mode == "standard":
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
                        stats=unavailable_solver_stats(),
                    )
                )
                status = "TIMEOUT"
                break
            build = build_cnf(
                dominance.reduced,
                k,
                distances,
                additional_constraints=constraints,
            )
            remaining = time_limit - (perf_counter() - started)
            solved = (
                solve_cnf(build, time_limit=remaining)
                if remaining > 0
                else SolverResult(
                    "TIMEOUT", 0.0, None, unavailable_solver_stats()
                )
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

    if best_cost > lb and mode == "incremental":
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
                    stats=unavailable_solver_stats(),
                )
            )
            status = "TIMEOUT"
        else:
            build = build_incremental_cnf(
                dominance.reduced,
                first_k,
                distances,
                additional_constraints=constraints,
            )
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
                        stats=unavailable_solver_stats(),
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
                                    stats=unavailable_solver_stats(),
                                )
                            )
                            status = "TIMEOUT"
                            break

                        active_adjacency = (
                            adjacency_clauses(
                                dominance.reduced, distances, k, build.vars_x
                            )
                            if constraints.adjacency
                            else []
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
                                    stats=unavailable_solver_stats(),
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
        mode=mode,
        additional_constraints=constraints.enabled_names(),
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
