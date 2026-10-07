from itertools import permutations
import unittest
from unittest.mock import patch

from pysat.card import ITotalizer
from pysat.solvers import Solver

from experiments.objective_encoding_ablation import (
    _counter, run_fixed, run_optimization,
)
import experiments.objective_encoding_ablation as ablation
from tests.helpers import brute_force_magazine_cost, make_instance


class ObjectiveEncodingExperimentTests(unittest.TestCase):
    def setUp(self):
        self.instance = make_instance(
            [{0, 1}, {1, 2}, {2, 3}, {0, 3}], 4, 2, "ablation-small"
        )
        self.expected = min(
            brute_force_magazine_cost(self.instance, sequence)
            for sequence in permutations(range(self.instance.n))
        )

    def test_all_optimization_modes_match_brute_force(self):
        for mode in ("seqcounter-fresh", "seqcounter-accumulated", "itotalizer-assumption"):
            with self.subTest(mode=mode):
                _, summary = run_optimization(self.instance, 20, mode, 30.0)
                self.assertEqual(summary["status"], "OPTIMAL")
                self.assertEqual(summary["final_incumbent"], self.expected)

    def test_fixed_encodings_agree_at_multiple_bounds(self):
        # Exercise the actual static formulations independently of optimizer state.
        from src.dominance import preprocess_dominance
        from src.encoding import build_direct_cnf

        dominance = preprocess_dominance(self.instance)
        anchor = dominance.original_to_local[0]
        build = build_direct_cnf(dominance.reduced, 0, anchor)
        literals = list(build.vars_t.values())
        for bound in range(len(literals)):
            seq, _ = _counter(literals, bound, build.vpool.top)
            totalizer = ITotalizer(lits=literals, ubound=bound, top_id=build.vpool.top)
            total = [list(clause) for clause in totalizer.cnf.clauses]
            if bound < len(totalizer.rhs):
                total.append([-totalizer.rhs[bound]])
            totalizer.delete()
            with Solver(name="cadical300", bootstrap_with=build.cnf.clauses + seq) as solver:
                seq_sat = solver.solve()
            with Solver(name="cadical300", bootstrap_with=build.cnf.clauses + total) as solver:
                total_sat = solver.solve()
            self.assertEqual(seq_sat, total_sat, f"bound={bound}")

    def test_fresh_and_accumulated_formula_accounting(self):
        actual_session = ablation.IncrementalSolverSession
        made = []

        def tracked_session(*args, **kwargs):
            session = actual_session(*args, **kwargs)
            made.append(session)
            return session

        with patch.object(ablation, "IncrementalSolverSession", side_effect=tracked_session):
            fresh_rows, _ = run_optimization(self.instance, 20, "seqcounter-fresh", 30.0)
        self.assertEqual(len(made), len(fresh_rows))
        self.assertEqual(len({session.pid for session in made}), len(made))
        for row in fresh_rows:
            self.assertEqual(
                row["current_total_clauses"],
                row["base_clauses"] + row["objective_clauses_added"],
            )
            self.assertEqual(
                row["current_total_variables"],
                row["base_variables"] + row["objective_aux_variables_added"],
            )

        made.clear()
        with patch.object(ablation, "IncrementalSolverSession", side_effect=tracked_session):
            accumulated_rows, _ = run_optimization(
                self.instance, 20, "seqcounter-accumulated", 30.0
            )
        self.assertEqual(len(made), 1)
        for previous, current in zip(accumulated_rows, accumulated_rows[1:]):
            self.assertEqual(
                current["current_total_clauses"],
                previous["current_total_clauses"] + current["objective_clauses_added"],
            )
            self.assertEqual(
                current["current_total_variables"],
                previous["current_total_variables"] + current["objective_aux_variables_added"],
            )

    def test_totalizer_objective_is_added_only_once_in_trajectory(self):
        rows, _ = run_optimization(self.instance, 20, "itotalizer-assumption", 30.0)
        self.assertTrue(rows)
        self.assertGreater(rows[0]["objective_clauses_added"], 0)
        for row in rows[1:]:
            self.assertEqual(row["objective_clauses_added"], 0)
            self.assertEqual(row["objective_aux_variables_added"], 0)
            self.assertEqual(row["current_total_clauses"], rows[0]["current_total_clauses"])
            self.assertEqual(row["current_total_variables"], rows[0]["current_total_variables"])

    def test_fixed_harness_is_one_independent_call_per_encoding(self):
        for mode in ("fixed-seqcounter", "fixed-totalizer"):
            rows, summary = run_fixed(self.instance, 20, mode, 30.0)
            self.assertEqual(len(rows), 1)
            self.assertEqual(summary["solver_calls"], 1)
            self.assertEqual(rows[0]["k"], 19)


if __name__ == "__main__":
    unittest.main()
