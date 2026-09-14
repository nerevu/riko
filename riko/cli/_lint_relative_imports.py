"""Checks that sibling modules use explicit relative imports."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ._import_graph import _collect_imports, _iter_modules, _module_package


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


def _suggestion(
    package: str, imported: str, names: tuple[tuple[str, str | None], ...]
) -> str:
    rendered_names = ", ".join(
        f"{name} as {alias}" if alias else name for name, alias in names
    )

    if imported == package:
        suggestion = f"from . import {rendered_names}"
    else:
        suffix = imported.removeprefix(f"{package}.")
        suggestion = f"from .{suffix} import {rendered_names}"

    return suggestion


def _iter_issues(root: Path) -> tuple[_RelativeIssue, ...]:
    issues: list[_RelativeIssue] = []

    for module in _iter_modules(root):
        package = _module_package(module)

        for ref in _collect_imports(module):
            if ref.level or not ref.imported.startswith("riko"):
                continue

            parent = ref.imported.rpartition(".")[0]
            is_sibling = ref.imported == package or parent == package

            if not is_sibling:
                continue

            if ref.form == "from":
                suggestion = _suggestion(package, ref.imported, ref.names)
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


def _check_relative_imports(root: Path) -> int:
    issues = _iter_issues(root)

    for issue in issues:
        print(issue.format())

    return 1 if issues else 0
