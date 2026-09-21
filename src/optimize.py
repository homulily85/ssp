from __future__ import annotations

from time import perf_counter

from .distances import pairwise_distances
from .dominance import preprocess_dominance
from .encoding import build_tsp_cnf
from .ktns import ktns
from .model import ALGORITHM, IterationResult, OptimizationResult, SSPInstance, TSPBuildResult
from .solver import IncrementalSolverSession, unavailable_solver_stats
from .subtour import decode_successor, find_cycles, subtour_cut
from .upper_bound import construct_upper_bound
from .validate import validate_tsp_solution


def lower_bound(instance: SSPInstance) -> int:
    required_tools: set[int] = set()
    for required in instance.requirements:
        required_tools.update(required)
    return max(instance.c, len(required_tools))


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
    if k >= build.t_literal_count:
        return []
    if k < 0 or k >= len(build.totalizer_rhs):
        raise AssertionError(f"ITotalizer has no output for bound {k}")
    return [-build.totalizer_rhs[k]]


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
        clauses=build.base_clause_count + total_subtour_cuts,
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
) -> OptimizationResult:
    """Solve SSP exactly with one incremental TSP-SAT + CEGAR session."""
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
    best_magazines = upper.magazine_configs
    best_inserted = _inserted_tools(best_magazines)
    iterations: list[IterationResult] = []
    status = "OPTIMAL"

    # The upper-bound sequence is feasible; a matching valid lower bound is
    # already a certificate, so no SAT formula or worker is necessary.
    if best_cost > lb:
        first_k = best_cost - 1
        build = build_tsp_cnf(dominance.reduced, first_k)
        remaining = time_limit - (perf_counter() - started)
        if remaining <= 0:
            iterations.append(
                _iteration(
                    build,
                    k=first_k,
                    cegar_round=1,
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
            with IncrementalSolverSession(build.cnf.clauses) as session:
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
                                    cegar_round=cegar_round,
                                    status="TIMEOUT",
                                    solve_time=0.0,
                                    stats=unavailable_solver_stats(),
                                    total_subtour_cuts=total_subtour_cuts,
                                )
                            )
                            status = "TIMEOUT"
                            break

                        solved = session.solve(
                            new_clauses=pending_clauses,
                            assumptions=_bound_assumptions(build, k),
                            time_limit=remaining,
                        )
                        pending_clauses = []
                        if solved.status == "TIMEOUT":
                            iterations.append(
                                _iteration(
                                    build,
                                    k=k,
                                    cegar_round=cegar_round,
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
                                    cegar_round=cegar_round,
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

                        successor = decode_successor(
                            solved.model, build.vars_x, dominance.reduced.n
                        )
                        bad_cycles = [
                            cycle for cycle in find_cycles(successor) if 0 not in cycle
                        ]
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
                                    cegar_round=cegar_round,
                                    status="SAT",
                                    solve_time=solved.solve_time,
                                    stats=solved.stats,
                                    total_subtour_cuts=total_subtour_cuts,
                                    subtours_found=len(bad_cycles),
                                    subtour_cuts_added=len(pending_clauses),
                                )
                            )
                            continue

                        validated = validate_tsp_solution(
                            instance, dominance, build, solved.model, k
                        )
                        iterations.append(
                            _iteration(
                                build,
                                k=k,
                                cegar_round=cegar_round,
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
                        next_k = validated.sat_cost - 1
                        break

    verification_cost, _ = ktns(
        best_full, instance.requirements, instance.m, instance.c
    )
    if verification_cost != best_cost:
        raise AssertionError(
            f"stored cost {best_cost} does not match final KTNS cost {verification_cost}"
        )
    if sum(map(len, best_inserted)) != best_cost:
        raise AssertionError("stored insertion sets do not match the final KTNS cost")
    return OptimizationResult(
        instance=instance,
        dominance=dominance,
        algorithm=ALGORITHM,
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
