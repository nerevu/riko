"""
Scan riko for the defect classes past bug-fix sessions kept repairing.

Purpose: catch a new instance of a mistake class this repo has already paid to fix,
before it lands. The classes were mined from the 39 ``[FIX]`` commits (and fixups)
since v0.77.3 and the triage notes of 2026-10-05, 10-28/29, 10-30, and 10-31.

Rules (code, class, what it flags):

    RM101 truthiness  ``x or default`` where ``x`` is a value (``0``/``""`` valid)
    RM102 truthiness  ``if x:`` / ``if not x:`` / a comprehension ``if x`` on a
                      value-like name
    RM103 stopiter    one-argument ``next(it)`` in a generator, outside ``try``
    RM201 hash-order  builtin ``hash()``; iterating, materializing, or splatting a
                      set without ``sorted``
    RM301 last-wins   ``json.load(s)`` without ``object_pairs_hook``
    RM401 close       only a ``Generator``/``AsyncGenerator`` is closed (no
                      ``else`` branch closes the rest)
    RM402 close       a user callback's result is discarded (an awaitable never runs)
    RM403 close       ``async for`` over a call in an async generator, without
                      ``aclosing``
    RM501 decode      ``.decode()`` on a chunk/line/raw value (use an incremental
                      decoder)
    RM502 find-slice  a ``.find()``/``.rfind()`` result sliced with no ``-1`` check
    RM601 unbounded   a ``timeout``/``grace`` parameter defaulting to ``0`` or ``inf``
    RM701 frozen      a frozen record field typed set/list/dict, or typed frozen with
                      no ``converter=``
    RM801 parity      sync/async twins (``x``/``ax``, ``_x``/``_ax``) passing
                      different I/O keywords (``timeout``, ``encoding``, ...)

Known gaps, found by running the rules on the pre-fix files: no rule for a sync
``close()`` that returns a coroutine (bb14c8f9); an empty CSV fails inside meza; the
exchangerate timeout rode ``Fetch``'s default, so RM801 never saw it. RM301 covers
only the JSON-document surface of "last-wins"; most of that class's history is
registry and id collisions, now guarded by ``Registry`` and tests. ``--since`` merges
``REF...HEAD`` with the working-tree diff, so line numbers can drift when uncommitted
edits sit above a committed hunk.

Out of scope (needs a type checker or a run): lying overloads and guards that narrow
to ``Unknown`` (``reveal_types.py``); sync/async output parity (a harness run); a fix
later undone by a refactor (``.claude/skills/triage/fail_first.py``).

Inputs:
    default        lines changed in the working tree vs HEAD, plus untracked files
    --diff-file F  lines a saved unified diff adds (``-`` reads stdin, following the
                   pointer ``gates.py scope tidy`` prints for a large scope)
    --staged       lines changed in the index
    --since REF    lines changed in ``REF...HEAD`` plus the working tree
    --all          every line (expect already-triaged leads; use ``--rule``)
    --rule CODE    only these rule codes or prefixes (repeatable: ``--rule RM1``)
    --tests        also scan ``tests/``
    paths          restrict to these files/directories

Truthiness and frozen-record rules skip ``riko/cli`` (flags and argv, not data).
Suppress a reviewed site with a trailing ``# mistake-ok: RM101`` comment, not
``noqa``: ``ruff --fix`` strips unknown ``noqa`` codes.

Outputs: leads grouped by class, most-often-fixed class first (``CLASS_HISTORY`` holds
each class's fix count and the fixes behind it; bump it when a new fix lands), one
``path:line: CODE: message | source`` per lead, then per-class counts on stderr. Exits
1 when any lead is reported.

Origin: /audit of the bug-fix sessions on 2026-11-01 (58bc2070 sibling re-audit,
84c7f004 close landscape, 05a01114 ijson, f5eeae62 meza), promoted to /tidy the same
day.

Run:

    python .claude/skills/land/gates.py scope tidy \\
        | python .claude/skills/tidy/mistake_scan.py --diff-file -
    python .claude/skills/tidy/mistake_scan.py --since main

Smoke tests: uv run --active pytest .claude/skills/tidy/test_mistake_scan.py --no-cov
"""

from __future__ import annotations

import argparse
import ast
import re
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from collections.abc import Iterator

GIT = shutil.which("git") or "git"
ROOT = Path(__file__).resolve().parents[3]
GENERATED = {"_configs.py", "_names.py", "_module_ids.py"}
SAVED_DIFF = re.compile(r"written to (\S+);")
SUPPRESS = re.compile(r"#\s*mistake-ok:\s*([A-Z0-9, ]+)")
VALUE_NAME = re.compile(
    r"(count|limit|timeout|offset|start|stop|end|length|value|default|port|seed|key|"
    r"field|replace|sep|delim|num|index|idx|amount|step|width|size|delay|interval|"
    r"text|content|prefix|suffix|assign|func|match|repl|precision|places|base|max|"
    r"min|attr|path|ext|query|format|encoding|emit|newval|inputs|item|rule|word)",
    re.IGNORECASE,
)
PREDICATE = re.compile(
    r"^_?(is|has|can|should|use|allow|enable|strict|native)[_A-Z]|^_?(is|has)$"
)
BOOLISH = re.compile(
    r"(^|_)(flag|enabled|ok|done|closed|closing|found|seen|verbose|debug|test|async|binary|native|strict|emit|multi|reverse|recursive|lazy|dry|keepends|mode|seed)$|_is_|_has_|(match|ed|ing)$",
    re.IGNORECASE,
)
EMPTY_DEFAULTS = {
    "''",
    '""',
    "{}",
    "[]",
    "()",
    "0",
    "False",
    "None",
    "set()",
    "dict()",
    "list()",
    "tuple()",
}
CALLBACK_NAME = re.compile(
    r"^_?(cleanup|callback|hook|on_[a-z_]+|factory|finalizer|teardown)$"
)
CHUNK_NAME = re.compile(
    r"(chunk|raw|piece|block|part|line|buf|data|content|payload)", re.IGNORECASE
)
IO_KEYWORDS = {
    "timeout",
    "encoding",
    "remove_BOM",
    "decode",
    "chunksize",
    "limit",
    "errors",
    "newline",
    "mode",
    "headers",
}
GENERATOR_TYPES = {"Generator", "AsyncGenerator", "GeneratorType", "AsyncGeneratorType"}
MUTABLE_TYPES = {
    "set",
    "list",
    "dict",
    "Set",
    "List",
    "Dict",
    "MutableMapping",
    "MutableSequence",
    "MutableSet",
    "bytearray",
}
FROZEN_TYPES = {
    "frozenset",
    "tuple",
    "FrozenDict",
    "AbstractSet",
    "Mapping",
    "Sequence",
}
SET_OPS = (ast.BitOr, ast.BitAnd, ast.Sub, ast.BitXor)
CLASS_HISTORY = {
    "close": (
        12,
        (
            "64f59e8f 0e46faa0 c1bfb665 e91f15d4 2f7aed5b 8cbe9be8 bac81221 "
            "bb14c8f9; 10-31 raw return, async close(), loop aclosing; "
            "11-01 async_merge aclosing"
        ),
    ),
    "last-wins": (
        11,
        (
            "83687951 57ab5eea 8bb1e03a; 10-05 parse_dag keys, alias/id collisions, "
            "registry shadow; 10-31 dup JSON keys, migrate keys, target shadow, "
            "codegen names"
        ),
    ),
    "truthiness": (
        7,
        (
            "78952d53 db3fc807; 10-05 port null; "
            "10-31 regex, falsy func, rename '', DotDict ''"
        ),
    ),
    "parity": (
        7,
        (
            "79cf0381 5e14b54d 9e98699c; "
            "10-31 exchangerate timeout, ijson shape, async_write; "
            "11-01 async fetchpage/exchangerate encoding"
        ),
    ),
    "decode": (4, "4013ebf1 09819f69; 10-31 async_write multibyte, fetchtext BOM"),
    "stopiter": (
        4,
        "4013ebf1 empty source; 10-31 empty CSV, regex zero-width; 11-01 regex $N",
    ),
    "hash-order": (3, "10-05 graph order; 10-31 tz abbreviations, hash module"),
    "frozen": (3, "1906d375; 10-05 deep-frozen definitions; 10-31 WriteCapabilities"),
    "unbounded": (
        3,
        "737f19d6 fetch timeout, 998daf8b async_map limit; 10-31 async fetch timeout",
    ),
    "find-slice": (1, "10-31 fetchpage.get_string"),
}


class Lead(NamedTuple):
    path: Path
    line: int
    code: str
    kind: str
    message: str


def label(node: ast.AST) -> str:
    match node:
        case ast.Name(id=name):
            result = name
        case ast.Attribute(value=value, attr=attr):
            result = f"{label(value)}.{attr}"
        case ast.Call(func=func):
            result = f"{label(func)}()"
        case ast.Subscript(value=value):
            result = f"{label(value)}[]"
        case _:
            result = type(node).__name__

    return result


def is_value_like(node: ast.AST) -> bool:
    if isinstance(node, ast.Call):
        last = label(node.func).split(".")[-1]
        result = last == "get" and bool(node.args)
    elif isinstance(node, (ast.Name, ast.Attribute, ast.Subscript)):
        last = label(node).split(".")[-1].rstrip("[]")
        result = (
            not PREDICATE.search(last)
            and not BOOLISH.search(last)
            and not last.isupper()
            and bool(VALUE_NAME.search(last))
        )
    else:
        result = False

    return result


def is_set_expr(node: ast.AST) -> bool:
    match node:
        case ast.Set() | ast.SetComp():
            result = True
        case ast.Call(func=ast.Name(id="set" | "frozenset")):
            result = True
        case ast.Call(
            func=ast.Attribute(
                attr="difference" | "union" | "intersection" | "symmetric_difference"
            )
        ):
            result = True
        case ast.BinOp(op=op, left=left, right=right) if isinstance(op, SET_OPS):
            result = is_set_expr(left) or is_set_expr(right) or _is_keys(left)
        case _:
            result = False

    return result


def _is_keys(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and label(node.func).endswith(".keys")


def _annotation_names(node: ast.AST | None) -> set[str]:
    names = set()

    for sub in ast.walk(node) if node is not None else ():
        if isinstance(sub, ast.Name):
            names.add(sub.id)
        elif isinstance(sub, ast.Attribute):
            names.add(sub.attr)

    return names


def _outer_annotation(node: ast.AST | None) -> str:
    match node:
        case ast.Subscript(value=value):
            result = label(value).split(".")[-1]
        case ast.Name() | ast.Attribute():
            result = label(node).split(".")[-1]
        case ast.BinOp(left=left):
            result = _outer_annotation(left)
        case _:
            result = ""

    return result


def _is_frozen_record(cls: ast.ClassDef) -> bool:
    result = False

    for dec in cls.decorator_list:
        name = label(dec.func if isinstance(dec, ast.Call) else dec)

        if name.split(".")[-1] == "frozen":
            result = True
        elif isinstance(dec, ast.Call) and name.split(".")[-1] in {
            "define",
            "dataclass",
            "attrs",
            "s",
        }:
            result = result or any(
                kw.arg == "frozen"
                and isinstance(kw.value, ast.Constant)
                and kw.value.value is True
                for kw in dec.keywords
            )

    return result


def _calls_close(body: list[ast.stmt]) -> bool:
    return any(
        isinstance(n, ast.Attribute) and n.attr in {"close", "aclose"}
        for stmt in body
        for n in ast.walk(stmt)
    )


def _field_has_converter(value: ast.AST | None) -> bool:
    return (
        isinstance(value, ast.Call)
        and label(value.func).split(".")[-1] in {"field", "ib", "attrib"}
        and any(kw.arg == "converter" for kw in value.keywords)
    )


class Scanner(ast.NodeVisitor):
    def __init__(self, path: Path, source: str) -> None:
        self.path = path
        self.lines = source.splitlines()
        self.leads: list[Lead] = []
        self.functions: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
        self.try_depth = 0
        self.aclosing_depth = 0
        self.tooling = "cli" in path.parts and "riko" in path.parts

    def add(self, node: ast.AST, code: str, kind: str, message: str) -> None:
        self.leads.append(
            Lead(self.path, getattr(node, "lineno", 0), code, kind, message)
        )

    @property
    def function(self) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
        return self.functions[-1] if self.functions else None

    def _is_generator(self, func: ast.AST | None) -> bool:
        return func is not None and any(
            isinstance(n, (ast.Yield, ast.YieldFrom))
            for n in ast.walk(func)
            if self._owner(n, func)
        )

    def _owner(self, node: ast.AST, func: ast.AST) -> bool:
        return getattr(node, "_rm_func", None) is func

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for sub in ast.walk(node):
            sub._rm_func = node  # type: ignore[attr-defined]

        for inner in ast.walk(node):
            if inner is not node and isinstance(
                inner, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
            ):
                for sub in ast.walk(inner):
                    sub._rm_func = inner  # type: ignore[attr-defined]

        self._check_unbounded(node)
        self._check_find_slice(node)
        self.functions.append(node)
        self.generic_visit(node)
        self.functions.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.visit_FunctionDef(node)

    def visit_Try(self, node: ast.Try | ast.TryStar) -> None:
        catches = any(
            h.type is None
            or "StopIteration" in label(h.type)
            or "Exception" in ast.unparse(h.type)
            for h in node.handlers
        )
        self.try_depth += catches

        for stmt in node.body:
            self.visit(stmt)

        self.try_depth -= catches

        for part in (*node.handlers, *node.orelse, *node.finalbody):
            self.visit(part)

    def visit_TryStar(self, node: ast.TryStar) -> None:
        self.visit_Try(node)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        wraps = any("aclosing" in label(item.context_expr) for item in node.items)
        self.aclosing_depth += wraps
        self.generic_visit(node)
        self.aclosing_depth -= wraps

    def visit_With(self, node: ast.With) -> None:
        wraps = any("closing" in label(item.context_expr) for item in node.items)
        self.aclosing_depth += wraps
        self.generic_visit(node)
        self.aclosing_depth -= wraps

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        parent = getattr(node, "_rm_parent", None)

        if (
            isinstance(node.op, ast.Or)
            and is_value_like(node.values[0])
            and ast.unparse(node.values[-1]) not in EMPTY_DEFAULTS
            and not self.tooling
            and not isinstance(
                parent,
                (ast.If, ast.While, ast.IfExp, ast.Assert, ast.UnaryOp, ast.BoolOp),
            )
        ):
            self.add(
                node,
                "RM101",
                "truthiness",
                f"`{label(node.values[0])} or ...` replaces a falsy value; "
                "test `is None`",
            )

        self.generic_visit(node)

    def _check_test(self, node: ast.AST, test: ast.AST) -> None:
        target = (
            test.operand
            if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not)
            else test
        )

        if isinstance(target, ast.BoolOp):
            for value in target.values:
                self._check_test(node, value)
        elif (
            is_value_like(target)
            and not isinstance(target, ast.Call)
            and not self.tooling
        ):
            self.add(
                node,
                "RM102",
                "truthiness",
                f'truth test on `{label(target)}`; `0`/`""`/`False` may be valid',
            )

    def visit_If(self, node: ast.If | ast.While | ast.IfExp) -> None:
        self._check_test(node.test, node.test)
        test = node.test

        if (
            isinstance(node, ast.If)
            and isinstance(test, ast.Call)
            and label(test.func) == "isinstance"
            and len(test.args) == 2
            and _annotation_names(test.args[1]) & GENERATOR_TYPES
            and _calls_close(node.body)
            and not _calls_close(node.orelse)
        ):
            self.add(
                test,
                "RM401",
                "close",
                "only generators are closed; use get_sync_closer/get_async_closer",
            )

        self.generic_visit(node)

    def visit_While(self, node: ast.While) -> None:
        self.visit_If(node)

    def visit_IfExp(self, node: ast.IfExp) -> None:
        self.visit_If(node)

    def visit_comprehension(self, node: ast.comprehension) -> None:
        for test in node.ifs:
            self._check_test(test, test)

        if is_set_expr(node.iter):
            self.add(
                node.iter,
                "RM201",
                "hash-order",
                "comprehension over a set; order varies with PYTHONHASHSEED",
            )

        self.generic_visit(node)

    def visit_For(self, node: ast.For | ast.AsyncFor) -> None:
        if is_set_expr(node.iter):
            self.add(
                node,
                "RM201",
                "hash-order",
                "loop over a set; order varies with PYTHONHASHSEED",
            )

        if (
            isinstance(node, ast.AsyncFor)
            and isinstance(node.iter, ast.Call)
            and not self.aclosing_depth
            and isinstance(self.function, ast.AsyncFunctionDef)
            and self._is_generator(self.function)
        ):
            self.add(
                node,
                "RM403",
                "close",
                f"async generator iterates `{label(node.iter)}` without `aclosing`; "
                "abandoning it leaves the source open",
            )

        self.generic_visit(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self.visit_For(node)

    def visit_Call(self, node: ast.Call) -> None:
        name = label(node.func)
        last = name.split(".")[-1].rstrip("()")

        if any(isinstance(a, ast.Starred) and is_set_expr(a.value) for a in node.args):
            self.add(
                node,
                "RM201",
                "hash-order",
                "set splatted into a call; argument order varies with PYTHONHASHSEED",
            )
        elif name == "hash" and (
            self.function is None or self.function.name != "__hash__"
        ):
            self.add(
                node,
                "RM201",
                "hash-order",
                "builtin hash() is seeded per process; use coercion._canonical.digest",
            )
        elif (
            name in {"list", "tuple", "sorted"}
            and node.args
            and is_set_expr(node.args[0])
            and name != "sorted"
        ):
            self.add(
                node,
                "RM201",
                "hash-order",
                f"{name}() of a set; order varies with PYTHONHASHSEED",
            )
        elif name.endswith(".join") and node.args and is_set_expr(node.args[0]):
            self.add(
                node,
                "RM201",
                "hash-order",
                "join over a set; order varies with PYTHONHASHSEED",
            )
        elif name in {"json.load", "json.loads"} or (
            name in {"load", "loads"} and self._json_imported
        ):
            if not any(kw.arg == "object_pairs_hook" for kw in node.keywords):
                self.add(
                    node,
                    "RM301",
                    "last-wins",
                    f"{name}() keeps the last of duplicate keys; "
                    "pass object_pairs_hook",
                )
        elif (
            name == "next"
            and len(node.args) == 1
            and not self.try_depth
            and self._is_generator(self.function)
        ):
            self.add(
                node,
                "RM103",
                "stopiter",
                "next() in a generator; StopIteration becomes RuntimeError "
                "(pass a default)",
            )
        elif (
            last == "decode"
            and isinstance(node.func, ast.Attribute)
            and CHUNK_NAME.search(label(node.func.value))
            and not any(kw.arg == "final" for kw in node.keywords)
        ):
            self.add(
                node,
                "RM501",
                "decode",
                f"`{label(node.func.value)}.decode()` per chunk splits multibyte "
                "characters; use getincrementaldecoder",
            )

        self.generic_visit(node)

    def visit_Expr(self, node: ast.Expr) -> None:
        call = node.value

        if (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and CALLBACK_NAME.match(call.func.id)
        ):
            self.add(
                node,
                "RM402",
                "close",
                f"result of `{call.func.id}(...)` discarded; "
                "an awaitable return never runs",
            )

        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if _is_frozen_record(node) and not self.tooling:
            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(
                    stmt.target, ast.Name
                ):
                    outer = _outer_annotation(stmt.annotation)
                    ann = ast.unparse(stmt.annotation)

                    if "ClassVar" in ann or _field_has_converter(stmt.value):
                        continue

                    if outer in MUTABLE_TYPES:
                        self.add(
                            stmt,
                            "RM701",
                            "frozen",
                            f"frozen field `{stmt.target.id}: {ann}` is mutable; "
                            "convert to a frozen type",
                        )
                    elif outer in {"frozenset", "tuple", "FrozenDict", "AbstractSet"}:
                        self.add(
                            stmt,
                            "RM701",
                            "frozen",
                            f"frozen field `{stmt.target.id}: {ann}` has no converter; "
                            "a caller's mutable value is kept",
                        )

        self.generic_visit(node)

    @property
    def _json_imported(self) -> bool:
        return any("from json import" in line for line in self.lines)

    def _check_unbounded(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        args = node.args
        positional = [*args.posonlyargs, *args.args]
        pairs = [
            *zip(
                positional[len(positional) - len(args.defaults) :],
                args.defaults,
                strict=True,
            ),
            *zip(args.kwonlyargs, args.kw_defaults, strict=True),
        ]

        for arg, default in pairs:
            if default is None or not re.search(r"(timeout|grace)$", arg.arg):
                continue

            text = ast.unparse(default)

            if text in {"0", "0.0", "inf", "math.inf", "float('inf')"}:
                self.add(
                    default,
                    "RM601",
                    "unbounded",
                    f"`{arg.arg}={text}` waits forever by default; default to settings",
                )

    def _check_find_slice(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        found: dict[str, ast.AST] = {}

        for sub in ast.walk(node):
            if (
                isinstance(sub, ast.Assign)
                and len(sub.targets) == 1
                and isinstance(sub.targets[0], ast.Name)
                and isinstance(sub.value, (ast.Call, ast.BinOp))
                and any(
                    isinstance(c, ast.Call)
                    and label(c.func).split(".")[-1].rstrip("()") in {"find", "rfind"}
                    for c in ast.walk(sub.value)
                )
            ):
                found[sub.targets[0].id] = sub

        checked = {
            n.id
            for cmp in ast.walk(node)
            if isinstance(cmp, ast.Compare)
            for n in ast.walk(cmp)
            if isinstance(n, ast.Name)
        }

        for sub in ast.walk(node):
            if isinstance(sub, ast.Slice):
                for name in {
                    n.id for n in ast.walk(sub) if isinstance(n, ast.Name)
                } & set(found) - checked:
                    self.add(
                        found[name],
                        "RM502",
                        "find-slice",
                        f"`{name}` from find() is sliced without a -1 check",
                    )
                    del found[name]


def _check_parity(tree: ast.Module, path: Path) -> Iterator[Lead]:
    funcs: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs.setdefault(node.name, node)

    for name, sync in funcs.items():
        prefix = "_" if name.startswith("_") else ""
        twin = funcs.get(f"{prefix}a{name.removeprefix('_')}") or funcs.get(
            f"async_{name}"
        )

        if twin is None or isinstance(sync, ast.AsyncFunctionDef):
            continue

        def keywords(func: ast.AST) -> set[str]:
            return {
                kw.arg
                for call in ast.walk(func)
                if isinstance(call, ast.Call)
                for kw in call.keywords
                if kw.arg in IO_KEYWORDS
            }

        for missing, has, where in (
            (keywords(sync) - keywords(twin), name, twin),
            (keywords(twin) - keywords(sync), twin.name, sync),
        ):
            if missing:
                yield Lead(
                    path,
                    where.lineno,
                    "RM801",
                    "parity",
                    f"`{where.name}` never passes {sorted(missing)} "
                    f"that its twin `{has}` does",
                )


def _annotate_parents(tree: ast.AST) -> None:
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            child._rm_parent = node  # type: ignore[attr-defined]


def scan_file(path: Path) -> list[Lead]:
    source = path.read_text()
    tree = ast.parse(source)
    _annotate_parents(tree)
    scanner = Scanner(path, source)
    scanner.visit(tree)
    leads = [*scanner.leads, *_check_parity(tree, path)]
    lines = scanner.lines
    kept = []

    for lead in sorted(set(leads), key=lambda x: (x.line, x.code)):
        text = lines[lead.line - 1] if 0 < lead.line <= len(lines) else ""
        suppressed = SUPPRESS.search(text)

        if suppressed is None or not any(
            lead.code.startswith(c.strip())
            for c in suppressed.group(1).split(",")
            if c.strip()
        ):
            kept.append(lead)

    return kept


def git(*args: str) -> str:
    return subprocess.run(
        [GIT, *args], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout


def changed_lines(diff: str) -> dict[Path, set[int]]:
    changed: dict[Path, set[int]] = {}
    current: Path | None = None
    number = 0

    for line in diff.splitlines():
        if line.startswith("+++ "):
            current = None if line.endswith("/dev/null") else ROOT / line[6:]
        elif line.startswith("@@"):
            match = re.search(r"\+(\d+)", line)
            number = int(match.group(1)) if match is not None else 0
        elif current is not None and number:
            if line.startswith("+"):
                changed.setdefault(current, set()).add(number)
                number += 1
            elif line.startswith(" "):
                number += 1

    return changed


def load_diff(diff_file: str) -> str:
    if diff_file == "-":
        text = sys.stdin.read()
        pointer = SAVED_DIFF.search(text)

        if pointer is not None and "diff --git" not in text:
            text = (ROOT / pointer.group(1)).read_text()
    else:
        text = Path(diff_file).read_text()

    return text


def resolve_scope(args: argparse.Namespace) -> dict[Path, set[int]] | None:
    if args.all:
        scope = None
    elif args.diff_file is not None:
        scope = changed_lines(load_diff(args.diff_file))
    elif args.staged:
        scope = changed_lines(git("diff", "--cached", "-U0"))
    else:
        diff = git("diff", "-U0", f"{args.since}...HEAD") if args.since else ""
        scope = changed_lines(diff + git("diff", "-U0", "HEAD"))

        for name in git("ls-files", "--others", "--exclude-standard").splitlines():
            scope[ROOT / name] = set(range(1, 1_000_000))

    return scope


def gen_files(args: argparse.Namespace) -> Iterator[Path]:
    roots = [Path(p).resolve() for p in args.paths] or [
        ROOT / "riko",
        *([ROOT / "tests"] if args.tests else []),
    ]

    for root in roots:
        for path in sorted(root.rglob("*.py")) if root.is_dir() else [root]:
            if (
                path.suffix == ".py"
                and path.name not in GENERATED
                and "__pycache__" not in path.parts
            ):
                yield path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(__doc__ or "").split("\n\n")[0].strip(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("paths", nargs="*")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--all", action="store_true")
    group.add_argument("--staged", action="store_true")
    group.add_argument("--since")
    group.add_argument("--diff-file")
    parser.add_argument("--rule", action="append", default=[])
    parser.add_argument("--tests", action="store_true")
    args = parser.parse_args(argv)
    scope = resolve_scope(args)
    found: list[tuple[Lead, str]] = []

    for path in gen_files(args):
        if scope is not None and path not in scope:
            continue

        lines = path.read_text().splitlines()

        for lead in scan_file(path):
            in_scope = scope is None or lead.line in scope[path]
            selected = not args.rule or any(lead.code.startswith(r) for r in args.rule)

            if in_scope and selected:
                found.append(
                    (lead, lines[lead.line - 1].strip()[:90] if lead.line else "")
                )

    def rank(entry: tuple[Lead, str]) -> tuple[int, str, str, int]:
        lead = entry[0]
        return (-CLASS_HISTORY[lead.kind][0], lead.code, str(lead.path), lead.line)

    counts = Counter(lead.kind for lead, _ in found)
    kind = None

    for lead, text in sorted(found, key=rank):
        if lead.kind != kind:
            kind = lead.kind
            fixes, refs = CLASS_HISTORY[kind]
            print(f"\n## {kind}: fixed {fixes}x before ({refs}); {counts[kind]} leads")

        inside = lead.path.is_relative_to(ROOT)
        where = lead.path.relative_to(ROOT) if inside else lead.path
        print(f"{where}:{lead.line}: {lead.code}: {lead.message} | {text}")

    print(
        f"\n{len(found)} leads "
        + " ".join(
            f"{k}={counts[k]}"
            for k in sorted(counts, key=lambda k: -CLASS_HISTORY[k][0])
        ),
        file=sys.stderr,
    )
    return int(bool(found))


if __name__ == "__main__":
    sys.exit(main())
