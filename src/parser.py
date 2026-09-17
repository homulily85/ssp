from __future__ import annotations

import re
from pathlib import Path

from .model import SSPInstance


class SSPParseError(ValueError):
    """Raised when an SSP input file is malformed."""


_METADATA_RE = re.compile(
    r"^\s*(n|m|c|min|max)\s*=\s*(\d+)\s*$", re.IGNORECASE | re.MULTILINE
)
_PROBLEM_RE = re.compile(
    r"^\s*problem\s+(\d+)\s*:?\s*$", re.IGNORECASE | re.MULTILINE
)


def _error(path: Path, message: str, line: int | None = None) -> SSPParseError:
    where = str(path) if line is None else f"{path}:{line}"
    return SSPParseError(f"{where}: {message}")


def parse_file(path: str | Path, *, name_prefix: str | None = None) -> list[SSPInstance]:
    source = Path(path)
    try:
        lines = source.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise SSPParseError(f"cannot read {source}: {exc}") from exc

    metadata: dict[str, int] = {}
    headers: list[tuple[int, int]] = []
    for lineno, line in enumerate(lines, 1):
        match = _METADATA_RE.fullmatch(line)
        if match:
            key = match.group(1).lower()
            if key in {"n", "m", "c"}:
                value = int(match.group(2))
                if key in metadata and metadata[key] != value:
                    raise _error(source, f"conflicting metadata {key}", lineno)
                metadata[key] = value
            # min/max are intentionally ignored: they are not SSP constraints.
            continue
        match = _PROBLEM_RE.fullmatch(line)
        if match:
            headers.append((lineno, int(match.group(1))))

    missing = [key for key in ("n", "m", "c") if key not in metadata]
    if missing:
        raise _error(source, f"missing metadata: {', '.join(missing)}")
    n, m, c = metadata["n"], metadata["m"], metadata["c"]
    if n < 1 or m < 1:
        raise _error(source, "n and m must be positive")
    if not 1 <= c <= m:
        raise _error(source, f"capacity c={c} must satisfy 1 <= c <= m={m}")
    if not headers:
        raise _error(source, "no problem blocks found")

    problem_ids = [problem_id for _, problem_id in headers]
    if len(set(problem_ids)) != len(problem_ids):
        raise _error(source, "duplicate problem ID")
    if problem_ids != list(range(1, len(problem_ids) + 1)):
        raise _error(source, "problem IDs must be consecutive starting at 1")

    instances: list[SSPInstance] = []
    display = name_prefix if name_prefix is not None else str(source)
    for index, (header_line, problem_id) in enumerate(headers):
        end_line = headers[index + 1][0] - 1 if index + 1 < len(headers) else len(lines)
        rows: list[tuple[bool, ...]] = []
        for lineno in range(header_line + 1, end_line + 1):
            stripped = lines[lineno - 1].strip()
            if not stripped or (stripped and set(stripped) == {"-"}):
                continue
            if stripped.lower().startswith("best known value"):
                continue
            if _METADATA_RE.fullmatch(stripped):
                raise _error(source, "metadata is only allowed before problem blocks", lineno)
            values = stripped.split()
            if any(value not in {"0", "1"} for value in values):
                raise _error(source, "matrix row must contain only 0 or 1", lineno)
            if len(values) != n:
                raise _error(source, f"matrix row has {len(values)} values; expected {n}", lineno)
            rows.append(tuple(value == "1" for value in values))
        if len(rows) != m:
            raise _error(
                source,
                f"problem {problem_id} has {len(rows)} matrix rows; expected {m}",
                header_line,
            )

        matrix = tuple(rows)
        requirements = tuple(
            frozenset(tool for tool in range(m) if matrix[tool][job]) for job in range(n)
        )
        for job, required in enumerate(requirements):
            if len(required) > c:
                raise _error(
                    source,
                    f"problem {problem_id}, job {job} requires {len(required)} tools; capacity is {c}",
                    header_line,
                )
        instances.append(
            SSPInstance(
                name=f"{display}#problem-{problem_id}",
                n=n,
                m=m,
                c=c,
                matrix=matrix,
                requirements=requirements,
                source=source,
                problem_id=problem_id,
            )
        )
    return instances


def looks_like_ssp_file(path: Path) -> bool:
    try:
        head = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return False
    keys = {match.group(1).lower() for match in _METADATA_RE.finditer(head)}
    return {"n", "m", "c"} <= keys and bool(re.search(r"(?im)^\s*problem\s+\d+", head))


def discover_input_files(path: str | Path) -> list[Path]:
    target = Path(path)
    if target.is_file():
        return [target]
    if not target.is_dir():
        raise SSPParseError(f"input does not exist or is not a file/directory: {target}")
    return [candidate for candidate in sorted(target.rglob("*")) if candidate.is_file() and looks_like_ssp_file(candidate)]
