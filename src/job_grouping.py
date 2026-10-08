from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from pysat.card import CardEnc, EncType
from pysat.formula import CNF, IDPool

from .model import ReducedInstance


STRENGTHS = ("basic", "symmetry", "clique")


@dataclass(slots=True)
class JobGroupingBuild:
    cnf: CNF
    vpool: IDPool
    vars_x: dict[tuple[int, int], int]
    vars_y: dict[tuple[int, int], int]
    vars_active: dict[int, int]
    vars_insert: dict[tuple[int, int], int]
    objective_lits: tuple[int, ...]
    groups: int
    bound: int
    strength: str
    variable_counts: dict[str, int]
    encoding_time: float
    preprocessing_time: float


def incompatibility_cliques(instance: ReducedInstance, limit: int = 100) -> tuple[tuple[int, ...], ...]:
    """Find a bounded deterministic collection of greedy maximal cliques."""
    adjacency = [set() for _ in range(instance.n)]
    for i in range(instance.n):
        for j in range(i + 1, instance.n):
            if len(instance.requirements[i] | instance.requirements[j]) > instance.c:
                adjacency[i].add(j)
                adjacency[j].add(i)
    found: set[tuple[int, ...]] = set()
    for root in range(instance.n):
        clique = [root]
        candidates = sorted(adjacency[root])
        for vertex in candidates:
            if all(vertex in adjacency[member] for member in clique):
                clique.append(vertex)
        if len(clique) > 1:
            found.add(tuple(sorted(clique)))
        if len(found) >= limit:
            break
    return tuple(sorted(found, key=lambda c: (-len(c), c)))


def build_job_grouping_cnf(
    instance: ReducedInstance, bound: int, strength: str = "clique"
) -> JobGroupingBuild:
    """Build one exact, fresh sequential-counter grouping formula for K."""
    if bound < 0:
        raise ValueError("bound must be non-negative")
    if strength not in STRENGTHS:
        raise ValueError(f"unknown grouping strength: {strength}")
    started = perf_counter()
    preprocessing_started = perf_counter()
    cliques = incompatibility_cliques(instance) if strength == "clique" else ()
    preprocessing_time = perf_counter() - preprocessing_started
    n, m, c = instance.n, instance.m, instance.c
    groups = min(n, bound + 1)
    cnf, pool = CNF(), IDPool()
    x = {(j, g): pool.id(("x", j, g)) for j in range(n) for g in range(groups)}
    y = {(u, g): pool.id(("y", u, g)) for u in range(m) for g in range(groups)}
    active = {g: pool.id(("active", g)) for g in range(groups)}
    insert = {(u, g): pool.id(("insert", u, g)) for u in range(m) for g in range(1, groups)}
    primary = pool.top

    for j in range(n):
        cnf.extend(CardEnc.equals(
            lits=[x[j, g] for g in range(groups)], bound=1,
            vpool=pool, encoding=EncType.seqcounter,
        ).clauses)
    for g in range(groups):
        members = [x[j, g] for j in range(n)]
        for member in members:
            cnf.append([-member, active[g]])
        cnf.append([-active[g], *members])
        if g + 1 < groups:
            cnf.append([-active[g + 1], active[g]])
        for j, required in enumerate(instance.requirements):
            for u in required:
                cnf.append([-x[j, g], y[u, g]])
        for u in range(m):
            cnf.append([-y[u, g], active[g]])
        cnf.extend(CardEnc.atmost(
            lits=[y[u, g] for u in range(m)], bound=c,
            vpool=pool, encoding=EncType.seqcounter,
        ).clauses)

    for u in range(m):
        for g in range(1, groups):
            z, prev, added = y[u, g], y[u, g - 1], insert[u, g]
            # added <-> (z and not prev)
            cnf.extend(([-added, z], [-added, -prev], [-z, prev, added]))

    if strength in ("symmetry", "clique"):
        for j, required in enumerate(instance.requirements):
            for g in range(groups):
                cnf.append([*[-y[u, g] for u in sorted(required)],
                            *[x[j, h] for h in range(g + 1)]])

    if strength == "clique":
        for clique in cliques:
            for g in range(groups):
                cnf.extend(CardEnc.atmost(
                    lits=[x[j, g] for j in clique], bound=1,
                    vpool=pool, encoding=EncType.seqcounter,
                ).clauses)

    objective = tuple(insert[u, g] for g in range(1, groups) for u in range(m))
    if bound < len(objective) and objective:
        cnf.extend(CardEnc.atmost(
            lits=list(objective), bound=bound,
            vpool=pool, encoding=EncType.seqcounter,
        ).clauses)
    auxiliary = pool.top - primary
    return JobGroupingBuild(
        cnf=cnf, vpool=pool, vars_x=x, vars_y=y, vars_active=active,
        vars_insert=insert, objective_lits=objective, groups=groups,
        bound=bound, strength=strength,
        variable_counts={"primary": primary, "auxiliary": auxiliary,
                         "total": pool.top, "clauses": len(cnf.clauses)},
        encoding_time=perf_counter() - started - preprocessing_time,
        preprocessing_time=preprocessing_time,
    )


def decode_job_grouping(
    build: JobGroupingBuild, instance: ReducedInstance, model: tuple[int, ...]
) -> tuple[tuple[int, ...], tuple[frozenset[int], ...], int]:
    positive = {lit for lit in model if lit > 0}
    assignment: list[int] = []
    for j in range(instance.n):
        selected = [g for g in range(build.groups) if build.vars_x[j, g] in positive]
        if len(selected) != 1:
            raise AssertionError(f"job {j} has {len(selected)} group assignments")
        assignment.append(selected[0])
    groups = sorted(set(assignment))
    if groups != list(range(len(groups))):
        raise AssertionError("active groups are not a nonempty prefix")
    sequence = tuple(j for g in groups for j in range(instance.n) if assignment[j] == g)
    magazines = tuple(
        frozenset(u for u in range(instance.m) if build.vars_y[u, g] in positive)
        for g in groups
    )
    for g in range(build.groups):
        active_value = build.vars_active[g] in positive
        if active_value != (g < len(groups)):
            raise AssertionError("active-group indicator does not match assignments")
        if not active_value and any(build.vars_y[u, g] in positive for u in range(instance.m)):
            raise AssertionError("inactive group contains a tool")
    for g in range(1, build.groups):
        for u in range(instance.m):
            expected = (build.vars_y[u, g] in positive
                        and build.vars_y[u, g - 1] not in positive)
            if (build.vars_insert[u, g] in positive) != expected:
                raise AssertionError("decoded insertion variable disagrees with magazine transition")
    cost = sum(len(magazines[g] - magazines[g - 1]) for g in range(1, len(groups)))
    if cost > build.bound:
        raise AssertionError("decoded grouping exceeds objective bound")
    for g, magazine in enumerate(magazines):
        if len(magazine) > instance.c:
            raise AssertionError("decoded magazine exceeds capacity")
        if any(not instance.requirements[j] <= magazine for j in range(instance.n) if assignment[j] == g):
            raise AssertionError("decoded magazine misses a required tool")
    return sequence, magazines, cost
