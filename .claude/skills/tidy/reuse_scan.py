"""
Find code that restates an existing riko helper instead of calling it.

Purpose: catch hand-written copies of a helper's body: new code that never learned a
helper exists, and old code written before a new helper landed.

Helpers: every module-level function under ``riko/`` (generated files and
``@overload`` stubs skipped), and with ``--tests`` every one under ``tests/`` too
(``test_*`` functions and fixtures skipped), whose body, past its docstring, is one
``return <expr>`` (an expression helper, ``alist``), a short run of statements with
no ``return`` (a statement helper: a generator loop or a small procedure), or such a
run followed by ``return <name>`` of a name the run binds (a statement helper over the
setup statements; the returned name matches whatever the site binds there). Its
parameters become wildcards (``?0``, ``?1``) that match any expression, bound
consistently; the names its body binds (comprehension and loop targets, assignment
targets, lambda parameters) match any one site name each; every other name must
resolve to the same origin at the site (the same import, the same module-level
definition, or the same builtin; a site local of that name never matches). Patterns
under ``--min-size`` nodes, pure forwarding calls (``return f(a, b)``, every
argument a wildcard or constant), bare passthrough loops (one ``for``/``async for``
whose body is a single ``yield`` of its target), a pipe's ``parser``/``async_parser``,
and ``processor``/``operator``/``splitter``-decorated pipes are not indexed: each is a
module contract or the only delegation form, never a copy to reuse.

Matches: an expression helper matches any expression; a statement helper matches any
contiguous run of statements in a block. A match is skipped inside the helper's own
body, where the import layers bar the site's package from the helper's
(``riko/base/_config.py``), where a ``tests/`` helper meets a site outside ``tests/``
and ``examples/``, and on a span carrying ``# reuse-ok`` or
``# reuse-ok: name[, name]``. A private ``_helper`` matched from another file is
tagged ``private: promote?``; a site that is another helper's whole body (the same
statement or expression nodes) is tagged ``duplicate helper``, or ``color twin`` when
exactly one of the two is an ``async def`` (a sync/async pair to keep in step). A
helper with no parameters whose pattern holds no names only restates a literal; its
matches are tagged ``shared literal: name a constant``, since the fix is a module-level
constant both the helper and the site use, not a call.

Scopes (sites x helpers):

    default        lines added in the working tree vs HEAD plus untracked files x
                   every helper; and the whole tree x helpers the diff added or changed
    --diff-file F  the same, from a saved unified diff (``-`` reads stdin, following
                   the pointer ``gates.py scope tidy`` prints for a large scope)
    --staged       the same, from the index
    --since REF    the same, from ``REF...HEAD`` plus the working tree
    --all          the whole tree x every helper (the bootstrap sweep)
    --tests        also take sites from ``tests/`` and ``examples/``, and index
                   ``tests/`` helpers (for those sites only)
    --min-size N   the smallest pattern indexed, in AST nodes (default 5)
    --helper NAME  only these helpers (repeatable)
    --counts       print per-helper match counts only
    ROOT ...       scan only these roots (``riko``, ``tests``, ``examples``) for
                   sites and helpers, instead of ``riko`` (and ``--tests``'s two)
    --shapes       cluster near-identical constructions instead (below); ignores
                   ``--helper``, ``--counts``, and ``--min-size``
    --shape-min-size N  the smallest shape candidate, in AST nodes (default 6)
    --min-count N  the fewest members a reported shape cluster has (default 3)
    --all-callees  keep the declaration-idiom calls ``--shapes`` skips (below)
    --spans SPEC   with ``--shapes``, keep only clusters whose members span the
                   roots SPEC names: a comma list of terms, each ``ROOT`` (a member
                   lies in ROOT), ``only:ROOT`` (every member lies in an ``only:``
                   root), or ``mixed`` (members lie in two or more roots), as in
                   ``examples,tests``, ``only:examples``, or ``riko,mixed``

Outputs: matches grouped by helper, most matches first: a ``## helper (path:line):
N matches`` header, then ``path:line: could use helper(?0=..., ...) [tags] |
source``; a helper matched more than once on one line prints once. Per-scope totals
go to stderr. Exits 1 when any match is reported.

Known gaps: only same-shape copies match (a loop with ``.append`` never matches a
comprehension helper); a helper with setup statements before a ``return`` of anything
but a name they bind, and every method, are not indexed; a name reached through a
re-exporting package resolves to a different origin than its defining module, so that
site is missed.

Shapes (``--shapes``): instead of helpers, cluster near-identical constructions (dict,
call, list, tuple, and set literals) that differ only in arbitrary values and keys,
each cluster a lead for one shared constant or builder. A candidate is a load-context
node outside annotations, subscript slices, and ``type`` aliases, of at least
``--shape-min-size`` AST nodes (a constant or f-string counts as one), holding at least
one constant or f-string, with at least one argument (a call) or two entries (any other
kind). Plain data is not a construction: a list, tuple, or set of bare constants, or a
keyword-less call over only such values (``frozenset({...})``, ``__all__``), is
skipped, as are declaration idioms whose shape is the API's, not a copy: calls to
``IDIOM_CALLEES`` (attrs ``field``/``define``, ``dataclass``, the ``processor``/
``operator``/``splitter`` decorators, ``click.option``/``argument``,
``ArgumentParser``, ``parser.add_argument``, ``re.compile``,
``pytest.raises``/``param``/``mark.xfail``/``mark.parametrize``), matched on the
callee's dotted name, or on its last part for an undotted entry (``attrs.field``
matches ``field``); their arguments are still scanned. Two levels group them:

    values  the node with every constant and f-string replaced by its type name;
            dict keys, keyword names, callees, and other names stay
    keys    a dict is its ``key=value-shape`` entries; a call is its callee and
            positional arguments (which must match) plus its keyword entries; a
            list, tuple, or set has no keys level. Two values shapes link when one
            has an entry the other lacks, or both share all but one entry and that
            entry's key differs (an entry whose value alone differs never links);
            linked shapes merge transitively

Key names stay in the entries rather than being abstracted: with no key anchor,
every two-string dict in the tree would merge. A group of ``--min-count`` members or
more is reported once: as a values cluster when every member has one values shape,
else as a keys cluster. Skipped: a cluster whose members are all direct elements of
one container (a table already shares its definition), a cluster whose every member
lies inside members of one larger cluster, and a member whose span carries any
``# reuse-ok`` marker (an outer node's marker covers the nodes inside it). Each
cluster prints a ``## skeleton: N members`` header (entries some members lack in
``[...]``), its distinct exact variants and the most common one, up to six varying
slots with their values (``absent`` counts members without it), the roots and files
spanned, and up to five ``path:line`` samples, most members first. The default and
diff scopes report a cluster when a member touches a changed line; ``--spans`` then
keeps the clusters whose spanned roots satisfy every term (a cross-root cluster is a
lead for a shared fixture or builder rather than a file-local constant).

Origin: 2026-11-24 /tidy question "what picks up a duplicate refactoring", after
``_AsyncFileWriteSession._aserialize`` restated ``alist``.

Run:

    python .claude/skills/tidy/reuse_scan.py
    python .claude/skills/tidy/reuse_scan.py --all --counts
    python .claude/skills/tidy/reuse_scan.py --all --tests
    python .claude/skills/tidy/reuse_scan.py --diff-file .claude/tidy-scope.diff
    python .claude/skills/tidy/reuse_scan.py --all --tests --shapes
    python .claude/skills/tidy/reuse_scan.py --all --shapes examples
    python .claude/skills/tidy/reuse_scan.py --all --tests --shapes --spans mixed
    python .claude/skills/tidy/reuse_scan.py --all --tests --shapes --spans riko,mixed
"""

from __future__ import annotations

import argparse
import ast
import builtins
import copy
import re
import sys
from collections import Counter, defaultdict
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

from riko.base._graph import gen_components

sys.path.insert(0, str(Path(__file__).parent))

from mistake_scan import GENERATED, ROOT, changed_lines, git, load_diff

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

type Env = dict[str, str]
type Node = ast.expr | ast.stmt
type Bodies = dict[tuple[int, ...], tuple[str, bool]]
type Shape = tuple[str, tuple[str, ...]]
type Shaped = ast.Dict | ast.Call | ast.List | ast.Tuple | ast.Set

_SKIP_FIELDS = frozenset({"ctx", "type_comment", "kind"})
_OK = re.compile(r"#\s*reuse-ok\b(?::\s*([\w, ]+))?")
_PLAIN = re.compile(r"[\w.:/-]{1,24}")
CONFIG = ROOT / "riko" / "base" / "_config.py"
MAX_STATEMENTS = 4
MIN_SIZE = 5
MIN_COUNT = 3
SHAPE_MIN_SIZE = 6
MAX_SAMPLES = 5
MAX_VALUES = 4
MAX_WIDTH = 120
MAX_SLOTS = 6
SHAPED = (ast.Dict, ast.Call, ast.List, ast.Tuple, ast.Set)
CONTAINERS = (ast.Dict, ast.List, ast.Tuple, ast.Set)
IDIOM_CALLEES = frozenset(
    {
        "field",
        "define",
        "dataclass",
        "processor",
        "operator",
        "splitter",
        "click.option",
        "click.argument",
        "ArgumentParser",
        "parser.add_argument",
        "re.compile",
        "pytest.raises",
        "pytest.param",
        "pytest.mark.xfail",
        "pytest.mark.parametrize",
    }
)
SITE_ROOTS = ("riko",)
TEST_ROOTS = ("tests", "examples")
BUILTINS = frozenset(dir(builtins))
CONTRACT_NAMES = frozenset({"parser", "async_parser"})
PIPE_DECORATORS = frozenset({"processor", "operator", "splitter"})
STUB_DECORATORS = frozenset({"overload", "abstractmethod"})


class Source(NamedTuple):
    """One parsed file: its path, module name, tree, lines, and name origins."""

    path: Path
    module: str
    tree: ast.Module
    lines: list[str]
    origins: dict[str, str]


class Helper(NamedTuple):
    """One indexed helper: where it is defined and the pattern its body forms."""

    name: str
    source: Source
    node: ast.FunctionDef | ast.AsyncFunctionDef
    params: tuple[str, ...]
    bound: frozenset[str]
    pattern: tuple[Node, ...]
    is_expr: bool

    @property
    def where(self) -> str:
        return f"{self.source.path.relative_to(ROOT)}:{self.node.lineno}"

    @property
    def span(self) -> range:
        return range(self.node.lineno, (self.node.end_lineno or 0) + 1)

    @property
    def is_async(self) -> bool:
        return isinstance(self.node, ast.AsyncFunctionDef)

    @property
    def is_literal(self) -> bool:
        names = (n for root in self.pattern for n in ast.walk(root))
        return not self.params and not any(isinstance(n, ast.Name) for n in names)


class Match(NamedTuple):
    """One site that restates a helper's body."""

    helper: Helper
    source: Source
    line: int
    end: int
    bindings: tuple[str, ...]
    tags: tuple[str, ...]

    @property
    def key(self) -> tuple[str, Path, int]:
        return self.helper.where, self.source.path, self.line


def get_module(path: Path) -> str:
    parts = path.relative_to(ROOT).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def resolve_relative(module: str, path: Path, level: int, name: str | None) -> str:
    package = module if path.name == "__init__.py" else module.rpartition(".")[0]

    for _ in range(level - 1):
        package = package.rpartition(".")[0]

    base = package if level else ""
    return ".".join(part for part in (base, name or "") if part)


def gen_import_origins(
    tree: ast.Module, module: str, path: Path
) -> Iterator[tuple[str, str]]:
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            source = resolve_relative(module, path, node.level, node.module)
            yield from ((a.asname or a.name, f"{source}.{a.name}") for a in node.names)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                key = alias.asname or alias.name.partition(".")[0]
                yield key, alias.name if alias.asname else key


def gen_defined_names(stmt: ast.stmt) -> Iterator[str]:
    match stmt:
        case ast.FunctionDef(name=name) | ast.AsyncFunctionDef(name=name):
            yield name
        case ast.ClassDef(name=name):
            yield name
        case ast.Assign(targets=targets):
            yield from (
                n.id for t in targets for n in ast.walk(t) if isinstance(n, ast.Name)
            )
        case (
            ast.AnnAssign(target=ast.Name(id=name))
            | ast.TypeAlias(name=ast.Name(id=name))
        ):
            yield name


def build_origins(tree: ast.Module, module: str, path: Path) -> dict[str, str]:
    origins = dict(gen_import_origins(tree, module, path))
    origins.update(
        (name, f"{module}.{name}")
        for stmt in tree.body
        for name in gen_defined_names(stmt)
    )
    return origins


def load_source(path: Path) -> Source | None:
    text = path.read_text()

    try:
        tree = ast.parse(text)
    except SyntaxError:
        found = None
    else:
        module = get_module(path)
        origins = build_origins(tree, module, path)
        found = Source(path, module, tree, text.splitlines(), origins)

    return found


def gen_paths(*roots: str) -> Iterator[Path]:
    for root in roots:
        for path in sorted((ROOT / root).rglob("*.py")):
            if path.name not in GENERATED and "__pycache__" not in path.parts:
                yield path


@cache
def load_layers() -> tuple[dict[str, set[str]], dict[str, str], dict[str, str]]:
    values = {
        target.id: ast.literal_eval(stmt.value)
        for stmt in ast.parse(CONFIG.read_text()).body
        if isinstance(stmt, (ast.Assign, ast.AnnAssign)) and stmt.value is not None
        for target in (stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target])
        if isinstance(target, ast.Name)
        and target.id in {"LAYER_DEPENDENCIES", "EXACT_LAYERS", "PREFIX_LAYERS"}
    }
    graph = values["LAYER_DEPENDENCIES"]

    @cache
    def reach(layer: str) -> frozenset[str]:
        return frozenset({layer}).union(*(reach(dep) for dep in graph[layer]))

    reachable = {layer: set(reach(layer)) for layer in graph}
    return reachable, values["EXACT_LAYERS"], values["PREFIX_LAYERS"]


@cache
def get_layer(module: str) -> str | None:
    _, exact, prefixes = load_layers()
    layer = exact.get(module)

    if layer is None:
        matches = [
            (prefix, candidate)
            for prefix, candidate in prefixes.items()
            if module == prefix or module.startswith(f"{prefix}.")
        ]
        layer = max(matches)[1] if matches else None

    return layer


def can_import(site: Source, helper: Helper) -> bool:
    reachable, _, _ = load_layers()
    site_layer = get_layer(site.module)
    helper_layer = get_layer(helper.source.module)
    return (
        site_layer is None
        or helper_layer is None
        or helper_layer in reachable.get(site_layer, set())
    )


def is_reachable(site: Source, helper: Helper) -> bool:
    is_test = helper.source.module.partition(".")[0] == "tests"
    return can_import(site, helper) and (
        not is_test or site.module.partition(".")[0] in TEST_ROOTS
    )


def get_body(func: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.stmt]:
    body = func.body
    first = body[0] if body else None
    has_doc = (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    )
    return body[1:] if has_doc else body


def get_params(func: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[str, ...]:
    args = func.args
    named = [*args.posonlyargs, *args.args, *args.kwonlyargs]
    rest = [arg for arg in (args.vararg, args.kwarg) if arg is not None]
    return tuple(arg.arg for arg in (*named, *rest))


def get_bound(body: list[ast.stmt] | list[ast.expr]) -> frozenset[str]:
    names = set()

    for node in (child for stmt in body for child in ast.walk(stmt)):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            names.add(node.id)
        elif isinstance(node, ast.arg):
            names.add(node.arg)

    return frozenset(names)


def gen_decorator_names(func: ast.FunctionDef | ast.AsyncFunctionDef):
    for node in func.decorator_list:
        match node.func if isinstance(node, ast.Call) else node:
            case ast.Name(id=name) | ast.Attribute(attr=name):
                yield name


def is_stub(func: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return not STUB_DECORATORS.isdisjoint(gen_decorator_names(func))


def is_test_only(func: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return func.name.startswith("test_") or "fixture" in set(gen_decorator_names(func))


def is_contract(func: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return func.name in CONTRACT_NAMES or not PIPE_DECORATORS.isdisjoint(
        gen_decorator_names(func)
    )


def is_passthrough(body: list[ast.stmt]) -> bool:
    match body:
        case [
            ast.For(
                target=ast.Name(id=target),
                body=[ast.Expr(value=ast.Yield(value=ast.Name(id=value)))],
                orelse=[],
            )
            | ast.AsyncFor(
                target=ast.Name(id=target),
                body=[ast.Expr(value=ast.Yield(value=ast.Name(id=value)))],
                orelse=[],
            )
        ]:
            found = target == value
        case _:
            found = False

    return found


def has_return(body: list[ast.stmt]) -> bool:
    nested = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)
    pending: list[ast.AST] = list(body)
    found = False

    while pending and not found:
        node = pending.pop()
        found = isinstance(node, ast.Return)

        if not isinstance(node, nested):
            pending.extend(ast.iter_child_nodes(node))

    return found


def get_size(nodes: tuple[Node, ...], params: tuple[str, ...]) -> int:
    return sum(
        not isinstance(node, (ast.expr_context, ast.operator, ast.cmpop))
        and not (isinstance(node, ast.Name) and node.id in params)
        for root in nodes
        for node in ast.walk(root)
    )


def is_forwarding(node: ast.AST, params: tuple[str, ...]) -> bool:
    def is_leaf(arg: ast.AST) -> bool:
        inner = arg.value if isinstance(arg, ast.Starred) else arg
        return isinstance(inner, ast.Constant) or (
            isinstance(inner, ast.Name) and inner.id in params
        )

    match node:
        case ast.Await(value=inner):
            found = is_forwarding(inner, params)
        case ast.Call(func=func, args=args, keywords=keywords):
            callee = {n.id for n in ast.walk(func) if isinstance(n, ast.Name)}
            found = not callee & set(params) and all(
                map(is_leaf, [*args, *(kw.value for kw in keywords)])
            )
        case _:
            found = False

    return found


def build_helper(
    source: Source, func: ast.FunctionDef | ast.AsyncFunctionDef, min_size: int
) -> Helper | None:
    body = get_body(func)
    params = get_params(func)
    match body:
        case [ast.Return(value=ast.expr() as value)]:
            is_expr, setup = True, []
        case [*setup, ast.Return(value=ast.Name(id=name))] if name in get_bound(
            setup
        ) and not has_return(setup):
            is_expr, value = False, None
        case _:
            is_expr, value, setup = False, None, body

    is_stmts = 0 < len(setup) <= MAX_STATEMENTS and not has_return(setup)
    pattern: tuple[Node, ...] = ()

    if value is not None:
        pattern = () if is_forwarding(value, params) else (value,)
    elif is_stmts and not all(isinstance(s, (ast.Pass, ast.Expr)) for s in setup):
        pattern = tuple(setup)

    indexed = (
        pattern
        and not is_stub(func)
        and not is_contract(func)
        and not is_passthrough(body)
        and not (len(pattern) == 1 and isinstance(pattern[0], ast.Name))
        and get_size(pattern, params) >= min_size
    )
    return (
        Helper(func.name, source, func, params, get_bound(body), pattern, is_expr)
        if indexed
        else None
    )


def gen_helpers(
    sources: list[Source], min_size: int, include_tests: bool = False
) -> Iterator[Helper]:
    roots = ("riko", "tests") if include_tests else ("riko",)

    for source in sources:
        if source.module.partition(".")[0] in roots:
            for stmt in source.tree.body:
                if isinstance(
                    stmt, (ast.FunctionDef, ast.AsyncFunctionDef)
                ) and not is_test_only(stmt):
                    helper = build_helper(source, stmt, min_size)

                    if helper is not None:
                        yield helper


def get_scope_locals(tree: ast.Module) -> dict[int, frozenset[str]]:
    """Gets, per node id, the local names of the function enclosing it."""
    scopes: dict[int, frozenset[str]] = {}

    def visit(node: ast.AST, names: frozenset[str]) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            body = node.body if isinstance(node.body, list) else [node.body]
            params = {
                arg.arg for arg in ast.walk(node.args) if isinstance(arg, ast.arg)
            }
            names = names | params | get_bound(body)

        scopes[id(node)] = names

        for child in ast.iter_child_nodes(node):
            visit(child, names)

    visit(tree, frozenset())
    return scopes


class Matcher:
    """Matches one helper's pattern against site nodes of one source."""

    def __init__(self, helper: Helper, site: Source, scopes: dict[int, frozenset[str]]):
        self.helper = helper
        self.site = site
        self.scopes = scopes
        self.wild = {name: f"?{i}" for i, name in enumerate(helper.params)}

    def get_origin(self, name: str, origins: dict[str, str]) -> str:
        return origins.get(name) or (f"builtins.{name}" if name in BUILTINS else name)

    def match_name(self, pat: ast.Name, node: ast.AST, env: Env) -> bool:
        if pat.id in self.wild:
            key = self.wild[pat.id]
            matched = isinstance(node, ast.expr) and (
                env.setdefault(key, ast.unparse(node)) == ast.unparse(node)
            )
        elif pat.id in self.helper.bound:
            matched = isinstance(node, ast.Name) and self.bind(pat.id, node.id, env)
        else:
            local = isinstance(node, ast.Name) and node.id in self.scopes.get(
                id(node), frozenset()
            )
            matched = (
                isinstance(node, ast.Name)
                and node.id == pat.id
                and not local
                and self.get_origin(pat.id, self.helper.source.origins)
                == self.get_origin(node.id, self.site.origins)
            )

        return matched

    def bind(self, pat: str, name: str, env: Env) -> bool:
        key = f"@{pat}"
        taken = {v for k, v in env.items() if k.startswith("@") and k != key}
        return name not in taken and env.setdefault(key, name) == name

    def match(self, pat: ast.AST, node: ast.AST, env: Env) -> bool:
        if isinstance(pat, ast.Name):
            matched = self.match_name(pat, node, env)
        elif isinstance(pat, ast.arg) and pat.arg in self.helper.bound:
            matched = isinstance(node, ast.arg) and self.bind(pat.arg, node.arg, env)
        elif type(pat) is not type(node):
            matched = False
        else:
            matched = all(
                self.match_field(getattr(pat, field), getattr(node, field, None), env)
                for field in pat._fields
                if field not in _SKIP_FIELDS
            )

        return matched

    def match_field(self, pat: object, node: object, env: Env) -> bool:
        if isinstance(pat, list) and isinstance(node, list):
            matched = len(pat) == len(node) and all(
                self.match_field(p, n, env) for p, n in zip(pat, node, strict=True)
            )
        elif isinstance(pat, ast.AST) and isinstance(node, ast.AST):
            matched = self.match(pat, node, env)
        else:
            matched = pat == node

        return matched

    def match_run(self, nodes: Sequence[Node]) -> Env | None:
        env: Env = {}
        pattern = self.helper.pattern
        matched = len(nodes) == len(pattern) and all(
            self.match(pat, node, env) for pat, node in zip(pattern, nodes, strict=True)
        )
        return env if matched else None


def get_head(node: ast.AST, params: tuple[str, ...] = ()) -> str | None:
    """Gets the fixed callee name a call starts with; ``None`` matches any head."""
    match node:
        case ast.Call(func=ast.Name(id=name)) if name not in params:
            head = name
        case ast.Call(func=ast.Attribute(attr=name)):
            head = f".{name}"
        case ast.Expr(value=value) | ast.Assign(value=value) | ast.Return(value=value):
            head = None if value is None else get_head(value, params)
        case _:
            head = None

    return head


def gen_blocks(tree: ast.AST) -> Iterator[list[ast.stmt]]:
    for node in ast.walk(tree):
        for field in ("body", "orelse", "finalbody"):
            block = getattr(node, field, None)

            if isinstance(block, list) and block and isinstance(block[0], ast.stmt):
                yield block


def get_ok_names(source: Source, start: int, end: int) -> set[str] | None:
    names: set[str] | None = None

    for text in source.lines[start - 1 : end]:
        found = _OK.search(text)

        if found is not None:
            listed = {n.strip() for n in (found.group(1) or "").split(",") if n.strip()}
            names = (names or set()) | (listed or {"*"})

    return names


def get_whole_bodies(helpers: list[Helper]) -> Bodies:
    """Gets each helper's name and color keyed by its pattern nodes' identities."""
    return {
        tuple(map(id, helper.pattern)): (helper.name, helper.is_async)
        for helper in helpers
    }


def gen_matches(
    helpers: list[Helper],
    sources: list[Source],
    lines: dict[Path, set[int]] | None,
    bodies: Bodies,
) -> Iterator[Match]:
    by_key: dict[tuple[int, type, str | None], list[Helper]] = defaultdict(list)

    for helper in helpers:
        root = helper.pattern[0]
        head = get_head(root, helper.params)
        size = 0 if helper.is_expr else len(helper.pattern)
        by_key[(size, type(root), head)].append(helper)

    for site in sources:
        wanted = None if lines is None else lines.get(site.path)

        if lines is not None and not wanted:
            continue

        scopes = get_scope_locals(site.tree)
        runs: list[tuple[bool, Sequence[Node]]] = [
            (True, [node]) for node in ast.walk(site.tree) if isinstance(node, ast.expr)
        ]
        runs.extend(
            (False, block[i : i + size])
            for block in gen_blocks(site.tree)
            for size in range(1, MAX_STATEMENTS + 1)
            for i in range(len(block) - size + 1)
        )

        for is_expr, nodes in runs:
            start = nodes[0].lineno
            end = nodes[-1].end_lineno or start

            if wanted is not None and not wanted.intersection(range(start, end + 1)):
                continue

            size = 0 if is_expr else len(nodes)
            kind, head = type(nodes[0]), get_head(nodes[0])
            candidates = by_key.get((size, kind, None), [])

            if head is not None:
                candidates = [*candidates, *by_key.get((size, kind, head), [])]

            for helper in candidates:
                match = check_site(helper, site, nodes, scopes, bodies, (start, end))

                if match is not None:
                    yield match


def check_site(
    helper: Helper,
    site: Source,
    nodes: Sequence[Node],
    scopes: dict[int, frozenset[str]],
    bodies: Bodies,
    span: tuple[int, int],
) -> Match | None:
    start, end = span
    own = site.path == helper.source.path and start in helper.span
    env = None if own else Matcher(helper, site, scopes).match_run(nodes)
    env = env if env is not None and is_reachable(site, helper) else None
    ok = None if env is None else get_ok_names(site, start, end)
    found = None

    if env is not None and not (ok and ({"*", helper.name} & ok)):
        tags = []
        other, is_async = bodies.get(tuple(map(id, nodes)), (None, False))

        if other is not None and other != helper.name:
            kind = "color twin" if is_async != helper.is_async else "duplicate helper"
            tags.append(f"{kind} {other}")

        if helper.is_literal:
            tags.append("shared literal: name a constant")

        if helper.name.startswith("_") and site.path != helper.source.path:
            tags.append("private: promote?")

        bindings = tuple(f"{k}={v}" for k, v in sorted(env.items()) if k[0] == "?")
        found = Match(helper, site, start, end, bindings, tuple(tags))

    return found


class Shaper:
    """Builds and caches the values shape and size of each node in one tree."""

    def __init__(self) -> None:
        self.texts: dict[int, str] = {}
        self.sizes: dict[int, int] = {}

    def get_text(self, node: object) -> str:
        if isinstance(node, list):
            text = f"[{','.join(self.get_text(n) for n in node)}]"
        elif isinstance(node, ast.AST):
            text = self.get_node_text(node)
        else:
            text = repr(node)

        return text

    def get_key(self, key: ast.expr | None) -> str:
        if key is None:
            text = "**"
        elif isinstance(key, ast.Constant):
            text = repr(key.value)
        else:
            text = self.get_text(key)

        return text

    def get_node_text(self, node: ast.AST) -> str:
        text = self.texts.get(id(node))

        if text is None:
            match node:
                case ast.Constant(value=value):
                    text = f"<{type(value).__name__}>"
                case ast.JoinedStr():
                    text = "<fstr>"
                case ast.Dict(keys=keys, values=values):
                    pairs = zip(keys, values, strict=True)
                    entries = (
                        f"{self.get_key(k)}:{self.get_text(v)}" for k, v in pairs
                    )
                    text = f"{{{','.join(entries)}}}"
                case _:
                    fields = (
                        self.get_text(getattr(node, field, None))
                        for field in node._fields
                        if field not in _SKIP_FIELDS
                    )
                    text = f"{type(node).__name__}({','.join(fields)})"

            self.texts[id(node)] = text

        return text

    def get_size(self, node: ast.AST) -> int:
        size = self.sizes.get(id(node))

        if size is None and isinstance(node, ast.JoinedStr):
            size = 1
        elif size is None:
            children = ast.iter_child_nodes(node)
            size = 1 + sum(
                self.get_size(child)
                for child in children
                if not isinstance(child, (ast.expr_context, ast.operator, ast.cmpop))
            )
            self.sizes[id(node)] = size

        return size

    def get_shape(self, node: Shaped) -> Shape:
        """Gets a node's head and its ``key=value-shape`` entries, in order."""
        match node:
            case ast.Dict(keys=keys, values=values):
                head = "dict"
                pairs = list(zip(map(self.get_key, keys), values, strict=True))
            case ast.Call(func=func, args=args, keywords=keywords):
                head = f"{self.get_text(func)}({self.get_text(args)})"
                pairs = [(kw.arg or "**", kw.value) for kw in keywords]
            case _:
                head, pairs = self.get_text(node), []

        return head, tuple(f"{key}={self.get_text(value)}" for key, value in pairs)


class Member(NamedTuple):
    """One shape candidate: its node, shape, container, and enclosing members."""

    source: Source
    node: Shaped
    shape: Shape
    size: int
    container: int | None
    ancestors: frozenset[int]

    @property
    def where(self) -> str:
        return f"{self.source.path.relative_to(ROOT)}:{self.node.lineno}"

    @property
    def end(self) -> int:
        return self.node.end_lineno or self.node.lineno

    @property
    def root(self) -> str:
        return self.source.module.partition(".")[0]

    @property
    def labels(self) -> frozenset[str]:
        return frozenset(entry.partition("=")[0] for entry in self.shape[1])


class Cluster(NamedTuple):
    """Members whose values shapes are equal or linked at the keys level."""

    members: tuple[Member, ...]

    @property
    def shapes(self) -> Counter[Shape]:
        return Counter(member.shape for member in self.members)

    @property
    def is_keys(self) -> bool:
        return len(self.shapes) > 1

    @property
    def size(self) -> int:
        return max(member.size for member in self.members)

    @property
    def ids(self) -> frozenset[int]:
        return frozenset(id(member.node) for member in self.members)

    @property
    def is_table(self) -> bool:
        containers = {member.container for member in self.members}
        return len(containers) == 1 and None not in containers

    @property
    def roots(self) -> frozenset[str]:
        return frozenset(member.root for member in self.members)


class Spans(NamedTuple):
    """The roots a cluster must span: required, allowed, and whether mixed."""

    spec: str
    required: frozenset[str]
    allowed: frozenset[str]
    mixed: bool

    @classmethod
    def parse(cls, spec: str) -> Spans:
        terms = [term.strip() for term in spec.split(",") if term.strip()]
        known = {*SITE_ROOTS, *TEST_ROOTS}
        allowed = {t.removeprefix("only:") for t in terms if t.startswith("only:")}
        required = {t for t in terms if t != "mixed" and not t.startswith("only:")}
        unknown = sorted((allowed | required) - known)

        if not terms or unknown:
            choices = ", ".join(sorted(known))
            message = f"unknown roots {unknown} (choose from {choices})"
            raise argparse.ArgumentTypeError(message if unknown else "empty spec")

        return cls(spec, frozenset(required), frozenset(allowed), "mixed" in terms)

    def is_spanned(self, cluster: Cluster) -> bool:
        roots = cluster.roots
        return (
            self.required <= roots
            and (not self.allowed or roots <= self.allowed)
            and (not self.mixed or len(roots) > 1)
        )


class Abstractor(ast.NodeTransformer):
    """Replaces constants (dict keys aside) and f-strings with type placeholders."""

    def visit_Constant(self, node: ast.Constant) -> ast.expr:
        return ast.Name(id=f"<{type(node.value).__name__}>")

    def visit_JoinedStr(self, node: ast.JoinedStr) -> ast.expr:
        return ast.Name(id="<fstr>")

    def visit_Dict(self, node: ast.Dict) -> ast.expr:
        node.values = [self.visit(value) for value in node.values]
        return node


def is_plain(node: ast.AST) -> bool:
    """Checks for a constant or a collection of constants, data rather than a build."""
    match node:
        case ast.Constant():
            found = True
        case ast.List(elts=elts) | ast.Tuple(elts=elts) | ast.Set(elts=elts):
            found = all(isinstance(elt, ast.Constant) for elt in elts)
        case ast.Call(args=args, keywords=[]):
            found = all(map(is_plain, args))
        case _:
            found = False

    return found


def is_candidate(node: ast.AST, shaper: Shaper, min_size: int) -> bool:
    match node:
        case ast.Call(args=args, keywords=keywords):
            entries = len(args) + len(keywords)
            least = 1
        case ast.Dict(keys=keys):
            entries, least = len(keys), 2
        case ast.List(elts=elts) | ast.Tuple(elts=elts) | ast.Set(elts=elts):
            entries, least = len(elts), 2
        case _:
            entries, least = 0, 1

    is_load = not isinstance(getattr(node, "ctx", None), (ast.Store, ast.Del))
    return (
        is_load
        and not is_plain(node)
        and entries >= least
        and shaper.get_size(node) >= min_size
        and any(isinstance(n, (ast.Constant, ast.JoinedStr)) for n in ast.walk(node))
    )


def is_idiom(node: ast.AST, idioms: frozenset[str]) -> bool:
    """Checks for a call to a listed callee: a dotted name, or an undotted leaf."""
    match node:
        case ast.Call(func=ast.Name(id=name) | ast.Attribute(attr=name) as func):
            found = name in idioms or ast.unparse(func) in idioms
        case _:
            found = False

    return found


def gen_shape_children(node: ast.AST) -> Iterator[ast.AST]:
    match node:
        case ast.arg(annotation=skipped) | ast.AnnAssign(annotation=skipped):
            pass
        case ast.FunctionDef(returns=skipped) | ast.AsyncFunctionDef(returns=skipped):
            pass
        case ast.Subscript(slice=skipped) | ast.TypeAlias(value=skipped):
            pass
        case _:
            skipped = None

    yield from (child for child in ast.iter_child_nodes(node) if child is not skipped)


def gen_members(
    source: Source, min_size: int, idioms: frozenset[str] = IDIOM_CALLEES
) -> Iterator[Member]:
    shaper = Shaper()
    pending: list[tuple[ast.AST, int | None, frozenset[int]]] = [
        (source.tree, None, frozenset())
    ]

    while pending:
        node, container, ancestors = pending.pop()

        if (
            isinstance(node, SHAPED)
            and is_candidate(node, shaper, min_size)
            and not is_idiom(node, idioms)
        ):
            shape, size = shaper.get_shape(node), shaper.get_size(node)
            yield Member(source, node, shape, size, container, ancestors)
            ancestors |= {id(node)}

        inner = id(node) if isinstance(node, CONTAINERS) else None
        pending.extend((child, inner, ancestors) for child in gen_shape_children(node))


def link_shapes(shapes: list[Shape]) -> list[list[Shape]]:
    """Groups shapes one added, removed, or re-keyed entry apart."""
    by_key: dict[Shape, list[tuple[int, str | None]]] = defaultdict(list)
    edges: list[tuple[int, int]] = []

    for index, (head, entries) in enumerate(shapes):
        ordered = tuple(sorted(entries))
        by_key[head, ordered].append((index, None))

        if len(ordered) > 1:
            for skip, entry in enumerate(ordered):
                label = entry.partition("=")[0]
                variant = ordered[:skip] + ordered[skip + 1 :]
                by_key[head, variant].append((index, label))

    for bucket in by_key.values():
        labels = {label for _, label in bucket}

        if None in labels or len(labels) > 1:
            first, *rest = (index for index, _ in bucket)
            edges.extend((first, index) for index in rest)

    components = gen_components(edges, range(len(shapes)))
    return [[shapes[index] for index in sorted(group)] for group in components]


def is_shape_ok(member: Member) -> bool:
    return get_ok_names(member.source, member.node.lineno, member.end) is not None


def get_place(member: Member) -> tuple[str, int, int]:
    return str(member.source.path), member.node.lineno, member.node.col_offset


def build_clusters(
    members: list[Member], min_count: int
) -> tuple[list[Cluster], Counter[str]]:
    """Builds the reported clusters and counts the skipped tables and nested ones."""
    by_shape: dict[Shape, list[Member]] = defaultdict(list)

    for member in members:
        by_shape[member.shape].append(member)

    groups = link_shapes(list(by_shape))
    found = [
        Cluster(tuple(sorted((m for s in group for m in by_shape[s]), key=get_place)))
        for group in groups
    ]
    outers: list[Cluster] = []
    skipped: Counter[str] = Counter()

    for cluster in sorted(found, key=lambda c: -c.size):
        if len(cluster.members) < min_count:
            continue

        if any(
            all(member.ancestors & outer.ids for member in cluster.members)
            for outer in outers
        ):
            skipped["nested"] += 1
        else:
            outers.append(cluster)
            skipped["table"] += cluster.is_table

    return [cluster for cluster in outers if not cluster.is_table], skipped


def format_value(value: object) -> str:
    text = value if isinstance(value, str) and _PLAIN.fullmatch(value) else repr(value)
    return text if len(text) <= 24 else f"{text[:23]}…"


def join_slot(path: str, label: str) -> str:
    return f"{path}{label}" if label.startswith("[") or not path else f"{path}.{label}"


def get_slot_label(key: ast.expr | None) -> str:
    if key is None:
        label = "**"
    elif isinstance(key, ast.Constant):
        label = str(key.value)
    else:
        label = ast.unparse(key)

    return label


def get_slot_children(node: ast.AST) -> list[tuple[str | None, ast.AST]]:
    match node:
        case ast.Dict(keys=keys, values=values):
            children = list(zip(map(get_slot_label, keys), values, strict=True))
        case ast.Call(args=args, keywords=keywords):
            children = [(f"[{i}]", arg) for i, arg in enumerate(args)]
            children.extend((kw.arg or "**", kw.value) for kw in keywords)
        case ast.List(elts=elts) | ast.Tuple(elts=elts) | ast.Set(elts=elts):
            children = [(f"[{i}]", elt) for i, elt in enumerate(elts)]
        case _:
            children = [(None, child) for child in ast.iter_child_nodes(node)]

    return children


def gen_slots(node: ast.AST, path: str) -> Iterator[tuple[str, str]]:
    match node:
        case ast.Constant(value=value):
            yield path or "value", format_value(value)
        case ast.JoinedStr():
            yield path or "value", format_value(ast.unparse(node))
        case _:
            for label, child in get_slot_children(node):
                inner = path if label is None else join_slot(path, label)
                yield from gen_slots(child, inner)


def get_slot_values(cluster: Cluster) -> dict[str, Counter[str]]:
    values: dict[str, Counter[str]] = {}

    for member in cluster.members:
        seen: Counter[str] = Counter()

        for path, value in gen_slots(member.node, ""):
            seen[path] += 1
            key = path if seen[path] == 1 else f"{path}~{seen[path]}"
            values.setdefault(key, Counter())[value] += 1

    return values


def get_slot_summary(cluster: Cluster) -> str:
    total = len(cluster.members)
    slots = get_slot_values(cluster).items()
    varying = [(p, c) for p, c in slots if len(c) > 1 or c.total() < total]
    varying.sort(key=lambda slot: -slot[1].total())
    parts = []

    for path, counter in varying[:MAX_SLOTS]:
        absent = total - counter.total()
        common = counter.most_common(MAX_VALUES)
        shown = [f"{value}×{count}" for value, count in common]
        rest = len(counter) - len(common)
        shown.extend([f"(+{rest} more)"] if rest else [])
        shown.extend([f"absent×{absent}"] if absent else [])
        parts.append(f"{path}: {', '.join(shown)}")

    extra = len(varying) - MAX_SLOTS
    parts.extend([f"(+{extra} more slots)"] if extra > 0 else [])
    return "; ".join(parts) or "none vary"


def get_extra_entry(label: str, is_dict: bool) -> str:
    if label == "**":
        text = "**…"
    elif is_dict:
        text = f"{label}: …"
    else:
        text = "…" if label.startswith("[") else f"{label}=…"

    return f"[{text}]"


def get_skeleton(cluster: Cluster) -> str:
    """Gets a cluster's most common member with placeholders; ``[...]`` is optional."""
    shape = cluster.shapes.most_common(1)[0][0]
    node = next(m.node for m in cluster.members if m.shape == shape)
    total = len(cluster.members)
    presence = Counter(label for m in cluster.members for label in m.labels)
    optional = {label for label, count in presence.items() if count < total}
    own = {entry.partition("=")[0] for entry in shape[1]}
    abstracted = Abstractor().visit(copy.deepcopy(node))

    match abstracted:
        case ast.Dict(keys=keys, values=values):
            parts = [
                (
                    "**" if k is None else Shaper().get_key(k),
                    f"**{ast.unparse(v)}"
                    if k is None
                    else f"{ast.unparse(k)}: {ast.unparse(v)}",
                )
                for k, v in zip(keys, values, strict=True)
            ]
            opener, closer, is_dict = "{", "}", True
        case ast.Call(func=func, args=args, keywords=keywords):
            parts = [(f"[{i}]", ast.unparse(arg)) for i, arg in enumerate(args)]
            parts.extend((kw.arg or "**", ast.unparse(kw)) for kw in keywords)
            opener, closer, is_dict = f"{ast.unparse(func)}(", ")", False
        case _:
            parts, opener, closer, is_dict = [], ast.unparse(abstracted), "", False

    texts = [f"[{text}]" if label in optional else text for label, text in parts]
    texts.extend(
        get_extra_entry(label, is_dict) for label in sorted(optional - own) if parts
    )
    text = f"{opener}{', '.join(texts)}{closer}"
    return text if len(text) <= MAX_WIDTH else f"{text[: MAX_WIDTH - 1]}…"


def touches(cluster: Cluster, lines: dict[Path, set[int]]) -> bool:
    return any(
        lines.get(m.source.path, set()) & set(range(m.node.lineno, m.end + 1))
        for m in cluster.members
    )


def get_roots(args: argparse.Namespace) -> tuple[str, ...]:
    return tuple(args.roots) or (*SITE_ROOTS, *(TEST_ROOTS if args.tests else ()))


def scan_shapes(args: argparse.Namespace) -> list[Cluster]:
    sources = [
        s for s in map(load_source, gen_paths(*get_roots(args))) if s is not None
    ]
    idioms = frozenset() if args.all_callees else IDIOM_CALLEES
    candidates = [
        m for s in sources for m in gen_members(s, args.shape_min_size, idioms)
    ]
    members = [m for m in candidates if not is_shape_ok(m)]
    clusters, skipped = build_clusters(members, args.min_count)
    keys = sum(cluster.is_keys for cluster in clusters)
    summary = (
        f"shape candidates: {len(candidates)}; reuse-ok: "
        f"{len(candidates) - len(members)}; clusters: {len(clusters)} "
        f"(values {len(clusters) - keys}, keys {keys}); members: "
        f"{sum(len(c.members) for c in clusters)}; skipped nested: "
        f"{skipped['nested']}, tables: {skipped['table']}"
    )

    if not args.all:
        lines = resolve_diff(args)
        clusters = [cluster for cluster in clusters if touches(cluster, lines)]
        summary += f"; touching the diff: {len(clusters)}"

    if args.spans is not None:
        clusters = [c for c in clusters if args.spans.is_spanned(c)]
        summary += f"; spanning {args.spans.spec}: {len(clusters)}"

    print(summary, file=sys.stderr)
    return clusters


def report_shapes(clusters: list[Cluster]) -> None:
    order = sorted(clusters, key=lambda c: (-len(c.members), get_skeleton(c)))

    for cluster in order:
        members = cluster.members
        variants = Counter(ast.unparse(m.node) for m in members)
        exact, count = variants.most_common(1)[0]
        exact = exact if len(exact) <= MAX_WIDTH else f"{exact[: MAX_WIDTH - 1]}…"
        level = f"keys, {len(cluster.shapes)} shapes" if cluster.is_keys else "values"
        roots = Counter(m.root for m in members)
        files = len({m.source.path for m in members})
        spread = ", ".join(f"{root}×{n}" for root, n in roots.most_common())
        print(f"## {get_skeleton(cluster)}: {len(members)} members ({level})")
        print(f"variants: {len(variants)}; most common ×{count}: {exact}")
        print(f"slots: {get_slot_summary(cluster)}")
        print(f"spans: {spread}; files: {files}")
        print(*(m.where for m in members[:MAX_SAMPLES]), sep="\n")


def resolve_diff(args: argparse.Namespace) -> dict[Path, set[int]]:
    if args.diff_file is not None:
        lines = changed_lines(load_diff(args.diff_file))
    elif args.staged:
        lines = changed_lines(git("diff", "--cached", "-U0"))
    else:
        diff = git("diff", "-U0", f"{args.since}...HEAD") if args.since else ""
        lines = changed_lines(diff + git("diff", "-U0", "HEAD"))

        for name in git("ls-files", "--others", "--exclude-standard").splitlines():
            lines[ROOT / name] = set(range(1, 1_000_000))

    return lines


def scan(args: argparse.Namespace) -> list[Match]:
    sources = [
        s for s in map(load_source, gen_paths(*get_roots(args))) if s is not None
    ]
    helpers = [
        helper
        for helper in gen_helpers(sources, args.min_size, args.tests)
        if not args.helper or helper.name in args.helper
    ]
    bodies = get_whole_bodies(helpers)

    if args.all:
        matches = list(gen_matches(helpers, sources, None, bodies))
        print(f"helpers indexed: {len(helpers)}", file=sys.stderr)
    else:
        lines = resolve_diff(args)
        changed = [h for h in helpers if lines.get(h.source.path, set()) & set(h.span)]
        new_code = list(gen_matches(helpers, sources, lines, bodies))
        new_helper = list(gen_matches(changed, sources, None, bodies))
        seen = {m.key for m in new_code}
        matches = new_code + [m for m in new_helper if m.key not in seen]
        print(
            f"helpers indexed: {len(helpers)}; changed: {len(changed)}; "
            f"new-code matches: {len(new_code)}; "
            f"new-helper matches: {len(matches) - len(new_code)}",
            file=sys.stderr,
        )

    return matches


def report(matches: list[Match], counts_only: bool) -> None:
    grouped: dict[str, list[Match]] = defaultdict(list)
    matches = list({m.key: m for m in matches}.values())

    for match in matches:
        grouped[match.helper.where].append(match)

    order = sorted(grouped, key=lambda where: (-len(grouped[where]), where))

    for where in order:
        group = sorted(grouped[where], key=lambda m: (str(m.source.path), m.line))
        helper = group[0].helper
        print(f"## {helper.name} ({where}): {len(group)} matches")

        if not counts_only:
            for m in group:
                path = m.source.path.relative_to(ROOT)
                tags = f" [{'; '.join(m.tags)}]" if m.tags else ""
                text = m.source.lines[m.line - 1].strip()[:90]
                print(
                    f"{path}:{m.line}: could use {helper.name}"
                    f"({', '.join(m.bindings)}){tags} | {text}"
                )

    tags = Counter(tag.partition(" ")[0] for m in matches for tag in m.tags)
    print(
        f"matches: {len(matches)} across {len(grouped)} helpers; tags: {dict(tags)}",
        file=sys.stderr,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(__doc__ or "").split("\n\n")[0].strip(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--all", action="store_true")
    group.add_argument("--staged", action="store_true")
    group.add_argument("--since")
    group.add_argument("--diff-file")
    parser.add_argument("--tests", action="store_true")
    parser.add_argument("--min-size", type=int, default=MIN_SIZE)
    parser.add_argument("--helper", action="append", default=[])
    parser.add_argument("--counts", action="store_true")
    parser.add_argument("--shapes", action="store_true")
    parser.add_argument("--shape-min-size", type=int, default=SHAPE_MIN_SIZE)
    parser.add_argument("--min-count", type=int, default=MIN_COUNT)
    parser.add_argument("--all-callees", action="store_true")
    parser.add_argument("--spans", type=Spans.parse)
    parser.add_argument("roots", nargs="*", choices=(*SITE_ROOTS, *TEST_ROOTS))
    args = parser.parse_args(argv)

    if args.spans is not None and not args.shapes:
        parser.error("--spans needs --shapes")

    if args.shapes:
        clusters = scan_shapes(args)
        report_shapes(clusters)
        found = bool(clusters)
    else:
        matches = scan(args)
        report(matches, args.counts)
        found = bool(matches)

    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
