from __future__ import annotations

from .model import DominanceResult, ReducedInstance, SSPInstance


def preprocess_dominance(instance: SSPInstance) -> DominanceResult:
    groups: dict[frozenset[int], list[int]] = {}
    for job, required in enumerate(instance.requirements):
        groups.setdefault(required, []).append(job)

    distinct_sets = tuple(groups)
    maximal_sets = {
        required
        for required in distinct_sets
        if not any(required < other for other in distinct_sets)
    }
    active_jobs = tuple(sorted(min(groups[required]) for required in maximal_sets))
    active_set = set(active_jobs)

    dominator: dict[int, int] = {}
    dominated_lists: dict[int, list[int]] = {job: [] for job in active_jobs}
    for job, required in enumerate(instance.requirements):
        if job in active_set:
            continue
        candidates = [
            active
            for active in active_jobs
            if required <= instance.requirements[active]
        ]
        if not candidates:
            raise AssertionError(f"job {job} has no active dominator")
        chosen = min(candidates, key=lambda active: (len(instance.requirements[active]), active))
        dominator[job] = chosen
        dominated_lists[chosen].append(job)

    dominated_by = {job: tuple(sorted(jobs)) for job, jobs in dominated_lists.items()}
    local_to_original = active_jobs
    original_to_local = {original: local for local, original in enumerate(local_to_original)}
    reduced = ReducedInstance(
        name=instance.name,
        m=instance.m,
        c=instance.c,
        requirements=tuple(instance.requirements[job] for job in local_to_original),
        local_to_original=local_to_original,
    )
    result = DominanceResult(
        active_jobs=active_jobs,
        dominator=dominator,
        dominated_by=dominated_by,
        local_to_original=local_to_original,
        original_to_local=original_to_local,
        reduced=reduced,
    )
    _assert_dominance_invariants(instance, result)
    return result


def _assert_dominance_invariants(instance: SSPInstance, result: DominanceResult) -> None:
    active = set(result.active_jobs)
    assert active.isdisjoint(result.dominator)
    assert active | set(result.dominator) == set(range(instance.n))
    for job, representative in result.dominator.items():
        assert representative in active
        assert instance.requirements[job] <= instance.requirements[representative]
    flattened = [job for jobs in result.dominated_by.values() for job in jobs]
    assert sorted(flattened) == sorted(result.dominator)


def reconstruct_sequence(
    reduced_sequence: tuple[int, ...] | list[int], result: DominanceResult
) -> tuple[int, ...]:
    sequence: list[int] = []
    for representative in reduced_sequence:
        if representative not in result.dominated_by:
            raise ValueError(f"job {representative} is not an active representative")
        sequence.extend(result.dominated_by[representative])
        sequence.append(representative)
    full = tuple(sequence)
    expected = set(result.active_jobs) | set(result.dominator)
    assert len(full) == len(expected)
    assert set(full) == expected
    return full
