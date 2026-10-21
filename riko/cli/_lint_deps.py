# vim: sw=4:ts=4:expandtab
"""
Checks the dependency rules deptry leaves open: run-time use, guards, and hook pins.

deptry reports missing, unused, and misplaced dependencies (a ``types-*`` stub package
declared in ``[project]`` or an extra is unused, since nothing imports it). But it
counts an import under ``TYPE_CHECKING`` as a use, counts an optional extra as declared
wherever it is imported, and never reads hook configuration.

This module holds every required dependency to an import that runs, every import of an
optional extra to a ``try`` that catches its ``ImportError``, and every pre-commit tool
pin to the version ``uv.lock`` resolves.
"""

from __future__ import annotations

import ast
import re
import tomllib
from importlib.metadata import packages_distributions
from typing import TYPE_CHECKING, NamedTuple

from ._import_graph import is_type_checking

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence
    from pathlib import Path

_REQUIREMENT_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
HOOK_PINNED: tuple[str, ...] = ("ruff",)


class DependencyIssue(NamedTuple):
    """
    A mismatch between riko's imports or hook pins and its declared dependencies.

    Attributes:

        where: The ``path:line`` of the offending import or pin, or the offending file.
        message: What is wrong and what to declare, import, or pin.

    """

    where: str
    message: str

    def __str__(self) -> str:
        """Renders the issue as a ``where message`` line."""
        return f"{self.where} {self.message}"


def normalize_distribution(name: str) -> str:
    """
    Normalizes a distribution name to its comparable form.

    Args:

        name: A distribution name in any accepted spelling.

    Returns:

        The lowercase name with runs of ``-``, ``_``, and ``.`` collapsed to ``-``.

    Examples:

        >>> normalize_distribution("Typing_Extensions")
        'typing-extensions'

    """
    return re.sub(r"[-_.]+", "-", name).lower()


def _get_requirement_name(requirement: str) -> str:
    """Extracts the normalized distribution name from a requirement string."""
    match = _REQUIREMENT_NAME.match(requirement)

    if match is None:
        raise ValueError(f"malformed requirement {requirement!r}")

    return normalize_distribution(match.group(1))


def _is_not_type_checking(test: ast.expr) -> bool:
    """Tells whether a test is exactly ``not TYPE_CHECKING``."""
    match test:
        case ast.UnaryOp(op=ast.Not(), operand=operand):
            is_negated = is_type_checking(operand)
        case _:
            is_negated = False

    return is_negated


_IMPORT_ERRORS = frozenset(
    {"ImportError", "ModuleNotFoundError", "Exception", "BaseException"}
)


def _catches_import_error(handler: ast.ExceptHandler) -> bool:
    """Tells whether an ``except`` clause catches a failed import."""
    match handler.type:
        case None:
            catches = True
        case ast.Name(id=name):
            catches = name in _IMPORT_ERRORS
        case ast.Tuple(elts=elts):
            names = (isinstance(e, ast.Name) and e.id in _IMPORT_ERRORS for e in elts)
            catches = any(names)
        case _:
            catches = False

    return catches


class RuntimeImport(NamedTuple):
    """
    A top-level module imported at run time.

    Attributes:

        name: The imported top-level module name.
        lineno: The import statement's line number.
        guarded: Whether a ``try`` around it catches a failed import.

    """

    name: str
    lineno: int
    guarded: bool


type _ImportNode = ast.Import | ast.ImportFrom


def _gen_import_nodes(
    node: ast.AST, typing_only: bool = False, guarded: bool = False
) -> Iterator[tuple[_ImportNode, bool]]:
    """Walks a tree for the import statements outside typing-only branches."""
    if isinstance(node, ast.Import | ast.ImportFrom):
        if not typing_only:
            yield node, guarded
    elif isinstance(node, ast.If):
        body_only = typing_only or is_type_checking(node.test)
        orelse_only = typing_only or _is_not_type_checking(node.test)

        for child in node.body:
            yield from _gen_import_nodes(child, body_only, guarded)

        for child in node.orelse:
            yield from _gen_import_nodes(child, orelse_only, guarded)
    elif isinstance(node, ast.Try | ast.TryStar):
        body_guarded = guarded or any(map(_catches_import_error, node.handlers))

        for child in [*node.body, *node.orelse]:
            yield from _gen_import_nodes(child, typing_only, body_guarded)

        for child in [*node.handlers, *node.finalbody]:
            yield from _gen_import_nodes(child, typing_only, guarded)
    else:
        for child in ast.iter_child_nodes(node):
            yield from _gen_import_nodes(child, typing_only, guarded)


def gen_runtime_imports(source: str) -> Iterator[RuntimeImport]:
    """
    Walks Python source for the top-level modules it imports at run time.

    An import is typing-only when it sits in the body of an ``if`` whose test is
    exactly ``TYPE_CHECKING`` or ``typing.TYPE_CHECKING``, or in the ``else`` of
    ``if not TYPE_CHECKING``; every other absolute import runs. It is guarded when it
    sits in the body or ``else`` of a ``try`` whose ``except`` catches ``ImportError``.

    Args:

        source: The Python source text.

    Yields:

        Each absolute import's top-level module, in source order.

    Examples:

        >>> source = '''
        ... import a.b
        ... if TYPE_CHECKING:
        ...     import c
        ... try:
        ...     from d import e
        ... except ImportError:
        ...     pass
        ... '''
        >>> [(i.name, i.guarded) for i in gen_runtime_imports(source)]
        [('a', False), ('d', True)]

    """
    for node, guarded in _gen_import_nodes(ast.parse(source)):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        else:
            names = [] if node.level or not node.module else [node.module]

        for name in names:
            yield RuntimeImport(name.split(".")[0], node.lineno, guarded)


def gen_import_issues(
    package_dir: Path,
    pyproject: Path,
    distributions: Mapping[str, Sequence[str]] | None = None,
) -> Iterator[DependencyIssue]:
    """
    Finds run-time imports that break the declared dependencies.

    An import of a distribution that only ``[project.optional-dependencies]``
    declares must be guarded, so riko still imports without the extra; and every
    ``[project]`` dependency must be imported somewhere outside ``TYPE_CHECKING``.
    A module no installed distribution provides is assumed to share its
    distribution's name.

    Args:

        package_dir: The package directory whose imports are checked.

        pyproject: The ``pyproject.toml`` declaring the dependencies.

        distributions: Maps each top-level module name to the providing distributions
            (default: the installed environment's mapping).

    Yields:

        One :class:`DependencyIssue` per unguarded optional import, in path then
        line order, then one per required dependency nothing imports, in name order.

    """
    provided = packages_distributions() if distributions is None else distributions
    project = tomllib.loads(pyproject.read_text(encoding="utf-8")).get("project", {})
    required = set(map(_get_requirement_name, project.get("dependencies", [])))
    extras = {
        _get_requirement_name(entry)
        for group in project.get("optional-dependencies", {}).values()
        for entry in group
    }
    used: set[str] = set()

    for path in sorted(package_dir.rglob("*.py")):
        for runtime in gen_runtime_imports(path.read_text(encoding="utf-8")):
            names = provided.get(runtime.name) or (runtime.name,)
            dists = set(map(normalize_distribution, names))
            used |= dists

            if dists <= extras - required and not runtime.guarded:
                msg = (
                    f"{runtime.name!r} comes from an optional extra; import it in a "
                    "try block that catches ImportError"
                )
                yield DependencyIssue(f"{path}:{runtime.lineno}", msg)

    for name in sorted(required - used):
        msg = (
            f"{name!r} is a [project] dependency that nothing imports at run time; "
            "import it outside TYPE_CHECKING or move it to a dependency group"
        )
        yield DependencyIssue(str(pyproject), msg)


def get_locked_version(lockfile: Path, name: str) -> str:
    """
    Reads the version ``uv.lock`` resolves a distribution to.

    Args:

        lockfile: The ``uv.lock`` file.
        name: The distribution name in any accepted spelling.

    Returns:

        The locked version string.

    Raises:

        LookupError: If the lock has no package of that name.

    """
    packages = tomllib.loads(lockfile.read_text(encoding="utf-8")).get("package", [])
    wanted = normalize_distribution(name)
    versions = [
        package["version"]
        for package in packages
        if normalize_distribution(package["name"]) == wanted
    ]

    if not versions:
        raise LookupError(f"{name!r} is not in {lockfile}")

    return versions[0]


def _get_pin_pattern(name: str) -> re.Pattern[str]:
    """Matches ``name==<version>`` as a whole requirement in hook configuration."""
    return re.compile(rf"(?<![\w.-])({re.escape(name)}==)([^\s,\]'\"]+)")


def build_pinned_config(text: str, versions: Mapping[str, str]) -> str:
    """
    Rewrites each ``name==<version>`` pin in hook configuration to a new version.

    Args:

        text: The pre-commit configuration text.
        versions: The version to pin each named distribution to.

    Returns:

        The configuration text with every matching pin replaced.

    Examples:

        >>> build_pinned_config("deps: [ruff==0.1.0]", {"ruff": "0.2.0"})
        'deps: [ruff==0.2.0]'

    """
    for name, version in versions.items():
        text = _get_pin_pattern(name).sub(rf"\g<1>{version}", text)

    return text


def gen_hook_pin_issues(config: Path, lockfile: Path) -> Iterator[DependencyIssue]:
    """
    Compares the tool pins in a pre-commit configuration against ``uv.lock``.

    Args:

        config: The ``.pre-commit-config.yaml`` file.
        lockfile: The ``uv.lock`` file.

    Yields:

        One :class:`DependencyIssue` per pin that differs from the locked version,
        and one per pinned tool the configuration never pins.

    """
    lines = config.read_text(encoding="utf-8").splitlines()

    for name in HOOK_PINNED:
        locked = get_locked_version(lockfile, name)
        pattern = _get_pin_pattern(name)
        pins = [
            (lineno, match.group(2))
            for lineno, line in enumerate(lines, 1)
            for match in pattern.finditer(line)
        ]

        if not pins:
            msg = f"no hook pins {name!r}; pin it as {name}=={locked}"
            yield DependencyIssue(str(config), msg)

        for lineno, version in pins:
            if version != locked:
                msg = f"hook pins {name}=={version} but uv.lock has {locked}"
                yield DependencyIssue(f"{config}:{lineno}", msg)


__all__ = [
    "HOOK_PINNED",
    "DependencyIssue",
    "RuntimeImport",
    "build_pinned_config",
    "gen_hook_pin_issues",
    "gen_import_issues",
    "gen_runtime_imports",
    "get_locked_version",
    "normalize_distribution",
]
