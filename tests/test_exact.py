from __future__ import annotations

import random
import unittest

from src.optimize import optimize_instance

from tests.helpers import brute_force_optimum, make_instance


class ExactEndToEndTests(unittest.TestCase):
    def test_hand_written_edge_cases(self):
        cases = [
            make_instance([{0}, {0}, {0}], 2, 1, "duplicates"),
            make_instance([{0}, {1}, {2}], 3, 3, "c-equals-m"),
            make_instance([{0, 1}, {0}, {1}, {2}], 3, 2, "dominance"),
            make_instance([{0}, {1}, {2}, {3}], 4, 2, "no-dominance"),
        ]
        for instance in cases:
            with self.subTest(instance=instance.name):
                expected, _ = brute_force_optimum(instance)
                actual = optimize_instance(instance)
                incremental = optimize_instance(instance, incremental=True)
                self.assertEqual(actual.optimum, expected)
                self.assertEqual(incremental.optimum, expected)
                self.assertEqual(incremental.mode, "incremental")
                self.assertEqual(actual.verification_cost, expected)

    def test_seeded_random_instances_match_exhaustive_search(self):
        randomizer = random.Random(20260917)
        for case in range(8):
            n = randomizer.randint(2, 6)
            m = randomizer.randint(3, 6)
            c = randomizer.randint(1, m)
            requirements = []
            for _ in range(n):
                size = randomizer.randint(0, c)
                requirements.append(set(randomizer.sample(range(m), size)))
            instance = make_instance(requirements, m, c, f"random-{case}")
            with self.subTest(instance=instance.name):
                expected, _ = brute_force_optimum(instance)
                result = optimize_instance(instance)
                incremental = optimize_instance(instance, incremental=True)
                self.assertEqual(result.optimum, expected)
                self.assertEqual(incremental.optimum, expected)


if __name__ == "__main__":
    unittest.main()
