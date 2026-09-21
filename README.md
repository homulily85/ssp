# SSP SAT Solver

Tài liệu kỹ thuật đầy đủ: [docs/implementation.md](docs/implementation.md).

Exact solver for the Job Sequencing and Tool Switching Problem described in
`plan.md`. It uses dominance preprocessing, an all-start greedy upper bound,
KTNS evaluation, and either SAT optimization with PySAT's CaDiCaL 3.0 backend
or MaxSAT optimization with the local EvalMaxSAT binary.

The encoding is split into a mandatory core and four optional constraint
groups: `symmetry`, `insertion-requirement`, `adjacency`, and
`required-transition`. All four are enabled by default. Use `--core-only` to
disable them, or repeat `--enable-constraint NAME` to enable only a selected
subset:

```bash
uv run ssp-sat data/dummy.txt --core-only
uv run ssp-sat data/dummy.txt \
  --enable-constraint symmetry \
  --enable-constraint adjacency
```

At-most-one job constraints for each position and the standard-mode global
insertion bound use PySAT sequential counters with the shared variable pool.

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

Select the optimization implementation with `--mode`. Standard mode rebuilds
the global sequential counter for every bound; incremental mode uses PySAT's
`ITotalizer` and reuses one CaDiCaL process:

```bash
uv run ssp-sat data/Catanzaro/datA1 --mode standard
uv run ssp-sat data/Catanzaro/datA1 --mode incremental
```

Two MaxSAT modes build one WCNF without the global insertion bound. The
original encoding minimizes weight-1 soft clauses `not t[u,j]`; the no-`t`
encoding minimizes transitions directly from consecutive `z` variables:

```bash
uv run ssp-sat data/Catanzaro/datA1 --mode maxsat
uv run ssp-sat data/Catanzaro/datA1 --mode maxsat-no-t
```

For `maxsat-no-t`, each soft clause is
`z[u,j-1] or not z[u,j]` for `j=2,...,N`. The reported objective adds the
fixed initial magazine cost `C` to EvalMaxSAT's raw objective.

It requires the executable `bin/EvalMaxSAT_bin`. EvalMaxSAT models and
objectives are independently checked against the encoding and KTNS.

On timeout the output is marked `TIMEOUT`; the reported cost is only the best
feasible upper bound, not a certified optimum. SAT workers are terminated.
In MaxSAT mode the parent sends `SIGTERM`, allowing EvalMaxSAT to print its
current incumbent; if none exists yet, the greedy/KTNS solution is retained.

If the run is stopped with `Ctrl+C`, the active solver process is terminated and
the CSV is written as `ssp_result_YYYY-MM-DD-HH-MM-SS_interupt.csv`, containing
only instances completed before the interrupt. The command then exits with
status 130. With `--no-csv`, no partial file is created. A custom `--csv` path is
respected; `_interupt` is inserted before its extension when interrupted.

The input can be one benchmark file or a directory searched recursively. A CSV
summary is written to `ssp_result_YYYY-MM-DD-HH-MM-SS.csv` by default. Every
problem in every selected file is solved independently.

Per-iteration console output and per-problem CSV output include CaDiCaL
`restarts`, `conflicts`, `decisions`, and `propagations` statistics. If a
CaDiCaL process is killed on timeout or interruption before returning its
statistics, these fields are reported as `N/A`, not as zero. The CSV also has
one Boolean column for each optional constraint. EvalMaxSAT does not expose
these statistics in its output, so MaxSAT rows report them as `N/A`.

## Test

```bash
.venv/bin/python -m unittest discover -s tests -v
```

The suite includes a smoke parse of all supplied data and exact comparisons
against exhaustive search on small instances.
