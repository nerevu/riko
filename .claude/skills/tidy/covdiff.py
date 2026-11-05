"""
Reports source lines that the tests being cut execute but their covering tests do not.

Usage:
    uv run --active python .claude/skills/tidy/covdiff.py [--data .coverage] \\
        CUT [CUT ...] -- COVER [COVER ...]

CUT and COVER are pytest node ids or prefixes (a file path, ``path::Class``, or
``path::Class::test``); a node id matches a prefix when it equals it or continues
it with ``::`` or ``[``. The data file must hold per-test contexts:

    COVERAGE_CORE=ctrace pytest --cov=riko --cov-context=test

pytest-cov records each test's lines under ``<nodeid>|setup``, ``<nodeid>|run``,
and ``<nodeid>|teardown``; lines run outside any test (import, collection) carry
the empty context and are never reported. Output is one line per file, relative
to the repository root, e.g. ``riko/x.py [12, 13, 40]``. Exits 1 when a line is
reported, 0 when the covering tests execute everything the cut tests do, and 2 on
a usage error or a missing data file.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import coverage

from riko.base._paths import ROOT_DIR

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

SEPARATOR = "--"


def is_match(context: str, prefixes: Iterable[str]) -> bool:
    nodeid = context.rpartition("|")[0]
    return any(nodeid == p or nodeid.startswith((f"{p}::", f"{p}[")) for p in prefixes)


def get_uncovered(
    contexts: Mapping[int, Sequence[str]], cut: Sequence[str], cover: Sequence[str]
) -> list[int]:
    return sorted(
        line
        for line, names in contexts.items()
        if "" not in names
        and any(is_match(c, cut) for c in names)
        and not any(is_match(c, cover) for c in names)
    )


def get_report(
    data: coverage.CoverageData, cut: Sequence[str], cover: Sequence[str], root: Path
) -> list[str]:
    found = {
        os.path.relpath(path, root): lines
        for path in data.measured_files()
        if (lines := get_uncovered(data.contexts_by_lineno(path), cut, cover))
    }
    return [f"{path} {found[path]}" for path in sorted(found)]


def main(argv: Sequence[str] | None = None, root: Path = ROOT_DIR) -> int:
    parser = argparse.ArgumentParser(
        description=(__doc__ or "").strip().splitlines()[0],
        usage="%(prog)s [--data DATA] CUT [CUT ...] -- COVER [COVER ...]",
    )
    parser.add_argument("--data", type=Path, default=Path(".coverage"))
    parser.add_argument("cut", nargs="+")
    args = list(sys.argv[1:] if argv is None else argv)

    if SEPARATOR not in args:
        parser.error(f"missing {SEPARATOR} between CUT and COVER ids")

    split = args.index(SEPARATOR)
    cover = args[split + 1 :]
    namespace = parser.parse_args(args[:split])

    if not cover:
        parser.error(f"no COVER ids after {SEPARATOR}")

    if not namespace.data.exists():
        parser.error(f"no coverage data at {namespace.data}")

    data = coverage.CoverageData(basename=str(namespace.data))
    data.read()
    report = get_report(data, namespace.cut, cover, root)

    for line in report:
        print(line)

    return 1 if report else 0


if __name__ == "__main__":
    raise SystemExit(main())
