"""Builds a static import graph without importing Riko modules."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

type _ImportKind = Literal["module", "local", "type"]


@dataclass(frozen=True, slots=True)
class _ModuleInfo:
    name: str
    path: Path
    is_package: bool
    tree: ast.Module


@dataclass(frozen=True, slots=True)
class _ImportRef:
    importer: str
    imported: str
    names: tuple[tuple[str, str | None], ...]
    path: Path
    line: int
    kind: _ImportKind
    form: Literal["import", "from"]
    level: int


def _get_modules(root: Path) -> tuple[_ModuleInfo, ...]:
    modules: list[_ModuleInfo] = []
    package = root.name

    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root)
        parts = list(relative.with_suffix("").parts)
        is_package = parts[-1] == "__init__"

        if is_package:
            parts.pop()

        name = ".".join([package, *parts])
        tree = ast.parse(path.read_text(), filename=str(path))
        modules.append(
            _ModuleInfo(name=name, path=path, is_package=is_package, tree=tree)
        )

    return tuple(modules)


def _resolve_from_module(current: _ModuleInfo, module: str | None, level: int) -> str:
    if level == 0:
        resolved = module or ""
    else:
        package = (
            current.name if current.is_package else current.name.rpartition(".")[0]
        )
        parts = package.split(".") if package else []
        keep = max(0, len(parts) - level + 1)
        base = parts[:keep]

        if module:
            base.extend(module.split("."))

        resolved = ".".join(base)

    return resolved


def _is_type_checking(test: ast.expr) -> bool:
    result = isinstance(test, ast.Name) and test.id == "TYPE_CHECKING"

    if isinstance(test, ast.Attribute):
        result = (
            isinstance(test.value, ast.Name)
            and test.value.id == "typing"
            and test.attr == "TYPE_CHECKING"
        )

    return result


class _ImportVisitor(ast.NodeVisitor):
    def __init__(self, module: _ModuleInfo) -> None:
        self.module = module
        self.refs: list[_ImportRef] = []
        self._local_depth = 0
        self._type_depth = 0

    @property
    def _kind(self) -> _ImportKind:
        if self._type_depth:
            kind: _ImportKind = "type"
        elif self._local_depth:
            kind = "local"
        else:
            kind = "module"

        return kind

    def visit_If(self, node: ast.If) -> None:
        if _is_type_checking(node.test):
            self.visit(node.test)
            self._type_depth += 1

            for child in node.body:
                self.visit(child)

            self._type_depth -= 1

            for child in node.orelse:
                self.visit(child)
        else:
            self.generic_visit(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)

        for default in node.args.defaults:
            self.visit(default)

        for default in node.args.kw_defaults:
            if default is not None:
                self.visit(default)

        self._local_depth += 1

        for child in node.body:
            self.visit(child)

        self._local_depth -= 1

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self._local_depth += 1
        self.visit(node.body)
        self._local_depth -= 1

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.refs.append(
                _ImportRef(
                    importer=self.module.name,
                    imported=alias.name,
                    names=((alias.name.rsplit(".", 1)[-1], alias.asname),),
                    path=self.module.path,
                    line=node.lineno,
                    kind=self._kind,
                    form="import",
                    level=0,
                )
            )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        imported = _resolve_from_module(self.module, node.module, node.level)
        self.refs.append(
            _ImportRef(
                importer=self.module.name,
                imported=imported,
                names=tuple((alias.name, alias.asname) for alias in node.names),
                path=self.module.path,
                line=node.lineno,
                kind=self._kind,
                form="from",
                level=node.level,
            )
        )


def _collect_imports(module: _ModuleInfo) -> tuple[_ImportRef, ...]:
    visitor = _ImportVisitor(module)
    visitor.visit(module.tree)
    return tuple(visitor.refs)


def _module_package(module: _ModuleInfo) -> str:
    return module.name if module.is_package else module.name.rpartition(".")[0]


def _resolve_import_targets():
    pass
