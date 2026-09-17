from __future__ import annotations

import csv
import os
import tempfile
from pathlib import Path
from typing import Iterable, TextIO

from .model import OptimizationResult


CSV_FIELDS = (
    "problem",
    "n",
    "n_reduced",
    "dominated",
    "lb",
    "initial_ub",
    "optimum",
    "sat_calls",
    "total_vars_last",
    "total_clauses_last",
    "sat_time",
    "total_time",
)


def print_result(result: OptimizationResult, stream: TextIO) -> None:
    dominance = result.dominance
    print(f"Problem: {result.instance.name}", file=stream)
    print(
        f"Original jobs: {result.instance.n} | Reduced jobs: {len(dominance.active_jobs)} | "
        f"Dominated jobs: {len(dominance.dominator)}",
        file=stream,
    )
    mapping = ", ".join(f"{job}->{representative}" for job, representative in sorted(dominance.dominator.items()))
    print(f"Dominance mapping: {mapping or '(none)'}", file=stream)
    print(f"Lower bound: {result.lower_bound}", file=stream)
    print(f"Greedy/KTNS upper bound: {result.initial_upper_bound}", file=stream)
    print(f"Initial greedy sequence: {list(result.initial_sequence)}", file=stream)
    for item in result.iterations:
        print(
            f"SAT iteration: k={item.k} {item.status} primary_variables={item.primary_variables} "
            f"auxiliary_variables={item.auxiliary_variables} total_variables={item.variables} "
            f"clauses={item.clauses} solve_time={item.solve_time:.6f}s",
            file=stream,
        )
    print(f"Optimal cost: {result.optimum}", file=stream)
    print(f"Optimal reduced sequence: {list(result.optimal_reduced_sequence)}", file=stream)
    print(f"Optimal reconstructed sequence: {list(result.optimal_sequence)}", file=stream)
    print(f"KTNS verification cost: {result.verification_cost}", file=stream)
    print(f"Total runtime: {result.total_runtime:.6f}s", file=stream)
    print(file=stream)


def _csv_row(result: OptimizationResult) -> dict[str, object]:
    last = result.iterations[-1] if result.iterations else None
    return {
        "problem": result.instance.name,
        "n": result.instance.n,
        "n_reduced": len(result.dominance.active_jobs),
        "dominated": len(result.dominance.dominator),
        "lb": result.lower_bound,
        "initial_ub": result.initial_upper_bound,
        "optimum": result.optimum,
        "sat_calls": len(result.iterations),
        "total_vars_last": last.variables if last else 0,
        "total_clauses_last": last.clauses if last else 0,
        "sat_time": f"{result.sat_time:.9f}",
        "total_time": f"{result.total_runtime:.9f}",
    }


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
