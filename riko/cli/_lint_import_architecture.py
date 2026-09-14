"""Generates and validates Riko's static package dependency architecture."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ._import_graph import _collect_imports, _iter_modules

_LAYER_ORDER = (
    "leaf",
    "values",
    "types",
    "definitions",
    "parse",
    "runtime",
    "plugins",
    "app",
)
_LAYER_INDEX = {name: index for index, name in enumerate(_LAYER_ORDER)}

_EXACT_LAYERS = {
    "riko": "app",
    "riko._metadata": "leaf",
    "riko.cast": "values",
    "riko.dotdict": "values",
    "riko.parsers": "parse",
    "riko._io": "runtime",
    "riko.autorss": "runtime",
    "riko.utils._formats": "runtime",
    "riko.utils.dates": "values",
}
_PREFIX_LAYERS = {
    "riko.base": "leaf",
    "riko.patched": "leaf",
    "riko.utils": "leaf",
    "riko.bado": "values",
    "riko.types": "types",
    "riko.definitions": "definitions",
    "riko._pubsub": "runtime",
    "riko.runtime": "runtime",
    "riko.modules": "plugins",
    "riko.ext": "plugins",
    "riko.cli": "app",
}


@dataclass(frozen=True, slots=True)
class _ArchitectureIssue:
    path: Path
    line: int
    importer: str
    importer_layer: str
    imported: str
    imported_layer: str

    def format(self) -> str:
        return (
            f"{self.path}:{self.line}: IAR001 {self.importer_layer} module "
            f"{self.importer} imports upward from {self.imported_layer} module "
            f"{self.imported}"
        )


def _layer_for(module: str) -> str | None:
    layer = _EXACT_LAYERS.get(module)

    if layer is None:
        matches = [
            (prefix, candidate)
            for prefix, candidate in _PREFIX_LAYERS.items()
            if module == prefix or module.startswith(f"{prefix}.")
        ]
        layer = max(matches, key=lambda item: len(item[0]))[1] if matches else None

    return layer


def _architecture(root: Path) -> tuple[
    tuple[tuple[str, str], ...], tuple[_ArchitectureIssue, ...], tuple[str, ...]
]:
    modules = _iter_modules(root)
    module_names = {module.name for module in modules}
    unclassified = tuple(sorted(name for name in module_names if _layer_for(name) is None))
    edges: set[tuple[str, str]] = set()
    issues: list[_ArchitectureIssue] = []

    for module in modules:
        importer_layer = _layer_for(module.name)

        if importer_layer is None:
            continue

        for ref in _collect_imports(module):
            if ref.kind != "module" or not ref.imported.startswith("riko"):
                continue

            imported_layer = _layer_for(ref.imported)

            if imported_layer is None:
                continue

            edges.add((importer_layer, imported_layer))

            if _LAYER_INDEX[importer_layer] < _LAYER_INDEX[imported_layer]:
                issues.append(
                    _ArchitectureIssue(
                        path=ref.path,
                        line=ref.line,
                        importer=module.name,
                        importer_layer=importer_layer,
                        imported=ref.imported,
                        imported_layer=imported_layer,
                    )
                )

    return tuple(sorted(edges)), tuple(issues), unclassified


def _render_architecture(root: Path) -> str:
    edges, issues, unclassified = _architecture(root)
    lines = [f"layers: {' < '.join(_LAYER_ORDER)}", "", "observed edges:"]
    lines.extend(f"  {source} -> {target}" for source, target in edges)

    if unclassified:
        lines.extend(["", "unclassified modules:"])
        lines.extend(f"  {name}" for name in unclassified)

    if issues:
        lines.extend(["", "upward imports:"])
        lines.extend(f"  {issue.importer} -> {issue.imported}" for issue in issues)

    return "\n".join(lines)


def _check_import_architecture(root: Path, *, render: bool = True) -> int:
    _, issues, unclassified = _architecture(root)

    if render:
        print(_render_architecture(root))

    for name in unclassified:
        print(f"IAR002 unclassified Riko module: {name}")

    for issue in issues:
        print(issue.format())

    return 1 if issues or unclassified else 0
