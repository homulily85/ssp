from __future__ import annotations

from pysat.card import CardEnc, EncType, ITotalizer
from pysat.formula import CNF, IDPool

from .model import AdditionalConstraints, CNFBuildResult, ReducedInstance


def build_cnf(
    instance: ReducedInstance,
    k: int,
    d_matrix: tuple[tuple[int, ...], ...],
    *,
    additional_constraints: AdditionalConstraints | None = None,
    defer_adjacency: bool = False,
    include_global_cardinality: bool = True,
) -> CNFBuildResult:
    cnf = CNF()
    vpool = IDPool()
    vars_x: dict[tuple[int, int], int] = {}
    vars_y: dict[tuple[int, int], int] = {}
    vars_z: dict[tuple[int, int], int] = {}
    vars_t: dict[tuple[int, int], int] = {}
    vars_s: dict[tuple[int, int, int], int] = {}
    n, m, c = instance.n, instance.m, instance.c
    additions = (
        additional_constraints
        if additional_constraints is not None
        else AdditionalConstraints.all()
    )

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
    named_variables_top = vpool.top

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

    # 4. Sequential-counter at-most-one job per position.
    for j in range(1, n + 1):
        position_literals = [vars_x[i, j] for i in range(n)]
        if len(position_literals) > 1:
            position_amo = CardEnc.atmost(
                lits=position_literals,
                bound=1,
                vpool=vpool,
                encoding=EncType.seqcounter,
            )
            cnf.extend(position_amo.clauses)
    position_amo_auxiliary_count = vpool.top - named_variables_top

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

    append_additional_constraints(
        cnf=cnf,
        instance=instance,
        d_matrix=d_matrix,
        k=k,
        vars_x=vars_x,
        vars_y=vars_y,
        vars_z=vars_z,
        vars_t=vars_t,
        enabled=additions,
        include_adjacency=not defer_adjacency,
    )

    # 9. Global sequential counter over insertion literals.
    t_literals = [vars_t[u, j] for j in range(1, n + 1) for u in range(m)]
    before_cardinality = vpool.top
    if include_global_cardinality and k < len(t_literals):
        card = CardEnc.atmost(lits=t_literals, bound=k, vpool=vpool, encoding=EncType.seqcounter)
        cnf.extend(card.clauses)
    card_auxiliary_count = vpool.top - before_cardinality
    auxiliary_count = (
        named_auxiliary_count
        + position_amo_auxiliary_count
        + card_auxiliary_count
    )
    counts = {
        "primary": primary_count,
        "auxiliary": auxiliary_count,
        "named_auxiliary": named_auxiliary_count,
        "position_amo_auxiliary": position_amo_auxiliary_count,
        "cardinality_auxiliary": card_auxiliary_count,
        "total": vpool.top,
        "clauses": len(cnf.clauses),
    }
    return CNFBuildResult(
        cnf,
        vpool,
        vars_x,
        vars_y,
        vars_z,
        vars_t,
        vars_s,
        counts,
        t_literal_count=len(t_literals),
    )


def adjacency_clauses(
    instance: ReducedInstance,
    d_matrix: tuple[tuple[int, ...], ...],
    k: int,
    vars_x: dict[tuple[int, int], int],
) -> list[list[int]]:
    """Return deterministic bound-dependent adjacency clauses."""
    clauses: list[list[int]] = []
    for i in range(instance.n):
        for h in range(instance.n):
            if i != h and instance.c + d_matrix[i][h] > k:
                for j in range(1, instance.n):
                    clauses.append([-vars_x[i, j], -vars_x[h, j + 1]])
    return clauses


def append_additional_constraints(
    *,
    cnf: CNF,
    instance: ReducedInstance,
    d_matrix: tuple[tuple[int, ...], ...],
    k: int,
    vars_x: dict[tuple[int, int], int],
    vars_y: dict[tuple[int, int], int],
    vars_z: dict[tuple[int, int], int],
    vars_t: dict[tuple[int, int], int],
    enabled: AdditionalConstraints,
    include_adjacency: bool,
) -> None:
    """Append the optional strengthening and symmetry constraints."""
    n, m = instance.n, instance.m

    if enabled.symmetry:
        pivot = min(
            range(n),
            key=lambda i: (
                -len(instance.requirements[i]),
                instance.local_to_original[i],
            ),
        )
        midpoint = (n + 1) // 2
        cnf.append([-vars_y[pivot, midpoint + 1]])

    if enabled.required_transition:
        for i, required in enumerate(instance.requirements):
            for j in range(1, n + 1):
                for u in sorted(required):
                    cnf.append(
                        [-vars_x[i, j], vars_z[u, j - 1], vars_t[u, j]]
                    )

    if enabled.insertion_requirement:
        jobs_requiring_tool = [
            [i for i, required in enumerate(instance.requirements) if u in required]
            for u in range(m)
        ]
        for j in range(2, n + 1):
            for u in range(m):
                cnf.append(
                    [-vars_t[u, j]]
                    + [vars_x[i, j] for i in jobs_requiring_tool[u]]
                )

    if enabled.adjacency and include_adjacency:
        cnf.extend(adjacency_clauses(instance, d_matrix, k, vars_x))


def build_incremental_cnf(
    instance: ReducedInstance,
    max_k: int,
    d_matrix: tuple[tuple[int, ...], ...],
    *,
    additional_constraints: AdditionalConstraints | None = None,
) -> CNFBuildResult:
    """Build bound-independent CNF plus one reusable iterative totalizer."""
    build = build_cnf(
        instance,
        max_k,
        d_matrix,
        additional_constraints=additional_constraints,
        defer_adjacency=True,
        include_global_cardinality=False,
    )
    if build.immediate_unsat:
        return build

    t_literals = [
        build.vars_t[u, j]
        for j in range(1, instance.n + 1)
        for u in range(instance.m)
    ]
    max_encoded_bound = min(max_k, len(t_literals) - 1)
    totalizer = ITotalizer(
        lits=t_literals,
        ubound=max_encoded_bound,
        top_id=build.vpool.top,
    )
    try:
        previous_top = build.vpool.top
        build.cnf.extend(totalizer.cnf.clauses)
        build.totalizer_rhs = tuple(totalizer.rhs)
        build.t_literal_count = len(t_literals)
        totalizer_auxiliary = totalizer.top_id - previous_top
        # ITotalizer accepts top_id rather than IDPool. Synchronize the shared
        # pool so any later allocation cannot collide with totalizer variables.
        build.vpool.top = totalizer.top_id
        build.variable_counts["cardinality_auxiliary"] = totalizer_auxiliary
        build.variable_counts["itotalizer_auxiliary"] = totalizer_auxiliary
        build.variable_counts["auxiliary"] += totalizer_auxiliary
        build.variable_counts["total"] = totalizer.top_id
        build.variable_counts["clauses"] = len(build.cnf.clauses)
    finally:
        totalizer.delete()
    return build
