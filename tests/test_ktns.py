from __future__ import annotations

import unittest
from itertools import permutations

from src.ktns import ktns

from tests.helpers import brute_force_magazine_cost, make_instance


class KTNSTests(unittest.TestCase):
    def test_matches_magazine_configuration_enumeration(self):
        instance = make_instance([{0}, {1, 2}, {0, 3}, {1}], 4, 2)
        for sequence in permutations(range(instance.n)):
            cost, configs = ktns(sequence, instance.requirements, instance.m, instance.c)
            self.assertEqual(cost, brute_force_magazine_cost(instance, sequence))
            self.assertTrue(all(len(config) <= instance.c for config in configs))

    def test_full_capacity_costs_exactly_capacity(self):
        instance = make_instance([{0}, {1}, {2}], 3, 3)
        cost, _ = ktns((0, 1, 2), instance.requirements, 3, 3)
        self.assertEqual(cost, 3)


if __name__ == "__main__":
    unittest.main()
