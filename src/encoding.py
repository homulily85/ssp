from __future__ import annotations

from pysat.card import CardEnc, EncType, ITotalizer
from pysat.formula import CNF, IDPool

from .model import ReducedInstance, TSPBuildResult


def _append_equals(
    cnf: CNF, lits: list[int], bound: int, vpool: IDPool
) -> None:
    """Append an equality cardinality encoded with PySAT's sequential counter."""
    cnf.extend(
        CardEnc.equals(
            lits=lits,
            bound=bound,
            vpool=vpool,
            encoding=EncType.seqcounter,
        ).clauses
    )


def build_tsp_cnf(instance: ReducedInstance, max_bound: int) -> TSPBuildResult:
    """Build the bound-independent TSP-SSP formula and one objective totalizer.

    Real job vertices use identifiers 1..N; vertex 0 is the empty-magazine
    dummy.  ``max_bound`` is the largest decision bound the optimizer will
    request (normally the greedy upper bound minus one).
    """
    if max_bound < 0:
        raise ValueError("max_bound must be non-negative")

    cnf = CNF()
    vpool = IDPool()
    vars_x: dict[tuple[int, int], int] = {}
    vars_z: dict[tuple[int, int], int] = {}
    vars_t: dict[tuple[int, int], int] = {}
    n, m, c = instance.n, instance.m, instance.c

    # Allocate all named primary variables before allowing cardinality
    # encoders to allocate auxiliaries through the shared pool.
    for predecessor in range(n + 1):
        for successor in range(n + 1):
            if predecessor != successor:
                vars_x[predecessor, successor] = vpool.id(
                    ("x", predecessor, successor)
                )
    for tool in range(m):
        for job in range(1, n + 1):
            vars_z[tool, job] = vpool.id(("z", tool, job))
            vars_t[tool, job] = vpool.id(("t", tool, job))

    primary_count = len(vars_x) + len(vars_z) + len(vars_t)
    before_sequential = vpool.top

    # The in/out degree equalities form a directed cycle cover.  CEGAR adds
    # only the subtour-elimination constraints that a model requires.
    for vertex in range(n + 1):
        _append_equals(
            cnf,
            [vars_x[vertex, successor] for successor in range(n + 1) if successor != vertex],
            1,
            vpool,
        )
        _append_equals(
            cnf,
            [vars_x[predecessor, vertex] for predecessor in range(n + 1) if predecessor != vertex],
            1,
            vpool,
        )

    # Every real job has a full magazine and contains its required tools.
    for job, required in enumerate(instance.requirements, start=1):
        for tool in required:
            cnf.append([vars_z[tool, job]])
        _append_equals(
            cnf,
            [vars_z[tool, job] for tool in range(m)],
            c,
            vpool,
        )

    # For the selected predecessor i of j, t[u,j] is exactly the tool added
    # while moving from i's magazine to j's magazine.
    for tool in range(m):
        for successor in range(1, n + 1):
            z_successor = vars_z[tool, successor]
            t_successor = vars_t[tool, successor]
            for predecessor in range(1, n + 1):
                if predecessor == successor:
                    continue
                edge = vars_x[predecessor, successor]
                z_predecessor = vars_z[tool, predecessor]
                cnf.extend(
                    (
                        [-edge, -t_successor, z_successor],
                        [-edge, -t_successor, -z_predecessor],
                        [-edge, -z_successor, z_predecessor, t_successor],
                    )
                )
            dummy_edge = vars_x[0, successor]
            cnf.extend(
                (
                    [-dummy_edge, -t_successor, z_successor],
                    [-dummy_edge, t_successor, -z_successor],
                )
            )

    sequential_auxiliary = vpool.top - before_sequential
    t_literals = [
        vars_t[tool, job]
        for job in range(1, n + 1)
        for tool in range(m)
    ]

    # ITotalizer is deliberately reserved for the objective alone.  Its RHS
    # literal at index k represents at least k+1 true insertion literals, so
    # assuming -rhs[k] enforces T <= k.
    max_encoded_bound = min(max_bound, len(t_literals) - 1)
    totalizer = ITotalizer(
        lits=t_literals,
        ubound=max_encoded_bound,
        top_id=vpool.top,
    )
    try:
        before_totalizer = vpool.top
        cnf.extend(totalizer.cnf.clauses)
        totalizer_rhs = tuple(totalizer.rhs)
        totalizer_auxiliary = totalizer.top_id - before_totalizer
        vpool.top = totalizer.top_id
    finally:
        totalizer.delete()

    counts = {
        "primary": primary_count,
        "sequential_counter_auxiliary": sequential_auxiliary,
        "itotalizer_auxiliary": totalizer_auxiliary,
        "auxiliary": sequential_auxiliary + totalizer_auxiliary,
        "total": vpool.top,
        "clauses": len(cnf.clauses),
    }
    return TSPBuildResult(
        cnf=cnf,
        vpool=vpool,
        vars_x=vars_x,
        vars_z=vars_z,
        vars_t=vars_t,
        variable_counts=counts,
        totalizer_rhs=totalizer_rhs,
        t_literal_count=len(t_literals),
        base_clause_count=len(cnf.clauses),
    )
