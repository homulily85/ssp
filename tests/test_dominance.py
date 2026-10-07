from __future__ import annotations

import unittest
from itertools import permutations

from src.dominance import preprocess_dominance, reconstruct_sequence
from src.ktns import ktns

from tests.helpers import make_instance


class DominanceTests(unittest.TestCase):
    def test_chain_keeps_only_maximal_representative(self):
        instance = make_instance([{0, 1}, {0, 1, 2}, {0, 1, 2, 3}], 4, 4)
        result = preprocess_dominance(instance)
        self.assertEqual(result.active_jobs, (2,))
        self.assertEqual(result.dominator, {0: 2, 1: 2})
        self.assertEqual(reconstruct_sequence((2,), result), (2, 0, 1))

    def test_duplicates_use_canonical_job(self):
        instance = make_instance([{0}, {0}, {1}], 2, 1)
        result = preprocess_dominance(instance)
        self.assertEqual(result.active_jobs, (0, 2))
        self.assertEqual(result.dominator[1], 0)

    def test_reconstruction_does_not_raise_best_reduced_cost(self):
        instance = make_instance([{0}, {0, 1}, {2}, {0, 1, 2}], 4, 3)
        result = preprocess_dominance(instance)
        for order in permutations(result.active_jobs):
            full = reconstruct_sequence(order, result)
            full_cost, _ = ktns(full, instance.requirements, instance.m, instance.c)
            representative_cost, _ = ktns(order, instance.requirements, instance.m, instance.c)
            self.assertLessEqual(full_cost, representative_cost)

    def test_unused_tools_are_compacted_and_remapped(self):
        instance = make_instance([{1, 4}, {1, 2}, {2, 4}], 6, 2)
        result = preprocess_dominance(instance)

        self.assertEqual(result.reduced.m, 3)
        self.assertEqual(result.reduced.c, 2)
        self.assertEqual(result.reduced.tool_to_original, (1, 2, 4))
        self.assertEqual(
            result.reduced.requirements,
            (frozenset({0, 2}), frozenset({0, 1}), frozenset({1, 2})),
        )

    def test_compacting_below_capacity_does_not_load_unused_tools(self):
        instance = make_instance([{2}, {2}], 5, 3)
        result = preprocess_dominance(instance)

        self.assertEqual(result.reduced.m, 1)
        self.assertEqual(result.reduced.c, 1)
        self.assertEqual(result.reduced.tool_to_original, (2,))


if __name__ == "__main__":
    unittest.main()
