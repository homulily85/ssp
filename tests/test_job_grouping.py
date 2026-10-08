from __future__ import annotations

import itertools
import unittest
from pathlib import Path
from unittest.mock import patch

from pysat.solvers import Solver

from src.dominance import preprocess_dominance
from src.job_grouping import build_job_grouping_cnf, decode_job_grouping
from src.ktns import ktns, ktns_switches
from src.optimize import optimize_instance
from src.parser import parse_file
from tests.helpers import make_instance


def oracle(sequence, requirements, m, c):
    """Independent DP over every feasible magazine state, including free M0."""
    states = [frozenset(s) for size in range(c + 1)
              for s in itertools.combinations(range(m), size)]
    costs = {state: 0 for state in states}
    parents = []
    for position, job in enumerate(sequence):
        nxt = {}
        parent = {}
        for current in states:
            if not requirements[job] <= current:
                continue
            best = min(
                (cost + (0 if position == 0 else len(current - previous)), previous)
                for previous, cost in costs.items()
                if position == 0 or len(previous) <= c
            ) if position == 0 else min(
                (cost + len(current - previous), previous)
                for previous, cost in costs.items()
            )
            nxt[current], parent[current] = best
        costs = nxt
        parents.append(parent)
    return min(costs.values()) if costs else 0


class FreeInitialKTNSTests(unittest.TestCase):
    def test_matches_independent_state_oracle_and_legacy_relation(self):
        for m in range(1, 4):
            for c in range(1, m + 1):
                subsets = [frozenset(s) for size in range(c + 1)
                           for s in itertools.combinations(range(m), size)]
                for requirements in itertools.product(subsets, repeat=3):
                    sequence = (0, 1, 2)
                    cost, configs = ktns_switches(sequence, requirements, m, c)
                    legacy, _ = ktns(sequence, requirements, m, c)
                    distinct = len(set().union(*requirements))
                    self.assertEqual(cost, oracle(sequence, requirements, m, c))
                    self.assertEqual(cost, legacy - min(c, distinct))
                    self.assertTrue(all(requirements[j] <= configs[p]
                                        for p, j in enumerate(sequence)))
                    self.assertEqual(
                        cost, sum(len(configs[p] - configs[p - 1])
                                  for p in range(1, len(configs)))
                    )

    def test_six_job_case_covers_repeats_dominance_and_preloaded_future_tools(self):
        requirements = (
            frozenset({0, 1}), frozenset({2}), frozenset({0}),
            frozenset({1, 3}), frozenset({0, 1}), frozenset({4}),
        )
        sequence = (2, 0, 1, 3, 4, 5)
        cost, configs = ktns_switches(sequence, requirements, 5, 2)
        legacy, _ = ktns(sequence, requirements, 5, 2)
        self.assertEqual(cost, oracle(sequence, requirements, 5, 2))
        self.assertEqual(cost, legacy - 2)
        self.assertIn(1, configs[0])  # tool 1 is preloaded before its first job
        self.assertNotIn(1, requirements[sequence[0]])


class GroupingEncodingTests(unittest.TestCase):
    def test_optimizer_creates_a_fresh_worker_for_each_bound(self):
        instance = parse_file(
            Path(__file__).resolve().parents[1] / "data/Yanasse/Tabela1/L1-1.txt"
        )[0]
        import src.optimize_grouping as grouping_optimizer

        original = grouping_optimizer.IncrementalSolverSession
        sessions = []

        class RecordingSession:
            def __init__(self, clauses):
                self.inner = original(clauses)
                sessions.append(self.inner)

            def solve(self, **kwargs):
                return self.inner.solve(**kwargs)

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                self.inner.__exit__(exc_type, exc_value, traceback)

        with patch.object(grouping_optimizer, "IncrementalSolverSession", RecordingSession):
            result = optimize_instance(
                instance, algorithm="job-grouping-sat", grouping_strength="clique",
                time_limit=10,
            )
        self.assertGreaterEqual(len(result.iterations), 2)
        self.assertEqual(len(sessions), len(result.iterations))
        self.assertEqual(len({id(session) for session in sessions}), len(sessions))

    def test_reaching_global_lower_bound_after_sat_certifies_optimal(self):
        instance = make_instance(
            [{2, 4}, {2, 4}, {0}, {2, 3}, {1, 3}, {1}], 5, 2
        )
        result = optimize_instance(
            instance, algorithm="job-grouping-sat", grouping_strength="basic",
            time_limit=5,
        )
        self.assertEqual(result.status, "OPTIMAL")
        self.assertEqual(result.best_cost, result.lower_bound)
        self.assertEqual(result.iterations[0].status, "SAT")

    def test_all_strengths_and_group_bound_match_brute_force(self):
        cases = [
            make_instance([{0}, {1}, {2}], 3, 1),
            make_instance([{0, 1}, {1, 2}, {0, 2}], 3, 2),
            make_instance([set(), {0}, {0, 1}], 2, 2),
        ]
        for capacity in (1, 2):
            legal = [frozenset(s) for size in range(capacity + 1)
                     for s in itertools.combinations(range(2), size)]
            cases.extend(make_instance(requirements, 2, capacity)
                         for requirements in itertools.product(legal, repeat=3))
        for instance in cases:
            optimum = min(
                ktns_switches(sequence, instance.requirements, instance.m, instance.c)[0]
                for sequence in itertools.permutations(range(instance.n))
            )
            reduced = preprocess_dominance(instance).reduced
            for strength in ("basic", "symmetry", "clique"):
                for bound in range(3):
                    build = build_job_grouping_cnf(reduced, bound, strength)
                    self.assertEqual(build.groups, min(reduced.n, bound + 1))
                    with Solver(name="cadical300", bootstrap_with=build.cnf.clauses) as solver:
                        satisfiable = solver.solve()
                        self.assertEqual(satisfiable, optimum <= bound,
                                         (instance, strength, bound))
                        if satisfiable:
                            sequence, _magazines, encoded = decode_job_grouping(
                                build, reduced, tuple(solver.get_model())
                            )
                            full = tuple(reduced.local_to_original[j] for j in sequence)
                            self.assertLessEqual(
                                ktns_switches(full, instance.requirements,
                                              instance.m, instance.c)[0], encoded
                            )


if __name__ == "__main__":
    unittest.main()
