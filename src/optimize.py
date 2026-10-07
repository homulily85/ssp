from __future__ import annotations

from contextlib import nullcontext
from time import perf_counter

from .dominance import preprocess_dominance
from .encoding import (
    build_direct_cnf,
    build_tsp_cnf,
    encode_direct_bound_fresh,
)
from .ktns import ktns
from .model import (
    ALGORITHM,
    ALGORITHMS,
    IterationResult,
    OptimizationResult,
    SolverResult,
    SSPInstance,
    TSPBuildResult,
)
from .solver import IncrementalSolverSession, unavailable_solver_stats
from .subtour import decode_successor, find_cycles, subtour_cut
from .upper_bound import construct_upper_bound
from .validate import validate_direct_solution, validate_tsp_solution


def lower_bound(instance: SSPInstance) -> int:
    required_tools: set[int] = set()
    for required in instance.requirements:
        required_tools.update(required)
    return len(required_tools)


def _inserted_tools(
    magazines: tuple[frozenset[int], ...]
) -> tuple[frozenset[int], ...]:
    previous: frozenset[int] = frozenset()
    inserted: list[frozenset[int]] = []
    for magazine in magazines:
        inserted.append(frozenset(magazine - previous))
        previous = magazine
    return tuple(inserted)


def _bound_assumptions(build: TSPBuildResult, k: int) -> list[int]:
    encoded_bound = k
    if encoded_bound < 0:
        raise AssertionError("decision bound must be non-negative")
    if encoded_bound >= build.t_literal_count:
        return []
    if encoded_bound >= len(build.totalizer_rhs):
        raise AssertionError(f"ITotalizer has no output for bound {k}")
    return [-build.totalizer_rhs[encoded_bound]]


def _iteration(
    build: TSPBuildResult,
    *,
    k: int,
    cegar_round: int,
    status: str,
    solve_time: float,
    stats: dict[str, int | float | None],
    total_subtour_cuts: int,
    subtours_found: int = 0,
    subtour_cuts_added: int = 0,
    actual_solution_cost: int | None = None,
) -> IterationResult:
    return IterationResult(
        k=k,
        cegar_round=cegar_round,
        status=status,
        primary_variables=build.variable_counts["primary"],
        auxiliary_variables=build.variable_counts["auxiliary"],
        variables=build.variable_counts["total"],
        clauses=build.base_clause_count + build.variable_counts.get("bound_clauses", 0) + total_subtour_cuts,
        solve_time=solve_time,
        subtours_found=subtours_found,
        subtour_cuts_added=subtour_cuts_added,
        total_subtour_cuts=total_subtour_cuts,
        actual_solution_cost=actual_solution_cost,
        stats=stats,
    )


def optimize_instance(
    instance: SSPInstance,
    time_limit: float = 600.0,
    *,
    algorithm: str,
) -> OptimizationResult:
    """Solve SSP with the explicitly selected incremental SAT encoding."""
    if time_limit <= 0:
        raise ValueError("time limit must be greater than zero")

    if algorithm not in ALGORITHMS:
        raise ValueError(f"unknown algorithm: {algorithm}")

    started = perf_counter()
    dominance = preprocess_dominance(instance)
    upper = construct_upper_bound(instance, dominance)
    lb = lower_bound(instance)

    best_cost = upper.cost
    best_reduced = upper.reduced_sequence
    best_full = upper.full_sequence
    best_magazines = upper.magazine_configs
    best_inserted = _inserted_tools(best_magazines)
    iterations: list[IterationResult] = []
    status = "OPTIMAL"

    # The upper-bound sequence is feasible; a matching valid lower bound is
    # already a certificate, so no SAT formula or worker is necessary.
    if best_cost > lb:
        first_k = best_cost - 1
        build = (build_direct_cnf(dominance.reduced, first_k,
                    dominance.original_to_local[upper.reduced_sequence[0]])
                 if algorithm == "direct-sat" else build_tsp_cnf(dominance.reduced, first_k))
        remaining = time_limit - (perf_counter() - started)
        if remaining <= 0:
            iterations.append(
                _iteration(
                    build,
                    k=first_k,
                    cegar_round=1 if algorithm == ALGORITHM else 0,
                    status="TIMEOUT",
                    solve_time=0.0,
                    stats=unavailable_solver_stats(),
                    total_subtour_cuts=0,
                )
            )
            status = "TIMEOUT"
        else:
            total_subtour_cuts = 0
            known_cuts: set[tuple[int, ...]] = set()
            next_k = first_k
            solver_context = (
                nullcontext()
                if algorithm == "direct-sat"
                else IncrementalSolverSession(build.cnf.clauses)
            )
            with solver_context as session:
                while next_k >= lb and status == "OPTIMAL":
                    k = next_k
                    cegar_round = 0
                    pending_clauses: list[list[int]] = []
                    while status == "OPTIMAL":
                        remaining = time_limit - (perf_counter() - started)
                        cegar_round += 1
                        if remaining <= 0:
                            iterations.append(
                                _iteration(
                                    build,
                                    k=k,
                                    cegar_round=cegar_round if algorithm == ALGORITHM else 0,
                                    status="TIMEOUT",
                                    solve_time=0.0,
                                    stats=unavailable_solver_stats(),
                                    total_subtour_cuts=total_subtour_cuts,
                                )
                            )
                            status = "TIMEOUT"
                            break

                        if algorithm == "direct-sat":
                            bound_clauses = encode_direct_bound_fresh(build, k)
                            assumptions = []
                            # This solver sees the base formula and exactly one
                            # freshly encoded objective bound. It is discarded
                            # before the next K, so neither learned clauses nor
                            # old objective counters can carry forward.
                            with IncrementalSolverSession(
                                build.cnf.clauses + bound_clauses
                            ) as fresh_session:
                                call_remaining = time_limit - (perf_counter() - started)
                                if call_remaining <= 0:
                                    solved = SolverResult(
                                        "TIMEOUT",
                                        0.0,
                                        None,
                                        unavailable_solver_stats(),
                                    )
                                else:
                                    solved = fresh_session.solve(
                                        new_clauses=[],
                                        assumptions=[],
                                        time_limit=call_remaining,
                                    )
                        else:
                            bound_clauses = []
                            assumptions = _bound_assumptions(build, k)
                            solved = session.solve(
                                new_clauses=pending_clauses + bound_clauses,
                                assumptions=assumptions,
                                time_limit=remaining,
                            )
                        pending_clauses = []
                        if solved.status == "TIMEOUT":
                            iterations.append(
                                _iteration(
                                    build,
                                    k=k,
                                    cegar_round=cegar_round if algorithm == ALGORITHM else 0,
                                    status="TIMEOUT",
                                    solve_time=solved.solve_time,
                                    stats=solved.stats,
                                    total_subtour_cuts=total_subtour_cuts,
                                )
                            )
                            status = "TIMEOUT"
                            break
                        if solved.status == "UNSAT":
                            iterations.append(
                                _iteration(
                                    build,
                                    k=k,
                                    cegar_round=cegar_round if algorithm == ALGORITHM else 0,
                                    status="UNSAT",
                                    solve_time=solved.solve_time,
                                    stats=solved.stats,
                                    total_subtour_cuts=total_subtour_cuts,
                                )
                            )
                            # First UNSAT bound certifies the latest incumbent.
                            next_k = lb - 1
                            break
                        if solved.status != "SAT" or solved.model is None:
                            raise AssertionError("solver returned an invalid SAT result")

                        bad_cycles = []
                        if algorithm == ALGORITHM:
                            successor = decode_successor(solved.model, build.vars_x, dominance.reduced.n)
                            bad_cycles = [cycle for cycle in find_cycles(successor) if 0 not in cycle]
                        if bad_cycles:
                            learned = [
                                subtour_cut(cycle, build.vars_x, dominance.reduced.n)
                                for cycle in bad_cycles
                            ]
                            pending_clauses = [
                                clause
                                for clause in learned
                                if tuple(clause) not in known_cuts
                            ]
                            if not pending_clauses:
                                raise AssertionError("CEGAR rediscovered only known subtour cuts")
                            known_cuts.update(map(tuple, pending_clauses))
                            total_subtour_cuts += len(pending_clauses)
                            iterations.append(
                                _iteration(
                                    build,
                                    k=k,
                                    cegar_round=cegar_round if algorithm == ALGORITHM else 0,
                                    status="SAT",
                                    solve_time=solved.solve_time,
                                    stats=solved.stats,
                                    total_subtour_cuts=total_subtour_cuts,
                                    subtours_found=len(bad_cycles),
                                    subtour_cuts_added=len(pending_clauses),
                                )
                            )
                            continue

                        validator = (validate_direct_solution if algorithm == "direct-sat"
                                     else validate_tsp_solution)
                        validated = validator(
                            instance, dominance, build, solved.model, k
                        )
                        iterations.append(
                            _iteration(
                                build,
                                k=k,
                                cegar_round=cegar_round if algorithm == ALGORITHM else 0,
                                status="SAT",
                                solve_time=solved.solve_time,
                                stats=solved.stats,
                                total_subtour_cuts=total_subtour_cuts,
                                actual_solution_cost=validated.sat_cost,
                            )
                        )
                        if (validated.ktns_cost, validated.full_sequence) < (
                            best_cost,
                            best_full,
                        ):
                            best_cost = validated.ktns_cost
                            best_reduced = validated.reduced_sequence
                            best_full = validated.full_sequence
                            best_magazines = validated.ktns_magazine_configs
                            best_inserted = _inserted_tools(best_magazines)

                        # A SAT witness may be strictly cheaper than the tested
                        # bound; skip all redundant intermediate bounds.
                        next_k = best_cost - 1
                        break

    verification_cost, _ = ktns(
        best_full, instance.requirements, instance.m, instance.c
    )
    if verification_cost > best_cost:
        raise AssertionError("KTNS cost exceeds incumbent cost")
    if sum(map(len, best_inserted)) != best_cost:
        raise AssertionError("stored insertion sets do not match the incumbent cost")
    return OptimizationResult(
        instance=instance,
        dominance=dominance,
        algorithm=algorithm,
        status=status,
        lower_bound=lb,
        initial_upper_bound=upper.cost,
        initial_reduced_sequence=upper.reduced_sequence,
        initial_sequence=upper.full_sequence,
        best_cost=best_cost,
        optimum=best_cost if status == "OPTIMAL" else None,
        optimal_reduced_sequence=best_reduced,
        optimal_sequence=best_full,
        magazine_configs=best_magazines,
        inserted_tools=best_inserted,
        verification_cost=verification_cost,
        iterations=tuple(iterations),
        total_runtime=perf_counter() - started,
    )
