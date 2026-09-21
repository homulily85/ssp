from __future__ import annotations

import stat
import tempfile
import textwrap
import unittest
from pathlib import Path

from src.distances import pairwise_distances
from src.dominance import preprocess_dominance
from src.encoding import build_maxsat_wcnf
from src.solver import SolverConfigurationError, solve_maxsat
from src.upper_bound import construct_upper_bound

from tests.helpers import make_instance


class EvalMaxSATTests(unittest.TestCase):
    def _build(self):
        instance = make_instance([{0}, {1}], 2, 1, "eval-maxsat")
        dominance = preprocess_dominance(instance)
        distances = pairwise_distances(dominance.reduced)
        upper = construct_upper_bound(instance, dominance, distances)
        return build_maxsat_wcnf(
            dominance.reduced,
            upper.cost,
            distances,
        )

    def _script(self, directory: str, source: str) -> Path:
        path = Path(directory) / "fake-eval-maxsat"
        path.write_text(
            "#!/usr/bin/env python3\n" + textwrap.dedent(source),
            encoding="utf-8",
        )
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        return path

    def test_parses_optimal_old_format_result(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = self._script(
                directory,
                """
                import sys
                assert "--TCT" not in sys.argv
                print("o 1")
                print("s OPTIMUM FOUND")
                print("v 1 -2")
                sys.exit(30)
                """,
            )
            result = solve_maxsat(self._build(), executable=executable)
        self.assertEqual(result.status, "OPTIMAL")
        self.assertEqual(result.objective, 1)
        self.assertEqual(result.model, (1, -2))

    def test_sigterm_collects_incumbent_at_timeout(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = self._script(
                directory,
                """
                import signal
                import sys
                import time

                def stop(signum, frame):
                    print("o 1")
                    print("s SATISFIABLE")
                    print("v 1 -2")
                    sys.exit(10)

                signal.signal(signal.SIGTERM, stop)
                while True:
                    time.sleep(0.01)
                """,
            )
            result = solve_maxsat(
                self._build(),
                time_limit=0.2,
                executable=executable,
            )
        self.assertEqual(result.status, "TIMEOUT")
        self.assertEqual(result.objective, 1)
        self.assertEqual(result.model, (1, -2))

    def test_sigterm_unknown_result_has_no_model(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = self._script(
                directory,
                """
                import signal
                import sys
                import time

                def stop(signum, frame):
                    print("s UNKNOWN")
                    sys.exit(0)

                signal.signal(signal.SIGTERM, stop)
                while True:
                    time.sleep(0.01)
                """,
            )
            result = solve_maxsat(
                self._build(),
                time_limit=0.2,
                executable=executable,
            )
        self.assertEqual(result.status, "TIMEOUT")
        self.assertIsNone(result.objective)
        self.assertIsNone(result.model)

    def test_process_ignoring_sigterm_is_killed_after_grace(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = self._script(
                directory,
                """
                import signal
                import time

                signal.signal(signal.SIGTERM, signal.SIG_IGN)
                while True:
                    time.sleep(0.01)
                """,
            )
            result = solve_maxsat(
                self._build(),
                time_limit=0.2,
                executable=executable,
                termination_grace=0.05,
            )
        self.assertEqual(result.status, "TIMEOUT")
        self.assertIsNone(result.model)
        self.assertLess(result.solve_time, 1.0)

    def test_malformed_natural_result_is_configuration_error(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = self._script(
                directory,
                """
                print("not a MaxSAT result")
                """,
            )
            with self.assertRaises(SolverConfigurationError):
                solve_maxsat(self._build(), executable=executable)

    def test_missing_binary_is_configuration_error(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(SolverConfigurationError):
                solve_maxsat(
                    self._build(),
                    executable=Path(directory) / "missing",
                )


if __name__ == "__main__":
    unittest.main()
