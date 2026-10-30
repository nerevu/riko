"""
Lifts module-level constants to the top of each file, private names first.

Usage:
    python .claude/skills/tidy/lift_constants.py FILE [FILE ...] [--dry-run]

A constant is a module-level assignment to an UPPER_CASE name (an optional leading
underscore marks it private). ``pytest.param`` tables, and constants built from
them, are exempt: they stay above the class that uses them. The constant block
follows the imports (and any ``if TYPE_CHECKING:`` block): private names first,
then public ones, each group in source order, but never above a constant it reads.
The module ``logger = get_logger(...)`` binding leads the block and ``type``
aliases (evaluated lazily, so always safe to hoist) follow it, each group set off
by a blank line. One-line constants sit on adjacent lines; a multi-line one gets a
blank line around it. Plain statements the lift brings together are one blank line
apart (the block follows the header by one); two blank lines stay only where the
source had them or where Ruff requires them, around a top-level function or class.

The header is the leading run of docstring, imports, guarded ``try`` imports, and
``if TYPE_CHECKING:`` blocks; later imports are code. A name assigned more than once
is never moved (lifting would let the later value win everywhere); it is reported
instead. A constant that calls a module function or class defined below it brings
that helper up too (every overload of it, and every helper it calls), placed just
before the first constant that needs it and after any constant the helper reads.
A constant that reads anything else defined later in the file (a fixture, a
lowercase module value, a name some later statement mutates in place) stays where
it is and is reported, so it can be renamed or moved by hand. An alias of a
same-file function or class (``LINT_COMMAND = _lint_command``) is not a constant
and stays put. Comment lines directly above a moved statement move with it. Only
files whose statements would change are reported and written: blank lines alone
never count, so the tool never respaces an already-ordered file, and a top block
that only swaps into private-first order reports as ``reordered``. A second pass
reports nothing.
"""

from __future__ import annotations

import argparse
import ast
import builtins
import re
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator


CONST = re.compile(r"^_?[A-Z][A-Z0-9_]*$")
GENERATED = {"_configs.py", "_names.py", "_module_ids.py"}
BUILTINS = set(dir(builtins))
HELPER_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)

MUTATORS = frozenset(
    {
        "add",
        "append",
        "clear",
        "discard",
        "extend",
        "insert",
        "pop",
        "popitem",
        "remove",
        "setdefault",
        "sort",
        "update",
    }
)

DEF_LINE = re.compile(r"(?:async def |def |class |@)")
SCOPES = (ast.Lambda, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)


type Helper = ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef


def get_targets(node: ast.stmt) -> list[str]:
    if isinstance(node, ast.Assign):
        targets = node.targets
    elif isinstance(node, ast.AnnAssign):
        targets = [node.target]
    elif isinstance(node, ast.TypeAlias):
        targets = [node.name]
    else:
        targets = []

    elts = [e for t in targets for e in (t.elts if isinstance(t, ast.Tuple) else [t])]
    return [e.id for e in elts if isinstance(e, ast.Name)]


def is_table(node: ast.stmt, tables: set[str]) -> bool:
    builds = any(
        isinstance(n, ast.Call) and ast.unparse(n.func) in {"pytest.param", "param"}
        for n in ast.walk(node)
    )
    return builds or bool(get_reads(node) & tables)


def is_constant(node: ast.stmt) -> bool:
    names = get_targets(node)
    value = getattr(node, "value", None)
    return bool(names) and all(map(CONST.match, names)) and value is not None


def is_logger(node: ast.stmt) -> bool:
    """Whether ``node`` is the module ``logger = get_logger(...)`` binding."""
    value = getattr(node, "value", None)
    return (
        get_targets(node) == ["logger"]
        and isinstance(value, ast.Call)
        and isinstance(value.func, ast.Name)
        and value.func.id == "get_logger"
    )


def is_movable(node: ast.stmt) -> bool:
    """Whether the lift places ``node``: a constant, the logger, or a type alias."""
    return is_constant(node) or is_logger(node) or isinstance(node, ast.TypeAlias)


def get_rank(node: ast.stmt) -> int:
    """Block position: logger, type aliases, private constants, public constants."""
    if is_logger(node):
        rank = 0
    elif isinstance(node, ast.TypeAlias):
        rank = 1
    else:
        rank = 3 - get_targets(node)[0].startswith("_")

    return rank


def get_group(node: ast.stmt) -> int:
    """Groups that a blank line separates: the logger, type aliases, constants."""
    return min(get_rank(node), 2)


def is_header(node: ast.stmt, index: int) -> bool:
    docstring = index == 0 and isinstance(node, ast.Expr)
    imports = isinstance(node, (ast.Import, ast.ImportFrom))
    checking = isinstance(node, ast.If) and "TYPE_CHECKING" in ast.unparse(node.test)
    guarded = isinstance(node, ast.Try) and any(
        isinstance(n, (ast.Import, ast.ImportFrom)) for n in node.body
    )
    return docstring or imports or checking or guarded


def get_reads(node: ast.AST) -> set[str]:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def get_import_reads(node: ast.stmt) -> set[str]:
    """Names a statement reads when the module runs (a ``type`` alias is lazy)."""
    return set() if isinstance(node, ast.TypeAlias) else get_reads(get_value(node))


def gen_bound(node: ast.AST) -> Iterator[str]:
    """Names a module-level statement binds, including inside ``try``/``if`` blocks."""
    if isinstance(node, HELPER_TYPES):
        yield node.name
    elif isinstance(node, SCOPES):
        pass
    elif isinstance(node, (ast.Import, ast.ImportFrom)):
        yield from ((a.asname or a.name).split(".")[0] for a in node.names)
    elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
        yield node.id
    else:
        for child in ast.iter_child_nodes(node):
            yield from gen_bound(child)


def gen_mutated(node: ast.stmt) -> Iterator[str]:
    """Names a module-level statement mutates in place (``X[k] = v``, ``X += v``)."""
    for n in ast.walk(node):
        if isinstance(n, ast.AugAssign):
            base = n.target
        elif isinstance(n, (ast.Subscript, ast.Attribute)) and isinstance(
            n.ctx, (ast.Store, ast.Del)
        ):
            base = n.value
        elif (
            isinstance(n, ast.Expr)
            and isinstance(n.value, ast.Call)
            and isinstance(n.value.func, ast.Attribute)
            and n.value.func.attr in MUTATORS
        ):
            base = n.value.func.value
        else:
            base = None

        if isinstance(base, ast.Name):
            yield base.id


def get_doubles(lines: list[str]) -> set[tuple[str, str]]:
    """Line pairs separated by exactly two blank lines."""
    return {
        (lines[i], lines[i + 3])
        for i in range(len(lines) - 3)
        if lines[i] and lines[i + 1] == lines[i + 2] == "" and lines[i + 3]
    }


def respace(new: str, old: str) -> str:
    """
    Leaves one blank line between plain statements the lift brought together.

    Two blank lines stay where the original had them, after an indented block
    (a function or class body), and before a ``def``, ``class``, or decorator.
    """
    text = re.sub(r"\n{4,}", "\n\n\n", new)
    keep = get_doubles(old.split("\n"))
    lines = text.split("\n")
    out: list[str] = []
    index = 0

    while index < len(lines):
        line = lines[index]
        out.append(line)
        tail = lines[index + 1 : index + 4]
        double = (
            len(tail) == 3
            and tail[0] == tail[1] == ""
            and bool(tail[2])
            and not line.startswith((" ", "\t"))
            and not tail[2].startswith((" ", "\t"))
            and not DEF_LINE.match(tail[2])
            and (line, tail[2]) not in keep
        )
        out.extend([""] if double else [])
        index += 3 if double else 1

    return "\n".join(out)


def squash(text: str) -> str:
    """Drops blank lines, so spacing alone never counts as a change."""
    return re.sub(r"\n[ \t]*(?=\n)", "", text)


def get_value(node: ast.stmt) -> ast.AST:
    return (
        node.value
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value
        else node
    )


def get_start(node: ast.stmt, lines: list[str]) -> int:
    decorators = getattr(node, "decorator_list", [])
    start = (decorators[0] if decorators else node).lineno - 1

    while start > 0 and lines[start - 1].lstrip().startswith("#"):
        start -= 1

    return start


def get_chunk(node: ast.stmt, lines: list[str]) -> tuple[int, int, str]:
    start = get_start(node, lines)
    end = node.end_lineno or node.lineno
    return start, end, "".join(lines[start:end]).rstrip("\n") + "\n"


def order(
    constants: list[ast.stmt], helpers: dict[int, list[Helper]]
) -> list[ast.stmt]:
    """Orders constants, each preceded by the not-yet-placed helpers it calls."""
    defined = {name for node in constants for name in get_targets(node)}
    needs = {
        id(node): (
            get_import_reads(node).union(
                *(get_reads(h) for h in helpers.get(id(node), []))
            )
            & defined
        )
        - set(get_targets(node))
        for node in constants
    }
    ranked = sorted(constants, key=lambda n: (get_rank(n), n.lineno))
    placed: list[ast.stmt] = []
    done: set[str] = set()

    while ranked:
        node = next(n for n in ranked if needs[id(n)] <= done)
        ranked.remove(node)
        fresh = [h for h in helpers.get(id(node), []) if h not in placed]
        placed.extend(sorted(fresh, key=lambda h: h.lineno))
        placed.append(node)
        done |= set(get_targets(node))

    return placed


def build_text(
    text: str,
    header: list[ast.stmt],
    helpers: dict[int, list[Helper]],
    constants: list[ast.stmt],
) -> str:
    lines = text.splitlines(keepends=True)
    ordered = order(constants, helpers)
    spans = [get_chunk(n, lines) for n in ordered]
    chunks = {id(n): span[2] for n, span in zip(ordered, spans, strict=True)}
    drop = {i for start, end, _ in spans for i in range(start, end)}
    insert_at = max((n.end_lineno or n.lineno) for n in header) if header else 0
    kept_before = [line for i, line in enumerate(lines[:insert_at]) if i not in drop]
    kept_after = [
        line for i, line in enumerate(lines[insert_at:], insert_at) if i not in drop
    ]
    block = ""

    for previous, node in zip([None, *ordered], ordered, strict=False):
        defs = isinstance(node, HELPER_TYPES) or isinstance(previous, HELPER_TYPES)
        multiline = node.end_lineno != node.lineno
        after_multiline = (
            previous is not None and previous.end_lineno != previous.lineno
        )
        between = (
            "".join(lines[previous.end_lineno : get_start(node, lines)])
            if isinstance(previous, HELPER_TYPES) and previous.end_lineno is not None
            else None
        )

        if (
            isinstance(node, HELPER_TYPES)
            and between is not None
            and not between.strip()
        ):
            gap = between
        elif defs:
            gap = "\n\n"
        elif previous is not None and get_group(previous) != get_group(node):
            gap = "\n"
        else:
            gap = "\n" if multiline or after_multiline else ""

        block += (gap if previous is not None else "") + chunks[id(node)]

    before = "".join(kept_before).rstrip("\n") + "\n" if kept_before else ""
    after = "".join(kept_after).lstrip("\n")
    gap = "\n\n" if DEF_LINE.match(after) else "\n"
    lead = "\n\n" if isinstance(ordered[0], HELPER_TYPES) else "\n"
    new = before + (lead if before else "") + block + gap + after
    new = respace(new, text)
    return new.rstrip("\n") + "\n"


def lift(path: Path, dry: bool) -> list[str]:
    text = path.read_text()
    body = ast.parse(text).body
    first_code = next(
        (i for i, n in enumerate(body) if not is_header(n, i) and not is_movable(n)),
        len(body),
    )
    header = [n for i, n in enumerate(body[:first_code]) if is_header(n, i)]
    code_seen = False
    top: list[ast.stmt] = []
    late: list[ast.stmt] = []
    tables: set[str] = set()

    for index, node in enumerate(body):
        if is_header(node, index):
            continue
        elif is_constant(node) and is_table(node, tables):
            tables |= set(get_targets(node))
            code_seen = True
        elif is_movable(node):
            (late if code_seen else top).append(node)
        else:
            code_seen = True

    functions: dict[str, list[Helper]] = {}

    for n in body:
        if isinstance(n, HELPER_TYPES):
            functions.setdefault(n.name, []).append(n)

    module_names = {
        name for node in body if node not in header for name in gen_bound(node)
    }
    available = (
        BUILTINS
        | {name for node in header for name in gen_bound(node)}
        | {name for node in top for name in get_targets(node)}
        | {node.name.id for node in body if isinstance(node, ast.TypeAlias)}
    )
    mutated = {
        name
        for node in body
        if node not in header and not isinstance(node, HELPER_TYPES)
        for name in gen_mutated(node)
    }
    helpers: dict[int, list[Helper]] = {}
    moved: list[ast.stmt] = []
    report = []

    counts = Counter(name for node in body for name in get_targets(node))

    for node in late:
        rebound = [name for name in get_targets(node) if counts[name] > 1]

        if rebound:
            names = ", ".join(rebound)
            report.append(f"{path}:{node.lineno} {names} is assigned more than once")
            continue

        value = get_value(node)

        if isinstance(value, ast.Name) and value.id in functions:
            continue

        reads = get_import_reads(node)
        missing = reads & module_names - available
        pending = sorted(missing & set(functions))
        closure: list[str] = []

        while pending:
            name = pending.pop()

            if name not in closure:
                closure.append(name)
                calls = {r for h in functions[name] for r in get_reads(h)}
                pending.extend(sorted(calls & set(functions)))

        helper_reads = {
            r for name in closure for h in functions[name] for r in get_reads(h)
        } & module_names
        blocked = (
            (missing - set(functions))
            | (helper_reads - available - set(functions))
            | ((reads | helper_reads) & mutated)
        )

        if blocked:
            names = ", ".join(sorted(blocked))
            report.append(f"{path}:{node.lineno} {get_targets(node)[0]} needs {names}")
        else:
            helpers[id(node)] = [h for name in closure for h in functions[name]]
            moved.append(node)
            available |= set(get_targets(node))

    current = [*top, *moved]
    new = build_text(text, header, helpers, current) if current else text

    if squash(new) != squash(text):
        report.extend(f"{path}:{n.lineno} {get_targets(n)[0]} -> top" for n in moved)
        report.extend([f"{path}: reordered"] if not moved else [])

        if not dry:
            path.write_text(new)

    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(__doc__ or "").strip().splitlines()[0]
    )
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    for path in args.files:
        if path.name in GENERATED:
            print(f"{path}: generated; change its generator instead")
            continue

        for line in lift(path, args.dry_run):
            print(line)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
