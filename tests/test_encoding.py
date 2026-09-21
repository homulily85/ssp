from __future__ import annotations

import unittest
from unittest.mock import patch

from pysat.card import CardEnc, EncType
from pysat.solvers import Solver

from src.encoding import build_tsp_cnf
from src.model import ReducedInstance
from src.subtour import decode_successor, find_cycles, subtour_cut


class TSPEncodingTests(unittest.TestCase):
    def _build(
        self,
        requirements: list[set[int]],
        m: int,
        c: int,
        max_bound: int = 8,
    ):
        reduced = ReducedInstance(
            "encoding",
            m,
            c,
            tuple(frozenset(required) for required in requirements),
            tuple(range(len(requirements))),
        )
        return reduced, build_tsp_cnf(reduced, max_bound)

    def test_primary_variables_use_tsp_vertices_without_self_loops(self):
        reduced, build = self._build([{0}, {1}, {0, 1}], 3, 2)
        self.assertEqual(len(build.vars_x), (reduced.n + 1) * reduced.n)
        self.assertEqual(len(build.vars_z), reduced.n * reduced.m)
        self.assertEqual(len(build.vars_t), reduced.n * reduced.m)
        self.assertFalse(
            any((vertex, vertex) in build.vars_x for vertex in range(reduced.n + 1))
        )
        self.assertEqual(
            build.variable_counts["primary"],
            len(build.vars_x) + len(build.vars_z) + len(build.vars_t),
        )

    def test_all_non_objective_cardinalities_use_sequential_counters(self):
        _, _ = self._build([{0}, {1}], 2, 1)
        original = CardEnc.equals
        with patch("src.encoding.CardEnc.equals", wraps=original) as equals:
            self._build([{0}, {1}], 2, 1)
        # 2 degree equalities for every vertex and one capacity equality/job.
        self.assertEqual(equals.call_count, 2 * 3 + 2)
        self.assertTrue(
            all(call.kwargs["encoding"] == EncType.seqcounter for call in equals.call_args_list)
        )

    def test_capacity_and_required_tools_are_enforced(self):
        _, build = self._build([{0, 1}], 3, 2)
        with Solver(name="cadical300", bootstrap_with=build.cnf.clauses) as solver:
            self.assertTrue(
                solver.solve(
                    assumptions=[build.vars_z[0, 1], build.vars_z[1, 1], -build.vars_z[2, 1]]
                )
            )
            self.assertFalse(solver.solve(assumptions=[-build.vars_z[0, 1]]))
            self.assertFalse(
                solver.solve(
                    assumptions=[build.vars_z[0, 1], build.vars_z[1, 1], build.vars_z[2, 1]]
                )
            )

    def test_dummy_and_real_transitions_define_insertions(self):
        _, build = self._build([{0}, {1}], 2, 1)
        cycle = [build.vars_x[0, 1], build.vars_x[1, 2], build.vars_x[2, 0]]
        with Solver(name="cadical300", bootstrap_with=build.cnf.clauses) as solver:
            self.assertTrue(solver.solve(assumptions=cycle))
            model = {literal for literal in solver.get_model() if literal > 0}
        self.assertIn(build.vars_t[0, 1], model)
        self.assertNotIn(build.vars_t[1, 1], model)
        self.assertNotIn(build.vars_t[0, 2], model)
        self.assertIn(build.vars_t[1, 2], model)

    def test_totalizer_assumptions_match_the_insertion_bound(self):
        _, build = self._build([{0}, {1}], 2, 1, max_bound=2)
        with Solver(name="cadical300", bootstrap_with=build.cnf.clauses) as solver:
            self.assertFalse(solver.solve(assumptions=[-build.totalizer_rhs[1]]))
            self.assertTrue(solver.solve(assumptions=[-build.totalizer_rhs[2]]))

    def test_all_bad_cycles_produce_exit_cuts(self):
        reduced, build = self._build([{0}] * 5, 1, 1, max_bound=2)
        forced_cover = [
            build.vars_x[0, 1],
            build.vars_x[1, 0],
            build.vars_x[2, 3],
            build.vars_x[3, 2],
            build.vars_x[4, 5],
            build.vars_x[5, 4],
        ]
        with Solver(name="cadical300", bootstrap_with=build.cnf.clauses) as solver:
            self.assertTrue(solver.solve(assumptions=forced_cover))
            successor = decode_successor(solver.get_model(), build.vars_x, reduced.n)
        bad_cycles = [cycle for cycle in find_cycles(successor) if 0 not in cycle]
        self.assertEqual({frozenset(cycle) for cycle in bad_cycles}, {frozenset({2, 3}), frozenset({4, 5})})
        cuts = [subtour_cut(cycle, build.vars_x, reduced.n) for cycle in bad_cycles]
        with Solver(
            name="cadical300", bootstrap_with=build.cnf.clauses + cuts
        ) as solver:
            self.assertFalse(solver.solve(assumptions=forced_cover))


if __name__ == "__main__":
    unittest.main()
