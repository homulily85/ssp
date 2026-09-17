from __future__ import annotations

import unittest

from pysat.solvers import Solver

from src.distances import pairwise_distances
from src.dominance import preprocess_dominance
from src.encoding import build_cnf
from src.model import ReducedInstance
from src.solver import solve_cnf

from tests.helpers import make_instance


class EncodingTests(unittest.TestCase):
    def _build(self, requirements, m, c, k):
        dominance = preprocess_dominance(make_instance(requirements, m, c))
        reduced = dominance.reduced
        return reduced, build_cnf(reduced, k, pairwise_distances(reduced))

    def test_k_below_capacity_is_immediately_unsat(self):
        _, build = self._build([{0}], 2, 1, 0)
        self.assertTrue(build.immediate_unsat)
        self.assertEqual(solve_cnf(build).status, "UNSAT")

    def test_decoded_x_is_always_a_permutation(self):
        reduced, build = self._build([{0}, {1}, {2}], 3, 2, 6)
        with Solver(name="cadical300", bootstrap_with=build.cnf.clauses) as solver:
            seen = 0
            while solver.solve():
                model = {literal for literal in solver.get_model() if literal > 0}
                selected = [
                    tuple(i for i in range(reduced.n) if build.vars_x[i, j] in model)
                    for j in range(1, reduced.n + 1)
                ]
                self.assertTrue(all(len(jobs) == 1 for jobs in selected))
                self.assertEqual({jobs[0] for jobs in selected}, set(range(reduced.n)))
                solver.add_clause([-build.vars_x[selected[j - 1][0], j] for j in range(1, reduced.n + 1)])
                seen += 1
            self.assertEqual(seen, 6)

    def test_magazine_counter_accepts_exactly_c_tools(self):
        _, build = self._build([{0}], 3, 2, 3)
        with Solver(name="cadical300", bootstrap_with=build.cnf.clauses) as solver:
            for mask in range(8):
                assumptions = [
                    build.vars_z[u, 1] if mask & (1 << u) else -build.vars_z[u, 1]
                    for u in range(3)
                ]
                expected = mask.bit_count() == 2 and bool(mask & 1)
                self.assertEqual(solver.solve(assumptions=assumptions), expected)

    def test_transition_truth_table(self):
        reduced = ReducedInstance(
            "transition", 2, 1, (frozenset(), frozenset()), (0, 1)
        )
        build = build_cnf(reduced, 2, pairwise_distances(reduced))
        with Solver(name="cadical300", bootstrap_with=build.cnf.clauses) as solver:
            t = build.vars_t[0, 2]
            z0 = build.vars_z[0, 1]
            z1 = build.vars_z[0, 2]
            for before, after, expected in ((0, 0, 0), (0, 1, 1), (1, 0, 0), (1, 1, 0)):
                assumptions = [z0 if before else -z0, z1 if after else -z1, t if expected else -t]
                self.assertTrue(solver.solve(assumptions=assumptions))

    def test_adjacency_pruning(self):
        reduced, build = self._build([{0, 1}, {2, 3}], 4, 2, 3)
        self.assertEqual(reduced.n, 2)
        with Solver(name="cadical300", bootstrap_with=build.cnf.clauses) as solver:
            self.assertFalse(
                solver.solve(assumptions=[build.vars_x[0, 1], build.vars_x[1, 2]])
            )


if __name__ == "__main__":
    unittest.main()
