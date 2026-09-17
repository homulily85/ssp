from __future__ import annotations

from pysat.card import CardEnc, EncType
from pysat.formula import CNF, IDPool

from .model import CNFBuildResult, ReducedInstance


def build_cnf(
    instance: ReducedInstance,
    k: int,
    d_matrix: tuple[tuple[int, ...], ...],
) -> CNFBuildResult:
    cnf = CNF()
    vpool = IDPool()
    vars_x: dict[tuple[int, int], int] = {}
    vars_y: dict[tuple[int, int], int] = {}
    vars_z: dict[tuple[int, int], int] = {}
    vars_t: dict[tuple[int, int], int] = {}
    vars_s: dict[tuple[int, int, int], int] = {}
    n, m, c = instance.n, instance.m, instance.c

    if k < c:
        return CNFBuildResult(
            cnf, vpool, vars_x, vars_y, vars_z, vars_t, vars_s,
            {"primary": 0, "auxiliary": 0, "total": 0, "clauses": 0},
            immediate_unsat=True,
        )

    # Allocate every named variable first so PySAT auxiliaries cannot collide.
    for i in range(n):
        for j in range(1, n + 1):
            vars_x[i, j] = vpool.id(("x", i, j))
        for j in range(1, n + 2):
            vars_y[i, j] = vpool.id(("y", i, j))
    for u in range(m):
        for j in range(0, n + 1):
            vars_z[u, j] = vpool.id(("z", u, j))
        for j in range(1, n + 1):
            vars_t[u, j] = vpool.id(("t", u, j))
    for j in range(1, n + 1):
        for q in range(0, m + 1):
            for r in range(0, c + 2):
                vars_s[q, r, j] = vpool.id(("s", q, r, j))

    primary_count = len(vars_x) + len(vars_y) + len(vars_z) + len(vars_t)
    named_auxiliary_count = len(vars_s)

    # 1. y boundaries.
    for i in range(n):
        cnf.append([vars_y[i, 1]])
        cnf.append([-vars_y[i, n + 1]])

    # 2. y monotonicity.
    for i in range(n):
        for j in range(1, n + 1):
            cnf.append([-vars_y[i, j + 1], vars_y[i, j]])

    # 3. x <-> (y_j and not y_{j+1}).
    for i in range(n):
        for j in range(1, n + 1):
            x, y, y_next = vars_x[i, j], vars_y[i, j], vars_y[i, j + 1]
            cnf.extend([[-x, y], [-x, -y_next], [-y, y_next, x]])

    # 4. Pairwise at-most-one job per position.
    for j in range(1, n + 1):
        for i in range(n):
            for h in range(i + 1, n):
                cnf.append([-vars_x[i, j], -vars_x[h, j]])

    # 5. Job requirements.
    for i, required in enumerate(instance.requirements):
        for j in range(1, n + 1):
            for u in sorted(required):
                cnf.append([-vars_x[i, j], vars_z[u, j]])

    # 6. Exact magazine capacity order-counter.
    for j in range(1, n + 1):
        for q in range(0, m + 1):
            cnf.append([vars_s[q, 0, j]])
        for r in range(1, c + 2):
            cnf.append([-vars_s[0, r, j]])
        for q in range(0, m + 1):
            for r in range(q + 1, c + 2):
                cnf.append([-vars_s[q, r, j]])
        for q in range(1, m + 1):
            for r in range(1, min(q, c + 1) + 1):
                a = vars_s[q, r, j]
                b = vars_s[q - 1, r, j]
                z = vars_z[q - 1, j]
                d = vars_s[q - 1, r - 1, j]
                cnf.extend([[-a, b, z], [-a, b, d], [-b, a], [-z, -d, a]])
        cnf.append([vars_s[m, c, j]])
        cnf.append([-vars_s[m, c + 1, j]])

    # 7. Empty initial magazine.
    for u in range(m):
        cnf.append([-vars_z[u, 0]])

    # 8. t <-> (z_j and not z_{j-1}).
    for j in range(1, n + 1):
        for u in range(m):
            t, z, previous = vars_t[u, j], vars_z[u, j], vars_z[u, j - 1]
            cnf.extend([[-t, z], [-t, -previous], [-z, previous, t]])

    # 9. Required tool was present or is inserted now.
    for i, required in enumerate(instance.requirements):
        for j in range(1, n + 1):
            for u in sorted(required):
                cnf.append([-vars_x[i, j], vars_z[u, j - 1], vars_t[u, j]])

    # 10. Bound-dependent adjacency pruning.
    for i in range(n):
        for h in range(n):
            if i != h and c + d_matrix[i][h] > k:
                for j in range(1, n):
                    cnf.append([-vars_x[i, j], -vars_x[h, j + 1]])

    # 11. Global sequential counter over insertion literals.
    t_literals = [vars_t[u, j] for j in range(1, n + 1) for u in range(m)]
    before_cardinality = vpool.top
    if k < len(t_literals):
        card = CardEnc.atmost(lits=t_literals, bound=k, vpool=vpool, encoding=EncType.seqcounter)
        cnf.extend(card.clauses)
    card_auxiliary_count = vpool.top - before_cardinality
    auxiliary_count = named_auxiliary_count + card_auxiliary_count
    counts = {
        "primary": primary_count,
        "auxiliary": auxiliary_count,
        "named_auxiliary": named_auxiliary_count,
        "cardinality_auxiliary": card_auxiliary_count,
        "total": vpool.top,
        "clauses": len(cnf.clauses),
    }
    return CNFBuildResult(
        cnf, vpool, vars_x, vars_y, vars_z, vars_t, vars_s, counts
    )
