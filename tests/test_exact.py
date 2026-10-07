from __future__ import annotations

import io
import random
import unittest

from src.model import ALGORITHM
from src.optimize import optimize_instance
from src.report import print_result

from tests.helpers import brute_force_optimum, make_instance


class ExactEndToEndTests(unittest.TestCase):
    def test_solver_statistics_and_cegar_fields_are_reported(self):
        instance = make_instance(
            [{0, 1}, {1, 2}, {2, 3}, {0, 3}], 4, 2, "stats"
        )
        result = optimize_instance(instance, algorithm="tsp-sat-cegar")
        self.assertEqual(result.algorithm, ALGORITHM)
        for iteration in result.iterations:
            for key in ("restarts", "conflicts", "decisions", "propagations"):
                self.assertIn(key, iteration.stats)
            self.assertGreaterEqual(iteration.cegar_round, 1)
            self.assertGreaterEqual(iteration.subtour_cuts_added, 0)
        output = io.StringIO()
        print_result(result, output)
        self.assertIn("Algorithm: tsp-sat-cegar", output.getvalue())
        self.assertIn("cuts_total=", output.getvalue())

    def test_hand_written_cases(self):
        cases = [
            (make_instance([{0}], 1, 1, "one-job"), 1),
            (make_instance([{0, 1}, {0, 1}, {0, 1}], 3, 2, "same-tools"), 2),
            (make_instance([{0, 1}, {2, 3}], 4, 2, "disjoint"), 4),
            (make_instance([{0, 1}, {0}, {1}, {2}], 3, 2, "dominance"), None),
            (make_instance([{0}, {1}, {2}, {3}], 4, 2, "no-dominance"), None),
        ]
        for instance, expected_cost in cases:
            with self.subTest(instance=instance.name):
                expected, _ = brute_force_optimum(instance)
                result = optimize_instance(instance, algorithm="tsp-sat-cegar")
                self.assertEqual(result.status, "OPTIMAL")
                self.assertEqual(result.optimum, expected)
                if expected_cost is not None:
                    self.assertEqual(result.optimum, expected_cost)
                self.assertEqual(result.verification_cost, expected)

    def test_compacted_tools_preserve_the_original_optimum(self):
        instance = make_instance([{1, 4}, {1, 2}, {2, 4}], 6, 2, "tool-pruning")
        expected, _ = brute_force_optimum(instance)

        result = optimize_instance(instance, algorithm="tsp-sat-cegar")

        self.assertEqual(result.dominance.reduced.m, 3)
        self.assertEqual(result.status, "OPTIMAL")
        self.assertEqual(result.optimum, expected)
        self.assertEqual(result.verification_cost, expected)

    def test_seeded_random_instances_match_exhaustive_search(self):
        randomizer = random.Random(20260921)
        for case in range(12):
            n = randomizer.randint(2, 6)
            m = randomizer.randint(3, 6)
            c = randomizer.randint(1, m)
            requirements = [
                set(randomizer.sample(range(m), randomizer.randint(0, c)))
                for _ in range(n)
            ]
            instance = make_instance(requirements, m, c, f"random-{case}")
            with self.subTest(instance=instance.name):
                expected, _ = brute_force_optimum(instance)
                result = optimize_instance(instance, algorithm="tsp-sat-cegar")
                self.assertEqual(result.optimum, expected)
                self.assertEqual(result.verification_cost, expected)

    def test_sat_witness_can_skip_intermediate_bounds(self):
        instance = make_instance(
            [{0, 1}, {1, 2}, {2, 3}, {0, 3}], 4, 2, "bound-jump"
        )
        result = optimize_instance(instance, algorithm="tsp-sat-cegar")
        sat_witnesses = [
            item
            for item in result.iterations
            if item.status == "SAT" and item.actual_solution_cost is not None
        ]
        for witness in sat_witnesses:
            self.assertLessEqual(witness.actual_solution_cost, witness.k)


if __name__ == "__main__":
    unittest.main()
