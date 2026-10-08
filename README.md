# SSP SAT Solver

Exact solver for the Job Sequencing and Tool Switching Problem (SSP), using
PySAT and CaDiCaL 3.0. Select `direct-sat`, `tsp-sat-cegar`, or
`job-grouping-sat` explicitly.

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

`job-grouping-sat` is a separate pure SAT formulation. It assigns jobs to
ordered groups that share a magazine configuration, uses sequential counters
for every cardinality constraint, and starts a fresh CaDiCaL process for each
decreasing objective bound. Its objective preloads the first magazine for
free and counts insertions only after that configuration. Use
`--grouping-strength basic|symmetry|clique`; `clique` is the default.
Grouping runs require a CSV checkpoint and support `--resume`:

```bash
uv run ssp-sat data/Yanasse --algorithm job-grouping-sat \
  --grouping-strength clique --limit 1200 \
  --csv results/yanasse_job_grouping.csv
uv run ssp-sat data/Yanasse --algorithm job-grouping-sat \
  --grouping-strength clique --limit 1200 \
  --csv results/yanasse_job_grouping.csv --resume
```

The checkpoint is atomically replaced after each instance, fingerprints the
dataset and solver settings, and stores the incumbent sequence. The current
repository contains 1,350 parser-verified Yanasse inputs: A 340, B 330, C 340,
D 260, E 80. The 2026 C-B&B paper reports 1,390 inputs and 370 for group B.
Its cited public [HGS-SSP repository](https://github.com/jordanamecler/HGS-SSP/tree/master/Instances/Yanasse)
(`Instances/Yanasse`, source commit `075705c5463c26a48a8f812153aad747fe15ce6b`)
also contains 330 B files, byte-for-byte matching this checkout. No source for
the extra 40 instances was found. Runs are therefore incomplete relative to
the paper's reported count; no synthetic replacements are used.

`direct-sat` uses job-position assignment variables and restricts the first
greedy job to the first half of positions to break reversal symmetry.
`tsp-sat-cegar` uses adjacency variables, an empty dummy vertex and lazy
subtour elimination. Both use sequential counters for assignment and capacity. TSP-SAT uses one
reusable `ITotalizer` for insertion bounds; direct adds a fresh sequential
counter for each tested bound, so those objective clauses accumulate.

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

The suite covers all encodings, symmetry breaking, insertion bounds, CEGAR
cuts, timeouts, CLI selection, dominance reconstruction, and independent
exhaustive checks using all magazine sizes from zero through C.

Python callers must also select an algorithm explicitly:

```python
result = optimize_instance(instance, algorithm="direct-sat", time_limit=120)
```
