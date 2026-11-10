"""
Lists docstring and user-doc examples, or near-duplicate pairs among them, for review.

Usage:
    python .claude/skills/tidy/example_scan.py extract [ROOT ...]
    python .claude/skills/tidy/example_scan.py dups [--threshold T] [--rst PATH ...]
        [ROOT ...]

``extract`` prints every docstring that holds a ``>>>`` example as a compact block
(``=== file:line qualname`` followed by the example lines), so an agent reads the
leads file instead of whole modules. ``dups`` compares the input statements of every
example block (imports dropped, quotes and whitespace normalized) across the given
roots and rst files and prints pairs whose Jaccard similarity is at least the
threshold (default 0.8), highest first. Every line is a lead, not a verdict: a module
docstring and its ``pipe`` sharing setup, or a send/receive pair, may be intended.
Defaults: roots ``riko examples``; rst ``README.rst docs/*.rst``. Promoted from the
2026-11-10 example audit.
"""

from __future__ import annotations

import argparse
import ast
import re
from itertools import combinations
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

_ROOTS = ("riko", "examples")
_PROMPT = re.compile(r"^(>>>|\.\.\.)\s?")
_SPACE = re.compile(r"\s+")

type _Documented = ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef


def _gen_defs(tree: ast.AST, prefix: str = "") -> Iterator[tuple[str, _Documented]]:
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            yield f"{prefix}{node.name}", node
            yield from _gen_defs(node, f"{prefix}{node.name}.")


def gen_examples(*roots: str) -> Iterator[tuple[str, list[str]]]:
    for root in roots:
        for path in sorted(Path(root).rglob("*.py")):
            source = path.read_text()
            if ">>>" not in source:
                continue
            tree = ast.parse(source)
            nodes: list[tuple[str, _Documented]] = [("<module>", tree)]
            for name, node in [*nodes, *_gen_defs(tree)]:
                doc = ast.get_docstring(node, clean=False)
                if doc and ">>>" in doc:
                    lines = doc.splitlines()
                    start = next(i for i, line in enumerate(lines) if ">>>" in line)
                    lineno = node.body[0].lineno + start
                    body = [line.strip() for line in lines[start:] if line.strip()]
                    yield f"{path}:{lineno} {name}", body


def gen_rst_examples(*paths: str) -> Iterator[tuple[str, list[str]]]:
    for path in paths:
        block: list[str] = []
        start = 0
        for number, line in enumerate(Path(path).read_text().splitlines(), 1):
            if line.startswith("    ") and line.strip().startswith((">>>", "...")):
                start = start or number
                block.append(line)
            elif block and line.strip() and not line.startswith("    "):
                yield f"{path}:{start}", block
                block, start = [], 0
        if block:
            yield f"{path}:{start}", block


def _statements(lines: list[str]) -> frozenset[str]:
    stmts = {
        _SPACE.sub("", _PROMPT.sub("", line.strip()).replace("'", '"'))
        for line in lines
        if line.lstrip().startswith((">>>", "..."))
    }
    return frozenset(s for s in stmts if s and not s.startswith(("from", "import")))


def gen_dups(blocks: list[tuple[str, list[str]]], threshold: float) -> Iterator[str]:
    sets = [
        (loc, stmts) for loc, lines in blocks if len(stmts := _statements(lines)) > 1
    ]
    scored = [
        (len(a & b) / len(a | b), left, right)
        for (left, a), (right, b) in combinations(sets, 2)
    ]
    for score, left, right in sorted(scored, reverse=True):
        if score >= threshold:
            yield f"{score:.2f}  {left}  <->  {right}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    extract = sub.add_parser("extract")
    extract.add_argument("roots", nargs="*", default=list(_ROOTS))
    dups = sub.add_parser("dups")
    dups.add_argument("roots", nargs="*", default=list(_ROOTS))
    dups.add_argument("--threshold", type=float, default=0.8)
    dups.add_argument("--rst", nargs="*", default=None)
    args = parser.parse_args()

    if args.command == "extract":
        for loc, body in gen_examples(*args.roots):
            print(f"=== {loc}", *body, sep="\n")
    else:
        rst = (
            args.rst
            if args.rst is not None
            else ["README.rst", *map(str, sorted(Path("docs").glob("*.rst")))]
        )
        blocks = [*gen_rst_examples(*rst), *gen_examples(*args.roots)]
        for line in gen_dups(blocks, args.threshold):
            print(line)


if __name__ == "__main__":
    main()
