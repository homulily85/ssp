# SSP SAT Solver

Exact solver for the Job Sequencing and Tool Switching Problem described in
`plan.md`. It uses dominance preprocessing, an all-start greedy upper bound,
KTNS evaluation, a SAT encoding, and a strict descending search with PySAT's
CaDiCaL 3.0 backend.

`min`, `max`, and `best known value ...` lines in benchmark files are ignored.
Only `n`, `m`, `c`, the problem blocks, and their Boolean matrices affect a
solution.

## Run

Install the project (or synchronize it with `uv`) to make the `ssp-sat`
console command available outside the repository root:

```bash
uv sync
uv run ssp-sat data/dummy.txt
```

It can also be run directly by its Python package name from the repository:

```bash
.venv/bin/python -m src data/dummy.txt
.venv/bin/python -m src data/Catanzaro/datA1 --csv results.csv
.venv/bin/python -m src data --no-csv
```

The input can be one benchmark file or a directory searched recursively. A CSV
summary is written to `ssp_results.csv` by default. Every problem in every
selected file is solved independently.

## Test

```bash
.venv/bin/python -m unittest discover -s tests -v
```

The suite includes a smoke parse of all supplied data and exact comparisons
against exhaustive search on small instances.
