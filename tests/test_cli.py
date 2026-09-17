from __future__ import annotations

import csv
import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from src.cli import _csv_output_path, main
from src.optimize import optimize_instance

from tests.helpers import make_instance


class CLITests(unittest.TestCase):
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

    def test_file_input_writes_default_schema(self):
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
                status = main([str(source), "--csv", str(output)])
            self.assertEqual(status, 0)
            self.assertIn("Optimal cost: 2", console.getvalue())
            with output.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["optimum"], "2")
            self.assertEqual(rows[0]["sat_calls"], "0")
            self.assertEqual(rows[0]["restarts"], "0")
            self.assertEqual(rows[0]["conflicts"], "0")
            self.assertEqual(rows[0]["decisions"], "0")
            self.assertEqual(rows[0]["propagations"], "0")

    def test_incremental_flag_is_reported_in_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "simple.txt"
            output = root / "result.csv"
            source.write_text(
                "n=1\nm=1\nc=1\nproblem 1\n---\n1\n",
                encoding="utf-8",
            )
            with redirect_stdout(io.StringIO()):
                status = main(
                    [str(source), "--incremental", "--csv", str(output)]
                )
            self.assertEqual(status, 0)
            with output.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["mode"], "incremental")

    def test_constraint_selection_is_reported_in_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "simple.txt"
            source.write_text(
                "n=1\nm=1\nc=1\nproblem 1\n---\n1\n",
                encoding="utf-8",
            )
            cases = (
                ([], ("true", "true", "true", "true")),
                (["--core-only"], ("false", "false", "false", "false")),
                (
                    [
                        "--enable-constraint",
                        "symmetry",
                        "--enable-constraint",
                        "adjacency",
                    ],
                    ("true", "false", "true", "false"),
                ),
            )
            fields = (
                "constraint_symmetry",
                "constraint_insertion_requirement",
                "constraint_adjacency",
                "constraint_required_transition",
            )
            for index, (arguments, expected) in enumerate(cases):
                output = root / f"result-{index}.csv"
                with redirect_stdout(io.StringIO()):
                    status = main([str(source), *arguments, "--csv", str(output)])
                self.assertEqual(status, 0)
                with output.open(encoding="utf-8", newline="") as handle:
                    row = next(csv.DictReader(handle))
                self.assertEqual(tuple(row[field] for field in fields), expected)

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
            completed = optimize_instance(make_instance([{0}], 1, 1, "completed"))
            stdout = io.StringIO()
            stderr = io.StringIO()
            with patch(
                "src.cli.optimize_instance",
                side_effect=[completed, KeyboardInterrupt()],
            ), redirect_stdout(stdout), redirect_stderr(stderr):
                status = main([str(source), "--csv", str(output)])
            self.assertEqual(status, 130)
            self.assertIn("1 completed instances", stderr.getvalue())
            self.assertFalse(output.exists())
            with interrupted_output.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["problem"], "completed")


if __name__ == "__main__":
    unittest.main()
