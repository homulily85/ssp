# SSP SAT Solver

Exact solver for the Job Sequencing and Tool Switching Problem (SSP), using
PySAT and CaDiCaL 3.0. Select an algorithm explicitly with the required
`--algorithm direct-sat|tsp-sat-cegar` option.

Both encodings use an initially empty magazine containing **at most C** tools.
Cost counts each tool insertion, including the first load. Unused tools do not
incur a cost. Dominance preprocessing keeps maximal job requirements and
compacts tool IDs; removed jobs are restored immediately after their representative.

The initial upper bound uses the frequency greedy policy from `direct.py`:
order jobs by decreasing sum of required-tool frequencies, load missing tools,
and evict tools not required by the current job when capacity is exceeded.
Ties use original job IDs; eviction ties remove the largest original tool ID.
Its actual magazine policy supplies the initial incumbent. The lower bound is
the number of distinct required tools. KTNS evaluates SAT sequences and verifies
that the final incumbent can be executed at no greater cost.

`direct-sat` uses job-position assignment variables and restricts the first
greedy job to the first half of positions to break reversal symmetry.
`tsp-sat-cegar` uses adjacency variables, an empty dummy vertex and lazy
subtour elimination. Both use sequential counters for assignment and capacity,
and one reusable `ITotalizer` for insertion bounds through solver assumptions.

## Run

```bash
uv sync
uv run ssp-sat data/dummy.txt --algorithm direct-sat
uv run ssp-sat data/Catanzaro/datA1 --algorithm tsp-sat-cegar --limit 120 --csv results.csv
uv run ssp-sat data/dummy.txt --algorithm direct-sat --problem 3
uv run ssp-sat data --algorithm direct-sat --no-csv
```

`--limit` is a wall-clock limit per problem. On timeout the solver reports the
best feasible incumbent as a best known solution and does not claim optimality.
The input may be a benchmark file or a directory searched recursively.
Use `--problem ID` with a benchmark file to solve only that numbered problem;
the option is not supported for directory input. Without it, every problem in
the input is solved.

The console and CSV output include the number of solver calls, CEGAR rounds,
subtour cuts, variable/clause counts, and CaDiCaL statistics. Direct reports zero CEGAR rounds and subtour cuts. `min`, `max`,
and `best known value ...` input lines are deliberately ignored.

## Test

```bash
uv run python -m unittest discover -s tests -v
```

The suite covers both encodings, symmetry breaking, insertion bounds, CEGAR
cuts, timeouts, CLI selection, dominance reconstruction, and independent
exhaustive checks using all magazine sizes from zero through C.

Python callers must also select an algorithm explicitly:

```python
result = optimize_instance(instance, algorithm="direct-sat", time_limit=120)
```
