"""Order-SAT master with exact KTNS checking and subsequence CEGAR cuts.

Run from the repository root with ``python -m experiments.order_ktns_cegar``.
This is an experimental optimizer and does not alter the production solvers.
"""
from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, Iterable, Sequence

from pysat.formula import IDPool

from src.dominance import preprocess_dominance, reconstruct_sequence
from src.ktns import ktns
from src.model import SSPInstance, SolverResult
from src.optimize import lower_bound
from src.parser import parse_file
from src.solver import IncrementalSolverSession, unavailable_solver_stats
from src.upper_bound import construct_upper_bound


ROOT = Path(__file__).resolve().parents[1]
REFERENCE_COSTS = {
    ("datB1", 1): 25,
    ("datB1", 2): 32,
    ("datB1", 3): 29,
    ("datC1", 1): 103,
    ("datC1", 2): 109,
    ("datC1", 3): 100,
}
STAT_KEYS = ("restarts", "conflicts", "decisions", "propagations")
ITERATION_FIELDS = (
    "dataset", "problem", "reference_cost", "k", "cegar_round", "status",
    "solve_time", "elapsed_total", "candidate_sequence", "candidate_sequence_original",
    "candidate_cost", "candidate_full_cost", "incumbent_before", "incumbent_after",
    "core_size_before", "core_size_after", "core_sequence", "cut_length",
    "cut_type", "shrink_calls", "shrink_time", "shrink_completed", "duplicate_cut",
    "candidates_at_k", "cuts_at_k", "total_cuts", "master_variables",
    "master_base_clauses", "master_transitivity_clauses", "current_master_clauses",
    "is_solver_call",
    "restarts", "conflicts", "decisions", "propagations",
)
SUMMARY_FIELDS = (
    "dataset", "problem", "reference_cost", "initial_ub", "final_incumbent",
    "gap_to_reference", "status", "total_runtime", "solver_calls",
    "candidate_sequences", "total_cuts", "duplicate_cuts", "total_shrink_calls",
    "total_shrink_time", "avg_core_size", "min_core_size", "max_core_size",
    "avg_core_ratio", "avg_cut_length", "total_conflicts", "total_decisions",
    "total_propagations", "total_restarts", "best_incumbent_time", "tested_bounds",
)
BOUNDS_FIELDS = (
    "dataset", "problem", "reference_cost", "k", "candidates_at_k", "cuts_at_k",
    "avg_core_size", "min_core_size", "max_core_size", "avg_core_ratio",
    "avg_cut_length", "best_cost_at_k", "elapsed_at_k_end",
)


@dataclass(frozen=True)
class OrderMaster:
    n: int
    order_vars: dict[tuple[int, int], int]
    clauses: tuple[tuple[int, ...], ...]
    transitivity_clause_count: int
    symmetry_clause_count: int

    @property
    def variable_count(self) -> int:
        return len(self.order_vars)

    @property
    def base_clause_count(self) -> int:
        return len(self.clauses)

    def before_lit(self, i: int, j: int) -> int:
        if i == j or i not in range(self.n) or j not in range(self.n):
            raise ValueError("before_lit requires two distinct valid job IDs")
        return self.order_vars[i, j] if i < j else -self.order_vars[j, i]


def build_order_master(n: int, *, symmetry_break: bool = True) -> OrderMaster:
    """Build a pure tournament-order CNF with no position or tooling state."""
    if n < 1:
        raise ValueError("order master requires at least one job")
    pool = IDPool()
    variables = {(i, j): pool.id(("before", i, j))
                 for i in range(n) for j in range(i + 1, n)}
    clauses: list[tuple[int, ...]] = []
    for i, j, k in combinations(range(n), 3):
        o_ij, o_jk, o_ik = variables[i, j], variables[j, k], variables[i, k]
        clauses.append((-o_ij, -o_jk, o_ik))
        clauses.append((o_ij, o_jk, -o_ik))
    transitivity_count = len(clauses)
    symmetry_count = 0
    if symmetry_break and n >= 2:
        clauses.append((variables[0, 1],))
        symmetry_count = 1
    assert pool.top == n * (n - 1) // 2
    return OrderMaster(
        n=n,
        order_vars=variables,
        clauses=tuple(clauses),
        transitivity_clause_count=transitivity_count,
        symmetry_clause_count=symmetry_count,
    )


def before_lit(master: OrderMaster, i: int, j: int) -> int:
    """Return the signed literal asserting that i precedes j."""
    return master.before_lit(i, j)


def decode_order(model: Sequence[int], master: OrderMaster) -> tuple[int, ...]:
    """Decode and independently validate one total-order SAT model."""
    positive = {literal for literal in model if literal > 0}
    ranks = [0] * master.n
    relation: dict[tuple[int, int], bool] = {}
    for i in range(master.n):
        for j in range(i + 1, master.n):
            variable = master.order_vars[i, j]
            i_before_j = variable in positive
            relation[i, j] = i_before_j
            relation[j, i] = not i_before_j
            if i_before_j:
                ranks[j] += 1
            else:
                ranks[i] += 1
    if sorted(ranks) != list(range(master.n)):
        raise AssertionError(f"order model has non-unique or invalid ranks: {ranks}")
    sequence = tuple(sorted(range(master.n), key=ranks.__getitem__))
    if len(sequence) != master.n or set(sequence) != set(range(master.n)):
        raise AssertionError("decoded order is not a permutation")
    if len(set(ranks)) != master.n:
        raise AssertionError("decoded order ranks are not unique")
    for i in range(master.n):
        for j in range(i + 1, master.n):
            if relation[sequence[i], sequence[j]] is not True:
                raise AssertionError("decoded order disagrees with pairwise model")
    if (master.symmetry_clause_count and master.n >= 2
            and master.order_vars[0, 1] not in positive):
        raise AssertionError("decoded order violates reversal symmetry breaking")
    return sequence


def _ktns_reduced(sequence: Sequence[int], requirements, m: int, c: int):
    # Dominance compaction can leave no used tools. Add one unused dummy tool
    # solely to satisfy KTNS's public capacity precondition; it is never loaded.
    if m == 0:
        return ktns(sequence, requirements, 1, 1)
    return ktns(sequence, requirements, m, c)


@dataclass(frozen=True)
class ShrinkResult:
    core: tuple[int, ...]
    core_cost: int
    calls: int
    elapsed: float
    completed: bool


def shrink_subsequence(
    sequence: Sequence[int], requirements, m: int, c: int, k: int,
    *, deadline: float | None = None,
) -> ShrinkResult:
    """Deterministically delete jobs while preserving KTNS cost greater than k."""
    started = perf_counter()
    core = list(sequence)
    if deadline is not None and perf_counter() >= deadline:
        return ShrinkResult(tuple(core), 0, 0, perf_counter() - started, False)
    core_cost, _ = _ktns_reduced(core, requirements, m, c)
    if core_cost <= k:
        raise ValueError("cannot shrink a subsequence that does not violate the bound")
    calls = 0
    index = 0
    while index < len(core):
        if deadline is not None and perf_counter() >= deadline:
            return ShrinkResult(tuple(core), core_cost, calls,
                                perf_counter() - started, False)
        trial = core[:index] + core[index + 1:]
        if not trial:
            index += 1
            continue
        trial_cost, _ = _ktns_reduced(trial, requirements, m, c)
        calls += 1
        if trial_cost > k:
            core = trial
            core_cost = trial_cost
        else:
            index += 1
    return ShrinkResult(tuple(core), core_cost, calls, perf_counter() - started, True)


def subsequence_cut(master: OrderMaster, core: Sequence[int]) -> tuple[int, ...]:
    """Forbid the relative order chain witnessed by a bad subsequence."""
    if not core:
        return ()
    if len(set(core)) != len(core) or any(job not in range(master.n) for job in core):
        raise ValueError("core must contain distinct valid reduced job IDs")
    return tuple(-master.before_lit(core[i], core[i + 1])
                 for i in range(len(core) - 1))


def _canonical_cut(cut: Sequence[int]) -> tuple[int, ...]:
    return tuple(sorted(cut))


def _all_subset_sequences(sequence: Sequence[int]) -> Iterable[tuple[int, ...]]:
    for mask in range(1 << len(sequence)):
        yield tuple(sequence[i] for i in range(len(sequence)) if mask & (1 << i))


def _value(value: Any) -> Any:
    if isinstance(value, (tuple, list, dict)):
        return json.dumps(value, separators=(",", ":"), sort_keys=True)
    return value


def _write_csv(path: Path, fields: tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: _value(row.get(field)) for field in fields})


def _dataset(instance: SSPInstance) -> str:
    return instance.source.stem if instance.source else instance.name


def _event_row(base: dict[str, Any], *, k: int, status: str, elapsed: float,
               incumbent_before: int, incumbent_after: int, core: Sequence[int] = (),
               core_size_before: int | None = None, cut_length: int | None = None,
               cut_type: str | None = None, shrink_calls: int = 0,
               shrink_time: float = 0.0, shrink_completed: bool = True,
               duplicate: bool = False, master: OrderMaster, current_clauses: int,
               total_cuts: int, reduced_sequence: Sequence[int] = (),
               full_sequence: Sequence[int] = (), reduced_cost: int | None = None,
               full_cost: int | None = None, stats=None) -> dict[str, Any]:
    stats = stats or {}
    return {
        **base,
        "k": k,
        "cegar_round": None,
        "status": status,
        "solve_time": 0.0,
        "elapsed_total": elapsed,
        "candidate_sequence": tuple(reduced_sequence),
        "candidate_sequence_original": tuple(full_sequence),
        "candidate_cost": reduced_cost,
        "candidate_full_cost": full_cost,
        "incumbent_before": incumbent_before,
        "incumbent_after": incumbent_after,
        "core_size_before": core_size_before,
        "core_size_after": len(core) if core else (0 if core_size_before == 0 else None),
        "core_sequence": tuple(core),
        "cut_length": cut_length,
        "cut_type": cut_type,
        "shrink_calls": shrink_calls,
        "shrink_time": shrink_time,
        "shrink_completed": shrink_completed,
        "duplicate_cut": duplicate,
        "candidates_at_k": None,
        "cuts_at_k": None,
        "total_cuts": total_cuts,
        "master_variables": master.variable_count,
        "master_base_clauses": master.base_clause_count,
        "master_transitivity_clauses": master.transitivity_clause_count,
        "current_master_clauses": current_clauses,
        "is_solver_call": False,
        **{name: stats.get(name) for name in STAT_KEYS},
    }


def _solver_row(base: dict[str, Any], *, k: int, round_no: int, status: str,
                solve_time: float, elapsed: float, candidate: Sequence[int] | None,
                full_candidate: Sequence[int] | None, reduced_cost: int | None,
                full_cost: int | None, incumbent_before: int, incumbent_after: int,
                core: Sequence[int] = (), core_size_before: int | None = None,
                cut_length: int | None = None, cut_type: str | None = None,
                shrink_calls: int = 0, shrink_time: float = 0.0,
                shrink_completed: bool = True, duplicate: bool = False,
                candidates_at_k: int = 0, cuts_at_k: int = 0, total_cuts: int = 0,
                master: OrderMaster, current_clauses: int,
                stats: dict[str, int | float | None]) -> dict[str, Any]:
    return {
        **base,
        "k": k,
        "cegar_round": round_no,
        "status": status,
        "solve_time": solve_time,
        "elapsed_total": elapsed,
        "candidate_sequence": tuple(candidate) if candidate is not None else None,
        "candidate_sequence_original": tuple(full_candidate) if full_candidate is not None else None,
        "candidate_cost": reduced_cost,
        "candidate_full_cost": full_cost,
        "incumbent_before": incumbent_before,
        "incumbent_after": incumbent_after,
        "core_size_before": core_size_before,
        "core_size_after": len(core) if core else (0 if core_size_before == 0 else None),
        "core_sequence": tuple(core),
        "cut_length": cut_length,
        "cut_type": cut_type,
        "shrink_calls": shrink_calls,
        "shrink_time": shrink_time,
        "shrink_completed": shrink_completed,
        "duplicate_cut": duplicate,
        "candidates_at_k": candidates_at_k,
        "cuts_at_k": cuts_at_k,
        "total_cuts": total_cuts,
        "master_variables": master.variable_count,
        "master_base_clauses": master.base_clause_count,
        "master_transitivity_clauses": master.transitivity_clause_count,
        "current_master_clauses": current_clauses,
        "is_solver_call": True,
        **{name: stats.get(name) for name in STAT_KEYS},
    }


def solve_instance(
    instance: SSPInstance,
    reference_cost: int,
    time_limit: float = 600.0,
    *,
    iteration_callback: Callable[[dict[str, Any]], None] | None = None,
    retain_iterations: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Optimize one SSP instance with a persistent Order-SAT CEGAR master."""
    if time_limit <= 0:
        raise ValueError("time limit must be greater than zero")
    started = perf_counter()
    deadline = started + time_limit
    dominance = preprocess_dominance(instance)
    reduced = dominance.reduced
    upper = construct_upper_bound(instance, dominance)
    initial_ub = upper.cost
    best_cost = upper.cost
    best_reduced = tuple(dominance.original_to_local[job]
                         for job in upper.reduced_sequence)
    best_full = upper.full_sequence
    best_time = perf_counter() - started

    # KTNS can improve the greedy magazine policy for the same sequence.
    reduced_initial_cost, _ = _ktns_reduced(
        best_reduced, reduced.requirements, reduced.m, reduced.c,
    )
    full_initial_cost, _ = ktns(
        best_full, instance.requirements, instance.m, instance.c,
    )
    if full_initial_cost > reduced_initial_cost:
        raise AssertionError("reconstructed greedy sequence is worse than its reduced order")
    if full_initial_cost < best_cost:
        best_cost = full_initial_cost
        best_time = perf_counter() - started

    lb = lower_bound(instance)
    master = build_order_master(reduced.n)
    base = {
        "dataset": _dataset(instance),
        "problem": instance.problem_id,
        "reference_cost": reference_cost,
    }
    iteration_rows: list[dict[str, Any]] = []
    bound_rows: list[dict[str, Any]] = []
    bound_counts: dict[int, dict[str, Any]] = {}
    tested_bounds: list[int] = []
    known_cuts: set[tuple[int, ...]] = set()
    total_cuts = duplicate_cuts = total_shrink_calls = 0
    total_shrink_time = 0.0
    candidate_sequences = solver_calls = 0
    stat_sums = {name: 0 for name in STAT_KEYS}
    stat_complete = {name: True for name in STAT_KEYS}
    core_size_sum = core_ratio_sum = 0.0
    core_count = cut_length_sum = cut_count = 0
    min_core_size: int | None = None
    max_core_size: int | None = None
    status = "OPTIMAL"

    def emit(row: dict[str, Any]) -> None:
        if retain_iterations:
            iteration_rows.append(row)
        if iteration_callback is not None:
            iteration_callback(row)

    def record_core(k_value: int, core_size: int, cut_size: int) -> None:
        nonlocal core_size_sum, core_ratio_sum, core_count
        nonlocal cut_length_sum, cut_count, min_core_size, max_core_size
        core_size_sum += core_size
        core_ratio_sum += core_size / reduced.n
        core_count += 1
        cut_length_sum += cut_size
        cut_count += 1
        min_core_size = core_size if min_core_size is None else min(min_core_size, core_size)
        max_core_size = core_size if max_core_size is None else max(max_core_size, core_size)
        data = bound_counts[k_value]
        data["core_size_sum"] += core_size
        data["core_ratio_sum"] += core_size / reduced.n
        data["core_count"] += 1
        data["min_core_size"] = core_size if data["min_core_size"] is None else min(data["min_core_size"], core_size)
        data["max_core_size"] = core_size if data["max_core_size"] is None else max(data["max_core_size"], core_size)
        data["cut_length_sum"] += cut_size
        data["cut_length_count"] += 1

    if best_cost > lb and perf_counter() < deadline:
        next_k = best_cost - 1
        pending_clauses: list[list[int]] = []
        pending_meta: dict[str, Any] | None = None
        with IncrementalSolverSession([list(clause) for clause in master.clauses]) as session:
            while next_k >= lb:
                k = next_k
                if not tested_bounds or tested_bounds[-1] != k:
                    if tested_bounds:
                        bound_counts[tested_bounds[-1]]["elapsed_end"] = perf_counter() - started
                    tested_bounds.append(k)
                    bound_counts[k] = {
                        "candidates": 0, "cuts": 0,
                        "core_size_sum": 0.0, "core_ratio_sum": 0.0,
                        "core_count": 0, "min_core_size": None,
                        "max_core_size": None, "cut_length_sum": 0.0,
                        "cut_length_count": 0, "best_cost": best_cost,
                        "elapsed_start": perf_counter() - started,
                        "elapsed_end": None,
                    }
                round_no = bound_counts[k]["candidates"] + 1
                remaining = deadline - perf_counter()
                if remaining <= 0:
                    status = "TIMEOUT"
                    break
                incumbent_before = best_cost
                clauses_to_add = pending_clauses
                pending_clauses = []
                pre_meta = pending_meta
                pending_meta = None
                solved = session.solve(
                    new_clauses=clauses_to_add,
                    assumptions=[],
                    time_limit=remaining,
                )
                solver_calls += 1
                for stat_name in STAT_KEYS:
                    value = solved.stats.get(stat_name)
                    if value is None:
                        stat_complete[stat_name] = False
                    else:
                        stat_sums[stat_name] += value
                if solved.status == "TIMEOUT":
                    status = "TIMEOUT"
                    row = _solver_row(
                        base, k=k, round_no=round_no, status="TIMEOUT",
                        solve_time=solved.solve_time, elapsed=perf_counter() - started,
                        candidate=None, full_candidate=None, reduced_cost=None,
                        full_cost=None, incumbent_before=incumbent_before,
                        incumbent_after=best_cost, candidates_at_k=bound_counts[k]["candidates"],
                        cuts_at_k=bound_counts[k]["cuts"], total_cuts=total_cuts,
                        master=master, current_clauses=master.base_clause_count + total_cuts,
                        stats=solved.stats,
                    )
                    if pre_meta:
                        row.update({
                            "cut_type": pre_meta["cut_type"],
                            "core_sequence": pre_meta["core"],
                            "core_size_before": pre_meta["core_size_before"],
                            "core_size_after": len(pre_meta["core"]),
                            "cut_length": len(pre_meta["cut"]),
                            "shrink_calls": pre_meta["shrink_calls"],
                            "shrink_time": pre_meta["shrink_time"],
                            "shrink_completed": True,
                        })
                    emit(row)
                    break
                if solved.status == "UNSAT":
                    row = _solver_row(
                        base, k=k, round_no=round_no, status="UNSAT",
                        solve_time=solved.solve_time, elapsed=perf_counter() - started,
                        candidate=None, full_candidate=None, reduced_cost=None,
                        full_cost=None, incumbent_before=incumbent_before,
                        incumbent_after=best_cost, candidates_at_k=bound_counts[k]["candidates"],
                        cuts_at_k=bound_counts[k]["cuts"], total_cuts=total_cuts,
                        master=master, current_clauses=master.base_clause_count + total_cuts,
                        stats=solved.stats,
                    )
                    if pre_meta:
                        row.update({
                            "cut_type": pre_meta["cut_type"],
                            "core_sequence": pre_meta["core"],
                            "core_size_before": pre_meta["core_size_before"],
                            "core_size_after": len(pre_meta["core"]),
                            "cut_length": len(pre_meta["cut"]),
                            "shrink_calls": pre_meta["shrink_calls"],
                            "shrink_time": pre_meta["shrink_time"],
                            "shrink_completed": True,
                        })
                    emit(row)
                    status = "OPTIMAL"
                    break
                if solved.status != "SAT" or solved.model is None:
                    raise AssertionError("order master returned an invalid SAT result")

                candidate_sequences += 1
                bound_counts[k]["candidates"] += 1
                candidate = decode_order(solved.model, master)
                candidate_cost, _ = _ktns_reduced(
                    candidate, reduced.requirements, reduced.m, reduced.c,
                )
                full_candidate = reconstruct_sequence(
                    tuple(reduced.local_to_original[job] for job in candidate), dominance,
                )
                full_cost, _ = ktns(
                    full_candidate, instance.requirements, instance.m, instance.c,
                )
                if full_cost > candidate_cost:
                    raise AssertionError(
                        "reconstructed KTNS cost exceeds reduced order KTNS cost"
                    )
                core: tuple[int, ...] = ()
                cut: tuple[int, ...] = ()
                cut_type = None
                shrink_calls = 0
                shrink_time = 0.0
                shrink_completed = True
                core_before = None
                duplicate = False

                if candidate_cost > k:
                    shrink = shrink_subsequence(
                        candidate, reduced.requirements, reduced.m, reduced.c,
                        k, deadline=deadline,
                    )
                    core = shrink.core
                    core_before = len(candidate)
                    shrink_calls, shrink_time = shrink.calls, shrink.elapsed
                    shrink_completed = shrink.completed
                    total_shrink_calls += shrink_calls
                    total_shrink_time += shrink_time
                    if not shrink.completed:
                        status = "TIMEOUT"
                    else:
                        if shrink.core_cost <= k:
                            raise AssertionError("shrinker returned a non-conflicting core")
                        for job in core:
                            reduced_core = tuple(x for x in core if x != job)
                            if reduced_core and _ktns_reduced(
                                reduced_core, reduced.requirements, reduced.m, reduced.c,
                            )[0] > k:
                                raise AssertionError("shrunk core is not inclusion-minimal")
                        cut = subsequence_cut(master, core)
                        cut_type = "candidate"
                        key = _canonical_cut(cut)
                        duplicate = key in known_cuts
                        if duplicate:
                            duplicate_cuts += 1
                            raise AssertionError(
                                "duplicate subsequence cut did not exclude the SAT candidate"
                            )
                        known_cuts.add(key)
                        total_cuts += 1
                        bound_counts[k]["cuts"] += 1
                        record_core(k, len(core), len(cut))
                        pending_clauses = [list(cut)]
                        pending_meta = {
                            "cut_type": cut_type, "core": core,
                            "core_size_before": core_before,
                            "shrink_calls": shrink_calls, "shrink_time": shrink_time,
                            "cut": cut,
                        }
                else:
                    # The total-order master found a feasible SSP sequence.
                    if full_cost < best_cost:
                        best_cost = full_cost
                        best_reduced = tuple(candidate)
                        best_full = tuple(full_candidate)
                        best_time = perf_counter() - started
                    bound_counts[k]["best_cost"] = best_cost

                current_clauses = master.base_clause_count + total_cuts
                row = _solver_row(
                    base, k=k, round_no=round_no, status="SAT",
                    solve_time=solved.solve_time, elapsed=perf_counter() - started,
                    candidate=candidate, full_candidate=full_candidate,
                    reduced_cost=candidate_cost, full_cost=full_cost,
                    incumbent_before=incumbent_before, incumbent_after=best_cost,
                    core=core, core_size_before=core_before, cut_length=len(cut) if cut_type else None,
                    cut_type=cut_type, shrink_calls=shrink_calls, shrink_time=shrink_time,
                    shrink_completed=shrink_completed, duplicate=duplicate,
                    candidates_at_k=bound_counts[k]["candidates"],
                    cuts_at_k=bound_counts[k]["cuts"], total_cuts=total_cuts,
                    master=master, current_clauses=current_clauses, stats=solved.stats,
                )
                emit(row)

                if status == "TIMEOUT":
                    break
                if candidate_cost > k:
                    if not cut:
                        # Empty clause is the correct certificate when a single
                        # job already exceeds K.
                        pending_clauses = [[]]
                        pending_meta = {
                            "cut_type": cut_type, "core": core,
                            "core_size_before": core_before,
                            "shrink_calls": shrink_calls, "shrink_time": shrink_time,
                            "cut": cut,
                        }
                    continue

                if best_cost == lb:
                    status = "OPTIMAL"
                    break
                new_k = best_cost - 1
                if new_k < lb:
                    status = "OPTIMAL"
                    break
                # The accepted sequence is already a known bad candidate for
                # the tighter bound. Shrink it now so the next SAT call cannot
                # rediscover the same sequence.
                post_shrink = shrink_subsequence(
                    candidate, reduced.requirements, reduced.m, reduced.c,
                    new_k, deadline=deadline,
                )
                total_shrink_calls += post_shrink.calls
                total_shrink_time += post_shrink.elapsed
                if not post_shrink.completed:
                    event = _event_row(
                        base, k=new_k, status="POST_INCUMBENT_SHRINK_TIMEOUT",
                        elapsed=perf_counter() - started, incumbent_before=best_cost,
                        incumbent_after=best_cost, core=post_shrink.core,
                        core_size_before=len(candidate), master=master,
                        current_clauses=master.base_clause_count + total_cuts,
                        total_cuts=total_cuts, reduced_sequence=candidate,
                        full_sequence=full_candidate, reduced_cost=candidate_cost,
                        full_cost=full_cost, shrink_calls=post_shrink.calls,
                        shrink_time=post_shrink.elapsed, shrink_completed=False,
                    )
                    emit(event)
                    status = "TIMEOUT"
                    break
                post_cut = subsequence_cut(master, post_shrink.core)
                key = _canonical_cut(post_cut)
                if key in known_cuts:
                    duplicate_cuts += 1
                    raise AssertionError("post-incumbent cut was already present in the master")
                known_cuts.add(key)
                total_cuts += 1
                bound_counts.setdefault(new_k, {
                    "candidates": 0, "cuts": 0,
                    "core_size_sum": 0.0, "core_ratio_sum": 0.0,
                    "core_count": 0, "min_core_size": None,
                    "max_core_size": None, "cut_length_sum": 0.0,
                    "cut_length_count": 0,
                    "best_cost": best_cost, "elapsed_start": perf_counter() - started,
                    "elapsed_end": None,
                })
                bound_counts[new_k]["cuts"] += 1
                record_core(new_k, len(post_shrink.core), len(post_cut))
                event = _event_row(
                    base, k=new_k, status="POST_INCUMBENT_CUT",
                    elapsed=perf_counter() - started, incumbent_before=best_cost,
                    incumbent_after=best_cost, core=post_shrink.core,
                    core_size_before=len(candidate), cut_length=len(post_cut),
                    cut_type="post-incumbent-cut", master=master,
                    current_clauses=master.base_clause_count + total_cuts,
                    total_cuts=total_cuts, reduced_sequence=candidate,
                    full_sequence=full_candidate, reduced_cost=candidate_cost,
                    full_cost=full_cost, shrink_calls=post_shrink.calls,
                    shrink_time=post_shrink.elapsed,
                )
                emit(event)
                pending_clauses = [list(post_cut)]
                pending_meta = {
                    "cut_type": "post-incumbent-cut", "core": post_shrink.core,
                    "core_size_before": len(candidate),
                    "shrink_calls": post_shrink.calls,
                    "shrink_time": post_shrink.elapsed, "cut": post_cut,
                }
                next_k = new_k
            else:
                status = "OPTIMAL" if best_cost == lb else status

    # Close bound-level telemetry, including bounds that received pre-solve
    # post-incumbent cuts but timed out before the next solver call.
    for k in tested_bounds:
        data = bound_counts[k]
        if data["elapsed_end"] is None:
            data["elapsed_end"] = perf_counter() - started
        count = data["core_count"]
        cut_count_at_k = data["cut_length_count"]
        bound_rows.append({
            **base, "k": k, "candidates_at_k": data["candidates"],
            "cuts_at_k": data["cuts"],
            "avg_core_size": data["core_size_sum"] / count if count else None,
            "min_core_size": data["min_core_size"],
            "max_core_size": data["max_core_size"],
            "avg_core_ratio": data["core_ratio_sum"] / count if count else None,
            "avg_cut_length": data["cut_length_sum"] / cut_count_at_k if cut_count_at_k else None,
            "best_cost_at_k": data["best_cost"],
            "elapsed_at_k_end": data["elapsed_end"],
        })

    elapsed = perf_counter() - started
    summary = {
        **base,
        "initial_ub": initial_ub,
        "final_incumbent": best_cost,
        "gap_to_reference": best_cost - reference_cost,
        "status": status,
        "total_runtime": elapsed,
        "solver_calls": solver_calls,
        "candidate_sequences": candidate_sequences,
        "total_cuts": total_cuts,
        "duplicate_cuts": duplicate_cuts,
        "total_shrink_calls": total_shrink_calls,
        "total_shrink_time": total_shrink_time,
        "avg_core_size": core_size_sum / core_count if core_count else None,
        "min_core_size": min_core_size,
        "max_core_size": max_core_size,
        "avg_core_ratio": core_ratio_sum / core_count if core_count else None,
        "avg_cut_length": cut_length_sum / cut_count if cut_count else None,
        **{f"total_{name}": stat_sums[name] if stat_complete[name] else None
           for name in STAT_KEYS},
        "best_incumbent_time": best_time,
        "tested_bounds": tuple(tested_bounds),
    }
    return iteration_rows, bound_rows, summary


def load_instances() -> list[tuple[SSPInstance, int]]:
    datasets = {
        filename: parse_file(ROOT / "data" / "Catanzaro" / filename)
        for filename in ("datB1", "datC1")
    }
    return [(datasets[name][problem - 1], reference)
            for (name, problem), reference in REFERENCE_COSTS.items()]


def run_benchmarks(output_dir: Path, time_limit: float = 600.0):
    bound_rows: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    output_dir.mkdir(parents=True, exist_ok=True)
    iteration_path = output_dir / "order_ktns_cegar_iterations.csv"
    with iteration_path.open("w", newline="", encoding="utf-8") as iteration_file:
        writer = csv.DictWriter(iteration_file, fieldnames=ITERATION_FIELDS)
        writer.writeheader()
        written = 0

        def write_iteration(row: dict[str, Any]) -> None:
            nonlocal written
            writer.writerow({key: _value(row.get(key)) for key in ITERATION_FIELDS})
            written += 1
            if written % 500 == 0:
                iteration_file.flush()

        for instance, reference in load_instances():
            print(f"START {_dataset(instance)} #{instance.problem_id}", flush=True)
            _, bounds, summary = solve_instance(
                instance,
                reference,
                time_limit,
                iteration_callback=write_iteration,
                retain_iterations=False,
            )
            iteration_file.flush()
            bound_rows.extend(bounds)
            summaries.append(summary)
            _write_csv(output_dir / "order_ktns_cegar_bounds.csv", BOUNDS_FIELDS, bound_rows)
            _write_csv(output_dir / "order_ktns_cegar_summary.csv", SUMMARY_FIELDS, summaries)
            print(
                f"DONE {_dataset(instance)} #{summary['problem']}: {summary['status']} "
                f"incumbent={summary['final_incumbent']} calls={summary['solver_calls']} "
                f"candidates={summary['candidate_sequences']} cuts={summary['total_cuts']} "
                f"runtime={summary['total_runtime']:.2f}s",
                flush=True,
            )
    return written, bound_rows, summaries


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "experiments" / "results")
    parser.add_argument("--time-limit", type=float, default=600.0)
    args = parser.parse_args()
    run_benchmarks(args.output_dir, args.time_limit)


if __name__ == "__main__":
    main()
