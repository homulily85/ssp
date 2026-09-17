from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.parser import SSPParseError, discover_input_files, parse_file


class ParserTests(unittest.TestCase):
    def _parse_text(self, text: str):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.txt"
            path.write_text(text, encoding="utf-8")
            return parse_file(path)

    def test_min_max_and_best_known_are_ignored(self):
        template = """n=2
m=3
min={minimum}
max={maximum}
c=2
problem 1:
---
1 0
0 1
0 0
best known value of the number of tool setups: {best}
"""
        first = self._parse_text(template.format(minimum=99, maximum=99, best=1))[0]
        second = self._parse_text(template.format(minimum=0, maximum=0, best=999))[0]
        self.assertEqual(first.matrix, second.matrix)
        self.assertEqual(first.requirements, (frozenset({0}), frozenset({1})))

    def test_problem_header_without_colon(self):
        instance = self._parse_text("n=1\nm=1\nc=1\nproblem 1\n---\n1\n")[0]
        self.assertEqual(instance.n, 1)

    def test_wrong_width_is_rejected(self):
        with self.assertRaises(SSPParseError):
            self._parse_text("n=2\nm=1\nc=1\nproblem 1\n1\n")

    def test_job_over_capacity_is_rejected(self):
        with self.assertRaises(SSPParseError):
            self._parse_text("n=1\nm=2\nc=1\nproblem 1\n1\n1\n")

    def test_all_supplied_data(self):
        root = Path(__file__).resolve().parents[1] / "data"
        files = discover_input_files(root)
        self.assertEqual(len(files), 168)
        count = sum(len(parse_file(path)) for path in files)
        self.assertEqual(count, 1671)


if __name__ == "__main__":
    unittest.main()
