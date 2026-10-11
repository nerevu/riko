# vim: sw=4:ts=4:expandtab
"""Checks riko's imports and hook pins against its declared and locked dependencies."""

from __future__ import annotations

import ast
import re
import sys
import tomllib
from importlib.metadata import packages_distributions
from typing import TYPE_CHECKING, Any, Literal, NamedTuple

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence
    from pathlib import Path

type ImportGuard = Literal["none", "try", "type_checking"]

_LOCAL_NAMES = frozenset({"riko", "__future__"})
_REQUIREMENT_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
_STUB_PREFIX = "types-"
HOOK_PINNED: tuple[str, ...] = ("ruff",)


class ImportSite(NamedTuple):
    """
    One import of a top-level name outside the standard library and riko.

    Attributes:

        path: The file holding the import.
        lineno: The import's line number.
        name: The imported top-level module name, such as ``dateutil``.
        guard: ``"none"`` when the import runs whenever its code runs, ``"try"``
            inside a ``try`` block, or ``"type_checking"`` under ``TYPE_CHECKING``.

    """

    path: Path
    lineno: int
    name: str
    guard: ImportGuard


class DependencyIssue(NamedTuple):
    """
    A mismatch between riko's imports and its declared dependencies.

    Attributes:

        where: The ``path:line`` of the offending import, or ``pyproject.toml``.
        message: What is wrong and what to declare or remove.

    """

    where: str
    message: str


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


def _get_guard(node: ast.AST, parents: Mapping[ast.AST, ast.AST]) -> ImportGuard:
    """Finds the strongest guard among an import's enclosing statements."""
    guards: set[ImportGuard] = set()
    parent = parents.get(node)

    while parent is not None:
        if isinstance(parent, ast.If) and "TYPE_CHECKING" in ast.unparse(parent.test):
            guards.add("type_checking")
        elif isinstance(parent, ast.Try):
            guards.add("try")

        parent = parents.get(parent)

    if "type_checking" in guards:
        guard: ImportGuard = "type_checking"
    elif "try" in guards:
        guard = "try"
    else:
        guard = "none"

    return guard


def _gen_imported_names(node: ast.AST) -> Iterator[str]:
    """Extracts the top-level module names from an absolute import statement."""
    if isinstance(node, ast.Import):
        for alias in node.names:
            yield alias.name.split(".")[0]
    elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
        yield node.module.split(".")[0]


def gen_import_sites(package_dir: Path) -> Iterator[ImportSite]:
    """
    Walks a package for imports of names outside the standard library and riko.

    Args:

        package_dir: The package directory to scan.

    Yields:

        One :class:`ImportSite` per third-party name per import statement, in path
        then line order.

    """
    excluded = _LOCAL_NAMES | sys.stdlib_module_names

    for path in sorted(package_dir.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        parents = {
            child: node
            for node in ast.walk(tree)
            for child in ast.iter_child_nodes(node)
        }
        imports = (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Import | ast.ImportFrom)
        )

        for node in sorted(imports, key=lambda node: node.lineno):
            for name in _gen_imported_names(node):
                if name not in excluded:
                    yield ImportSite(path, node.lineno, name, _get_guard(node, parents))


def _get_declared(data: Mapping[str, Any]) -> tuple[frozenset[str], frozenset[str]]:
    """Collects the required dependencies and every optional or group requirement."""
    project = data.get("project", {})
    required = frozenset(map(_get_requirement_name, project.get("dependencies", [])))
    groups = [
        *project.get("optional-dependencies", {}).values(),
        *data.get("dependency-groups", {}).values(),
    ]
    optional = frozenset(
        _get_requirement_name(entry)
        for group in groups
        for entry in group
        if isinstance(entry, str)
    )
    return required, optional


def _get_runtime_stubs(data: Mapping[str, Any]) -> list[str]:
    """Lists ``types-*`` stub packages declared as run-time requirements."""
    project = data.get("project", {})
    extras = project.get("optional-dependencies", {}).values()
    entries = [
        *project.get("dependencies", []),
        *(e for extra in extras for e in extra),
    ]
    names = map(_get_requirement_name, entries)
    return sorted({name for name in names if name.startswith(_STUB_PREFIX)})


def gen_dependency_issues(
    package_dir: Path,
    pyproject: Path,
    distributions: Mapping[str, Sequence[str]] | None = None,
) -> Iterator[DependencyIssue]:
    """
    Compares a package's imports against the dependencies its project declares.

    An unguarded import must come from a required dependency, an import in a ``try``
    block from any declared requirement (a dependency, an extra, or a dependency
    group), and every required dependency must be imported outside ``TYPE_CHECKING``.
    A ``types-*`` stub package must never be a required dependency or an extra. A
    module no installed distribution provides is assumed to share its
    distribution's name, so an uninstalled extra still matches its declaration.

    Args:

        package_dir: The package directory whose imports are checked.
        pyproject: The ``pyproject.toml`` declaring the dependencies.
        distributions: Maps each top-level module name to the distributions that
            provide it. Defaults to the installed environment's mapping.

    Yields:

        One :class:`DependencyIssue` per mismatch: imports in path then line order,
        then unused dependencies, then stub packages.

    """
    provided = packages_distributions() if distributions is None else distributions
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    required, optional = _get_declared(data)
    used: set[str] = set()

    for site in gen_import_sites(package_dir):
        names = provided.get(site.name) or (site.name,)
        dists = {normalize_distribution(name) for name in names}
        where = f"{site.path}:{site.lineno}"

        if site.guard != "type_checking":
            used |= dists

        if site.guard == "none" and not dists & required:
            msg = (
                f"{site.name!r} is imported unguarded but is not a [project] dependency"
            )
            yield DependencyIssue(where, msg)
        elif site.guard == "try" and not dists & (required | optional):
            msg = f"{site.name!r} is imported in a try block but declared nowhere"
            yield DependencyIssue(where, msg)

    for name in sorted(required - used):
        msg = f"{name!r} is a [project] dependency that nothing imports"
        yield DependencyIssue(str(pyproject), msg)

    for name in _get_runtime_stubs(data):
        msg = f"{name!r} is a typing stub; declare it in a dependency group"
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


def format_dependency_issue(issue: DependencyIssue) -> str:
    """Renders one issue as a ``where message`` line."""
    return f"{issue.where} {issue.message}"


__all__ = [
    "HOOK_PINNED",
    "DependencyIssue",
    "ImportSite",
    "build_pinned_config",
    "format_dependency_issue",
    "gen_dependency_issues",
    "gen_hook_pin_issues",
    "gen_import_sites",
    "get_locked_version",
    "normalize_distribution",
]
