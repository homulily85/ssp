from itertools import permutations
import random
import unittest

from pysat.solvers import Solver

from experiments.order_ktns_cegar import (
    _ktns_reduced,
    build_order_master,
    decode_order,
    solve_instance,
    subsequence_cut,
    before_lit,
    shrink_subsequence,
)
from src.ktns import ktns
from tests.helpers import make_instance


def ordering_model(master, sequence):
    relation = {job: position for position, job in enumerate(sequence)}
    return tuple(
        variable if relation[i] < relation[j] else -variable
        for (i, j), variable in master.order_vars.items()
    )


class OrderKtnsCegarTests(unittest.TestCase):
    def test_order_master_represents_every_total_order(self):
        for n in range(1, 6):
            master = build_order_master(n, symmetry_break=False)
            self.assertEqual(master.variable_count, n * (n - 1) // 2)
            self.assertEqual(master.transitivity_clause_count, 2 * (n * (n - 1) * (n - 2) // 6))
            with Solver(name="cadical300", bootstrap_with=master.clauses) as solver:
                for sequence in permutations(range(n)):
                    literals = [before_lit(master, sequence[i], sequence[i + 1])
                                for i in range(n - 1)]
                    self.assertTrue(solver.solve(assumptions=literals))
                    decoded = decode_order(solver.get_model(), master)
                    self.assertEqual(decoded, sequence)

    def test_transitivity_and_reversal_symmetry_break(self):
        master = build_order_master(5)
        self.assertEqual(master.variable_count, 10)
        self.assertEqual(master.transitivity_clause_count, 20)
        self.assertEqual(master.base_clause_count, 21)
        with Solver(name="cadical300", bootstrap_with=master.clauses) as solver:
            self.assertFalse(solver.solve(assumptions=[
                before_lit(master, 0, 1),
                before_lit(master, 1, 2),
                before_lit(master, 2, 0),
            ]))
            self.assertFalse(solver.solve(assumptions=[before_lit(master, 1, 0)]))
            for sequence in permutations(range(5)):
                assumptions = [before_lit(master, sequence[i], sequence[i + 1])
                               for i in range(4)]
                expected = sequence.index(0) < sequence.index(1)
                self.assertEqual(solver.solve(assumptions=assumptions), expected)
                if expected:
                    self.assertEqual(decode_order(solver.get_model(), master), sequence)

    def test_ktns_cost_is_invariant_under_reversal(self):
        requirements = (frozenset({0}), frozenset({1}), frozenset({0, 2}), frozenset({2}))
        for sequence in permutations(range(len(requirements))):
            forward = ktns(sequence, requirements, 3, 2)[0]
            reverse = ktns(tuple(reversed(sequence)), requirements, 3, 2)[0]
            self.assertEqual(forward, reverse)

    def test_ktns_is_monotone_on_all_subsequences(self):
        requirements = (frozenset({0}), frozenset({1}), frozenset({0, 2}), frozenset({2}))
        for sequence in permutations(range(len(requirements))):
            full_cost = ktns(sequence, requirements, 3, 2)[0]
            for mask in range(1 << len(sequence)):
                subsequence = tuple(sequence[i] for i in range(len(sequence))
                                    if mask & (1 << i))
                sub_cost = 0 if not subsequence else ktns(
                    subsequence, requirements, 3, 2,
                )[0]
                self.assertLessEqual(sub_cost, full_cost)

    def test_shrinking_produces_inclusion_minimal_core(self):
        requirements = (frozenset({0}), frozenset({1}), frozenset({2}),
                        frozenset({0}), frozenset({1}))
        sequence = (0, 1, 2, 3, 4)
        result = shrink_subsequence(sequence, requirements, 3, 1, 2)
        self.assertTrue(result.completed)
        self.assertGreater(result.core_cost, 2)
        for job in result.core:
            trial = tuple(item for item in result.core if item != job)
            trial_cost = 0 if not trial else ktns(trial, requirements, 3, 1)[0]
            self.assertLessEqual(trial_cost, 2)

    def test_subsequence_cut_is_sound_for_every_extension(self):
        requirements = (frozenset({0}), frozenset({1}), frozenset({2}),
                        frozenset({0}), frozenset({1}))
        core = (0, 1, 2)
        bound = 2
        self.assertGreater(ktns(core, requirements, 3, 1)[0], bound)
        master = build_order_master(5, symmetry_break=False)
        cut = subsequence_cut(master, core)
        for sequence in permutations(range(5)):
            if all(sequence.index(core[i]) < sequence.index(core[i + 1])
                   for i in range(len(core) - 1)):
                self.assertGreater(ktns(sequence, requirements, 3, 1)[0], bound)
                model = ordering_model(master, sequence)
                positive = set(model)
                self.assertFalse(any(lit in positive for lit in cut))

    def test_random_small_instances_match_exhaustive_optimum(self):
        rng = random.Random(9137)
        for case in range(12):
            n = rng.randint(2, 7)
            m = rng.randint(2, 4)
            c = rng.randint(1, m)
            requirements = [set(rng.sample(range(m), rng.randint(0, c)))
                            for _ in range(n)]
            instance = make_instance(requirements, m, c, f"order-random-{case}")
            expected = min(ktns(sequence, instance.requirements, m, c)[0]
                           for sequence in permutations(range(n)))
            _, _, summary = solve_instance(instance, reference_cost=999, time_limit=30.0)
            with self.subTest(case=case, n=n, m=m, c=c):
                self.assertEqual(summary["status"], "OPTIMAL")
                self.assertEqual(summary["final_incumbent"], expected)

    def test_all_empty_requirements_are_handled(self):
        instance = make_instance([set(), set(), set()], 2, 1, "empty-tools")
        _, _, summary = solve_instance(instance, reference_cost=0, time_limit=5.0)
        self.assertEqual(summary["status"], "OPTIMAL")
        self.assertEqual(summary["final_incumbent"], 0)


if __name__ == "__main__":
    unittest.main()
