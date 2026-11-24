"""
Prints the bodies of named functions in a Python file, docstrings stripped.

Purpose: read several helpers at once (a helper-chain or sync/async twin review) without
opening whole files or fighting shell quoting in awk/sed function extraction.

Inputs: ``PATH NAME [NAME ...]``.

Outputs: a ``=== path:line name`` header per matching function, then its source from
its first decorator, with the docstring and blank lines dropped.

Origin: 2026-11-23 single-use-helper review, used 3+ times that session; promoted
2026-11-24.
"""

from __future__ import annotations

import argparse
import ast
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

type FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef


def _get_docstring_lines(node: FunctionNode) -> range:
    """Gets the line numbers a function's docstring spans, if it has one."""
    first = node.body[0] if node.body else None
    lines = range(0)

    if (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    ):
        lines = range(first.lineno, (first.end_lineno or first.lineno) + 1)

    return lines


def gen_definitions(path: Path, *names: str) -> Iterator[str]:
    """Generates each named function's header and stripped source lines."""
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    wanted = frozenset(names)

    for node in ast.walk(ast.parse(source)):
        is_named = getattr(node, "name", None) in wanted

        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and is_named:
            decorators = [d.lineno for d in node.decorator_list]
            start = min([node.lineno, *decorators])
            skipped = _get_docstring_lines(node)
            yield f"=== {path}:{node.lineno} {node.name}"

            for number in range(start, (node.end_lineno or node.lineno) + 1):
                line = lines[number - 1]

                if number not in skipped and line.strip():
                    yield line


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(__doc__ or "").strip().splitlines()[0]
    )
    parser.add_argument("path", type=Path)
    parser.add_argument("names", nargs="+")
    args = parser.parse_args(argv)

    for line in gen_definitions(args.path, *args.names):
        print(line)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
