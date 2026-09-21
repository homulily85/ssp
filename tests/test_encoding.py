from __future__ import annotations

import unittest

from pysat.solvers import Solver

from src.distances import pairwise_distances
from src.dominance import preprocess_dominance
from src.encoding import (
    adjacency_clauses,
    build_cnf,
    build_incremental_cnf,
    build_maxsat_no_t_wcnf,
    build_maxsat_wcnf,
)
from src.model import AdditionalConstraints, ReducedInstance
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

    def test_optional_constraints_are_separate_from_core_encoding(self):
        reduced = ReducedInstance(
            "optional-constraints",
            4,
            2,
            (frozenset({0, 1}), frozenset({2, 3})),
            (0, 1),
        )
        distances = pairwise_distances(reduced)
        core = build_cnf(
            reduced,
            3,
            distances,
            additional_constraints=AdditionalConstraints.none(),
        )
        representatives = {
            "symmetry": [-core.vars_y[0, 2]],
            "required-transition": [
                -core.vars_x[0, 1],
                core.vars_z[0, 0],
                core.vars_t[0, 1],
            ],
            "insertion-requirement": [
                -core.vars_t[0, 2],
                core.vars_x[0, 2],
            ],
            "adjacency": [-core.vars_x[0, 1], -core.vars_x[1, 2]],
        }
        for clause in representatives.values():
            self.assertNotIn(clause, core.cnf.clauses)

        for name, clause in representatives.items():
            with self.subTest(constraint=name):
                selected = build_cnf(
                    reduced,
                    3,
                    distances,
                    additional_constraints=AdditionalConstraints.from_names([name]),
                )
                self.assertIn(clause, selected.cnf.clauses)

    def test_decoded_x_is_always_a_permutation(self):
        reduced, build = self._build([{0}, {1}, {2}], 3, 2, 6)
        self.assertGreater(build.variable_counts["position_amo_auxiliary"], 0)
        self.assertNotIn(
            [-build.vars_x[0, 1], -build.vars_x[1, 1]],
            build.cnf.clauses,
        )
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
            # The structural encoding has six permutations; reversal symmetry
            # breaking keeps the four with pivot job 0 in the first half.
            self.assertEqual(seen, 4)

    def test_largest_requirement_job_is_in_first_half(self):
        reduced = ReducedInstance(
            "symmetry",
            5,
            3,
            (
                frozenset({0}),
                frozenset({1, 2, 3}),
                frozenset({0, 4}),
                frozenset({2}),
            ),
            (0, 1, 2, 3),
        )
        build = build_cnf(reduced, 12, pairwise_distances(reduced))
        # N=4, ceil(N/2)+1=3, and local job 1 is the unique argmax.
        self.assertIn([-build.vars_y[1, 3]], build.cnf.clauses)
        with Solver(name="cadical300", bootstrap_with=build.cnf.clauses) as solver:
            self.assertFalse(solver.solve(assumptions=[build.vars_x[1, 3]]))

    def test_symmetry_pivot_tie_uses_smallest_original_job_id(self):
        reduced = ReducedInstance(
            "symmetry-tie",
            4,
            2,
            (frozenset({0, 1}), frozenset({2, 3}), frozenset({0})),
            (3, 7, 9),
        )
        build = build_cnf(reduced, 6, pairwise_distances(reduced))
        # Jobs 0 and 1 tie on |R|; original job 3 wins over original job 7.
        self.assertIn([-build.vars_y[0, 3]], build.cnf.clauses)
        self.assertNotIn([-build.vars_y[1, 3]], build.cnf.clauses)

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
        z0, z1, t = 1, 2, 3
        transition_clauses = [[-t, z1], [-t, -z0], [-z1, z0, t]]
        with Solver(name="cadical300", bootstrap_with=transition_clauses) as solver:
            for before, after, expected in ((0, 0, 0), (0, 1, 1), (1, 0, 0), (1, 1, 0)):
                assumptions = [z0 if before else -z0, z1 if after else -z1, t if expected else -t]
                self.assertTrue(solver.solve(assumptions=assumptions))

    def test_inserted_tool_must_be_required_from_second_position(self):
        reduced = ReducedInstance(
            "insertion-requirement",
            3,
            2,
            (frozenset({0}), frozenset({1})),
            (0, 1),
        )
        build = build_cnf(reduced, 4, pairwise_distances(reduced))
        # Tool 2 is required by no active job, so it cannot be inserted at j=2.
        self.assertIn([-build.vars_t[2, 2]], build.cnf.clauses)
        # Tool 0 may be inserted at j=2 only when job 0 is at that position.
        self.assertIn(
            [-build.vars_t[0, 2], build.vars_x[0, 2]],
            build.cnf.clauses,
        )
        with Solver(name="cadical300", bootstrap_with=build.cnf.clauses) as solver:
            self.assertFalse(solver.solve(assumptions=[build.vars_t[2, 2]]))

    def test_initial_filler_insertions_remain_allowed(self):
        reduced = ReducedInstance(
            "initial-fill",
            2,
            2,
            (frozenset({0}),),
            (0,),
        )
        build = build_cnf(reduced, 2, pairwise_distances(reduced))
        self.assertNotIn([-build.vars_t[1, 1]], build.cnf.clauses)
        with Solver(name="cadical300", bootstrap_with=build.cnf.clauses) as solver:
            self.assertTrue(solver.solve(assumptions=[build.vars_t[1, 1]]))

    def test_adjacency_pruning(self):
        reduced, build = self._build([{0, 1}, {2, 3}], 4, 2, 3)
        self.assertEqual(reduced.n, 2)
        with Solver(name="cadical300", bootstrap_with=build.cnf.clauses) as solver:
            self.assertFalse(
                solver.solve(assumptions=[build.vars_x[0, 1], build.vars_x[1, 2]])
            )

    def test_itotalizer_matches_standard_cardinality_bounds(self):
        dominance = preprocess_dominance(
            make_instance([{0, 1}, {1, 2}, {2, 3}, {0, 3}], 4, 2)
        )
        reduced = dominance.reduced
        distances = pairwise_distances(reduced)
        max_k = 6
        incremental = build_incremental_cnf(reduced, max_k, distances)
        self.assertGreater(incremental.variable_counts["itotalizer_auxiliary"], 0)
        for k in range(reduced.c, max_k + 1):
            standard = build_cnf(reduced, k, distances)
            extra = adjacency_clauses(
                reduced, distances, k, incremental.vars_x
            )
            assumptions = (
                [-incremental.totalizer_rhs[k]]
                if k < incremental.t_literal_count
                else []
            )
            with Solver(
                name="cadical300",
                bootstrap_with=incremental.cnf.clauses + extra,
            ) as incremental_solver, Solver(
                name="cadical300", bootstrap_with=standard.cnf.clauses
            ) as standard_solver:
                self.assertEqual(
                    incremental_solver.solve(assumptions=assumptions),
                    standard_solver.solve(),
                    f"different satisfiability at k={k}",
                )

    def test_maxsat_uses_unit_soft_clauses_without_global_cardinality(self):
        dominance = preprocess_dominance(
            make_instance([{0, 1}, {1, 2}, {2, 3}], 4, 2)
        )
        reduced = dominance.reduced
        build = build_maxsat_wcnf(
            reduced,
            6,
            pairwise_distances(reduced),
        )
        expected_soft = [
            [-build.core.vars_t[tool, position]]
            for position in range(1, reduced.n + 1)
            for tool in range(reduced.m)
        ]
        self.assertEqual(build.wcnf.soft, expected_soft)
        self.assertEqual(build.wcnf.wght, [1] * len(expected_soft))
        self.assertEqual(build.wcnf.hard, build.core.cnf.clauses)
        self.assertEqual(
            build.core.variable_counts["cardinality_auxiliary"], 0
        )

    def test_maxsat_no_t_uses_z_transition_soft_clauses(self):
        dominance = preprocess_dominance(
            make_instance([{0, 1}, {1, 2}, {2, 3}], 4, 2)
        )
        reduced = dominance.reduced
        build = build_maxsat_no_t_wcnf(
            reduced,
            6,
            pairwise_distances(reduced),
        )
        with_t = build_maxsat_wcnf(
            reduced,
            6,
            pairwise_distances(reduced),
        )
        expected_soft = [
            [
                build.core.vars_z[tool, position - 1],
                -build.core.vars_z[tool, position],
            ]
            for position in range(2, reduced.n + 1)
            for tool in range(reduced.m)
        ]
        self.assertFalse(build.core.vars_t)
        self.assertEqual(build.core.t_literal_count, 0)
        self.assertEqual(build.wcnf.soft, expected_soft)
        self.assertEqual(build.wcnf.wght, [1] * len(expected_soft))
        self.assertEqual(build.wcnf.hard, build.core.cnf.clauses)
        self.assertEqual(build.core.variable_counts["cardinality_auxiliary"], 0)
        self.assertEqual(
            build.core.variable_counts["primary"],
            with_t.core.variable_counts["primary"] - reduced.m * reduced.n,
        )

    def test_maxsat_no_t_rewrites_insertion_requirement(self):
        reduced = ReducedInstance(
            "maxsat-no-t-constraints",
            3,
            2,
            (frozenset({0}), frozenset({1})),
            (0, 1),
        )
        build = build_maxsat_no_t_wcnf(
            reduced,
            4,
            pairwise_distances(reduced),
        )
        self.assertIn(
            [build.core.vars_z[2, 1], -build.core.vars_z[2, 2]],
            build.wcnf.hard,
        )
        self.assertIn(
            [
                build.core.vars_z[0, 1],
                -build.core.vars_z[0, 2],
                build.core.vars_x[0, 2],
            ],
            build.wcnf.hard,
        )
        self.assertIn(
            [
                -build.core.vars_x[0, 2],
                build.core.vars_z[0, 1],
                build.core.vars_z[0, 2],
            ],
            build.wcnf.hard,
        )

    def test_adjacency_clause_sets_grow_as_bound_decreases(self):
        reduced, build = self._build([{0, 1}, {2, 3}, {0, 2}], 4, 2, 6)
        distances = pairwise_distances(reduced)
        at_four = {tuple(c) for c in adjacency_clauses(reduced, distances, 4, build.vars_x)}
        at_three = {tuple(c) for c in adjacency_clauses(reduced, distances, 3, build.vars_x)}
        self.assertLessEqual(at_four, at_three)


if __name__ == "__main__":
    unittest.main()
