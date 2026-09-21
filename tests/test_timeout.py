from __future__ import annotations

import csv
import io
import multiprocessing
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from src.encoding import build_tsp_cnf
from src.dominance import preprocess_dominance
from src.optimize import optimize_instance
from src.report import print_result, write_csv
from src.solver import IncrementalSolverSession

from tests.helpers import make_instance


def _sleeping_incremental_worker(clauses, channel):
    time.sleep(10)


class TimeoutTests(unittest.TestCase):
    def _build(self):
        dominance = preprocess_dominance(make_instance([{0}, {1}], 2, 1))
        return build_tsp_cnf(dominance.reduced, 2)

    def test_incremental_session_timeout_terminates_worker(self):
        build = self._build()
        with patch(
            "src.solver._incremental_solver_worker",
            _sleeping_incremental_worker,
        ):
            session = IncrementalSolverSession(build.cnf.clauses)
            result = session.solve(new_clauses=[], assumptions=[], time_limit=0.02)
        self.assertEqual(result.status, "TIMEOUT")
        self.assertTrue(all(value is None for value in result.stats.values()))
        self.assertFalse(
            any(
                child.name == "ssp-cadical300-incremental"
                for child in multiprocessing.active_children()
            )
        )

    def test_incremental_session_reuses_one_worker(self):
        with IncrementalSolverSession([]) as session:
            pid = session.pid
            first = session.solve(new_clauses=[[1]], assumptions=[], time_limit=1)
            second = session.solve(new_clauses=[], assumptions=[-1], time_limit=1)
            self.assertEqual(session.pid, pid)
            self.assertEqual(first.status, "SAT")
            self.assertEqual(second.status, "UNSAT")
        self.assertFalse(
            any(
                child.name == "ssp-cadical300-incremental"
                for child in multiprocessing.active_children()
            )
        )

    def test_keyboard_interrupt_terminates_incremental_worker(self):
        with patch(
            "src.solver._incremental_solver_worker",
            _sleeping_incremental_worker,
        ), patch("src.solver.wait", side_effect=KeyboardInterrupt):
            session = IncrementalSolverSession([])
            with self.assertRaises(KeyboardInterrupt):
                session.solve(new_clauses=[], assumptions=[], time_limit=10)
        self.assertFalse(
            any(
                child.name == "ssp-cadical300-incremental"
                for child in multiprocessing.active_children()
            )
        )

    def test_optimizer_does_not_claim_optimum_after_timeout(self):
        instance = make_instance(
            [{0, 1}, {1, 2}, {2, 3}, {0, 3}], 4, 2, "timeout"
        )
        result = optimize_instance(instance, time_limit=1e-9)
        self.assertEqual(result.status, "TIMEOUT")
        self.assertIsNone(result.optimum)
        self.assertEqual(result.best_cost, result.initial_upper_bound)
        self.assertEqual(result.iterations[-1].status, "TIMEOUT")

        console = io.StringIO()
        print_result(result, console)
        self.assertIn("restarts=N/A", console.getvalue())
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "timeout.csv"
            write_csv([result], output)
            with output.open(encoding="utf-8", newline="") as handle:
                row = next(csv.DictReader(handle))
            for key in ("restarts", "conflicts", "decisions", "propagations"):
                self.assertEqual(row[key], "N/A")

    def test_non_positive_limit_is_rejected(self):
        instance = make_instance([{0}], 1, 1)
        with self.assertRaises(ValueError):
            optimize_instance(instance, time_limit=0)


if __name__ == "__main__":
    unittest.main()
