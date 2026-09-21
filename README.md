# SSP TSP-SAT Solver

Exact solver for the Job Sequencing and Tool Switching Problem (SSP).  It
keeps the existing dominance preprocessing, all-start greedy upper bound and
KTNS evaluator, then proves optimality with an incremental TSP-SAT + CEGAR
solver built on PySAT and CaDiCaL 3.0.

The SAT formulation has a dummy vertex `0`, adjacency variables `x[i,j]`,
magazine state variables `z[u,j]`, and insertion variables `t[u,j]`. Degree
constraints create a cycle cover; dummy-free cycles are removed lazily by
subtour-exit cuts. All degree and capacity cardinalities use PySAT sequential
counters. The single objective cardinality uses one reusable `ITotalizer` and
changes its bound through solver assumptions.

## Run

```bash
uv sync
uv run ssp-sat data/dummy.txt
uv run ssp-sat data/Catanzaro/datA1 --limit 120 --csv results.csv
uv run ssp-sat data --no-csv
```

`--limit` is a wall-clock limit per problem. On timeout the solver reports the
greedy/KTNS incumbent as a best known solution and does not claim optimality.
The input may be a benchmark file or a directory searched recursively.

The console and CSV output include the number of solver calls, CEGAR rounds,
subtour cuts, variable/clause counts, and CaDiCaL statistics. `min`, `max`,
and `best known value ...` input lines are deliberately ignored.

## Test

```bash
uv run python -m unittest discover -s tests -v
```

The suite covers the TSP encoding, dummy and real transitions, ITotalizer
bounds, multi-subtour cuts, timeouts, parser coverage, and brute-force checks
on small SSP instances.
