"""
Lists candidate test overlaps, misfits, and move targets for an agent to verify.

Usage:
    python .claude/skills/tidy/overlap_scan.py [--files PATH ...] [--no-doctests]
        [--min-shared N] [--limit N] [--json]

The scan is static (AST only, nothing is imported or run) and prints *candidates*:
every line is a lead to read, not a verdict. Sections:

- ``helpers`` -- ``tests/_*.py`` names with zero or one importing file (fold the name
  beside its one user), and module-level definitions repeated across test files with
  identical source (one copy belongs in ``tests/_*.py``).
- ``shapes`` -- test methods whose bodies are identical once literals are blanked
  (one parametrized table), within a class or across files.
- ``overlaps`` -- test pairs in different files (or a test and a collected doctest)
  that share distinctive literals: inputs and expected values seen in few places.
  Module-level tables a test names are counted as that test's literals.
- ``doctest-args`` -- a doctest call and a ``pytest.param`` row that name the same
  callee and share a distinctive argument and an expected value (short literals
  such as ``"8"`` or ``"many"`` that ``overlaps`` cannot see).
- ``doctest-raises`` -- a doctest ``Traceback`` and a ``pytest.raises`` (inline, or a
  table row carrying the exception and fragment) for the same exception whose
  ``match`` fragment is found in the doctest's message; ``(same callee)`` marks the
  pairs most likely to be one case.
- ``names`` -- test methods with the same name (``async_`` dropped) in different
  files: often one rule asserted twice.
- ``cross-subject`` -- classes that lean on a name whose ``Test<Subject>`` class
  lives in another file of the same tier (a move candidate).
- ``unsupported`` -- public-tier classes that use names missing from the supported
  surface in ``riko/base/_api_surface.py`` (internal, or a deliberate exception).
- ``placement`` -- module-level helpers with exactly one user class that sit
  below it or with other classes in between (the rule puts them directly above;
  file-wide ``*_PENDING`` tripwire markers stay at the top).
- ``tier`` -- functional-tier classes that touch none of the end-to-end markers
  (CLI runners, examples, stored fixture workflows).

Both doctest sections miss rows given as a bare list with ``ids=[...]`` and doctest
constants reachable only through a variable, and a ``match`` given as an
f-string.

``--where NAME...`` instead prints where each test class or method (``Class``,
``test_x``, or ``Class::test_x``) lives now, as ``path::Class[::method]``.

``--files`` limits the report to entries that touch the given test files: run it
with both halves after a split or merge.
"""

from __future__ import annotations

import argparse
import ast
import builtins
import doctest
import json
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path

DESCRIPTION = "List candidate test overlaps, misfits, and move targets."
TIERS = ("public", "internal", "functional")
DOCTEST_ROOTS = ("riko", "examples")
DOCTEST_FILES = ("README.rst", "docs")
MIN_STR = 5
MIN_ARG = 2
MIN_INT = 10
MAX_SPREAD = 6
MIN_SHAPE_DUMP = 300
CROSS_SUBJECT_MIN = 3
UBIQUITOUS = 6
SECTIONS = (
    "helpers",
    "shapes",
    "overlaps",
    "doctest-args",
    "doctest-raises",
    "names",
    "cross-subject",
    "unsupported",
    "placement",
    "tier",
)
QUOTED = re.compile(r"'([^']{5,})'|\"([^\"]{5,})\"")
NUMBER = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?(?![\w.])")
BUILTINS = frozenset(dir(builtins))
FUNCTION_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)
API_SURFACE = "riko/base/_api_surface.py"
PUBLIC_MODULES = frozenset({"riko.coercion._configs", "riko.types.modules"})
E2E_NAMES = frozenset(
    {
        "CliRunner",
        "run_command",
        "run_module",
        "run_document",
        "run_workflow",
        "gen_fixture_paths",
        "EXAMPLES_DIR",
        "dispatcher",
        "workflow_resolver",
        "subprocess",
        "main",
    }
)
E2E_STR = re.compile(r"(^|[/_])(pipe_|workflows/|examples)|\.json$")
WORD_STOP = frozenset(
    {"title", "content", "description", "value", "items", "utf-8", "error"}
)


@dataclass
class Unit:
    """One test method, or one docstring's doctest examples."""

    path: str
    name: str
    line: int
    literals: set[str] = field(default_factory=set)

    @property
    def where(self) -> str:
        return f"{self.path}:{self.line} {self.name}"


@dataclass
class TestFile:
    path: Path
    tier: str
    tree: ast.Module
    source: str
    tables: dict[str, set[str]] = field(default_factory=dict)

    @property
    def rel(self) -> str:
        return self.path.as_posix()


def gen_literals(node: ast.AST):
    for child in ast.walk(node):
        value = child.value if isinstance(child, ast.Constant) else None
        if isinstance(value, bytes):
            value = value.decode(errors="replace")
        if isinstance(value, str):
            text = value.strip()
            if len(text) >= MIN_STR and text.lower() not in WORD_STOP:
                yield text


def gen_names(node: ast.AST):
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            yield child.id
        elif isinstance(child, ast.Attribute):
            yield child.attr


class _Blank(ast.NodeTransformer):
    def visit_Constant(self, node: ast.Constant) -> ast.AST:
        return ast.copy_location(ast.Constant(value="_"), node)


def get_shape(func: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    body = list(func.body)
    first = body[0] if body else None
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
        body = body[1:]
    blanked = [_Blank().visit(ast.parse(ast.unparse(stmt))) for stmt in body]
    prefix = "async " if isinstance(func, ast.AsyncFunctionDef) else ""
    return prefix + "\n".join(ast.dump(stmt) for stmt in blanked)


def get_tier(path: Path) -> str | None:
    parts = path.parts
    return next((part for part in parts if part in TIERS), None)


def load_test_files(root: Path) -> list[TestFile]:
    files = []

    for tier in TIERS:
        for path in sorted((root / "tests" / tier).glob("test_*.py")):
            source = path.read_text()
            rel = path.relative_to(root)
            files.append(TestFile(rel, tier, ast.parse(source), source))

    for file in files:
        for stmt in file.tree.body:
            targets = []
            if isinstance(stmt, ast.Assign):
                targets = [t.id for t in stmt.targets if isinstance(t, ast.Name)]
            elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                targets = [stmt.target.id]
            for target in targets:
                file.tables[target] = set(gen_literals(stmt))

    return files


def gen_classes(file: TestFile):
    for stmt in file.tree.body:
        if isinstance(stmt, ast.ClassDef) and stmt.name.startswith("Test"):
            yield stmt


def gen_tests(cls: ast.ClassDef):
    for stmt in cls.body:
        is_func = isinstance(stmt, FUNCTION_NODES)
        if is_func and stmt.name.startswith("test"):
            yield stmt


def build_units(files: list[TestFile]) -> list[Unit]:
    units = []

    for file in files:
        for cls in gen_classes(file):
            for func in gen_tests(cls):
                literals = set(gen_literals(func))
                for name in gen_names(func):
                    literals |= file.tables.get(name, set())
                name = f"{cls.name}.{func.name}"
                units.append(Unit(file.rel, name, func.lineno, literals))

    return units


def gen_doctest_sources(root: Path):
    for top in DOCTEST_ROOTS:
        yield from sorted((root / top).rglob("*.py"))
    for top in DOCTEST_FILES:
        path = root / top
        yield from ([path] if path.is_file() else sorted(path.rglob("*.rst")))


def get_leaf(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        leaf = node.id
    elif isinstance(node, ast.Attribute):
        leaf = node.attr
    else:
        leaf = None
    return leaf


def gen_constants(*nodes: ast.AST):
    for node in nodes:
        for child in ast.walk(node):
            is_value = isinstance(child, ast.Constant) and not isinstance(
                child.value, bool
            )
            if is_value:
                yield repr(child.value)


def get_number(text: str) -> str:
    return repr(float(text) if "." in text else int(text))


def get_outputs(want: str) -> set[str]:
    try:
        tree = ast.parse(want.strip(), mode="eval")
    except SyntaxError:
        quoted = {repr(t) for found in QUOTED.findall(want) for t in found if t}
        outputs = quoted | {get_number(text) for text in NUMBER.findall(want)}
    else:
        outputs = set(gen_constants(tree))
    return outputs


@dataclass
class Example:
    """One doctest example: its parsed source, expected output, and exception line."""

    path: str
    name: str
    line: int
    source: str
    tree: ast.Module | None
    want: str
    exc_msg: str | None

    @property
    def where(self) -> str:
        return f"{self.path}:{self.line} doctest {self.name}"

    @property
    def callees(self) -> set[str]:
        nodes = [] if self.tree is None else ast.walk(self.tree)
        calls = (get_leaf(node.func) for node in nodes if isinstance(node, ast.Call))
        return {name for name in calls if name is not None} - BUILTINS

    @property
    def inputs(self) -> set[str]:
        return set() if self.tree is None else set(gen_constants(self.tree))

    @property
    def outputs(self) -> set[str]:
        return get_outputs(self.want)

    @property
    def exception(self) -> str:
        head = (self.exc_msg or "").partition(":")[0].strip()
        return head.rsplit(".", 1)[-1]

    @property
    def message(self) -> str:
        return (self.exc_msg or "").partition(":")[2].strip()


def gen_docstring_groups(root: Path, parser: doctest.DocTestParser):
    for path in gen_doctest_sources(root):
        rel = path.relative_to(root).as_posix()
        text = path.read_text()

        if path.suffix == ".rst":
            yield rel, rel, 1, parser.get_examples(text)
            continue

        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            is_doc = isinstance(node, (ast.Module, ast.ClassDef, *FUNCTION_NODES))
            doc = ast.get_docstring(node, clean=False) if is_doc else None
            if doc and ">>>" in doc:
                line = getattr(node, "lineno", 1)
                name = getattr(node, "name", "<module>")
                yield rel, name, line, parser.get_examples(doc)


def build_examples(root: Path) -> list[Example]:
    parser = doctest.DocTestParser()
    examples = []

    for rel, name, line, found in gen_docstring_groups(root, parser):
        for example in found:
            try:
                tree = ast.parse(example.source)
            except SyntaxError:
                tree = None
            examples.append(
                Example(
                    rel, name, line, example.source, tree, example.want, example.exc_msg
                )
            )

    return examples


def build_doctest_units(examples: list[Example]) -> list[Unit]:
    groups = defaultdict(set)

    for example in examples:
        literals = groups[example.path, example.name, example.line]
        if example.tree is not None:
            literals |= set(gen_literals(example.tree))
        literals |= {
            text
            for found in QUOTED.findall(example.want)
            for text in found
            if text and text.lower() not in WORD_STOP
        }

    return [
        Unit(path, f"doctest {name}", line, literals)
        for (path, name, line), literals in groups.items()
        if literals
    ]


def gen_overlaps(units: list[Unit], doc_units: list[Unit], min_shared: int):
    spread = Counter(lit for unit in units + doc_units for lit in unit.literals)
    keep = {lit for lit, count in spread.items() if count <= MAX_SPREAD}
    trimmed = [(unit, unit.literals & keep) for unit in units]
    trimmed_docs = [(unit, unit.literals & keep) for unit in doc_units]
    by_literal = defaultdict(list)

    for index, (_, lits) in enumerate(trimmed + trimmed_docs):
        for lit in lits:
            by_literal[lit].append(index)

    pool = trimmed + trimmed_docs
    pairs = Counter()

    for indexes in by_literal.values():
        for a, b in combinations(sorted(set(indexes)), 2):
            left, right = pool[a][0], pool[b][0]
            both_docs = left.name.startswith("doctest") and right.name.startswith(
                "doctest"
            )
            if left.path != right.path and not both_docs:
                pairs[a, b] += 1

    for (a, b), count in pairs.most_common():
        if count >= min_shared:
            shared = sorted(pool[a][1] & pool[b][1], key=len, reverse=True)
            yield count, pool[a][0], pool[b][0], shared[:4]


@dataclass
class Row:
    """One ``pytest.param`` row and the test that consumes it."""

    path: str
    line: int
    test: str
    names: set[str]
    constants: set[str]


@dataclass
class Raise:
    """One ``pytest.raises`` call, or a table row carrying an exception and message."""

    path: str
    line: int
    test: str
    names: set[str]
    exceptions: set[str]
    matches: tuple[str, ...]


def is_param(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and get_leaf(node.func) == "param"


def get_defined(stmt: ast.stmt) -> list[str]:
    if isinstance(stmt, (*FUNCTION_NODES, ast.ClassDef)):
        names = [stmt.name]
    elif isinstance(stmt, ast.Assign):
        names = [t.id for t in stmt.targets if isinstance(t, ast.Name)]
    elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
        names = [stmt.target.id]
    else:
        names = []
    return names


def build_param_tables(file: TestFile) -> dict[str, list[ast.Call]]:
    tables = {}

    for stmt in file.tree.body:
        if isinstance(stmt, ast.Assign | ast.AnnAssign) and stmt.value is not None:
            params = [node for node in ast.walk(stmt.value) if is_param(node)]
            for name in get_defined(stmt):
                tables[name] = params

    return tables


def gen_param_rows(
    func: ast.FunctionDef | ast.AsyncFunctionDef, tables: dict[str, list[ast.Call]]
):
    for decorator in func.decorator_list:
        for node in ast.walk(decorator):
            if is_param(node):
                yield node
            elif isinstance(node, ast.Name):
                yield from tables.get(node.id, [])


def get_exceptions(node: ast.AST) -> set[str]:
    elts = node.elts if isinstance(node, ast.Tuple) else [node]
    return {leaf for leaf in map(get_leaf, elts) if leaf is not None}


def gen_strings(*nodes: ast.AST):
    for node in nodes:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.value
        elif isinstance(node, ast.Call):
            yield from gen_strings(*node.args)


def get_matches(call: ast.Call) -> tuple[str, ...]:
    values = (keyword.value for keyword in call.keywords if keyword.arg == "match")
    return tuple(gen_strings(*values))


def get_row_raise(row: ast.Call) -> tuple[set[str], tuple[str, ...]]:
    leaves = (get_leaf(arg) for arg in row.args)
    exceptions = {
        leaf for leaf in leaves if leaf and leaf.endswith(("Error", "Exception"))
    }
    return exceptions, tuple(gen_strings(*row.args))


def build_rows(files: list[TestFile]) -> tuple[list[Row], list[Raise]]:
    rows, raises = [], []

    for file in files:
        tables = build_param_tables(file)
        for cls in gen_classes(file):
            for func in gen_tests(cls):
                test = f"{cls.name}.{func.name}"
                names = set(gen_names(func))
                for row in gen_param_rows(func, tables):
                    row_names = names | set(gen_names(row))
                    constants = set(gen_constants(*row.args))
                    if constants:
                        rows.append(
                            Row(file.rel, row.lineno, test, row_names, constants)
                        )
                    exceptions, matches = get_row_raise(row)
                    if exceptions and "raises" in names:
                        raises.append(
                            Raise(
                                file.rel,
                                row.lineno,
                                test,
                                row_names,
                                exceptions,
                                matches,
                            )
                        )
                for node in ast.walk(func):
                    is_raises = isinstance(node, ast.Call) and node.args
                    if is_raises and get_leaf(node.func) == "raises":
                        exceptions = get_exceptions(node.args[0])
                        raises.append(
                            Raise(
                                file.rel,
                                node.lineno,
                                test,
                                names,
                                exceptions,
                                get_matches(node),
                            )
                        )

    return rows, raises


def get_name_spread(files: list[TestFile]) -> Counter[str]:
    spread = Counter()

    for file in files:
        for cls in gen_classes(file):
            spread.update(set(gen_names(cls)))

    return spread


def is_distinctive(literal: str) -> bool:
    try:
        value = ast.literal_eval(literal)
    except (ValueError, SyntaxError):
        value = None
    if value is None or isinstance(value, bool):
        distinctive = False
    elif isinstance(value, int | float):
        distinctive = abs(value) >= MIN_INT
    elif isinstance(value, str | bytes):
        distinctive = len(value) >= MIN_ARG
    else:
        distinctive = True
    return distinctive


def get_head(text: str, width: int) -> str:
    lines = text.strip().splitlines()
    return lines[0][:width] if lines else ""


def gen_doctest_args(examples: list[Example], rows: list[Row], spread: Counter[str]):
    leads = {}

    for example in examples:
        callee = {name for name in example.callees if spread[name] <= UBIQUITOUS}
        inputs, outputs = example.inputs, example.outputs
        for row in rows:
            if not callee & row.names:
                continue
            shared_in = {lit for lit in row.constants & inputs if is_distinctive(lit)}
            shared_out = row.constants & outputs
            if shared_in and shared_out:
                key = example.where, row.path, row.test
                lead = leads.setdefault(key, (example, row, [], set(), set()))
                lead[2].append(row.line)
                lead[3].update(shared_in)
                lead[4].update(shared_out)

    for example, row, lines, shared_in, shared_out in leads.values():
        source, want = get_head(example.source, 60), get_head(example.want, 30)
        at = ",".join(map(str, lines))
        ins, outs = ", ".join(sorted(shared_in)), ", ".join(sorted(shared_out))
        text = (
            f"{example.where}: {source} -> {want}\n"
            f"      <-> {row.path}:{at} {row.test}\n"
            f"      in {ins}; out {outs}"
        )
        yield text, [example.path, row.path]


def has_match(fragment: str, message: str) -> bool:
    try:
        found = re.search(fragment, message) is not None
    except re.error:
        found = fragment in message
    return found


def gen_doctest_raises(examples: list[Example], raises: list[Raise]):
    seen = set()

    for example in examples:
        if example.exc_msg is None:
            continue
        exception, message, callees = (
            example.exception,
            example.message,
            example.callees,
        )
        for raised in raises:
            key = example.where, raised.path, raised.test
            fragment = next((f for f in raised.matches if has_match(f, message)), None)
            hit = exception in raised.exceptions and fragment is not None
            if hit and key not in seen:
                seen.add(key)
                tag = " (same callee)" if callees & raised.names else ""
                text = (
                    f"{example.where}: {exception}: {get_head(message, 60)}\n"
                    f"      <-> {raised.path}:{raised.line} {raised.test}"
                    f" match={fragment!r}{tag}"
                )
                yield text, [example.path, raised.path]


def gen_shapes(files: list[TestFile]):
    by_shape = defaultdict(list)

    for file in files:
        for cls in gen_classes(file):
            for func in gen_tests(cls):
                shape = get_shape(func)
                if len(shape) >= MIN_SHAPE_DUMP:
                    where = f"{file.rel}:{func.lineno} {cls.name}.{func.name}"
                    by_shape[shape].append((file.rel, where))

    for group in by_shape.values():
        if len(group) > 1:
            yield [where for _, where in group], sorted({path for path, _ in group})


def gen_same_names(units: list[Unit]):
    by_name = defaultdict(list)

    for unit in units:
        method = unit.name.split(".", 1)[1].removeprefix("test_")
        by_name[method.removeprefix("async_")].append(unit)

    for method, group in sorted(by_name.items()):
        paths = sorted({unit.path for unit in group})
        if len(paths) > 1:
            yield f"{method}\n      " + "\n      ".join(u.where for u in group), paths


def _import_module(node: ast.ImportFrom) -> str:
    return "." * node.level + (node.module or "")


def gen_helper_issues(root: Path, files: list[TestFile]):
    users = defaultdict(set)

    for path in [*root.glob("tests/**/*.py"), *root.glob("conftest.py")]:
        tree = ast.parse(path.read_text())
        rel = path.relative_to(root).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = _import_module(node).rsplit(".", 1)[-1] or "tests"
                module = "__init__" if module == "tests" else module
                for alias in node.names:
                    users[module, alias.name].add(rel)

    for helper in sorted(root.glob("tests/_*.py")):
        tree = ast.parse(helper.read_text())
        inside = Counter(
            node.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
        )
        for stmt in tree.body:
            names = []
            if isinstance(stmt, (*FUNCTION_NODES, ast.ClassDef)):
                names = [stmt.name]
            elif isinstance(stmt, ast.Assign):
                names = [t.id for t in stmt.targets if isinstance(t, ast.Name)]
            for name in names:
                if name.startswith(("_", "pytest_")):
                    continue
                found = users.get((helper.stem, name), set())
                internal = inside[name] > 0
                if not internal and len(found) <= 1:
                    rel = helper.relative_to(root).as_posix()
                    who = ", ".join(sorted(found)) or "no test file"
                    yield f"{rel}:{stmt.lineno} {name}: used by {who}", [rel, *found]

    by_source = defaultdict(list)

    for file in files:
        for stmt in file.tree.body:
            if isinstance(stmt, FUNCTION_NODES):
                text = ast.unparse(stmt).replace(f"def {stmt.name}(", "def _(", 1)
            elif isinstance(stmt, ast.Assign | ast.AnnAssign):
                text = ast.unparse(stmt)
            else:
                continue
            by_source[text].append(f"{file.rel}:{stmt.lineno}")

    for text, where in by_source.items():
        paths = {w.split(":", 1)[0] for w in where}
        if len(paths) > 1:
            head = text.splitlines()[0][:70]
            yield (
                f"identical in {len(paths)} files: {head}\n      "
                + "\n      ".join(where),
                sorted(paths),
            )


def _camel(name: str) -> str:
    return "".join(part[:1].upper() + part[1:] for part in name.strip("_").split("_"))


def gen_cross_subject(files: list[TestFile]):
    owner = {}

    for file in files:
        for cls in gen_classes(file):
            subject = cls.name.removeprefix("Test").removeprefix("Async")
            owner[file.tier, subject] = file.rel

    spread = defaultdict(Counter)

    for file in files:
        for cls in gen_classes(file):
            spread[file.tier].update(set(gen_names(cls)))

    for file in files:
        riko_names = set()
        for stmt in ast.walk(file.tree):
            if isinstance(stmt, ast.ImportFrom) and (stmt.module or "").startswith(
                "riko"
            ):
                riko_names |= {alias.asname or alias.name for alias in stmt.names}

        for cls in gen_classes(file):
            own = cls.name.removeprefix("Test").removeprefix("Async")
            counts = Counter(name for name in gen_names(cls) if name in riko_names)
            for name, count in counts.most_common():
                other = owner.get((file.tier, _camel(name)))
                common = spread[file.tier][name] > UBIQUITOUS
                elsewhere = other is not None and other != file.rel
                lean = count >= CROSS_SUBJECT_MIN and not common
                if elsewhere and lean and _camel(name) != own:
                    where = f"{file.rel}:{cls.lineno} {cls.name}"
                    lead = f"uses {name} x{count}; Test{_camel(name)} lives in {other}"
                    yield f"{where} {lead}", [file.rel, other]


def load_supported(root: Path) -> frozenset[str]:
    tree = ast.parse((root / API_SURFACE).read_text())
    names = set()

    for stmt in tree.body:
        if isinstance(stmt, ast.Assign):
            targets = [t.id for t in stmt.targets if isinstance(t, ast.Name)]
            if targets and not any(t.startswith("PRIVATE") for t in targets):
                names |= {
                    node.value
                    for node in ast.walk(stmt)
                    if isinstance(node, ast.Constant) and isinstance(node.value, str)
                }

    return frozenset(names)


def _is_public_module(module: str) -> bool:
    parts = module.split(".")
    is_pipe = parts[:2] == ["riko", "modules"] and len(parts) == 3
    return module in PUBLIC_MODULES or (is_pipe and not parts[2].startswith("_"))


def gen_unsupported(files: list[TestFile], supported: frozenset[str]):
    for file in files:
        if file.tier != "public":
            continue
        private = {}
        for stmt in ast.walk(file.tree):
            is_riko = isinstance(stmt, ast.ImportFrom) and (
                stmt.module or ""
            ).startswith("riko")
            if is_riko and not _is_public_module(stmt.module or ""):
                for alias in stmt.names:
                    if alias.name not in supported:
                        private[alias.asname or alias.name] = alias.name
        for cls in gen_classes(file):
            used = Counter(name for name in gen_names(cls) if name in private)
            if used:
                names = ", ".join(f"{n} x{c}" for n, c in used.most_common())
                yield f"{file.rel}:{cls.lineno} {cls.name}: {names}", [file.rel]


def get_misplaced(file: TestFile) -> list[tuple[str, str, int, str]]:
    classes = list(gen_classes(file))
    module_uses = set()

    for stmt in file.tree.body:
        if not isinstance(stmt, (ast.ClassDef, *FUNCTION_NODES)):
            module_uses |= set(gen_names(stmt)) - set(get_defined(stmt))

    misplaced = []
    defined_at = {
        name: stmt.lineno for stmt in file.tree.body for name in get_defined(stmt)
    }

    for stmt in file.tree.body:
        is_test = isinstance(stmt, ast.ClassDef) and stmt.name.startswith("Test")
        for name in [] if is_test else get_defined(stmt):
            users = [c for c in classes if name in set(gen_names(c))]
            skip = len(users) != 1 or name.endswith("_PENDING") or name in module_uses
            if skip:
                continue
            user = users[0]
            index = classes.index(user)
            twin = user.name.replace("TestAsync", "Test", 1)
            previous = classes[index - 1] if index else None
            if previous is not None and previous.name == twin:
                user = previous
            needs = set(gen_names(stmt)) - set(get_defined(stmt))
            later = [n for n in needs if defined_at.get(n, 0) > user.lineno]
            if later and not isinstance(stmt, FUNCTION_NODES):
                continue
            between = [c.name for c in classes if stmt.lineno < c.lineno < user.lineno]
            if user.lineno < stmt.lineno:
                lead = f"below its one user {user.name}"
            elif between:
                lead = f"not directly above its one user {user.name}"
            else:
                continue
            misplaced.append((name, user.name, stmt.lineno, lead))

    return misplaced


def gen_placement(files: list[TestFile]):
    for file in files:
        for name, _, lineno, lead in get_misplaced(file):
            yield f"{file.rel}:{lineno} {name}: {lead}", [file.rel]


def gen_tier_issues(files: list[TestFile]):
    for file in files:
        if file.tier != "functional":
            continue
        for cls in gen_classes(file):
            names = set(gen_names(cls))
            strings = {
                node.value
                for node in ast.walk(cls)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)
            }
            for name in names & set(file.tables):
                strings |= file.tables[name]
            e2e = names & E2E_NAMES or any(E2E_STR.search(s) for s in strings)
            if not e2e:
                message = "no CLI, example, or fixture-workflow marker"
                yield f"{file.rel}:{cls.lineno} {cls.name}: {message}", [file.rel]


def where(root: Path, *names: str) -> int:
    """Prints each test file's ``path::Class[::method]`` matching a name."""
    found = 0

    for file in load_test_files(root):
        for cls in gen_classes(file):
            for func in [None, *gen_tests(cls)]:
                symbol = cls.name if func is None else f"{cls.name}::{func.name}"
                leaf = cls.name if func is None else func.name
                if leaf in names or symbol in names:
                    line = cls.lineno if func is None else func.lineno
                    print(f"{file.rel}:{line} {file.rel}::{symbol}")
                    found += 1

    return 0 if found else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument("--files", nargs="*", default=[], help="focus on these files")
    parser.add_argument("--no-doctests", action="store_true", help="skip doctests")
    parser.add_argument("--min-shared", type=int, default=2, help="overlap threshold")
    parser.add_argument("--limit", type=int, default=40, help="max overlap pairs")
    parser.add_argument("--json", action="store_true", help="print JSON")
    parser.add_argument("--where", nargs="+", help="locate test classes or methods")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]

    if args.where:
        return where(root, *args.where)
    focus = {Path(f).resolve().relative_to(root).as_posix() for f in args.files}

    def keep(paths) -> bool:
        return not focus or bool(focus & set(paths))

    os.chdir(root)
    root = Path(".")
    files = load_test_files(root)
    units = build_units(files)
    examples = [] if args.no_doctests else build_examples(root)
    doc_units = build_doctest_units(examples)
    rows, raises = build_rows(files)
    report = {section: [] for section in SECTIONS}

    for text, paths in gen_helper_issues(root, files):
        if keep(paths):
            report["helpers"].append(text)

    for group, paths in gen_shapes(files):
        if keep(paths):
            report["shapes"].append("\n      ".join(group))

    for count, left, right, shared in gen_overlaps(units, doc_units, args.min_shared):
        if keep([left.path, right.path]) and len(report["overlaps"]) < args.limit:
            lits = ", ".join(repr(s[:40]) for s in shared)
            report["overlaps"].append(
                f"{count} shared: {left.where}\n      <-> {right.where}\n      {lits}"
            )

    for text, paths in gen_doctest_args(examples, rows, get_name_spread(files)):
        if keep(paths) and len(report["doctest-args"]) < args.limit:
            report["doctest-args"].append(text)

    for text, paths in gen_doctest_raises(examples, raises):
        if keep(paths) and len(report["doctest-raises"]) < args.limit:
            report["doctest-raises"].append(text)

    for text, paths in gen_same_names(units):
        if keep(paths):
            report["names"].append(text)

    for text, paths in gen_cross_subject(files):
        if keep(paths):
            report["cross-subject"].append(text)

    for text, paths in gen_unsupported(files, load_supported(root)):
        if keep(paths):
            report["unsupported"].append(text)

    for text, paths in gen_placement(files):
        if keep(paths):
            report["placement"].append(text)

    for text, paths in gen_tier_issues(files):
        if keep(paths):
            report["tier"].append(text)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for section, lines in report.items():
            print(f"== {section} ({len(lines)})")
            for line in lines:
                print(f"  - {line}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
