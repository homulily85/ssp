"""Reproducible objective-encoding ablation for the direct SAT formulation.

This module is deliberately separate from the production optimizer. Run it from
the repository root with ``python -m experiments.objective_encoding_ablation``.
"""
from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

from pysat.card import CardEnc, EncType, ITotalizer
from pysat.formula import IDPool

from src.dominance import preprocess_dominance
from src.encoding import build_direct_cnf
from src.model import SSPInstance
from src.parser import parse_file
from src.solver import IncrementalSolverSession
from src.upper_bound import construct_upper_bound
from src.optimize import lower_bound
from src.validate import validate_direct_solution


ROOT = Path(__file__).resolve().parents[1]
REFERENCE_COSTS = {
    ("datB1", 1): 25, ("datB1", 2): 32, ("datB1", 3): 29,
    ("datC1", 1): 103, ("datC1", 2): 109, ("datC1", 3): 100,
}
OPTIMIZATION_MODES = (
    "seqcounter-fresh", "seqcounter-accumulated", "itotalizer-assumption",
)
FIXED_MODES = ("fixed-seqcounter", "fixed-totalizer")
STAT_KEYS = ("restarts", "conflicts", "decisions", "propagations")
ITERATION_FIELDS = (
    "dataset", "problem", "mode", "run_type", "reference_cost", "k", "status",
    "solve_time", "elapsed_total", "incumbent_before", "sat_cost", "ktns_cost",
    "incumbent_after", "sequence", "base_variables", "base_clauses",
    "objective_aux_variables_added", "objective_clauses_added",
    "current_total_variables", "current_total_clauses", "restarts", "conflicts",
    "decisions", "propagations",
)
SUMMARY_FIELDS = (
    "dataset", "problem", "mode", "run_type", "reference_cost", "initial_ub",
    "final_incumbent", "status", "total_runtime", "solver_calls", "total_conflicts",
    "total_decisions", "total_propagations", "total_restarts", "sat_calls",
    "unsat_calls", "best_incumbent_time", "tested_bounds",
)


@dataclass
class FormulaStats:
    top: int
    clauses: int


def _counter(literals: list[int], bound: int, top: int) -> tuple[list[list[int]], int]:
    pool = IDPool(start_from=top + 1)
    encoded = CardEnc.atmost(
        lits=literals, bound=bound, vpool=pool, encoding=EncType.seqcounter,
    )
    return encoded.clauses, pool.top - top


def _totalizer(literals: list[int], bound: int, top: int):
    """Build a static totalizer with outputs through ``bound`` inclusive."""
    # PySAT exposes its totalizer implementation as ITotalizer. We build it
    # once to the fixed bound and freeze the resulting CNF into one-shot SAT.
    return ITotalizer(lits=literals, ubound=bound, top_id=top)


def _csv_value(value: Any) -> Any:
    if isinstance(value, (tuple, list, dict)):
        return json.dumps(value, separators=(",", ":"), sort_keys=True)
    return value


def _write_csv(path: Path, fields: tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key)) for key in fields})


def _row_base(instance: SSPInstance, reference: int) -> dict[str, Any]:
    return {
        "dataset": instance.source.stem if instance.source else instance.name,
        "problem": instance.problem_id,
        "reference_cost": reference,
    }


def _new_iter_row(base: dict[str, Any], mode: str, run_type: str, k: int,
                  status: str, solve_time: float, elapsed: float, incumbent_before: int,
                  sat_cost: int | None, ktns_cost: int | None, incumbent_after: int,
                  sequence: tuple[int, ...] | None, base_vars: int, base_clauses: int,
                  aux_added: int, clauses_added: int, total_vars: int, total_clauses: int,
                  stats: dict[str, int | float | None]) -> dict[str, Any]:
    return {
        **base, "mode": mode, "run_type": run_type, "k": k, "status": status,
        "solve_time": solve_time, "elapsed_total": elapsed,
        "incumbent_before": incumbent_before, "sat_cost": sat_cost,
        "ktns_cost": ktns_cost, "incumbent_after": incumbent_after,
        "sequence": sequence, "base_variables": base_vars, "base_clauses": base_clauses,
        "objective_aux_variables_added": aux_added,
        "objective_clauses_added": clauses_added,
        "current_total_variables": total_vars, "current_total_clauses": total_clauses,
        **{key: stats.get(key) for key in STAT_KEYS},
    }


def _summary(base: dict[str, Any], mode: str, run_type: str, initial: int,
             incumbent: int, status: str, runtime: float, rows: list[dict[str, Any]],
             bounds: list[int], best_time: float | None) -> dict[str, Any]:
    return {
        **base, "mode": mode, "run_type": run_type, "initial_ub": initial,
        "final_incumbent": incumbent, "status": status, "total_runtime": runtime,
        "solver_calls": len(rows),
        **{f"total_{key}": (None if any(row.get(key) is None for row in rows)
                              else sum(row.get(key, 0) for row in rows)) for key in STAT_KEYS},
        "sat_calls": sum(row["status"] == "SAT" for row in rows),
        "unsat_calls": sum(row["status"] == "UNSAT" for row in rows),
        "best_incumbent_time": best_time,
        "tested_bounds": bounds,
    }


def run_optimization(instance: SSPInstance, reference: int, mode: str,
                     time_limit: float = 600.0) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if mode not in OPTIMIZATION_MODES:
        raise ValueError(f"unknown optimization mode: {mode}")
    started = perf_counter()
    dominance = preprocess_dominance(instance)
    upper = construct_upper_bound(instance, dominance)
    incumbent = upper.cost
    lb = lower_bound(instance)
    anchor = dominance.original_to_local[upper.reduced_sequence[0]]
    build = build_direct_cnf(dominance.reduced, max(0, incumbent - 1), anchor)
    base_vars, base_clauses = build.vpool.top, len(build.cnf.clauses)
    literals = list(build.vars_t.values())
    base = _row_base(instance, reference)
    rows: list[dict[str, Any]] = []
    bounds: list[int] = []
    status = "OPTIMAL" if incumbent == lb else "TIMEOUT"
    best_time = 0.0
    if incumbent > lb:
        status = "OPTIMAL"
        totalizer = None
        totalizer_clauses: list[list[int]] = []
        totalizer_aux = 0
        if mode == "itotalizer-assumption":
            totalizer = ITotalizer(
                lits=literals, ubound=min(incumbent - 1, len(literals) - 1),
                top_id=base_vars,
            )
            totalizer_clauses = [list(clause) for clause in totalizer.cnf.clauses]
            totalizer_aux = totalizer.top_id - base_vars
            build.cnf.extend(totalizer_clauses)
        if mode == "seqcounter-accumulated" or mode == "itotalizer-assumption":
            session = IncrementalSolverSession(build.cnf.clauses)
        else:
            session = None
        accumulated = FormulaStats(
            top=base_vars + totalizer_aux,
            clauses=base_clauses + len(totalizer_clauses),
        )
        try:
            next_k = incumbent - 1
            while next_k >= lb:
                k = next_k
                bounds.append(k)
                incumbent_before = incumbent
                elapsed = perf_counter() - started
                remaining = time_limit - elapsed
                if remaining <= 0:
                    status = "TIMEOUT"
                    break
                objective_clauses: list[list[int]] = []
                aux_added = 0
                assumptions: list[int] = []
                if mode.startswith("seqcounter"):
                    objective_clauses, aux_added = _counter(
                        literals, k, base_vars if mode == "seqcounter-fresh" else accumulated.top,
                    )
                elif k < len(literals):
                    if k >= len(totalizer.rhs):
                        raise AssertionError(f"ITotalizer has no output at bound {k}")
                    assumptions = [-totalizer.rhs[k]]
                    if not rows:
                        aux_added = totalizer_aux
                        objective_clauses = totalizer_clauses

                if mode == "seqcounter-fresh":
                    # A fresh process/session contains exactly the base and this bound.
                    fresh = IncrementalSolverSession(build.cnf.clauses + objective_clauses)
                    try:
                        solved = fresh.solve(new_clauses=[], assumptions=[], time_limit=max(
                            1e-9, time_limit - (perf_counter() - started)))
                    finally:
                        fresh.close()
                    current_vars, current_clauses = base_vars + aux_added, base_clauses + len(objective_clauses)
                else:
                    solved = session.solve(
                        new_clauses=objective_clauses, assumptions=assumptions,
                        time_limit=max(1e-9, time_limit - (perf_counter() - started)),
                    )
                    if mode == "seqcounter-accumulated":
                        accumulated.top += aux_added
                        accumulated.clauses += len(objective_clauses)
                    current_vars, current_clauses = accumulated.top, accumulated.clauses
                call_status = solved.status
                sat_cost = ktns_cost = None
                sequence = None
                if solved.status == "SAT":
                    validated = validate_direct_solution(instance, dominance, build, solved.model, k)
                    sat_cost, ktns_cost = validated.sat_cost, validated.ktns_cost
                    sequence = validated.full_sequence
                    if ktns_cost < incumbent:
                        incumbent = ktns_cost
                        best_time = perf_counter() - started
                    next_k = incumbent - 1
                elif solved.status == "UNSAT":
                    next_k = lb - 1
                elif solved.status == "TIMEOUT":
                    status = "TIMEOUT"
                    next_k = lb - 1
                else:
                    raise AssertionError(f"unexpected solver status {solved.status}")
                rows.append(_new_iter_row(
                    base, mode, "optimization", k, call_status, solved.solve_time,
                    perf_counter() - started, incumbent_before, sat_cost, ktns_cost,
                    incumbent, sequence, base_vars, base_clauses, aux_added,
                    len(objective_clauses), current_vars, current_clauses, solved.stats,
                ))
                if call_status == "TIMEOUT":
                    break
            if next_k < lb and status != "TIMEOUT":
                status = "OPTIMAL"
        finally:
            if session is not None:
                session.close()
            if totalizer is not None:
                totalizer.delete()
    summary = _summary(base, mode, "optimization", upper.cost, incumbent, status,
                       perf_counter() - started, rows, bounds, best_time)
    return rows, summary


def run_fixed(instance: SSPInstance, reference: int, mode: str,
              time_limit: float = 600.0) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if mode not in FIXED_MODES:
        raise ValueError(f"unknown fixed mode: {mode}")
    started = perf_counter()
    k = reference - 1
    dominance = preprocess_dominance(instance)
    upper = construct_upper_bound(instance, dominance)
    anchor = dominance.original_to_local[upper.reduced_sequence[0]]
    build = build_direct_cnf(dominance.reduced, max(0, k), anchor)
    base_vars, base_clauses = build.vpool.top, len(build.cnf.clauses)
    literals = list(build.vars_t.values())
    clauses: list[list[int]] = []
    aux_added = 0
    if mode == "fixed-seqcounter":
        clauses, aux_added = _counter(literals, k, base_vars)
    else:
        totalizer = _totalizer(literals, k, base_vars)
        clauses = [list(clause) for clause in totalizer.cnf.clauses]
        aux_added = totalizer.top_id - base_vars
        if k < len(totalizer.rhs):
            clauses.append([-totalizer.rhs[k]])
        totalizer.delete()
    session = IncrementalSolverSession(build.cnf.clauses + clauses)
    try:
        solved = session.solve(new_clauses=[], assumptions=[], time_limit=max(1e-9, time_limit - (perf_counter() - started)))
    finally:
        session.close()
    incumbent = upper.cost
    sat_cost = ktns_cost = None
    sequence = None
    if solved.status == "SAT":
        validated = validate_direct_solution(instance, dominance, build, solved.model, k)
        sat_cost, ktns_cost, sequence = validated.sat_cost, validated.ktns_cost, validated.full_sequence
        incumbent = min(incumbent, ktns_cost)
    row = _new_iter_row(
        _row_base(instance, reference), mode, "fixed-k", k, solved.status,
        solved.solve_time, perf_counter() - started, upper.cost, sat_cost, ktns_cost,
        incumbent, sequence, base_vars, base_clauses, aux_added, len(clauses),
        base_vars + aux_added, base_clauses + len(clauses), solved.stats,
    )
    summary = _summary(_row_base(instance, reference), mode, "fixed-k", upper.cost,
                       incumbent, solved.status, perf_counter() - started, [row], [k],
                       0.0 if incumbent < upper.cost else None)
    return [row], summary


def load_instances() -> list[tuple[SSPInstance, int]]:
    loaded: dict[str, list[SSPInstance]] = {}
    for filename in ("datB1", "datC1"):
        loaded[filename] = parse_file(ROOT / "data" / "Catanzaro" / filename)
    return [(loaded[name][problem - 1], reference)
            for (name, problem), reference in REFERENCE_COSTS.items()]


def run_experiments(output_dir: Path, time_limit: float = 600.0) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    iterations: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    # Deliberately serial: order is stable and resource contention is avoided.
    for instance, reference in load_instances():
        for mode in OPTIMIZATION_MODES:
            print(f"START optimization {instance.source.stem} #{instance.problem_id} {mode}", flush=True)
            rows, summary = run_optimization(instance, reference, mode, time_limit)
            iterations.extend(rows)
            summaries.append(summary)
            _write_csv(output_dir / "objective_ablation_iterations.csv", ITERATION_FIELDS, iterations)
            _write_csv(output_dir / "objective_ablation_summary.csv", SUMMARY_FIELDS, summaries)
            print(f"DONE {summary['dataset']} #{summary['problem']} {mode}: {summary['status']} "
                  f"incumbent={summary['final_incumbent']} runtime={summary['total_runtime']:.2f}s", flush=True)
        for mode in FIXED_MODES:
            print(f"START fixed-K {instance.source.stem} #{instance.problem_id} {mode}", flush=True)
            rows, summary = run_fixed(instance, reference, mode, time_limit)
            iterations.extend(rows)
            summaries.append(summary)
            _write_csv(output_dir / "objective_ablation_iterations.csv", ITERATION_FIELDS, iterations)
            _write_csv(output_dir / "objective_ablation_summary.csv", SUMMARY_FIELDS, summaries)
            print(f"DONE {summary['dataset']} #{summary['problem']} {mode}: {summary['status']} "
                  f"runtime={summary['total_runtime']:.2f}s", flush=True)
    return iterations, summaries


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "experiments" / "results")
    parser.add_argument("--time-limit", type=float, default=600.0)
    args = parser.parse_args()
    run_experiments(args.output_dir, args.time_limit)


if __name__ == "__main__":
    main()
