"""
Moves test classes or methods between test files, with their helpers and imports.

Usage:
    python .claude/skills/tidy/move_tests.py DEST SPEC [SPEC ...] [--before CLASS]
        [--rename NEW] [--with-helpers] [--dry-run]
    python .claude/skills/tidy/move_tests.py --merge DEST_CLASS SPEC [...]
        [--with-helpers] [--dry-run]
    python .claude/skills/tidy/move_tests.py --check SPEC [SPEC ...]
    python .claude/skills/tidy/move_tests.py --sort SPEC [SPEC ...] [--dry-run]
    python .claude/skills/tidy/move_tests.py --delete SPEC [SPEC ...] [--dry-run]
    python .claude/skills/tidy/move_tests.py --drop-row path::TABLE ID [ID ...]
    python .claude/skills/tidy/move_tests.py --place path::NAME [...] --above CLASS
    python .claude/skills/tidy/move_tests.py --place-leads FILE [FILE ...] [--dry-run]

``SPEC`` is ``path::Class`` (a whole class) or ``path::Class::method`` (one test
method). ``DEST`` is ``path`` for classes, ``path::Class`` for methods, which are
appended to the end of that class. ``--before CLASS`` places moved classes above
``CLASS`` in ``DEST`` instead of at the end; ``--rename`` renames a single moved
class (or method).

What moves with a spec:

- its decorators and the comment lines directly above it;
- module-level helpers of the source file (functions, classes, constants) that the
  moved code uses, transitively, when nothing left in the source still uses them.
  They land directly above the moved class (or above the destination class).
  A helper the source still needs is reported, not copied: import it, or lift it
  into ``tests/_*.py`` when three or more copies would share it. A moved method
  carries its helpers only with ``--with-helpers`` (judged with the method left
  out of its class); they land directly above the destination class. Without it,
  every helper the method uses is reported and stays put;
- the imports the moved code needs, copied from the source's import statements.

Modes:

- ``--merge`` moves every method of each ``path::Class`` into ``DEST``
  (``path::Class``, same or another file) and removes the emptied class; a class
  with class-level statements other than its docstring is refused.
- ``--check`` prints, for each spec, the riko names it uses (directly or through
  the source file's helpers) that are not on the supported surface, so a move to
  ``public`` can be decided before it is made; it exits 1 when any spec uses one.
- ``--sort`` orders each class as the layout rule wants: other members, behavior
  tests, rejection tests (built on ``pytest.raises`` and named for a refusal),
  then strict-xfail tripwires (a ``strict=True`` xfail decorator or a module-level
  marker holding one). The order within each group is kept, and the heuristic
  classification is printed; ``--kind TEST=KIND`` (repeatable) reclassifies a
  misfiled test as ``behavior``, ``rejection``, or ``tripwire``.

- ``--delete`` removes each test method or class (decorators and leading
  comments included), and the class too when its last method goes.
- ``--drop-row`` removes the ``pytest.param(..., id=ID)`` rows from the
  module-level table ``TABLE``.
- ``--place`` moves module-level helpers of one file (with their leading
  comments and trailing ``name.attr = ...`` lines) directly above ``CLASS``, in
  source order.
- ``--place-leads`` applies ``overlap_scan.py``'s placement leads to each FILE:
  every helper with one user class moves directly above it (above the sync class
  of a twin pair). Helpers that a module-level statement also uses are left
  alone, since moving them could break import order.

Moves, merges, and renames also repoint backticked citations of the moved symbol
(``path::Class[::test]`` and ``Class::test``) in ``_docs/`` (archive and research
excepted), ``CLAUDE.md``, ``CONTRIBUTING.rst``, ``README.rst``, and ``docs/*.rst``;
``--delete`` lists the citations it leaves dangling. Touched files are then run
through ``ruff format``. Imports are never sorted or
pruned here: ``ruff check --fix`` at the gates owns that. A destination name
collision aborts before anything is written.
"""

from __future__ import annotations

import argparse
import ast
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

DESCRIPTION = "Move test classes or methods between test files."
RUFF = shutil.which("ruff") or "ruff"
ROOT = Path(__file__).resolve().parents[3]
TIERS = ("public", "internal", "functional")
FUNCTION_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)
STRING_TYPE = re.compile(r"[A-Za-z_][\w.]*(\[[\w.,\[\] |]*\])?( \| [\w.\[\], |]+)*")

sys.path.insert(0, str(Path(__file__).parent))
from overlap_scan import (  # noqa: E402
    KIND_OVERRIDES,
    TestFile,
    get_kind,
    get_misplaced,
    get_xfail_markers,
    load_supported,
)
from overlap_scan import _is_public_module as is_public_module  # noqa: E402


@dataclass
class Spec:
    path: Path
    cls: str
    method: str | None = None

    @classmethod
    def parse(cls, text: str) -> Spec:
        path, *names = text.split("::")
        if not 1 <= len(names) <= 2:
            raise SystemExit(f"bad spec {text!r}: want path::Class[::method]")
        return cls(Path(path), *names)


def get_start(node: ast.stmt, lines: list[str]) -> int:
    decorators = getattr(node, "decorator_list", [])
    start = min([node.lineno, *(d.lineno for d in decorators)]) - 1

    while start > 0 and lines[start - 1].lstrip().startswith("#"):
        start -= 1

    return start


def get_defined(stmt: ast.stmt) -> list[str]:
    if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
        names = [stmt.name]
    elif isinstance(stmt, ast.Assign):
        names = [t.id for t in stmt.targets if isinstance(t, ast.Name)]
    elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
        names = [stmt.target.id]
    else:
        names = []
    return names


def get_used(node: ast.AST, skip: ast.AST | None = None) -> set[str]:
    nodes, stack = [], [node]

    while stack:
        current = stack.pop()
        if current is not skip:
            nodes.append(current)
            stack.extend(ast.iter_child_nodes(current))

    used = {n.id for n in nodes if isinstance(n, ast.Name)}

    for child in nodes:
        text = child.value if isinstance(child, ast.Constant) else None
        if isinstance(text, str) and STRING_TYPE.fullmatch(text):
            try:
                parsed = ast.parse(text, mode="eval")
            except SyntaxError:
                continue
            used |= {n.id for n in ast.walk(parsed) if isinstance(n, ast.Name)}

    return used


def get_imports(tree: ast.Module) -> dict[str, str]:
    imports = {}

    for stmt in ast.walk(tree):
        if isinstance(stmt, ast.ImportFrom):
            module = "." * stmt.level + (stmt.module or "")
            for alias in stmt.names:
                bound = alias.asname or alias.name
                suffix = f" as {alias.asname}" if alias.asname else ""
                imports[bound] = f"from {module} import {alias.name}{suffix}"
        elif isinstance(stmt, ast.Import):
            for alias in stmt.names:
                bound = alias.asname or alias.name.split(".")[0]
                suffix = f" as {alias.asname}" if alias.asname else ""
                imports[bound] = f"import {alias.name}{suffix}"

    return imports


def find_class(tree: ast.Module, name: str) -> ast.ClassDef:
    found = next(
        (s for s in tree.body if isinstance(s, ast.ClassDef) and s.name == name), None
    )
    if found is None:
        raise SystemExit(f"class {name} not found")
    return found


def find_method(cls: ast.ClassDef, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    found = next(
        (s for s in cls.body if isinstance(s, FUNCTION_NODES) and s.name == name), None
    )
    if found is None:
        raise SystemExit(f"method {cls.name}.{name} not found")
    return found


def get_helpers(
    tree: ast.Module, moved: ast.stmt, owner: ast.stmt | None = None
) -> tuple[list[ast.stmt], set[str]]:
    defs = {}

    for stmt in tree.body:
        if stmt is not moved and stmt is not owner:
            for name in get_defined(stmt):
                defs[name] = stmt

    wanted, queue = {}, list(get_used(moved))

    while queue:
        name = queue.pop()
        stmt = defs.get(name)
        if stmt is not None and id(stmt) not in wanted:
            wanted[id(stmt)] = stmt
            queue.extend(get_used(stmt))

    def is_kept(stmt: ast.stmt) -> bool:
        return id(stmt) not in wanted and stmt is not moved

    left = set()

    for stmt in tree.body:
        if is_kept(stmt) and not isinstance(stmt, ast.Import | ast.ImportFrom):
            left |= get_used(stmt, moved)

    movable, shared = [], set()

    for stmt in wanted.values():
        names = set(get_defined(stmt))
        if names & left:
            shared |= names
        else:
            movable.append(stmt)

    movable.sort(key=lambda s: s.lineno)
    return movable, shared


def move(
    dest: str,
    spec: Spec,
    before: str | None,
    rename: str | None,
    dry: bool,
    with_helpers: bool,
):
    dest_path, *dest_cls = dest.split("::")
    dest_file = Path(dest_path)
    same = dest_file.resolve() == spec.path.resolve()
    src_lines = spec.path.read_text().splitlines(keepends=True)
    src_tree = ast.parse("".join(src_lines))
    cls = find_class(src_tree, spec.cls)
    method = None if spec.method is None else find_method(cls, spec.method)
    node = cls if method is None else method

    if method is not None and not dest_cls:
        raise SystemExit("moving a method needs DEST as path::Class")
    if method is None and dest_cls:
        raise SystemExit("moving a class needs DEST as a path")

    if method is None:
        helpers, shared = get_helpers(src_tree, cls)
    elif with_helpers and not same:
        helpers, shared = get_helpers(src_tree, method, cls)
    else:
        helpers = []
        outside = get_used(method) - {s for st in cls.body for s in get_defined(st)}
        defs = {n for st in src_tree.body for n in get_defined(st)}
        shared = outside & defs

    blocks = [(get_start(h, src_lines), h.end_lineno or 0) for h in helpers]
    blocks.append((get_start(node, src_lines), node.end_lineno or 0))
    moved_text = {}
    emptied = method is not None and cls.body == [method]
    whole = (get_start(cls, src_lines), cls.end_lineno or 0) if emptied else None

    for start, end in blocks:
        moved_text[start] = "".join(src_lines[start:end])

    body = moved_text.pop(blocks[-1][0])
    if rename is not None:
        old = node.name
        body = body.replace(f"class {old}", f"class {rename}", 1)
        body = body.replace(f"def {old}(", f"def {rename}(", 1)
    helper_text = "\n\n".join(t.rstrip("\n") + "\n" for t in moved_text.values())

    dest_text = "".join(src_lines) if same else _read(dest_file)
    dest_tree = ast.parse(dest_text)
    dest_lines = dest_text.splitlines(keepends=True)
    taken = {n for st in dest_tree.body for n in get_defined(st)}
    new_names = {n for h in helpers for n in get_defined(h)}
    if method is None:
        new_names.add(rename or node.name)
    clash = new_names & taken if not same else set()

    if clash:
        raise SystemExit(f"{dest_file} already defines {sorted(clash)}")

    src_imports = get_imports(src_tree)
    dest_imports = get_imports(dest_tree)
    needed = set(get_used(node))
    for helper in helpers:
        needed |= get_used(helper)
    adds = (
        []
        if same
        else sorted(
            {
                src_imports[n]
                for n in needed
                if n in src_imports and n not in dest_imports
            }
        )
    )
    missing = [] if same else sorted(shared - taken)

    print(f"{spec.path}::{spec.cls}{'::' + spec.method if spec.method else ''}")
    print(f"  -> {dest}")
    for helper in helpers:
        print(f"  helper moved: {', '.join(get_defined(helper))}")
    for name in missing:
        print(f"  helper still used in source, NOT moved: {name}")
    for line in adds:
        print(f"  import added: {line}")

    if dry:
        return []

    if method is None:
        insert_text = (helper_text + "\n\n" if helper_text else "") + body
        if before is None:
            index = len(dest_lines)
            insert_text = "\n\n" + insert_text
        else:
            index = get_start(find_class(dest_tree, before), dest_lines)
            insert_text += "\n\n"
    else:
        dest_node = find_class(dest_tree, dest_cls[0])
        index = dest_node.end_lineno or 0
        insert_text = "\n" + body

    import_at = max(
        (
            s.end_lineno or 0
            for s in dest_tree.body
            if isinstance(s, ast.Import | ast.ImportFrom)
        ),
        default=0,
    )
    removed = {i for start, end in blocks for i in range(start, end)}
    if whole is not None:
        removed |= set(range(*whole))
        print(f"  removed emptied class {spec.cls}")
    inserts = {index: insert_text}
    if method is not None and helper_text:
        inserts[get_start(dest_node, dest_lines)] = helper_text + "\n\n"
    if adds:
        imports = "".join(f"{line}\n" for line in adds)
        inserts[import_at] = imports + inserts.get(import_at, "")

    def splice(lines: list[str], drop: set[int]) -> str:
        out = []
        for i in range(len(lines) + 1):
            out.append(inserts.get(i, ""))
            if i < len(lines) and i not in drop:
                out.append(lines[i])
        return "".join(out)

    if same:
        spec.path.write_text(splice(src_lines, removed))
        touched = [spec.path]
    else:
        dest_file.write_text(splice(dest_lines, set()))
        spec.path.write_text(
            "".join(line for i, line in enumerate(src_lines) if i not in removed)
        )
        touched = [dest_file, spec.path]

    old = (_rel(spec.path), spec.cls, spec.method)
    if method is None:
        new = (_rel(dest_file), rename or spec.cls, None)
    else:
        new = (_rel(dest_file), dest_cls[0], rename or spec.method)
    rewrite_citations(old, new)
    return touched


def _rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def _gen_doc_paths():
    docs = ROOT / "_docs"
    skip = {docs / "archive", docs / "research"}
    for path in sorted(docs.rglob("*.md")):
        if not any(parent in skip for parent in path.parents):
            yield path
    yield from (ROOT / name for name in ("CLAUDE.md", "CONTRIBUTING.rst", "README.rst"))
    yield from sorted((ROOT / "docs").glob("*.rst"))


def rewrite_citations(
    old: tuple[str, str, str | None], new: tuple[str, str, str | None]
) -> None:
    """Repoints doc citations of a moved or renamed test class or method."""
    (old_path, old_cls, old_method), (new_path, new_cls, new_method) = old, new
    old_short = old_path.removeprefix("tests/")
    new_short = new_path.removeprefix("tests/")
    old_symbol = old_cls if old_method is None else f"{old_cls}::{old_method}"
    new_symbol = new_cls if new_method is None else f"{new_cls}::{new_method}"
    end = r"(?=::|`|\[)"
    with_path = re.compile(
        rf"`(tests/)?{re.escape(old_short)}::{re.escape(old_symbol)}{end}"
    )
    bare = re.compile(rf"`{re.escape(old_symbol)}{end}") if old_method else None
    renamed_cls = (
        re.compile(rf"`{re.escape(old_cls)}(?=::)") if old_method is None else None
    )

    def _with_path(match: re.Match[str]) -> str:
        path = new_path if match[1] else new_short
        return f"`{path}::{new_symbol}"

    for path in _gen_doc_paths():
        if not path.exists():
            continue
        text = path.read_text()
        updated = with_path.sub(_with_path, text)
        if bare is not None:
            updated = bare.sub(f"`{new_symbol}", updated)
        if renamed_cls is not None and new_cls != old_cls:
            updated = renamed_cls.sub(f"`{new_cls}", updated)
        if updated != text:
            path.write_text(updated)
            print(f"  citations repointed in {path.relative_to(ROOT)}")


def _read(path: Path) -> str:
    return path.read_text() if path.exists() else ""


KINDS = {"other": 0, "behavior": 1, "rejection": 2, "tripwire": 3}


def check(spec: Spec) -> list[str]:
    tree = ast.parse(spec.path.read_text())
    cls = find_class(tree, spec.cls)
    node = cls if spec.method is None else find_method(cls, spec.method)
    helpers, _ = get_helpers(tree, node) if spec.method is None else ([], set())
    defs = {n: st for st in tree.body for n in get_defined(st)}
    seen, queue = set(), list(get_used(node))

    while queue:
        name = queue.pop()
        if name in defs and name not in seen:
            seen.add(name)
            queue.extend(get_used(defs[name]))

    used = get_used(node) | seen
    for helper in helpers:
        used |= get_used(helper)

    supported = load_supported(ROOT)
    private = []

    for stmt in ast.walk(tree):
        if not isinstance(stmt, ast.ImportFrom):
            continue
        module = stmt.module or ""
        if module.startswith("riko") and not is_public_module(module):
            for alias in stmt.names:
                bound = alias.asname or alias.name
                if bound in used and alias.name not in supported:
                    private.append(f"{alias.name} (from {stmt.module})")

    return sorted(set(private))


def sort_class(spec: Spec, dry: bool) -> list[Path]:
    text = spec.path.read_text()
    lines = text.splitlines(keepends=True)
    tree = ast.parse(text)
    cls = find_class(tree, spec.cls)
    markers = get_xfail_markers(tree)
    members = list(cls.body)
    first = members[0]
    has_doc = isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
    sortable = members[1:] if has_doc else members
    chunks = []

    for index, stmt in enumerate(sortable):
        start = get_start(stmt, lines)
        end = stmt.end_lineno or 0
        chunk = "".join(lines[start:end]).rstrip("\n") + "\n"
        chunks.append((get_kind(stmt, markers), index, chunk, stmt))

    ordered = sorted(chunks, key=lambda c: (c[0], c[1]))
    names = {0: "other", 1: "behavior", 2: "rejection", 3: "tripwire"}
    moved = [c for c, o in zip(chunks, ordered, strict=True) if c[1] != o[1]]
    print(f"{spec.path}::{spec.cls}: {len(moved)} member(s) reordered")
    for kind, _, _, stmt in ordered:
        name = getattr(stmt, "name", type(stmt).__name__)
        print(f"  {names[kind]:9} {name}")

    if dry or not moved:
        return []

    begin = get_start(sortable[0], lines)
    stop = sortable[-1].end_lineno or 0
    body = "\n".join(chunk for _, _, chunk, _ in ordered)
    spec.path.write_text("".join(lines[:begin]) + body + "".join(lines[stop:]))
    return [spec.path]


def merge(dest: str, spec: Spec, dry: bool, with_helpers: bool) -> list[Path]:
    tree = ast.parse(spec.path.read_text())
    cls = find_class(tree, spec.cls)
    methods = [st.name for st in cls.body if isinstance(st, FUNCTION_NODES)]
    others = [
        st
        for st in cls.body
        if not isinstance(st, FUNCTION_NODES)
        and not (isinstance(st, ast.Expr) and isinstance(st.value, ast.Constant))
    ]
    touched = set()

    if others:
        names = ", ".join(ast.unparse(st).splitlines()[0][:50] for st in others)
        raise SystemExit(
            f"{spec.cls} has class-level statements to merge by hand: {names}"
        )

    for method in methods:
        part = Spec(spec.path, spec.cls, method)
        touched |= set(move(dest, part, None, None, dry, with_helpers))

    if not dry:
        lines = spec.path.read_text().splitlines(keepends=True)
        tree = ast.parse("".join(lines))
        is_left = any(
            isinstance(st, ast.ClassDef) and st.name == spec.cls for st in tree.body
        )
        if is_left:
            empty = find_class(tree, spec.cls)
            start, end = get_start(empty, lines), empty.end_lineno or 0
            spec.path.write_text("".join(lines[:start] + lines[end:]))
            print(f"  removed empty class {spec.cls}")
        dest_path, dest_cls = dest.split("::")[:2]
        old = (_rel(spec.path), spec.cls, None)
        rewrite_citations(old, (_rel(Path(dest_path)), dest_cls, None))
        touched.add(spec.path)

    return sorted(touched)


def delete(spec: Spec, dry: bool) -> list[Path]:
    lines = spec.path.read_text().splitlines(keepends=True)
    tree = ast.parse("".join(lines))
    cls = find_class(tree, spec.cls)
    node = cls if spec.method is None else find_method(cls, spec.method)
    if spec.method is not None and cls.body == [node]:
        node = cls
    start, end = get_start(node, lines), node.end_lineno or 0
    print(f"deleted {spec.path}::{spec.cls}{'::' + spec.method if spec.method else ''}")
    if node is cls and spec.method is not None:
        print(f"  removed emptied class {spec.cls}")

    if dry:
        return []

    spec.path.write_text("".join(lines[:start] + lines[end:]))
    symbol = spec.cls if spec.method is None else f"{spec.cls}::{spec.method}"
    cited = re.compile(rf"\b{re.escape(symbol)}(?:`|::|\[)")
    for path in _gen_doc_paths():
        if path.exists() and cited.search(path.read_text()):
            print(f"  still cited in {path.relative_to(ROOT)}; repoint or remove it")
    return [spec.path]


def _gen_row_ids(element: ast.expr):
    if isinstance(element, ast.Call):
        for keyword in element.keywords:
            value = keyword.value
            if keyword.arg == "id" and isinstance(value, ast.Constant):
                yield value.value


def drop_rows(path: Path, table: str, ids: list[str], dry: bool) -> list[Path]:
    text = path.read_text()
    lines = text.splitlines(keepends=True)
    tree = ast.parse(text)
    found = None

    for stmt in tree.body:
        if table in get_defined(stmt):
            found = stmt

    value = getattr(found, "value", None)
    if not isinstance(value, ast.List | ast.Tuple):
        raise SystemExit(f"{path}: no module-level list or tuple named {table}")

    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))

    def at(lineno: int, col: int) -> int:
        prefix = lines[lineno - 1].encode()[:col].decode(errors="ignore")
        return offsets[lineno - 1] + len(prefix)

    spans, missing = [], set(ids)
    elements = value.elts

    for index, element in enumerate(elements):
        row_ids = set(_gen_row_ids(element)) & set(ids)
        if not row_ids:
            continue
        missing -= row_ids
        start = at(element.lineno, element.col_offset)
        if index + 1 < len(elements):
            nxt = elements[index + 1]
            end = at(nxt.lineno, nxt.col_offset)
        else:
            end = at(element.end_lineno or 0, element.end_col_offset or 0)
            rest = text[end:]
            end += len(rest) - len(rest.lstrip(" ,"))
        line_start = text.rfind("\n", 0, start) + 1
        if not text[line_start:start].strip():
            start = line_start
            end = text.rfind("\n", 0, end) + 1 if index + 1 < len(elements) else end
        spans.append((start, end))

    if missing:
        raise SystemExit(f"{path}::{table}: no rows with id {sorted(missing)}")

    print(f"{path}::{table}: dropped {len(spans)} row(s): {', '.join(ids)}")

    if dry:
        return []

    for start, end in sorted(spans, reverse=True):
        text = text[:start] + text[end:]

    path.write_text(text)
    return [path]


def _get_segments(tree: ast.Module, lines: list[str]) -> list[tuple[str, int, int]]:
    segments = []

    for stmt in tree.body:
        names = get_defined(stmt)
        target = stmt.targets[0] if isinstance(stmt, ast.Assign) else None
        if isinstance(target, ast.Attribute) and segments:
            owner = ast.unparse(target.value)
            if owner == segments[-1][0]:
                name, start, _ = segments[-1]
                segments[-1] = (name, start, stmt.end_lineno or 0)
                continue
        name = names[0] if names else ""
        segments.append((name, get_start(stmt, lines), stmt.end_lineno or 0))

    return segments


def place(specs: list[Spec], above: str, dry: bool) -> list[Path]:
    paths = {spec.path for spec in specs}
    if len(paths) != 1:
        raise SystemExit("--place takes helpers from one file")

    path = paths.pop()
    lines = path.read_text().splitlines(keepends=True)
    tree = ast.parse("".join(lines))
    segments = {name: (start, end) for name, start, end in _get_segments(tree, lines)}
    names = [spec.cls for spec in specs]
    missing = [name for name in names if name not in segments]

    if missing:
        raise SystemExit(f"{path}: no module-level {missing}")

    target = get_start(find_class(tree, above), lines)
    blocks = sorted(segments[name] for name in names)
    print(f"{path}: placing {', '.join(names)} above {above}")

    if dry:
        return []

    removed = {i for start, end in blocks for i in range(start, end)}
    text = "\n\n".join("".join(lines[s:e]).rstrip("\n") for s, e in blocks)
    out = []

    for index, line in enumerate(lines):
        if index == target:
            out.append(text + "\n\n\n")
        if index not in removed:
            out.append(line)

    path.write_text("".join(out))
    return [path]


def place_leads(paths: list[Path], dry: bool) -> list[Path]:
    touched = []

    for path in paths:
        rel = path.resolve().relative_to(ROOT)
        tier = next((part for part in rel.parts if part in TIERS), "")
        source = path.read_text()
        file = TestFile(rel, tier, ast.parse(source), source)
        groups = {}
        for name, target, _, _ in get_misplaced(file):
            if target:
                groups.setdefault(target, []).append(name)

        for target, names in groups.items():
            specs = [Spec(path, name) for name in names]
            touched += place(specs, target, dry)

    return touched


def main() -> int:
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument(
        "args", nargs="+", help="DEST SPEC... (or SPEC... with --check/--sort)"
    )
    parser.add_argument("--before", help="place moved classes above this class")
    parser.add_argument("--rename", help="rename the single moved class or method")
    parser.add_argument(
        "--with-helpers",
        action="store_true",
        help="carry helpers only moved methods use",
    )
    parser.add_argument("--dry-run", action="store_true", help="print the plan only")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check", action="store_true", help="list private names SPECs use"
    )
    mode.add_argument(
        "--merge", action="store_true", help="merge classes into DEST class"
    )
    mode.add_argument("--sort", action="store_true", help="order SPEC classes")
    mode.add_argument("--delete", action="store_true", help="delete SPEC tests")
    mode.add_argument(
        "--drop-row", action="store_true", help="drop path::TABLE rows by id"
    )
    mode.add_argument("--place", action="store_true", help="move helpers above")
    mode.add_argument(
        "--place-leads", action="store_true", help="apply placement leads to FILEs"
    )
    parser.add_argument("--above", help="with --place: the class to place above")
    parser.add_argument(
        "--kind",
        action="append",
        default=[],
        metavar="TEST=KIND",
        help="with --sort: classify TEST as behavior, rejection, or tripwire",
    )
    args = parser.parse_args()
    unknown = [k for k in args.kind if k.partition("=")[2] not in KINDS]

    if unknown:
        parser.error(f"--kind takes TEST=KIND with KIND in {sorted(KINDS)}: {unknown}")
    KIND_OVERRIDES.update(
        (name, KINDS[kind]) for name, _, kind in (k.partition("=") for k in args.kind)
    )

    if args.place_leads:
        return _fix(set(place_leads([Path(a) for a in args.args], args.dry_run)))

    if args.drop_row:
        table, *ids = args.args
        path, _, name = table.partition("::")
        touched = set(drop_rows(Path(path), name, ids, args.dry_run))
        return _fix(touched)
    touched = set()
    status = 0
    dest = ""

    if args.check or args.sort or args.delete or args.place:
        specs = [Spec.parse(text) for text in args.args]
    else:
        dest, *rest = args.args
        if not rest:
            raise SystemExit("need DEST and at least one SPEC")
        specs = [Spec.parse(text) for text in rest]

    if args.rename and len(specs) > 1:
        raise SystemExit("--rename takes a single spec")

    if args.place:
        if args.above is None:
            raise SystemExit("--place needs --above CLASS")
        return _fix(set(place(specs, args.above, args.dry_run)))

    for spec in specs:
        if args.delete:
            touched |= set(delete(spec, args.dry_run))
        elif args.check:
            private = check(spec)
            where = (
                f"{spec.path}::{spec.cls}{'::' + spec.method if spec.method else ''}"
            )
            verdict = "supported only" if not private else "uses " + ", ".join(private)
            print(f"{where}: {verdict}")
            status |= bool(private)
        elif args.sort:
            touched |= set(sort_class(spec, args.dry_run))
        elif args.merge:
            touched |= set(merge(dest, spec, args.dry_run, args.with_helpers))
        else:
            touched |= set(
                move(
                    dest,
                    spec,
                    args.before,
                    args.rename,
                    args.dry_run,
                    args.with_helpers,
                )
            )

    return _fix(touched) or status


def _fix(touched: set[Path]) -> int:
    if touched:
        paths = sorted(str(p) for p in touched)
        subprocess.run((RUFF, "format", "-q", *paths), check=False)

    return 0


if __name__ == "__main__":
    sys.exit(main())
