from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


ADDITIONAL_CONSTRAINT_NAMES = (
    "symmetry",
    "insertion-requirement",
    "adjacency",
    "required-transition",
)

OptimizationMode = Literal["standard", "incremental", "maxsat", "maxsat-no-t"]
OPTIMIZATION_MODES: tuple[OptimizationMode, ...] = (
    "standard",
    "incremental",
    "maxsat",
    "maxsat-no-t",
)


@dataclass(frozen=True, slots=True)
class AdditionalConstraints:
    symmetry: bool = True
    insertion_requirement: bool = True
    adjacency: bool = True
    required_transition: bool = True

    @classmethod
    def all(cls) -> "AdditionalConstraints":
        return cls()

    @classmethod
    def none(cls) -> "AdditionalConstraints":
        return cls(False, False, False, False)

    @classmethod
    def from_names(cls, names: list[str] | tuple[str, ...]) -> "AdditionalConstraints":
        selected = set(names)
        unknown = selected.difference(ADDITIONAL_CONSTRAINT_NAMES)
        if unknown:
            raise ValueError(f"unknown additional constraints: {sorted(unknown)}")
        return cls(
            symmetry="symmetry" in selected,
            insertion_requirement="insertion-requirement" in selected,
            adjacency="adjacency" in selected,
            required_transition="required-transition" in selected,
        )

    def enabled_names(self) -> tuple[str, ...]:
        return tuple(
            name
            for name, enabled in (
                ("symmetry", self.symmetry),
                ("insertion-requirement", self.insertion_requirement),
                ("adjacency", self.adjacency),
                ("required-transition", self.required_transition),
            )
            if enabled
        )


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
class CNFBuildResult:
    cnf: Any
    vpool: Any
    vars_x: dict[tuple[int, int], int]
    vars_y: dict[tuple[int, int], int]
    vars_z: dict[tuple[int, int], int]
    vars_t: dict[tuple[int, int], int]
    vars_s: dict[tuple[int, int, int], int]
    variable_counts: dict[str, int]
    immediate_unsat: bool = False
    totalizer_rhs: tuple[int, ...] = ()
    t_literal_count: int = 0


@dataclass(slots=True)
class MaxSATBuildResult:
    core: CNFBuildResult
    wcnf: Any


@dataclass(frozen=True, slots=True)
class SolverResult:
    status: str
    solve_time: float
    model: tuple[int, ...] | None
    stats: dict[str, int | float | None]
    objective: int | None = None


@dataclass(frozen=True, slots=True)
class ValidationResult:
    reduced_sequence: tuple[int, ...]
    full_sequence: tuple[int, ...]
    sat_cost: int
    ktns_cost: int
    magazine_configs: tuple[frozenset[int], ...]


@dataclass(frozen=True, slots=True)
class IterationResult:
    k: int | None
    status: str
    primary_variables: int
    auxiliary_variables: int
    variables: int
    clauses: int
    solve_time: float
    stats: dict[str, int | float | None] = field(default_factory=dict)
    objective: int | None = None


@dataclass(frozen=True, slots=True)
class OptimizationResult:
    instance: SSPInstance
    dominance: DominanceResult
    mode: str
    additional_constraints: tuple[str, ...]
    status: str
    lower_bound: int
    initial_upper_bound: int
    initial_reduced_sequence: tuple[int, ...]
    initial_sequence: tuple[int, ...]
    best_cost: int
    optimum: int | None
    optimal_reduced_sequence: tuple[int, ...]
    optimal_sequence: tuple[int, ...]
    verification_cost: int
    iterations: tuple[IterationResult, ...]
    total_runtime: float

    @property
    def sat_time(self) -> float:
        return sum(item.solve_time for item in self.iterations)
