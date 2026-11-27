"""Checks that sibling modules use explicit relative imports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ._import_graph import collect_imports, load_modules

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True, slots=True)
class _RelativeIssue:
    path: Path
    line: int
    imported: str
    suggestion: str

    def format(self) -> str:
        return (
            f"{self.path}:{self.line}: IRL001 sibling import {self.imported!r} "
            f"must be relative; use {self.suggestion}"
        )


def _iter_issues(root: Path) -> tuple[_RelativeIssue, ...]:
    issues: list[_RelativeIssue] = []

    for module in load_modules(root):
        package = module.package

        for ref in collect_imports(module):
            if ref.level or not ref.imported.startswith("riko"):
                continue

            parent = ref.imported.rpartition(".")[0]
            is_sibling = ref.imported == package or parent == package

            if not is_sibling:
                continue

            if ref.form == "from":
                rendered_names = ", ".join(
                    f"{name} as {alias}" if alias else name for name, alias in ref.names
                )
                suffix = ref.imported.removeprefix(package).removeprefix(".")
                suggestion = f"from .{suffix} import {rendered_names}"
            else:
                child = ref.imported.rsplit(".", 1)[-1]
                alias = ref.names[0][1]
                imported_name = (
                    f"{child} as {alias}" if alias and alias != child else child
                )
                suggestion = f"from . import {imported_name}"

            issues.append(
                _RelativeIssue(
                    path=ref.path,
                    line=ref.line,
                    imported=ref.imported,
                    suggestion=suggestion,
                )
            )

    return tuple(issues)


def lint_relative_imports(root: Path) -> int:
    issues = _iter_issues(root)

    for issue in issues:
        print(issue.format())

    return 1 if issues else 0
