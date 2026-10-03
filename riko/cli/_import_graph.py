"""Builds a static import graph without importing Riko modules."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from tokenize import open as open_python
from typing import TYPE_CHECKING, Literal

from riko.base.exceptions import ImportAnalysisError

if TYPE_CHECKING:
    from pathlib import Path

type _ImportKind = Literal["module", "local", "type"]


@dataclass(frozen=True, slots=True)
class ModuleInfo:
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


def _get_modules(root: Path) -> tuple[ModuleInfo, ...]:
    modules: list[ModuleInfo] = []
    package = root.name

    for path in sorted(root.rglob("*.py")):
        try:
            with open_python(path) as stream:
                source = stream.read()

            tree = ast.parse(source, filename=str(path))
        except (OSError, SyntaxError, UnicodeError) as exc:
            raise ImportAnalysisError(f"{path}: {exc}") from exc

        relative = path.relative_to(root)
        parts = list(relative.with_suffix("").parts)

        if is_package := parts[-1] == "__init__":
            parts.pop()

        name = ".".join([package, *parts])
        module = ModuleInfo(name=name, path=path, is_package=is_package, tree=tree)
        modules.append(module)

    return tuple(modules)


def _resolve_from_module(current: ModuleInfo, module: str | None, level: int) -> str:
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
    return isinstance(test, ast.Name) and test.id == "TYPE_CHECKING"


class _ImportVisitor(ast.NodeVisitor):
    def __init__(self, module: ModuleInfo) -> None:
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


def collect_imports(module: ModuleInfo) -> tuple[_ImportRef, ...]:
    visitor = _ImportVisitor(module)
    visitor.visit(module.tree)
    return tuple(visitor.refs)


def _module_package(module: ModuleInfo) -> str:
    return module.name if module.is_package else module.name.rpartition(".")[0]


def resolve_import_targets(
    ref: _ImportRef, module_names: set[str] | frozenset[str]
) -> tuple[str, ...]:
    if ref.form == "import":
        result = (ref.imported,) if ref.imported else ()
    else:
        targets: list[str] = []

        for name, _ in ref.names:
            if name == "*":
                target = ref.imported
            else:
                candidate = f"{ref.imported}.{name}" if ref.imported else name
                target = candidate if candidate in module_names else ref.imported

            if target and target not in targets:
                targets.append(target)

        result = tuple(targets)

    return result
