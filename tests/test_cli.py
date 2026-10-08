from __future__ import annotations

import csv
import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from src.cli import _csv_output_path, build_argument_parser, main
from src.model import ALGORITHM
from src.optimize import optimize_instance

from tests.helpers import make_instance


def main_with_algorithm(argv):
    return main([*argv, "--algorithm", ALGORITHM])


class CLITests(unittest.TestCase):
    def test_legacy_mode_switch_is_not_accepted(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            build_argument_parser().parse_args(
                ["instance.txt", "--mode", "incremental"]
            )

    def test_timestamped_csv_names(self):
        timestamp = "2026-09-17-12-34-56"
        self.assertEqual(
            _csv_output_path(None, timestamp, interrupted=False),
            Path("ssp_result_2026-09-17-12-34-56.csv"),
        )
        self.assertEqual(
            _csv_output_path(None, timestamp, interrupted=True),
            Path("ssp_result_2026-09-17-12-34-56_interupt.csv"),
        )
        self.assertEqual(
            _csv_output_path(Path("custom.csv"), timestamp, interrupted=True),
            Path("custom_interupt.csv"),
        )

    def test_file_input_writes_tsp_cegar_csv_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "simple.txt"
            output = root / "result.csv"
            source.write_text(
                "n=2\nm=2\nmin=99\nmax=99\nc=2\n"
                "problem 1\n---\n1 0\n0 1\n",
                encoding="utf-8",
            )
            console = io.StringIO()
            with redirect_stdout(console):
                status = main_with_algorithm([str(source), "--csv", str(output)])
            self.assertEqual(status, 0)
            self.assertIn("Optimal cost: 2", console.getvalue())
            with output.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["algorithm"], ALGORITHM)
            self.assertEqual(rows[0]["optimum"], "2")
            self.assertEqual(rows[0]["solver_calls"], "0")
            self.assertEqual(rows[0]["cegar_rounds"], "0")
            self.assertEqual(rows[0]["subtour_cuts"], "0")

    def test_problem_option_solves_only_the_requested_problem(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "two.txt"
            output = root / "result.csv"
            source.write_text(
                "n=1\nm=1\nc=1\n"
                "problem 1\n---\n1\n"
                "problem 2\n---\n1\n",
                encoding="utf-8",
            )
            completed = optimize_instance(make_instance([{0}], 1, 1, "selected"), algorithm="tsp-sat-cegar")
            with patch("src.cli.optimize_instance", return_value=completed) as optimize:
                status = main_with_algorithm(
                    [str(source), "--problem", "2", "--csv", str(output)]
                )

            self.assertEqual(status, 0)
            self.assertEqual(optimize.call_count, 1)
            self.assertEqual(optimize.call_args.args[0].problem_id, 2)
            with output.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual([row["problem"] for row in rows], ["selected"])

    def test_problem_option_rejects_unknown_problem_before_solving(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "simple.txt"
            source.write_text(
                "n=1\nm=1\nc=1\nproblem 1\n---\n1\n", encoding="utf-8"
            )
            stderr = io.StringIO()
            with patch("src.cli.optimize_instance") as optimize, redirect_stderr(stderr):
                status = main_with_algorithm([str(source), "--problem", "2", "--no-csv"])

            self.assertEqual(status, 2)
            self.assertIn("problem 2 was not found", stderr.getvalue())
            optimize.assert_not_called()

    def test_problem_option_rejects_non_positive_ids_and_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for argv, expected_error in (
                (["input.txt", "--problem", "0"], "--problem must be greater than zero"),
                ([str(root), "--problem", "1"], "single input file"),
            ):
                stderr = io.StringIO()
                with redirect_stderr(stderr):
                    status = main_with_algorithm(argv)
                self.assertEqual(status, 2)
                self.assertIn(expected_error, stderr.getvalue())

    def test_grouping_checkpoint_resumes_without_duplicate_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "two.txt"
            output = root / "grouping.csv"
            source.write_text(
                "n=1\nm=1\nc=1\nproblem 1\n---\n1\n"
                "problem 2\n---\n1\n", encoding="utf-8"
            )
            completed = optimize_instance(
                make_instance([{0}], 1, 1, "selected"),
                algorithm="job-grouping-sat", time_limit=2,
            )
            args = [str(source), "--algorithm", "job-grouping-sat",
                    "--csv", str(output), "--limit", "2"]
            with patch("src.cli.optimize_instance", return_value=completed) as optimize:
                self.assertEqual(main(args), 0)
                self.assertEqual(optimize.call_count, 2)
                self.assertEqual(main([*args, "--resume"]), 0)
                self.assertEqual(optimize.call_count, 2)
            with output.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 2)
            self.assertEqual({row["objective_definition"] for row in rows},
                             {"free-initial-magazine-v1"})

    def test_grouping_rejects_no_csv_and_incompatible_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "one.txt"
            output = root / "grouping.csv"
            source.write_text("1 1 1\n1\n", encoding="utf-8")
            for argv, expected in (
                ([str(source), "--algorithm", "job-grouping-sat", "--no-csv"],
                 "requires durable CSV"),
            ):
                stderr = io.StringIO()
                with redirect_stderr(stderr):
                    self.assertEqual(main(argv), 2)
                self.assertIn(expected, stderr.getvalue())
            result = optimize_instance(make_instance([{0}], 1, 1),
                                       algorithm="job-grouping-sat", time_limit=2)
            args = [str(source), "--algorithm", "job-grouping-sat",
                    "--csv", str(output), "--limit", "2"]
            with patch("src.cli.optimize_instance", return_value=result):
                self.assertEqual(main(args), 0)
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                self.assertEqual(main([*args, "--resume", "--grouping-strength", "basic"]), 2)
            self.assertIn("fingerprint does not match", stderr.getvalue())

    def test_grouping_interrupt_preserves_prior_rows_for_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output = root / "two.txt", root / "checkpoint.csv"
            source.write_text(
                "n=1\nm=1\nc=1\nproblem 1\n---\n1\n"
                "problem 2\n---\n1\n", encoding="utf-8"
            )
            completed = optimize_instance(make_instance([{0}], 1, 1),
                                          algorithm="job-grouping-sat", time_limit=2)
            args = [str(source), "--algorithm", "job-grouping-sat",
                    "--csv", str(output), "--limit", "2"]
            with patch("src.cli.optimize_instance",
                       side_effect=[completed, KeyboardInterrupt()]), redirect_stderr(io.StringIO()):
                self.assertEqual(main(args), 130)
            with output.open(encoding="utf-8", newline="") as handle:
                self.assertEqual(len(list(csv.DictReader(handle))), 1)
            with patch("src.cli.optimize_instance", return_value=completed) as optimize:
                self.assertEqual(main([*args, "--resume"]), 0)
                self.assertEqual(optimize.call_count, 1)
            with output.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 2)

    def test_keyboard_interrupt_writes_only_completed_instances(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "two.txt"
            output = root / "partial.csv"
            interrupted_output = root / "partial_interupt.csv"
            source.write_text(
                "n=1\nm=1\nc=1\n"
                "problem 1\n---\n1\n"
                "problem 2\n---\n1\n",
                encoding="utf-8",
            )
            completed = optimize_instance(make_instance([{0}], 1, 1, "completed"), algorithm="tsp-sat-cegar")
            stdout = io.StringIO()
            stderr = io.StringIO()
            with patch(
                "src.cli.optimize_instance",
                side_effect=[completed, KeyboardInterrupt()],
            ), redirect_stdout(stdout), redirect_stderr(stderr):
                status = main_with_algorithm([str(source), "--csv", str(output)])
            self.assertEqual(status, 130)
            self.assertIn("1 completed instances", stderr.getvalue())
            self.assertFalse(output.exists())
            with interrupted_output.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["problem"], "completed")


if __name__ == "__main__":
    unittest.main()
