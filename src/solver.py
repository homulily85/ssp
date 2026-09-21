from __future__ import annotations

import multiprocessing
from multiprocessing.connection import Connection, wait
from time import perf_counter

from pysat.solvers import NoSuchSolverError, Solver

from .model import SolverResult


class SolverConfigurationError(RuntimeError):
    pass


_TRACKED_STATS = ("restarts", "conflicts", "decisions", "propagations")


def _with_tracked_stats(stats: dict[str, int | float]) -> dict[str, int | float]:
    normalized = dict(stats)
    for key in _TRACKED_STATS:
        normalized.setdefault(key, 0)
    return normalized


def unavailable_solver_stats() -> dict[str, None]:
    """Return explicit unknown statistics after a killed worker."""
    return {key: None for key in _TRACKED_STATS}


def _incremental_solver_worker(
    clauses: list[list[int]], channel: Connection
) -> None:
    """Own one CaDiCaL instance and receive clauses/assumptions incrementally."""
    try:
        with Solver(
            name="cadical300", bootstrap_with=clauses, use_timer=True
        ) as solver:
            previous_stats: dict[str, int | float] = {}
            while True:
                command = channel.recv()
                if command[0] == "STOP":
                    return
                if command[0] != "SOLVE":
                    raise ValueError(f"unknown incremental solver command: {command[0]}")
                _, new_clauses, assumptions = command
                if new_clauses:
                    solver.append_formula(new_clauses)
                satisfiable = solver.solve(assumptions=assumptions)
                cumulative_stats = _with_tracked_stats(
                    dict(solver.accum_stats() or {})
                )
                iteration_stats = {
                    key: cumulative_stats[key] - previous_stats.get(key, 0)
                    for key in _TRACKED_STATS
                }
                previous_stats = cumulative_stats
                channel.send(
                    (
                        "RESULT",
                        "SAT" if satisfiable else "UNSAT",
                        float(solver.time()),
                        tuple(solver.get_model()) if satisfiable else None,
                        iteration_stats,
                    )
                )
    except EOFError:
        return
    except BaseException as exc:
        try:
            channel.send(("ERROR", type(exc).__name__, str(exc)))
        except BaseException:
            pass
    finally:
        channel.close()


def _stop_process(process: multiprocessing.Process) -> None:
    if process.is_alive():
        process.terminate()
        process.join(timeout=1.0)
    if process.is_alive():
        process.kill()
        process.join()


class IncrementalSolverSession:
    """Parent-side handle for one time-limited persistent CaDiCaL worker."""

    def __init__(self, clauses: list[list[int]]):
        methods = multiprocessing.get_all_start_methods()
        context = multiprocessing.get_context("fork" if "fork" in methods else "spawn")
        self._channel, child_channel = context.Pipe(duplex=True)
        self._process = context.Process(
            target=_incremental_solver_worker,
            args=(clauses, child_channel),
            name="ssp-cadical300-incremental",
        )
        self._closed = False
        try:
            self._process.start()
        except BaseException:
            self._channel.close()
            child_channel.close()
            self._closed = True
            raise
        child_channel.close()

    @property
    def pid(self) -> int | None:
        return self._process.pid

    def solve(
        self,
        *,
        new_clauses: list[list[int]],
        assumptions: list[int],
        time_limit: float,
    ) -> SolverResult:
        if self._closed:
            raise RuntimeError("incremental solver session is closed")
        if time_limit <= 0:
            raise ValueError("time limit must be greater than zero")
        started = perf_counter()
        try:
            self._channel.send(("SOLVE", new_clauses, assumptions))
            remaining = time_limit - (perf_counter() - started)
            if remaining <= 0:
                self.close(force=True)
                return SolverResult(
                    "TIMEOUT",
                    perf_counter() - started,
                    None,
                    unavailable_solver_stats(),
                )
            ready = wait([self._channel, self._process.sentinel], timeout=remaining)
            elapsed = perf_counter() - started
            if self._channel not in ready:
                if self._process.sentinel in ready and self._channel.poll():
                    ready.append(self._channel)
                elif self._process.sentinel in ready:
                    self._process.join()
                    raise SolverConfigurationError(
                        "incremental CaDiCaL worker exited with code "
                        f"{self._process.exitcode} without a result"
                    )
                else:
                    self.close(force=True)
                    return SolverResult(
                        "TIMEOUT", elapsed, None, unavailable_solver_stats()
                    )
            try:
                payload = self._channel.recv()
            except EOFError as exc:
                raise SolverConfigurationError(
                    "incremental CaDiCaL worker closed without a result"
                ) from exc
            if payload[0] == "ERROR":
                raise SolverConfigurationError(
                    f"incremental CaDiCaL worker failed: {payload[1]}: {payload[2]}"
                )
            _, status, solve_time, model, stats = payload
            return SolverResult(status, solve_time, model, stats)
        except KeyboardInterrupt:
            self.close(force=True)
            raise
        except (NoSuchSolverError, ImportError, BrokenPipeError, EOFError, OSError, RuntimeError) as exc:
            self.close(force=True)
            if isinstance(exc, SolverConfigurationError):
                raise
            raise SolverConfigurationError(
                "PySAT CaDiCaL 3.0 backend 'cadical300' is unavailable or failed"
            ) from exc

    def close(self, *, force: bool = False) -> None:
        if self._closed:
            return
        self._closed = True
        if not force and self._process.is_alive():
            try:
                self._channel.send(("STOP",))
                self._process.join(timeout=1.0)
            except (BrokenPipeError, EOFError, OSError):
                pass
        _stop_process(self._process)
        self._channel.close()

    def __enter__(self) -> "IncrementalSolverSession":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close(force=exc_type is not None)
