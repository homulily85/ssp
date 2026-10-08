from __future__ import annotations

import argparse
import sys
import pysat
from datetime import datetime
from pathlib import Path

from .optimize import optimize_instance
from .model import ALGORITHMS
from .parser import SSPParseError, discover_input_files, parse_file
from .report import print_result, write_csv
from .solver import SolverConfigurationError
from .grouping_report import (
    CONFIGURATION_VERSION, OBJECTIVE_VERSION, append_grouping_row,
    dataset_fingerprint, grouping_row, make_instance_key,
    read_grouping_checkpoint, sha256_file,
)


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Exact SAT solvers for SSP instances, including job grouping"
    )
    parser.add_argument("input", type=Path, help="input benchmark file or directory")
    parser.add_argument(
        "--problem",
        type=int,
        default=None,
        metavar="ID",
        help="solve only problem ID from a single input file",
    )
    parser.add_argument(
        "--limit",
        type=float,
        default=600.0,
        metavar="SECONDS",
        help="time limit for each problem (default: 600 seconds)",
    )
    parser.add_argument("--algorithm", required=True, choices=ALGORITHMS)
    parser.add_argument(
        "--grouping-strength", choices=("basic", "symmetry", "clique"),
        default="clique", help="strength for job-grouping-sat (default: clique)",
    )
    parser.add_argument("--resume", action="store_true", help="resume a grouping CSV checkpoint")
    output = parser.add_mutually_exclusive_group()
    output.add_argument(
        "--csv",
        type=Path,
        default=None,
        help="CSV output path (default: timestamped ssp_result_*.csv)",
    )
    output.add_argument("--no-csv", action="store_true", help="disable CSV output")
    return parser


def _csv_output_path(
    requested: Path | None, timestamp: str, *, interrupted: bool
) -> Path:
    marker = "_interupt" if interrupted else ""
    if requested is None:
        return Path(f"ssp_result_{timestamp}{marker}.csv")
    if not interrupted:
        return requested
    return requested.with_name(f"{requested.stem}{marker}{requested.suffix}")


def main(argv: list[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    timestamp = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
    csv_path = _csv_output_path(args.csv, timestamp, interrupted=False)
    interrupted_csv_path = _csv_output_path(args.csv, timestamp, interrupted=True)
    results = []
    try:
        if args.resume and args.algorithm != "job-grouping-sat":
            raise ValueError("--resume is only supported by job-grouping-sat")
        if args.limit <= 0:
            raise ValueError("--limit must be greater than zero")
        if args.problem is not None and args.problem <= 0:
            raise ValueError("--problem must be greater than zero")
        if args.problem is not None and args.input.is_dir():
            raise ValueError("--problem can only be used with a single input file")
        files = discover_input_files(args.input)
        if not files:
            raise SSPParseError(f"no SSP benchmark files found under {args.input}")
        if args.algorithm == "job-grouping-sat":
            if args.no_csv:
                raise ValueError("job-grouping-sat requires durable CSV output; --no-csv is unavailable")
            if args.resume and args.csv is None:
                raise ValueError("--resume requires an explicit --csv path")
            if args.csv is None and args.resume:
                raise ValueError("--resume requires an explicit --csv path")
            destination = csv_path
            if args.input.is_dir():
                root = args.input.resolve()
                dataset = args.input.name
            else:
                root = args.input.resolve().parent
                dataset = args.input.parent.name or "single-file"
            configuration = {
                "algorithm": "job-grouping-sat", "strength": args.grouping_strength,
                "objective": OBJECTIVE_VERSION, "configuration_version": CONFIGURATION_VERSION,
                "time_limit": args.limit, "solver": "cadical300", "cardinality": "seqcounter",
                "pysat_version": pysat.__version__,
            }
            fingerprint = dataset_fingerprint(files, root, configuration)
            completed = read_grouping_checkpoint(destination, fingerprint) if args.resume else set()
            if destination.exists() and not args.resume:
                raise ValueError(f"output already exists; use --resume or choose another CSV: {destination}")
            failures = 0
            selected_count = 0
            for path in files:
                relative = path.resolve().relative_to(root).as_posix()
                checksum = sha256_file(path)
                for instance in parse_file(path, name_prefix=relative):
                    key = make_instance_key(relative, instance.problem_id, args.grouping_strength)
                    if args.problem is not None and instance.problem_id != args.problem:
                        continue
                    selected_count += 1
                    if key in completed:
                        continue
                    try:
                        result = optimize_instance(
                            instance, time_limit=args.limit, algorithm=args.algorithm,
                            grouping_strength=args.grouping_strength,
                        )
                        print_result(result, sys.stdout)
                        row = grouping_row(
                            instance, dataset=dataset, source_file=relative,
                            strength=args.grouping_strength, checksum=checksum,
                            fingerprint=fingerprint, time_limit=args.limit, result=result,
                        )
                        if result.status == "ERROR":
                            failures += 1
                    except KeyboardInterrupt:
                        raise
                    except Exception as exc:
                        failures += 1
                        print(f"instance error {relative}#{instance.problem_id}: {exc}", file=sys.stderr)
                        row = grouping_row(
                            instance, dataset=dataset, source_file=relative,
                            strength=args.grouping_strength, checksum=checksum,
                            fingerprint=fingerprint, time_limit=args.limit, result=None,
                            error=f"{type(exc).__name__}: {exc}",
                        )
                    append_grouping_row(destination, row)
                    completed.add(key)
                    print(f"Checkpoint saved: {destination} ({len(completed)} completed)")
            if args.problem is not None and selected_count == 0:
                raise ValueError(f"{args.input}: problem {args.problem} was not found")
            print(f"Grouping CSV summary: {destination}")
            return 1 if failures else 0
        instances = []
        for path in files:
            try:
                display = (
                    str(path.relative_to(args.input))
                    if args.input.is_dir()
                    else str(path)
                )
            except ValueError:
                display = str(path)
            instances.extend(parse_file(path, name_prefix=display))
        if args.problem is not None:
            instances = [
                instance for instance in instances if instance.problem_id == args.problem
            ]
            if not instances:
                raise ValueError(
                    f"{args.input}: problem {args.problem} was not found"
                )
        for instance in instances:
            result = optimize_instance(instance, time_limit=args.limit, algorithm=args.algorithm)
            results.append(result)
            print_result(result, sys.stdout)
        if not args.no_csv:
            write_csv(results, csv_path)
            print(f"CSV summary: {csv_path}")
        return 0
    except KeyboardInterrupt:
        print("\nInterrupted by user.", file=sys.stderr)
        if args.algorithm == "job-grouping-sat":
            if args.csv is not None:
                print(f"Completed-instance checkpoint remains at {args.csv}", file=sys.stderr)
            return 130
        if not args.no_csv:
            try:
                write_csv(results, interrupted_csv_path)
                print(
                    f"Partial CSV summary ({len(results)} completed instances): "
                    f"{interrupted_csv_path}",
                    file=sys.stderr,
                )
            except OSError as exc:
                print(f"error writing partial CSV: {exc}", file=sys.stderr)
        return 130
    except (SSPParseError, SolverConfigurationError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
