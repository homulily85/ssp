from __future__ import annotations


def decode_successor(
    model: tuple[int, ...] | list[int],
    vars_x: dict[tuple[int, int], int],
    n: int,
) -> dict[int, int]:
    """Decode the selected outgoing edge of every vertex, including dummy 0."""
    positive = {literal for literal in model if literal > 0}
    successor: dict[int, int] = {}
    for vertex in range(n + 1):
        selected = [
            other
            for other in range(n + 1)
            if other != vertex and vars_x[vertex, other] in positive
        ]
        if len(selected) != 1:
            raise AssertionError(
                f"vertex {vertex} has {len(selected)} selected outgoing edges"
            )
        successor[vertex] = selected[0]
    if set(successor.values()) != set(range(n + 1)):
        raise AssertionError("decoded x variables do not give one incoming edge per vertex")
    return successor


def find_cycles(successor: dict[int, int]) -> tuple[tuple[int, ...], ...]:
    """Return every directed cycle of a successor permutation exactly once."""
    vertices = set(successor)
    if set(successor.values()) != vertices:
        raise AssertionError("successor relation is not a permutation")

    visited: set[int] = set()
    cycles: list[tuple[int, ...]] = []
    for start in sorted(vertices):
        if start in visited:
            continue
        cycle: list[int] = []
        current = start
        while current not in cycle:
            if current in visited:
                raise AssertionError("successor relation unexpectedly enters another cycle")
            cycle.append(current)
            current = successor[current]
        if current != start:
            raise AssertionError("successor relation is not a disjoint cycle cover")
        visited.update(cycle)
        cycles.append(tuple(cycle))
    return tuple(cycles)


def subtour_cut(
    subtour: tuple[int, ...] | list[int],
    vars_x: dict[tuple[int, int], int],
    n: int,
) -> list[int]:
    """Require at least one selected arc to leave a dummy-free subtour."""
    members = set(subtour)
    if not members or 0 in members:
        raise ValueError("a subtour cut must be non-empty and exclude dummy vertex 0")
    cut = [
        vars_x[source, target]
        for source in sorted(members)
        for target in range(n + 1)
        if target not in members
    ]
    if not cut:
        raise AssertionError("subtour cut is unexpectedly empty")
    return cut


def decode_hamiltonian_sequence(successor: dict[int, int], n: int) -> tuple[int, ...]:
    """Decode real vertices in the order reached after dummy vertex 0."""
    current = 0
    sequence: list[int] = []
    for _ in range(n):
        current = successor[current]
        if current == 0:
            raise AssertionError("dummy cycle closes before every real job is visited")
        sequence.append(current)
    if successor[current] != 0:
        raise AssertionError("decoded cycle does not return to dummy after N jobs")
    if set(sequence) != set(range(1, n + 1)):
        raise AssertionError("decoded Hamiltonian sequence is not a real-job permutation")
    return tuple(sequence)
