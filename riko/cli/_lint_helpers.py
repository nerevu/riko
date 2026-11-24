# vim: sw=4:ts=4:expandtab

"""
Counts the package's single-use helpers.

A private helper called from exactly one function (and imported by no other module) is
*called once*. It is a **single-use helper** when it is called once and is itself the
only caller of another called-once helper. E.g., ``_parse`` is the single-use helper in
``run -> _parse -> _split``. A single-use helper adds a hop a reader must follow without
being reused anywhere. Their count has a ceiling recorded in ``pyproject.toml`` under
``[tool.riko.helpers]`` that only ever ratchets down.

A reference is any use of the function's name inside another function (as a call
or as a value). Methods are told apart by their class. ``self.name`` or ``cls.name``
resolves to the enclosing class's method or one it inherits from a class in the same
module.

A helper is never called once when an unresolved ``obj.name`` or a string in its own
module could refer to it (any same-named function counts), when it is used at module or
class-body level, when another module imports it, or, for a method, when a subclass in
another module defines it or uses it on ``self``/``cls``. A subclass is any class whose
bases (``Base``, ``mod.Base``, or ``Base[T]``) reach the method's class through a chain
of scanned classes. A same-named attribute, string, or method of an unrelated class in
another module does not count.

``KEPT_HELPERS`` lists the helpers that stay by ruling (one that handles errors, is
passed by reference, is a ``cached_property``, recurses, closes a generator per item, or
mirrors a sync/async twin). A kept helper is not counted, and a kept entry that is no
longer a single-use helper is reported as stale so the list cannot rot.
"""

from __future__ import annotations

import ast
from collections import Counter, defaultdict
from itertools import chain, starmap
from typing import TYPE_CHECKING, NamedTuple

from riko.base._iterutils import sort_stably

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping
    from pathlib import Path

_MODULE = "<module>"
_UNKNOWN = "<unknown>"
_SELF_NAMES = frozenset({"self", "cls"})

KEPT_HELPERS: frozenset[tuple[str, str]] = frozenset(
    {
        ("riko/bado/itertools.py", "AsyncTee._aadvance"),
        ("riko/base/_iterutils.py", "Tee._advance"),
        ("riko/execution/_async_execution.py", "AsyncExecution._aacquire_entry"),
        ("riko/execution/_async_execution.py", "AsyncExecution._abuild_node_ports"),
        ("riko/execution/_async_execution.py", "AsyncExecution._abuild_splitter_ports"),
        ("riko/execution/_async_execution.py", "AsyncExecution._acquire_entry_once"),
        ("riko/execution/_provenance.py", "_TableProvenance._forget"),
        ("riko/execution/_sync_execution.py", "SyncExecution._acquire_entry"),
        ("riko/execution/_sync_execution.py", "SyncExecution._build_node_ports"),
        ("riko/execution/_sync_execution.py", "SyncExecution._build_splitter_ports"),
    }
)


def _is_private(name: str) -> bool:
    return name.startswith("_") and not name.startswith("__")


class _Scope(NamedTuple):
    """A function or class body: ``owner`` is the class ``self`` belongs to."""

    key: str
    function: bool
    owner: str | None


class _Ref(NamedTuple):
    """
    One use of a private name before it is resolved to a function.

    A bare name searches ``chain``, the enclosing functions, before the module. An
    attribute resolves through ``owner``'s classes, or is unknown without one.
    """

    caller: str
    name: str
    chain: tuple[str, ...]
    owner: str | None
    attribute: bool


class _Chain(NamedTuple):
    """One ``caller -> helper -> callee`` chain at the callee's definition."""

    path: Path
    line: int
    caller: str
    helper: str
    callee: str

    def __str__(self) -> str:
        """Renders the chain as a ``path:line: A -> B -> C`` line."""
        chain = f"{self.caller} -> {self.helper} -> {self.callee}"
        return f"{self.path}:{self.line}: {chain}"


def _get_base_name(base: ast.expr) -> str | None:
    """Gets a base class's bare name from ``Base``, ``mod.Base``, or ``Base[T]``."""
    target = base.value if isinstance(base, ast.Subscript) else base

    if isinstance(target, ast.Name):
        name = target.id
    elif isinstance(target, ast.Attribute):
        name = target.attr
    else:
        name = None

    return name


def _gen_lineage(key: str, bases: Mapping[str, tuple[str, ...]]) -> Iterator[str]:
    """Walks ``key`` and each same-module class it inherits from."""
    pending, seen = [key], set[str]()

    while pending:
        if (current := pending.pop(0)) in bases and current not in seen:
            seen.add(current)
            yield current
            pending.extend(bases[current])


class _ScopeVisitor(ast.NodeVisitor):
    """Collects one module's functions, class bases, and private-name uses."""

    def __init__(self) -> None:
        self.defs: dict[str, int] = {}
        self.bases: dict[str, tuple[str, ...]] = {}
        self.refs: list[_Ref] = []
        self.imported_names: set[str] = set()
        self.methods: set[str] = set()
        self.parents: dict[str, tuple[str, ...]] = {}
        self.self_uses: set[tuple[str, str]] = set()
        self.scopes: list[_Scope] = []

    def _qualify(self, name: str) -> str:
        return f"{self.scopes[-1].key}.{name}" if self.scopes else name

    def _add_ref(self, name: str, owner: str | None, attribute: bool) -> None:
        """Records a use of ``name`` by the innermost scope if ``name`` is private."""
        if _is_private(name):
            caller = self.scopes[-1].key if self.scopes else _MODULE
            chain = tuple(scope.key for scope in self.scopes if scope.function)
            self.refs.append(_Ref(caller, name, chain, owner, attribute))

    def _visit_body(self, scope: _Scope, body: list[ast.stmt]) -> None:
        self.scopes.append(scope)

        for statement in body:
            self.visit(statement)

        self.scopes.pop()

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        """Visits a function's decorators and signature in its enclosing scope."""
        for decorator in node.decorator_list:
            self.visit(decorator)

        self.visit(node.args)

        if node.returns is not None:
            self.visit(node.returns)

        key = self._qualify(node.name)
        self.defs.setdefault(key, node.lineno)
        parent = self.scopes[-1] if self.scopes else None

        if parent is None:
            owner = None
        elif parent.function:
            owner = parent.owner
        else:
            owner = parent.key
            self.methods.add(key)

        self._visit_body(_Scope(key, True, owner), node.body)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Records a function and the uses in its body."""
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Records an async function and the uses in its body."""
        self._visit_function(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Records a class's same-module bases and the uses in its body."""
        for expr in [*node.decorator_list, *node.bases, *node.keywords]:
            self.visit(expr)

        key = self._qualify(node.name)
        bases = (base.id for base in node.bases if isinstance(base, ast.Name))
        self.bases[key] = tuple(bases)
        names = map(_get_base_name, node.bases)
        self.parents[key] = tuple(name for name in names if name is not None)
        self._visit_body(_Scope(key, False, None), node.body)

    def visit_Name(self, node: ast.Name) -> None:
        """Records a bare name."""
        self._add_ref(node.id, None, False)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        """Records ``obj.name``, resolving ``self`` and ``cls`` to their class."""
        value = node.value

        if not isinstance(value, ast.Name):
            owner = None
        elif value.id in _SELF_NAMES:
            owner = self.scopes[-1].owner if self.scopes else None

            if owner is not None:
                self.self_uses.add((owner, node.attr))
        else:
            owner = value.id

        self._add_ref(node.attr, owner, True)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """Records the names a module imports, which may be another's helpers."""
        self.imported_names.update(alias.name for alias in node.names)

    def visit_Constant(self, node: ast.Constant) -> None:
        """Records a string naming an identifier, as in ``getattr(obj, "_x")``."""
        if isinstance(node.value, str) and node.value.isidentifier():
            self._add_ref(node.value, None, True)

    def resolve_ref(self, ref: _Ref) -> tuple[tuple[str, str], ...]:
        """
        Resolves a use to each function it may name, paired with its caller.

        A use that resolves names one function. An attribute that does not names every
        same-named function from an unknown caller.
        """
        if ref.attribute:
            lineage = () if ref.owner is None else _gen_lineage(ref.owner, self.bases)
            candidates = (f"{owner}.{ref.name}" for owner in lineage)
        else:
            chains = reversed(ref.chain)
            candidates = chain((f"{key}.{ref.name}" for key in chains), [ref.name])

        found = next((key for key in candidates if key in self.defs), None)
        caller = ref.caller if ref.caller in self.defs else _UNKNOWN
        suffix = f".{ref.name}"

        if found is not None:
            pairs: tuple[tuple[str, str], ...] = ((found, caller),)
        elif ref.attribute:
            keys = (k for k in self.defs if k == ref.name or k.endswith(suffix))
            pairs = tuple((key, _UNKNOWN) for key in keys)
        else:
            pairs = ()

        return pairs


class _ModuleScan(NamedTuple):
    """One module's functions and methods, the callers of each, and its imports."""

    path: Path
    defs: Mapping[str, int]
    callers: Mapping[str, frozenset[str]]
    imported_names: frozenset[str]
    methods: frozenset[str]
    parents: Mapping[str, tuple[str, ...]]
    self_uses: frozenset[tuple[str, str]]

    @classmethod
    def from_source(cls, path: Path, source: str) -> _ModuleScan:
        """Builds one module's scan and skips a function's uses of its own name."""
        visitor = _ScopeVisitor()
        visitor.visit(ast.parse(source))
        callers: defaultdict[str, set[str]] = defaultdict(set)

        for ref in visitor.refs:
            for target, caller in visitor.resolve_ref(ref):
                if target != ref.caller:
                    callers[target].add(caller)

        frozen = {key: frozenset(keys) for key, keys in callers.items()}
        return cls(
            path,
            visitor.defs,
            frozen,
            frozenset(visitor.imported_names),
            frozenset(visitor.methods),
            visitor.parents,
            frozenset(visitor.self_uses),
        )

    @property
    def members(self) -> frozenset[tuple[str, str]]:
        """Each ``(class, name)`` a class defines as a method or uses on ``self``."""
        defined = (key.rsplit(".", 1) for key in self.methods)
        return frozenset((owner, name) for owner, name in defined) | self.self_uses

    def gen_chains(
        self,
        outside: Counter[str],
        overrides: Mapping[tuple[str, str], frozenset[Path]],
    ) -> Iterator[_Chain]:
        """
        Finds this module's chains based on imports and subclasses elsewhere.

        Args:

            outside: The number of modules importing each name.
            overrides: The modules whose subclasses define or call each
                ``(class name, method)`` pair.

        Yields:

            Each chain, ordered by the callee's name.

        """
        single: dict[str, str] = {}

        for key, callers in self.callers.items():
            name = key.rsplit(".", 1)[-1]
            imported = outside[name] > (name in self.imported_names)
            owner = key.rpartition(".")[0].rsplit(".", 1)[-1]
            subclassed = overrides.get((owner, name), frozenset()) - {self.path}
            overridden = key in self.methods and bool(subclassed)
            used_elsewhere = imported or overridden
            (caller, *others) = callers
            is_function = caller in self.defs

            if _is_private(name) and is_function and not (others or used_elsewhere):
                single[key] = caller

        for callee, helper in sorted(single.items()):
            if helper in single:
                line = self.defs[callee]
                yield _Chain(self.path, line, single[helper], helper, callee)


def _build_overrides(
    scans: list[_ModuleScan],
) -> dict[tuple[str, str], frozenset[Path]]:
    """
    Builds the modules whose subclasses define or call each inherited method.

    A class's ancestors are found by bare name across every scanned module, so a
    subclass reaches its base through any chain of scanned classes.
    """
    parents: defaultdict[str, set[str]] = defaultdict(set)

    for scan in scans:
        for key, names in scan.parents.items():
            parents[key.rsplit(".", 1)[-1]].update(names)

    lineage = {name: tuple(names) for name, names in parents.items()}
    found: defaultdict[tuple[str, str], set[Path]] = defaultdict(set)

    for scan in scans:
        for owner, name in scan.members:
            bare = owner.rsplit(".", 1)[-1]
            ancestors = _gen_lineage(bare, lineage)

            for ancestor in ancestors:
                if ancestor != bare:
                    found[ancestor, name].add(scan.path)

    return {pair: frozenset(paths) for pair, paths in found.items()}


class ChainReport(NamedTuple):
    """
    The package's single-use helpers and the chains through them.

    ``chains`` holds every chain; ``keep`` holds the ``(path, helper)`` pairs that stay
    by ruling, which the count and the printed chains skip.

    Examples:

        >>> from pathlib import Path
        >>> source = "def run():\\n    _a()\\ndef _a():\\n    _b()\\ndef _b(): ..."
        >>> report = ChainReport.from_sources({Path("mod.py"): source})
        >>> report.helper_count
        1
        >>> report.issues
        ('mod.py:5: run -> _a -> _b',)

    """

    chains: tuple[_Chain, ...]
    keep: frozenset[tuple[Path, str]] = frozenset()

    @classmethod
    def from_sources(
        cls,
        sources: Mapping[Path, str],
        *,
        keep: frozenset[tuple[Path, str]] = frozenset(),
    ) -> ChainReport:
        """
        Builds the report for modules given as source code.

        A private name another module imports is never called once, nor is a method a
        subclass in another module defines or uses on ``self``.

        Args:

            sources: Each module's source code, keyed by its path.

        Kwargs:

            keep: The ``(path, helper)`` pairs that stay by ruling (default: none).

        Returns:

            The report, with its chains sorted by path and line.

        Examples:

            >>> from pathlib import Path
            >>> helper = "def run():\\n    _a()\\ndef _a():\\n    _b()\\ndef _b(): ..."
            >>> sources = {Path("a.py"): helper, Path("b.py"): "from .a import _b"}
            >>> ChainReport.from_sources(sources).helper_count
            0

        """
        scans = list(starmap(_ModuleScan.from_source, sources.items()))
        outside = Counter(chain.from_iterable(scan.imported_names for scan in scans))
        overrides = _build_overrides(scans)
        chains = chain.from_iterable(
            scan.gen_chains(outside, overrides) for scan in scans
        )
        return cls(sort_stably(chains), keep)

    @classmethod
    def from_roots(
        cls, *roots: Path, keep: frozenset[tuple[Path, str]] = frozenset()
    ) -> ChainReport:
        """
        Builds the report for every module under ``roots``.

        Args:

            roots: The package folders to scan.

        Kwargs:

            keep: The ``(path, helper)`` pairs that stay by ruling (default: none).

        Returns:

            The report, with its chains sorted by path and line.

        Examples:

            >>> from tempfile import TemporaryDirectory
            >>> from pathlib import Path
            >>> with TemporaryDirectory() as tmp:
            ...     _ = (Path(tmp) / "mod.py").write_text("def run(): ...")
            ...     ChainReport.from_roots(Path(tmp)).helper_count
            0

        """
        paths = chain.from_iterable(sorted(root.rglob("*.py")) for root in roots)
        sources = {path: path.read_text(encoding="utf-8") for path in paths}
        return cls.from_sources(sources, keep=keep)

    @property
    def counted(self) -> tuple[_Chain, ...]:
        """The chains through helpers that are not kept."""
        chains = self.chains
        return tuple(c for c in chains if (c.path, c.helper) not in self.keep)

    @property
    def stale(self) -> tuple[str, ...]:
        """Each kept helper that is no longer a single-use helper, as a line."""
        helpers = {(chain.path, chain.helper) for chain in self.chains}
        entries = sorted(self.keep - helpers)
        return tuple(f"{path}: {helper} is kept" for path, helper in entries)

    @property
    def issues(self) -> tuple[str, ...]:
        """Each counted chain as a ``path:line: A -> B -> C`` line."""
        return tuple(str(chain) for chain in self.counted)

    @property
    def helper_count(self) -> int:
        """The number of single-use helpers that are not kept."""
        return len({(chain.path, chain.helper) for chain in self.counted})
