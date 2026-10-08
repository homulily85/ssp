from __future__ import annotations

from time import perf_counter

from .dominance import preprocess_dominance, reconstruct_sequence
from .job_grouping import STRENGTHS, build_job_grouping_cnf, decode_job_grouping
from .ktns import ktns_switches
from .model import (
    IterationResult, OptimizationResult, SSPInstance, SolverResult,
    JOB_GROUPING_ALGORITHM,
)
from .solver import IncrementalSolverSession, unavailable_solver_stats
from .upper_bound import construct_upper_bound


def _free_load_lower_bound(instance: SSPInstance) -> int:
    distinct = {tool for row in instance.requirements for tool in row}
    return max(0, len(distinct) - instance.c)


def _charged_transitions(configs: tuple[frozenset[int], ...]) -> tuple[frozenset[int], ...]:
    result: list[frozenset[int]] = []
    for position, config in enumerate(configs):
        previous = configs[position - 1] if position else config
        result.append(frozenset(config - previous))
    return tuple(result)


def _count_consecutive_configurations(
    configs: tuple[frozenset[int], ...]
) -> int:
    return sum(position == 0 or config != configs[position - 1]
               for position, config in enumerate(configs))


def optimize_grouping_instance(
    instance: SSPInstance, *, time_limit: float, strength: str = "clique"
) -> OptimizationResult:
    if time_limit <= 0:
        raise ValueError("time limit must be greater than zero")
    if strength not in STRENGTHS:
        raise ValueError(f"grouping strength must be one of {STRENGTHS}")
    started = perf_counter()
    dominance = preprocess_dominance(instance)
    upper = construct_upper_bound(instance, dominance)
    lb = _free_load_lower_bound(instance)
    best_full = upper.full_sequence
    best_cost, best_magazines = ktns_switches(
        best_full, instance.requirements, instance.m, instance.c
    )
    preprocessing_time = perf_counter() - started
    best_reduced = upper.reduced_sequence
    initial_ub = best_cost
    time_to_best = preprocessing_time
    inserted = _charged_transitions(best_magazines)
    iterations: list[IterationResult] = []
    status = "OPTIMAL" if best_cost == lb else "TIMEOUT"
    last_groups = _count_consecutive_configurations(best_magazines)
    encoding_time = 0.0
    next_bound = best_cost - 1

    while next_bound >= lb and status != "OPTIMAL":
        remaining = time_limit - (perf_counter() - started)
        if remaining <= 0:
            status = "TIMEOUT"
            break
        build = build_job_grouping_cnf(dominance.reduced, next_bound, strength)
        encoding_time += build.encoding_time
        preprocessing_time += build.preprocessing_time
        remaining = time_limit - (perf_counter() - started)
        if remaining <= 0:
            iterations.append(IterationResult(
                k=next_bound, cegar_round=0, status="TIMEOUT",
                primary_variables=build.variable_counts["primary"],
                auxiliary_variables=build.variable_counts["auxiliary"],
                variables=build.variable_counts["total"], clauses=len(build.cnf.clauses),
                solve_time=0.0, stats=unavailable_solver_stats(),
            ))
            status = "TIMEOUT"
            break
        try:
            with IncrementalSolverSession(build.cnf.clauses) as session:
                call_remaining = time_limit - (perf_counter() - started)
                if call_remaining <= 0:
                    solved = SolverResult(
                        "TIMEOUT", 0.0, None, unavailable_solver_stats()
                    )
                else:
                    solved = session.solve(
                        new_clauses=[], assumptions=[], time_limit=call_remaining
                    )
        except KeyboardInterrupt:
            raise
        if solved.status == "TIMEOUT":
            iterations.append(IterationResult(
                k=next_bound, cegar_round=0, status="TIMEOUT",
                primary_variables=build.variable_counts["primary"],
                auxiliary_variables=build.variable_counts["auxiliary"],
                variables=build.variable_counts["total"], clauses=len(build.cnf.clauses),
                solve_time=solved.solve_time, stats=solved.stats,
            ))
            status = "TIMEOUT"
            break
        if solved.status == "UNSAT":
            iterations.append(IterationResult(
                k=next_bound, cegar_round=0, status="UNSAT",
                primary_variables=build.variable_counts["primary"],
                auxiliary_variables=build.variable_counts["auxiliary"],
                variables=build.variable_counts["total"], clauses=len(build.cnf.clauses),
                solve_time=solved.solve_time, stats=solved.stats,
            ))
            status = "OPTIMAL"
            break
        if solved.status != "SAT" or solved.model is None:
            raise AssertionError("fresh grouping solver returned an invalid result")

        local_sequence, _magazines, encoded_cost = decode_job_grouping(
            build, dominance.reduced, solved.model
        )
        representative_sequence = tuple(
            dominance.local_to_original[job] for job in local_sequence
        )
        full_sequence = reconstruct_sequence(representative_sequence, dominance)
        exact_cost, exact_magazines = ktns_switches(
            full_sequence, instance.requirements, instance.m, instance.c
        )
        if exact_cost > encoded_cost:
            raise AssertionError(
                f"decoded sequence costs {exact_cost}, above encoded bound {encoded_cost}"
            )
        iterations.append(IterationResult(
            k=next_bound, cegar_round=0, status="SAT",
            primary_variables=build.variable_counts["primary"],
            auxiliary_variables=build.variable_counts["auxiliary"],
            variables=build.variable_counts["total"], clauses=len(build.cnf.clauses),
            solve_time=solved.solve_time, actual_solution_cost=exact_cost,
            stats=solved.stats,
        ))
        if (exact_cost, full_sequence) < (best_cost, best_full):
            best_cost, best_full, best_magazines = exact_cost, full_sequence, exact_magazines
            best_reduced = representative_sequence
            inserted = _charged_transitions(best_magazines)
            last_groups = len(_magazines)
            time_to_best = perf_counter() - started
        if best_cost == lb:
            status = "OPTIMAL"
        next_bound = best_cost - 1
        del solved, build, local_sequence, _magazines

    verification, verified_magazines = ktns_switches(
        best_full, instance.requirements, instance.m, instance.c
    )
    if verification != best_cost or verified_magazines != best_magazines:
        raise AssertionError("free-preload incumbent failed independent verification")
    if sum(map(len, inserted)) != best_cost:
        raise AssertionError("charged transitions do not equal incumbent cost")
    return OptimizationResult(
        instance=instance, dominance=dominance, algorithm=JOB_GROUPING_ALGORITHM,
        status=status, lower_bound=lb, initial_upper_bound=initial_ub,
        initial_reduced_sequence=upper.reduced_sequence,
        initial_sequence=upper.full_sequence, best_cost=best_cost,
        optimum=best_cost if status == "OPTIMAL" else None,
        optimal_reduced_sequence=best_reduced, optimal_sequence=best_full,
        magazine_configs=best_magazines, inserted_tools=inserted,
        verification_cost=verification, iterations=tuple(iterations),
        total_runtime=perf_counter() - started, grouping_strength=strength,
        number_of_groups=last_groups, encoding_time=encoding_time,
        preprocessing_time=preprocessing_time, time_to_best=time_to_best,
    )
