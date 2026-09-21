# SSP TSP-SAT + CEGAR baseline

The implementation solves the decision problem “is there an SSP schedule with
at most `k` insertions?” using adjacency variables on a dummy-augmented TSP
graph. It starts from the all-start greedy/KTNS upper bound and searches
downward incrementally.

- `x[i,j]` selects an arc, while degree equalities create a cycle cover.
- `z[u,j]` is the magazine configuration at job vertex `j`; `t[u,j]` is the
  insertion set on arrival at that vertex.
- Degree and capacity equalities use PySAT sequential counters.
- A single ITotalizer bounds `sum(t)` through assumptions; the SAT formula is
  never rebuilt for a new objective bound.
- Dummy-free cycles are detected in each SAT model and removed with exit cuts.
  Every cut and all CaDiCaL learned state survive later CEGAR rounds/bounds.
- An independent verifier checks the decoded policy before the dominance
  reconstruction and KTNS full-sequence verification are accepted.

The current scope deliberately excludes symmetry breaking, dominance-derived
SAT cuts, edge pruning, carry/arc-flow variables and other strengthening
techniques. Dominance preprocessing itself, input parsing, KTNS and upper
bound construction remain part of the pipeline.
