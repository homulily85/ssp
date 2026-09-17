from __future__ import annotations

import csv
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from src.cli import main


class CLITests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
