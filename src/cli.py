from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .optimize import optimize_instance
from .parser import SSPParseError, discover_input_files, parse_file
from .report import print_result, write_csv
from .solver import SolverConfigurationError


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Exact SAT solver for SSP instances")
    parser.add_argument("input", type=Path, help="input benchmark file or directory")
    output = parser.add_mutually_exclusive_group()
    output.add_argument("--csv", type=Path, default=Path("ssp_results.csv"), help="CSV output path")
    output.add_argument("--no-csv", action="store_true", help="disable CSV output")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    try:
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
        results = []
        for instance in instances:
            result = optimize_instance(instance)
            results.append(result)
            print_result(result, sys.stdout)
        if not args.no_csv:
            write_csv(results, args.csv)
            print(f"CSV summary: {args.csv}")
        return 0
    except (SSPParseError, SolverConfigurationError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
