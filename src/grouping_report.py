from __future__ import annotations

import csv
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Iterable

from .model import OptimizationResult, SSPInstance


OBJECTIVE_VERSION = "free-initial-magazine-v1"
CONFIGURATION_VERSION = "job-grouping-sat-v1"
GROUPING_FIELDS = (
    "dataset", "source_file", "problem_id", "algorithm", "grouping_strength",
    "objective_definition", "status", "n", "n_reduced", "m", "c",
    "initial_lb", "initial_ub", "best_cost", "optimum", "number_of_groups",
    "solver_calls", "sat_calls", "unsat_calls", "sat_time", "encoding_time",
    "preprocessing_time", "total_runtime", "time_to_best", "primary_variables_last",
    "auxiliary_variables_last", "clauses_last", "total_conflicts", "total_decisions",
    "total_propagations", "total_restarts", "best_sequence", "input_checksum",
    "configuration_version", "configuration_fingerprint", "instance_key",
    "solver_backend", "cardinality_encoding", "time_limit", "solver_configuration",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def dataset_fingerprint(files: Iterable[Path], root: Path, configuration: dict[str, object]) -> str:
    digest = hashlib.sha256(json.dumps(configuration, sort_keys=True).encode())
    for path in files:
        digest.update(path.resolve().relative_to(root.resolve()).as_posix().encode())
        digest.update(bytes.fromhex(sha256_file(path)))
    return digest.hexdigest()


def make_instance_key(source_file: str, problem_id: int | None, strength: str) -> str:
    return json.dumps(
        [source_file, problem_id, "job-grouping-sat", strength, OBJECTIVE_VERSION],
        separators=(",", ":"),
    )


def _sum_stats(result: OptimizationResult, key: str) -> int | str:
    values = [item.stats.get(key) for item in result.iterations]
    if any(value is None for value in values):
        return "N/A"
    return sum(int(value) for value in values if value is not None)


def grouping_row(
    instance: SSPInstance,
    *,
    dataset: str,
    source_file: str,
    strength: str,
    checksum: str,
    fingerprint: str,
    time_limit: float,
    result: OptimizationResult | None,
    error: str | None = None,
) -> dict[str, object]:
    key = make_instance_key(source_file, instance.problem_id, strength)
    base: dict[str, object] = {
        "dataset": dataset, "source_file": source_file,
        "problem_id": instance.problem_id or "", "algorithm": "job-grouping-sat",
        "grouping_strength": strength,
        "objective_definition": OBJECTIVE_VERSION,
        "status": result.status if result else "ERROR",
        "n": instance.n, "n_reduced": len(result.dominance.active_jobs) if result else "",
        "m": instance.m, "c": instance.c,
        "initial_lb": result.lower_bound if result else "",
        "initial_ub": result.initial_upper_bound if result else "",
        "best_cost": result.best_cost if result else "",
        "optimum": result.optimum if result and result.optimum is not None else "",
        "number_of_groups": result.number_of_groups if result else "",
        "solver_calls": len(result.iterations) if result else 0,
        "sat_calls": sum(it.status == "SAT" for it in result.iterations) if result else 0,
        "unsat_calls": sum(it.status == "UNSAT" for it in result.iterations) if result else 0,
        "sat_time": f"{result.sat_time:.9f}" if result else 0,
        "encoding_time": f"{result.encoding_time:.9f}" if result else 0,
        "preprocessing_time": f"{result.preprocessing_time:.9f}" if result else 0,
        "total_runtime": f"{result.total_runtime:.9f}" if result else 0,
        "time_to_best": f"{result.time_to_best:.9f}" if result else 0,
        "primary_variables_last": result.iterations[-1].primary_variables if result and result.iterations else 0,
        "auxiliary_variables_last": result.iterations[-1].auxiliary_variables if result and result.iterations else 0,
        "clauses_last": result.iterations[-1].clauses if result and result.iterations else 0,
        "total_conflicts": _sum_stats(result, "conflicts") if result else 0,
        "total_decisions": _sum_stats(result, "decisions") if result else 0,
        "total_propagations": _sum_stats(result, "propagations") if result else 0,
        "total_restarts": _sum_stats(result, "restarts") if result else 0,
        "best_sequence": json.dumps(result.optimal_sequence if result else []),
        "input_checksum": checksum,
        "configuration_version": CONFIGURATION_VERSION,
        "configuration_fingerprint": fingerprint,
        "instance_key": key,
        "solver_backend": "cadical300", "cardinality_encoding": "seqcounter",
        "time_limit": time_limit,
        "solver_configuration": json.dumps({
            "solver": "cadical300", "cardinality": "seqcounter",
            "strength": strength, "time_limit": time_limit,
            "objective_version": OBJECTIVE_VERSION,
            "configuration_version": CONFIGURATION_VERSION,
        }, sort_keys=True, separators=(",", ":")),
    }
    if error:
        base["best_sequence"] = json.dumps({"error": error})
    return base


def read_grouping_checkpoint(path: Path, fingerprint: str) -> set[str]:
    if not path.exists():
        raise ValueError(f"resume CSV does not exist: {path}")
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if tuple(reader.fieldnames or ()) != GROUPING_FIELDS:
                raise ValueError("resume CSV has an invalid grouping schema")
            keys: set[str] = set()
            for row in reader:
                if row.get("configuration_fingerprint") != fingerprint:
                    raise ValueError("resume CSV configuration or dataset fingerprint does not match")
                key = row.get("instance_key", "")
                if not key or key in keys:
                    raise ValueError("resume CSV contains an empty or duplicate instance key")
                keys.add(key)
            return keys
    except (OSError, csv.Error) as exc:
        raise ValueError(f"cannot read resume CSV: {exc}") from exc


def append_grouping_row(path: Path, row: dict[str, object]) -> None:
    """Atomically replace the summary while streaming old rows through disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, text=True
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as out:
            writer = csv.DictWriter(out, fieldnames=GROUPING_FIELDS)
            writer.writeheader()
            if path.exists():
                with path.open(encoding="utf-8", newline="") as old:
                    reader = csv.DictReader(old)
                    if tuple(reader.fieldnames or ()) != GROUPING_FIELDS:
                        raise ValueError("existing grouping CSV has an invalid schema")
                    for previous in reader:
                        if previous.get("instance_key") != row["instance_key"]:
                            writer.writerow(previous)
            writer.writerow(row)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary_name, path)
        directory_fd = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise
