from itertools import permutations
import csv
import tempfile
from pathlib import Path
import io
import random
import unittest
from contextlib import redirect_stderr, redirect_stdout

from pysat.solvers import Solver

from src.cli import build_argument_parser, main
from src.dominance import preprocess_dominance
from src.encoding import build_direct_cnf
from src.optimize import optimize_instance
from src.upper_bound import construct_upper_bound
from src.validate import validate_direct_solution
from tests.helpers import make_instance, brute_force_magazine_cost


class DirectTests(unittest.TestCase):
    def test_cli_requires_valid_algorithm(self):
        for argv in (["input.txt"], ["input.txt", "--algorithm", "unknown"]):
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                build_argument_parser().parse_args(argv)
        for algorithm in ("direct-sat", "tsp-sat-cegar"):
            self.assertEqual(build_argument_parser().parse_args(
                ["input.txt", "--algorithm", algorithm]).algorithm, algorithm)

    def test_direct_cli_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "instance.txt"
            output = Path(directory) / "result.csv"
            source.write_text("n=4\nm=4\nc=2\nproblem 1\n---\n1 0 0 1\n1 1 0 0\n0 1 1 0\n0 0 1 1\n")
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main([str(source), "--algorithm", "direct-sat",
                                       "--csv", str(output)]), 0)
            with output.open() as handle:
                row = next(csv.DictReader(handle))
            self.assertEqual(row["algorithm"], "direct-sat")
            self.assertEqual(row["cegar_rounds"], "0")
            self.assertEqual(row["subtour_cuts"], "0")
            self.assertGreater(int(row["solver_calls"]), 0)
            self.assertEqual(row["status"], "OPTIMAL")

    def test_direct_constraints_and_independent_validator(self):
        original = make_instance([{0}, {1}, {2}], 3, 1)
        dominance = preprocess_dominance(original)
        build = build_direct_cnf(dominance.reduced, 3, 0)
        with Solver(name="cadical300", bootstrap_with=build.cnf.clauses) as solver:
            self.assertFalse(solver.solve(assumptions=[build.vars_x[0, 2]]))
            self.assertFalse(solver.solve(assumptions=[build.vars_x[0, 0], build.vars_x[0, 1]]))
            self.assertFalse(solver.solve(assumptions=[build.vars_x[0, 0], -build.vars_z[0, 0]]))
            self.assertFalse(solver.solve(assumptions=[build.vars_z[0, 0], build.vars_z[1, 0]]))
            self.assertFalse(solver.solve(assumptions=[-build.totalizer_rhs[2]]))
            sequence = [build.vars_x[job, job] for job in range(3)]
            self.assertTrue(solver.solve(assumptions=sequence + [-build.totalizer_rhs[3]]))
            model = solver.get_model()
        validated = validate_direct_solution(original, dominance, build, model, 3)
        self.assertEqual(validated.sat_cost, 3)
        for tool in range(3):
            altered = [(-lit if abs(lit) == build.vars_t[tool, 0] else lit) for lit in model]
            with self.assertRaises(AssertionError):
                validate_direct_solution(original, dominance, build, altered, 3)

    def test_greedy_preserves_original_ids_and_policy(self):
        instance = make_instance([{1}, {1, 4}, {2, 4}, {1, 2}, {1, 4}], 6, 2)
        dominance = preprocess_dominance(instance)
        upper = construct_upper_bound(instance, dominance)
        self.assertEqual(upper.reduced_sequence, (1, 2, 3))
        self.assertEqual(upper.full_sequence, (1, 0, 4, 2, 3))
        self.assertEqual(upper.cost, 4)
        self.assertEqual(upper.magazine_configs[:3], (frozenset({1, 4}),)*3)

    def test_both_algorithms_match_independent_exhaustive_oracle(self):
        rng = random.Random(710)
        cases = [make_instance([set(), set()], 4, 3),
                 make_instance([{2}, {2}], 5, 3),
                 make_instance([{0, 1}, {1, 2}, {2, 3}, {0, 3}], 4, 2)]
        for index in range(25):
            m = rng.randint(2, 4)
            c = rng.randint(1, m)
            cases.append(make_instance([set(rng.sample(range(m), rng.randint(0, c)))
                                       for _ in range(rng.randint(1, 5))], m, c, str(index)))
        for instance in cases:
            expected = min(brute_force_magazine_cost(instance, seq)
                           for seq in permutations(range(instance.n)))
            for algorithm in ("direct-sat", "tsp-sat-cegar"):
                with self.subTest(instance=instance.name, algorithm=algorithm):
                    result = optimize_instance(instance, algorithm=algorithm)
                    self.assertEqual(result.optimum, expected)
                    self.assertEqual(result.verification_cost, expected)
                    self.assertEqual(sum(map(len, result.inserted_tools)), expected)
                    if algorithm == "direct-sat":
                        self.assertEqual(result.cegar_rounds, 0)
                        self.assertEqual(result.subtour_cuts, 0)
                        self.assertTrue(all(item.cegar_round == 0 for item in result.iterations))

    def test_direct_timeout_keeps_greedy_incumbent(self):
        instance = make_instance([{0, 1}, {1, 2}, {2, 3}, {0, 3}], 4, 2)
        result = optimize_instance(instance, algorithm="direct-sat", time_limit=1e-9)
        self.assertEqual(result.status, "TIMEOUT")
        self.assertIsNone(result.optimum)
        self.assertEqual(result.best_cost, result.initial_upper_bound)
        self.assertEqual(result.iterations[-1].cegar_round, 0)
