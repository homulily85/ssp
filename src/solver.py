from __future__ import annotations

import multiprocessing
import subprocess
from multiprocessing.connection import Connection, wait
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

from pysat.solvers import NoSuchSolverError, Solver

from .model import CNFBuildResult, MaxSATBuildResult, SolverResult


class SolverConfigurationError(RuntimeError):
    pass


_TRACKED_STATS = ("restarts", "conflicts", "decisions", "propagations")


def _with_tracked_stats(stats: dict[str, int | float]) -> dict[str, int | float]:
    normalized = dict(stats)
    for key in _TRACKED_STATS:
        normalized.setdefault(key, 0)
    return normalized


def unavailable_solver_stats() -> dict[str, None]:
    """Return explicit unknown values when a killed worker cannot report stats."""
    return {key: None for key in _TRACKED_STATS}


def _eval_maxsat_binary() -> Path:
    return Path(__file__).resolve().parent.parent / "bin" / "EvalMaxSAT_bin"


def _eval_maxsat_error(
    message: str, stdout: str = "", stderr: str = ""
) -> SolverConfigurationError:
    details = []
    if stdout.strip():
        details.append(f"stdout: {stdout.strip()[-1000:]}")
    if stderr.strip():
        details.append(f"stderr: {stderr.strip()[-1000:]}")
    suffix = f" ({'; '.join(details)})" if details else ""
    return SolverConfigurationError(f"{message}{suffix}")


def _parse_eval_maxsat_output(
    stdout: str,
) -> tuple[str | None, int | None, tuple[int, ...] | None]:
    status: str | None = None
    objective: int | None = None
    model: tuple[int, ...] | None = None
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if line.startswith("s "):
            status = line[2:].strip()
        elif line.startswith("o "):
            try:
                objective = int(line.split(maxsplit=1)[1])
            except (IndexError, ValueError) as exc:
                raise _eval_maxsat_error(
                    f"invalid EvalMaxSAT objective line: {line!r}", stdout
                ) from exc
        elif line == "v":
            model = ()
        elif line.startswith("v "):
            try:
                model = tuple(int(literal) for literal in line.split()[1:])
            except ValueError as exc:
                raise _eval_maxsat_error(
                    f"invalid EvalMaxSAT model line: {line!r}", stdout
                ) from exc
    return status, objective, model


def solve_maxsat(
    build: MaxSATBuildResult,
    time_limit: float = 600.0,
    *,
    executable: str | Path | None = None,
    termination_grace: float = 1.0,
) -> SolverResult:
    """Run EvalMaxSAT and request its incumbent with SIGTERM at the deadline."""
    if time_limit <= 0:
        raise ValueError("time limit must be greater than zero")
    if termination_grace <= 0:
        raise ValueError("termination grace must be greater than zero")

    binary = Path(executable) if executable is not None else _eval_maxsat_binary()
    if not binary.is_file():
        raise SolverConfigurationError(f"EvalMaxSAT binary not found: {binary}")
    if not binary.stat().st_mode & 0o111:
        raise SolverConfigurationError(f"EvalMaxSAT binary is not executable: {binary}")

    process: subprocess.Popen[str] | None = None
    started = perf_counter()
    timed_out = False
    with TemporaryDirectory(prefix="ssp-maxsat-") as directory:
        formula_path = Path(directory) / "instance.wcnf"
        build.wcnf.to_file(str(formula_path))
        remaining = time_limit - (perf_counter() - started)
        if remaining <= 0:
            return SolverResult(
                "TIMEOUT",
                perf_counter() - started,
                None,
                unavailable_solver_stats(),
            )
        try:
            process = subprocess.Popen(
                [str(binary), "--old", str(formula_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                stdout, stderr = process.communicate(timeout=remaining)
            except subprocess.TimeoutExpired:
                timed_out = True
                process.terminate()
                try:
                    stdout, stderr = process.communicate(timeout=termination_grace)
                except subprocess.TimeoutExpired:
                    process.kill()
                    stdout, stderr = process.communicate()
        except KeyboardInterrupt:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.communicate(timeout=termination_grace)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate()
            raise
        except OSError as exc:
            if process is not None and process.poll() is None:
                process.kill()
                process.communicate()
            raise SolverConfigurationError(
                f"failed to run EvalMaxSAT binary {binary}: {exc}"
            ) from exc

    elapsed = perf_counter() - started
    status_line, objective, model = _parse_eval_maxsat_output(stdout)
    return_code = process.returncode if process is not None else None
    stats = unavailable_solver_stats()

    if status_line == "OPTIMUM FOUND":
        if return_code != 30 or objective is None or model is None:
            raise _eval_maxsat_error(
                "incomplete or inconsistent optimal EvalMaxSAT result",
                stdout,
                stderr,
            )
        return SolverResult("OPTIMAL", elapsed, model, stats, objective)
    if status_line == "SATISFIABLE":
        if return_code != 10 or objective is None or model is None:
            raise _eval_maxsat_error(
                "incomplete or inconsistent incumbent EvalMaxSAT result",
                stdout,
                stderr,
            )
        return SolverResult("TIMEOUT", elapsed, model, stats, objective)
    if status_line == "UNKNOWN":
        if not timed_out and return_code != 0:
            raise _eval_maxsat_error(
                "unexpected EvalMaxSAT UNKNOWN result", stdout, stderr
            )
        return SolverResult("TIMEOUT", elapsed, None, stats)
    if status_line == "UNSATISFIABLE":
        if return_code != 20:
            raise _eval_maxsat_error(
                "inconsistent EvalMaxSAT UNSATISFIABLE result", stdout, stderr
            )
        return SolverResult("UNSAT", elapsed, None, stats)
    if timed_out:
        return SolverResult("TIMEOUT", elapsed, None, stats)
    raise _eval_maxsat_error(
        f"EvalMaxSAT exited with code {return_code} without a recognized status",
        stdout,
        stderr,
    )


def _solver_worker(clauses: list[list[int]], sender: Connection) -> None:
    """Run CaDiCaL in an isolated process and return a serializable result."""
    try:
        with Solver(
            name="cadical300", bootstrap_with=clauses, use_timer=True
        ) as solver:
            satisfiable = solver.solve()
            payload = (
                "RESULT",
                "SAT" if satisfiable else "UNSAT",
                float(solver.time()),
                tuple(solver.get_model()) if satisfiable else None,
                _with_tracked_stats(dict(solver.accum_stats() or {})),
            )
        sender.send(payload)
    except BaseException as exc:
        try:
            sender.send(("ERROR", type(exc).__name__, str(exc)))
        except BaseException:
            pass
    finally:
        sender.close()


def _incremental_solver_worker(
    clauses: list[list[int]], channel: Connection
) -> None:
    """Keep one CaDiCaL instance alive and solve successive assumptions."""
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
                iteration_stats = dict(cumulative_stats)
                for key in _TRACKED_STATS:
                    iteration_stats[key] = (
                        cumulative_stats[key] - previous_stats.get(key, 0)
                    )
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


def solve_cnf(build: CNFBuildResult, time_limit: float = 600.0) -> SolverResult:
    if time_limit <= 0:
        raise ValueError("time limit must be greater than zero")
    if build.immediate_unsat:
        return SolverResult("UNSAT", 0.0, None, {})

    methods = multiprocessing.get_all_start_methods()
    context = multiprocessing.get_context("fork" if "fork" in methods else "spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(
        target=_solver_worker,
        args=(build.cnf.clauses, sender),
        name="ssp-cadical300",
    )
    started = perf_counter()
    try:
        process.start()
        sender.close()
        ready = wait([receiver, process.sentinel], timeout=time_limit)
        elapsed = perf_counter() - started
        if receiver not in ready:
            if process.sentinel in ready and receiver.poll():
                ready.append(receiver)
            elif process.sentinel in ready:
                process.join()
                raise SolverConfigurationError(
                    f"CaDiCaL worker exited with code {process.exitcode} without a result"
                )
            else:
                _stop_process(process)
                return SolverResult(
                    "TIMEOUT", elapsed, None, unavailable_solver_stats()
                )

        try:
            payload = receiver.recv()
        except EOFError as exc:
            raise SolverConfigurationError("CaDiCaL worker closed without a result") from exc
        process.join(timeout=1.0)
        _stop_process(process)
        if payload[0] == "ERROR":
            raise SolverConfigurationError(
                f"CaDiCaL worker failed: {payload[1]}: {payload[2]}"
            )
        _, status, solve_time, model, stats = payload
        return SolverResult(status, solve_time, model, stats)
    except KeyboardInterrupt:
        _stop_process(process)
        raise
    except (NoSuchSolverError, ImportError, OSError, RuntimeError) as exc:
        _stop_process(process)
        if isinstance(exc, SolverConfigurationError):
            raise
        raise SolverConfigurationError(
            "PySAT CaDiCaL 3.0 backend 'cadical300' is unavailable or failed to initialize"
        ) from exc
    finally:
        receiver.close()
        sender.close()


class IncrementalSolverSession:
    """Parent-side handle for a persistent, time-limited CaDiCaL worker."""

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
            ready = wait(
                [self._channel, self._process.sentinel], timeout=remaining
            )
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
        except (BrokenPipeError, EOFError, OSError, RuntimeError) as exc:
            self.close(force=True)
            if isinstance(exc, SolverConfigurationError):
                raise
            raise SolverConfigurationError(
                "incremental CaDiCaL worker communication failed"
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
        if self._process.pid is not None and not self._process.is_alive():
            self._process.join()
        self._channel.close()

    def __enter__(self) -> "IncrementalSolverSession":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close(force=exc_type is not None)
