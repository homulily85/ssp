from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


ALGORITHM = "tsp-sat-cegar"
JOB_GROUPING_ALGORITHM = "job-grouping-sat"
ALGORITHMS = ("direct-sat", ALGORITHM, JOB_GROUPING_ALGORITHM)


@dataclass(frozen=True, slots=True)
class SSPInstance:
    name: str
    n: int
    m: int
    c: int
    matrix: tuple[tuple[bool, ...], ...]
    requirements: tuple[frozenset[int], ...]
    source: Path | None = None
    problem_id: int | None = None


@dataclass(frozen=True, slots=True)
class ReducedInstance:
    name: str
    m: int
    c: int
    requirements: tuple[frozenset[int], ...]
    local_to_original: tuple[int, ...]
    tool_to_original: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if not self.tool_to_original:
            object.__setattr__(self, "tool_to_original", tuple(range(self.m)))
        if len(self.tool_to_original) != self.m:
            raise ValueError("tool_to_original must contain one ID per reduced tool")
        if len(set(self.tool_to_original)) != self.m:
            raise ValueError("tool_to_original contains duplicate tool IDs")

    @property
    def n(self) -> int:
        return len(self.requirements)


@dataclass(frozen=True, slots=True)
class DominanceResult:
    active_jobs: tuple[int, ...]
    dominator: dict[int, int]
    dominated_by: dict[int, tuple[int, ...]]
    local_to_original: tuple[int, ...]
    original_to_local: dict[int, int]
    reduced: ReducedInstance


@dataclass(slots=True)
class TSPBuildResult:
    """The immutable base formula and variable maps for one reduced instance."""

    cnf: Any
    vpool: Any
    vars_x: dict[tuple[int, int], int]
    vars_z: dict[tuple[int, int], int]
    vars_t: dict[tuple[int, int], int]
    variable_counts: dict[str, int]
    totalizer_rhs: tuple[int, ...]
    t_literal_count: int
    base_clause_count: int


@dataclass(slots=True)
class DirectBuildResult(TSPBuildResult):
    anchor_job: int


@dataclass(frozen=True, slots=True)
class SolverResult:
    status: str
    solve_time: float
    model: tuple[int, ...] | None
    stats: dict[str, int | float | None]


@dataclass(frozen=True, slots=True)
class ValidationResult:
    reduced_sequence: tuple[int, ...]
    full_sequence: tuple[int, ...]
    sat_cost: int
    ktns_cost: int
    magazine_configs: tuple[frozenset[int], ...]
    inserted_tools: tuple[frozenset[int], ...]
    ktns_magazine_configs: tuple[frozenset[int], ...]


@dataclass(frozen=True, slots=True)
class IterationResult:
    k: int
    cegar_round: int
    status: str
    primary_variables: int
    auxiliary_variables: int
    variables: int
    clauses: int
    solve_time: float
    subtours_found: int = 0
    subtour_cuts_added: int = 0
    total_subtour_cuts: int = 0
    actual_solution_cost: int | None = None
    stats: dict[str, int | float | None] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class OptimizationResult:
    instance: SSPInstance
    dominance: DominanceResult
    algorithm: str
    status: str
    lower_bound: int
    initial_upper_bound: int
    initial_reduced_sequence: tuple[int, ...]
    initial_sequence: tuple[int, ...]
    best_cost: int
    optimum: int | None
    optimal_reduced_sequence: tuple[int, ...]
    optimal_sequence: tuple[int, ...]
    magazine_configs: tuple[frozenset[int], ...]
    inserted_tools: tuple[frozenset[int], ...]
    verification_cost: int
    iterations: tuple[IterationResult, ...]
    total_runtime: float
    grouping_strength: str | None = None
    number_of_groups: int = 0
    encoding_time: float = 0.0
    preprocessing_time: float = 0.0
    time_to_best: float = 0.0

    @property
    def sat_time(self) -> float:
        return sum(item.solve_time for item in self.iterations)

    @property
    def cegar_rounds(self) -> int:
        return len(self.iterations) if self.algorithm == ALGORITHM else 0

    @property
    def subtour_cuts(self) -> int:
        return sum(item.subtour_cuts_added for item in self.iterations)
