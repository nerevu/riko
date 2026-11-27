"""Checks that internal imports use each symbol's defining module."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import chain
from typing import TYPE_CHECKING

from ._import_graph import collect_imports, load_modules

if TYPE_CHECKING:
    from pathlib import Path


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
    modules = load_modules(root)
    source_map = {module.name: module.symbol_sources for module in modules}
    issues: list[_CanonicalIssue] = []

    for ref in chain.from_iterable(map(collect_imports, modules)):
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


def lint_canonical_imports(root: Path) -> int:
    issues = _iter_issues(root)

    for issue in issues:
        print(issue.format())

    return 1 if issues else 0
