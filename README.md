# SSP SAT Solver

Tài liệu kỹ thuật đầy đủ: [docs/implementation.md](docs/implementation.md).

Exact solver for the Job Sequencing and Tool Switching Problem described in
`plan.md`. It uses dominance preprocessing, an all-start greedy upper bound,
KTNS evaluation, a SAT encoding, and a strict descending search with PySAT's
CaDiCaL 3.0 backend.

At-most-one job constraints for each position and the global insertion bound
are encoded with PySAT sequential counters using the same variable pool.
From position 2 onward, an inserted tool must be required by the job at that
position; position 1 remains exempt so the initial magazine can contain filler
tools when a job requires fewer than `c` tools.

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

Each problem has a total 600-second time limit by default. Every CaDiCaL
invocation runs in a separate process and receives the time remaining for that
problem. Set a different limit with `--limit SECONDS`, for example:

```bash
uv run ssp-sat data/Catanzaro/datA1 --limit 120
```

Add `--incremental` to build the global insertion cardinality with PySAT's
`ITotalizer` and reuse one CaDiCaL process, its clauses, and learned state for
all descending bounds of a problem:

```bash
uv run ssp-sat data/Catanzaro/datA1 --incremental
```

Without this flag, the standard mode rebuilds the global sequential counter
and starts a fresh solver for every bound. Both modes keep the same strict
descending search and independent KTNS validation.

On timeout the worker process is terminated and the output is marked `TIMEOUT`;
the reported cost is only the best feasible upper bound, not a certified
optimum. No PySAT time-limit API is used.

If the run is stopped with `Ctrl+C`, the active CaDiCaL worker is terminated and
the CSV is written as `ssp_result_YYYY-MM-DD-HH-MM-SS_interupt.csv`, containing
only instances completed before the interrupt. The command then exits with
status 130. With `--no-csv`, no partial file is created. A custom `--csv` path is
respected; `_interupt` is inserted before its extension when interrupted.

The input can be one benchmark file or a directory searched recursively. A CSV
summary is written to `ssp_result_YYYY-MM-DD-HH-MM-SS.csv` by default. Every
problem in every selected file is solved independently.

## Test

```bash
.venv/bin/python -m unittest discover -s tests -v
```

The suite includes a smoke parse of all supplied data and exact comparisons
against exhaustive search on small instances.
