from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from .model import ADDITIONAL_CONSTRAINT_NAMES, AdditionalConstraints
from .optimize import optimize_instance
from .parser import SSPParseError, discover_input_files, parse_file
from .report import print_result, write_csv
from .solver import SolverConfigurationError


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Exact SAT solver for SSP instances")
    parser.add_argument("input", type=Path, help="input benchmark file or directory")
    parser.add_argument(
        "--limit",
        type=float,
        default=600.0,
        metavar="SECONDS",
        help="time limit for each problem (default: 600 seconds)",
    )
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="reuse one CaDiCaL solver with an iterative totalizer",
    )
    constraints = parser.add_mutually_exclusive_group()
    constraints.add_argument(
        "--enable-constraint",
        action="append",
        choices=ADDITIONAL_CONSTRAINT_NAMES,
        dest="enabled_constraints",
        metavar="NAME",
        help=(
            "enable one optional constraint; repeat to enable several "
            "(symmetry, insertion-requirement, adjacency, or "
            "required-transition; default: enable all)"
        ),
    )
    constraints.add_argument(
        "--core-only",
        action="store_true",
        help="disable every optional constraint and use only the core encoding",
    )
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
    if args.core_only:
        additional_constraints = AdditionalConstraints.none()
    elif args.enabled_constraints is None:
        additional_constraints = AdditionalConstraints.all()
    else:
        additional_constraints = AdditionalConstraints.from_names(
            args.enabled_constraints
        )
    timestamp = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
    csv_path = _csv_output_path(args.csv, timestamp, interrupted=False)
    interrupted_csv_path = _csv_output_path(args.csv, timestamp, interrupted=True)
    results = []
    try:
        if args.limit <= 0:
            raise ValueError("--limit must be greater than zero")
        files = discover_input_files(args.input)
        if not files:
            raise SSPParseError(f"no SSP benchmark files found under {args.input}")
        instances = []
        for path in files:
            try:
                display = str(path.relative_to(args.input)) if args.input.is_dir() else str(path)
            except ValueError:
                display = str(path)
            instances.extend(parse_file(path, name_prefix=display))
        for instance in instances:
            result = optimize_instance(
                instance,
                time_limit=args.limit,
                incremental=args.incremental,
                additional_constraints=additional_constraints,
            )
            results.append(result)
            print_result(result, sys.stdout)
        if not args.no_csv:
            write_csv(results, csv_path)
            print(f"CSV summary: {csv_path}")
        return 0
    except KeyboardInterrupt:
        print("\nInterrupted by user.", file=sys.stderr)
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
