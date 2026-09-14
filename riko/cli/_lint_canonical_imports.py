"""Checks that internal imports use each symbol's defining module."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from ._import_graph import (
    _collect_imports,
    _get_modules,
    _ModuleInfo,
    _resolve_from_module,
)


@dataclass(frozen=True, slots=True)
class _CanonicalIssue:
    path: Path
    line: int
    module: str
    name: str
    canonical_module: str

    def format(self) -> str:
        return (
            f"{self.path}:{self.line}: ICN001 import {self.name!r} from "
            f"{self.canonical_module}, not re-export {self.module}"
        )


def _bound_names(node: ast.AST) -> tuple[str, ...]:
    names: list[str] = []

    if isinstance(node, ast.Name):
        names.append(node.id)
    elif isinstance(node, (ast.Tuple, ast.List)):
        for child in node.elts:
            names.extend(_bound_names(child))

    return tuple(names)


def _runtime_symbol_sources(module: _ModuleInfo) -> dict[str, tuple[str, str]]:
    sources: dict[str, tuple[str, str]] = {}

    for node in module.tree.body:
        if isinstance(node, ast.ImportFrom):
            imported = node.module or ""

            if node.level:
                imported = _resolve_from_module(module, node.module, node.level)

            for alias in node.names:
                if alias.name != "*":
                    bound = alias.asname or alias.name
                    sources[bound] = (imported, alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                bound = alias.asname or alias.name.split(".", 1)[0]
                sources.pop(bound, None)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            sources.pop(node.name, None)
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]

            for target in targets:
                for name in _bound_names(target):
                    sources.pop(name, None)

    return sources


def _canonical_source(
    module: str, name: str, source_map: dict[str, dict[str, tuple[str, str]]]
) -> tuple[str, str]:
    current = (module, name)
    seen: set[tuple[str, str]] = set()

    while current not in seen:
        seen.add(current)
        source = source_map.get(current[0], {}).get(current[1])

        if source is None or not source[0].startswith("riko"):
            break

        current = source

    return current


def _iter_issues(root: Path) -> tuple[_CanonicalIssue, ...]:
    modules = _get_modules(root)
    source_map = {module.name: _runtime_symbol_sources(module) for module in modules}
    issues: list[_CanonicalIssue] = []

    for module in modules:
        for ref in _collect_imports(module):
            if ref.form != "from" or not ref.imported.startswith("riko"):
                continue

            for name, _ in ref.names:
                if name == "*":
                    continue

                canonical_module, _ = _canonical_source(ref.imported, name, source_map)

                if canonical_module != ref.imported:
                    issues.append(
                        _CanonicalIssue(
                            path=ref.path,
                            line=ref.line,
                            module=ref.imported,
                            name=name,
                            canonical_module=canonical_module,
                        )
                    )

    return tuple(issues)


def _check_canonical_imports(root: Path) -> int:
    issues = _iter_issues(root)

    for issue in issues:
        print(issue.format())

    return 1 if issues else 0
