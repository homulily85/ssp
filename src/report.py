from __future__ import annotations

import csv
import os
import tempfile
from pathlib import Path
from typing import Iterable, TextIO

from .model import OptimizationResult


CSV_FIELDS = (
    "problem",
    "algorithm",
    "status",
    "n",
    "n_reduced",
    "dominated",
    "lb",
    "initial_ub",
    "best_cost",
    "optimum",
    "solver_calls",
    "cegar_rounds",
    "subtour_cuts",
    "total_vars_last",
    "total_clauses_last",
    "sat_time",
    "restarts",
    "conflicts",
    "decisions",
    "propagations",
    "total_time",
)

_SOLVER_STATS = ("restarts", "conflicts", "decisions", "propagations")


def print_result(result: OptimizationResult, stream: TextIO) -> None:
    dominance = result.dominance
    print(f"Problem: {result.instance.name}", file=stream)
    print(f"Algorithm: {result.algorithm}", file=stream)
    print(
        f"Original jobs: {result.instance.n} | Reduced jobs: {len(dominance.active_jobs)} | "
        f"Dominated jobs: {len(dominance.dominator)}",
        file=stream,
    )
    mapping = ", ".join(
        f"{job}->{representative}"
        for job, representative in sorted(dominance.dominator.items())
    )
    print(f"Dominance mapping: {mapping or '(none)'}", file=stream)
    print(f"Lower bound: {result.lower_bound}", file=stream)
    print(f"Greedy/KTNS upper bound: {result.initial_upper_bound}", file=stream)
    print(f"Initial greedy sequence: {list(result.initial_sequence)}", file=stream)
    for item in result.iterations:
        solver_stats = " ".join(
            f"{key}={_iteration_stat(item, key)}" for key in _SOLVER_STATS
        )
        cost = item.actual_solution_cost if item.actual_solution_cost is not None else "N/A"
        print(
            f"SAT call: k={item.k} cegar={item.cegar_round} {item.status} "
            f"subtours={item.subtours_found} cuts_added={item.subtour_cuts_added} "
            f"cuts_total={item.total_subtour_cuts} actual_cost={cost} "
            f"primary_variables={item.primary_variables} "
            f"auxiliary_variables={item.auxiliary_variables} "
            f"total_variables={item.variables} clauses={item.clauses} "
            f"solve_time={item.solve_time:.6f}s {solver_stats}",
            file=stream,
        )
    print(f"Status: {result.status}", file=stream)
    if result.status == "OPTIMAL":
        print(f"Optimal cost: {result.optimum}", file=stream)
        print(
            f"Optimal reduced sequence: {list(result.optimal_reduced_sequence)}",
            file=stream,
        )
        print(
            f"Optimal reconstructed sequence: {list(result.optimal_sequence)}",
            file=stream,
        )
    else:
        print(f"Best known cost: {result.best_cost}", file=stream)
        print(
            f"Best reduced sequence: {list(result.optimal_reduced_sequence)}",
            file=stream,
        )
        print(
            f"Best reconstructed sequence: {list(result.optimal_sequence)}",
            file=stream,
        )
    print(f"KTNS verification cost: {result.verification_cost}", file=stream)
    print(f"Total runtime: {result.total_runtime:.6f}s", file=stream)
    print(file=stream)


def _csv_row(result: OptimizationResult) -> dict[str, object]:
    last = result.iterations[-1] if result.iterations else None
    return {
        "problem": result.instance.name,
        "algorithm": result.algorithm,
        "status": result.status,
        "n": result.instance.n,
        "n_reduced": len(result.dominance.active_jobs),
        "dominated": len(result.dominance.dominator),
        "lb": result.lower_bound,
        "initial_ub": result.initial_upper_bound,
        "best_cost": result.best_cost,
        "optimum": result.optimum if result.optimum is not None else "",
        "solver_calls": len(result.iterations),
        "cegar_rounds": result.cegar_rounds,
        "subtour_cuts": result.subtour_cuts,
        "total_vars_last": last.variables if last else 0,
        "total_clauses_last": last.clauses if last else 0,
        "sat_time": f"{result.sat_time:.9f}",
        "restarts": _aggregate_stat(result, "restarts"),
        "conflicts": _aggregate_stat(result, "conflicts"),
        "decisions": _aggregate_stat(result, "decisions"),
        "propagations": _aggregate_stat(result, "propagations"),
        "total_time": f"{result.total_runtime:.9f}",
    }


def _iteration_stat(item, key: str) -> int | float | str:
    value = item.stats.get(key)
    return "N/A" if value is None else value


def _aggregate_stat(result: OptimizationResult, key: str) -> int | float | str:
    values = [item.stats.get(key) for item in result.iterations]
    if any(value is None for value in values):
        return "N/A"
    return sum(value for value in values if value is not None)


def write_csv(results: Iterable[OptimizationResult], path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent, text=True
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
            writer.writeheader()
            for result in results:
                writer.writerow(_csv_row(result))
        os.replace(temporary_name, destination)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise
