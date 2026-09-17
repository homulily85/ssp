from __future__ import annotations

from pysat.solvers import NoSuchSolverError, Solver

from .model import CNFBuildResult, SolverResult


class SolverConfigurationError(RuntimeError):
    pass


def solve_cnf(build: CNFBuildResult) -> SolverResult:
    if build.immediate_unsat:
        return SolverResult("UNSAT", 0.0, None, {})
    try:
        with Solver(
            name="cadical300", bootstrap_with=build.cnf.clauses, use_timer=True
        ) as solver:
            satisfiable = solver.solve()
            solve_time = float(solver.time())
            stats = dict(solver.accum_stats() or {})
            model = tuple(solver.get_model()) if satisfiable else None
    except (NoSuchSolverError, ImportError, OSError, RuntimeError) as exc:
        raise SolverConfigurationError(
            "PySAT CaDiCaL 3.0 backend 'cadical300' is unavailable or failed to initialize"
        ) from exc
    return SolverResult("SAT" if satisfiable else "UNSAT", solve_time, model, stats)
