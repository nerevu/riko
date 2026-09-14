"""Generates and validates Riko's static package dependency architecture."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterator
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from riko.base._graph import AnyGraph, FrozenGraph, Graph, freeze_graph

from ._import_graph import _collect_imports, _get_modules

_LAYER_DEPENDENCIES: FrozenGraph[str] = freeze_graph(
    {
        "base": set[str](),
        "types": {"base"},
        "coercion": {"types"},
        "bado": {"types"},
        "definitions": {"types"},
        "io": {"coercion", "bado", "definitions"},
        "parsing": {"io"},
        "rss": {"parsing"},
        "modules": {"rss"},
        "runtime": {"modules"},
        "api": {"runtime"},
        "cli": {"api"},
    }
)


_EXACT_LAYERS = {
    "riko": "api",
    "riko._metadata": "base",
    "riko.dotdict": "coercion",
    "riko.parsers": "parsing",
}

_PREFIX_LAYERS = {
    "riko.base": "base",
    "riko.types": "types",
    "riko.coercion": "coercion",
    "riko.bado": "bado",
    "riko.io": "io",
    "riko.definitions": "definitions",
    "riko.rss": "rss",
    "riko.runtime": "runtime",
    "riko.modules": "modules",
    "riko.ext": "api",
    "riko.cli": "cli",
}


@dataclass(frozen=True, slots=True)
class ArchitectureViolation:
    path: Path
    line: int
    source_name: str
    target_name: str
    source_label: str
    target_label: str
    reason: Literal["forbidden_layer_dependency", "forbidden_same_layer_public_import"]

    def format(self) -> str:
        return (
            f"{self.path}:{self.line}: IAR001 {self.source_label} module "
            f"{self.source_name} imports upward from {self.target_label} module "
            f"{self.target_name}"
        )


@dataclass(frozen=True, slots=True)
class UnclassifiedModule:
    module: str
    path: Path


@dataclass(frozen=True, slots=True)
class ArchitectureReport:
    declared: FrozenGraph[str]
    observed: FrozenGraph[str]
    # type_only: FrozenGraph[str]
    violations: tuple[ArchitectureViolation, ...]
    unclassified: tuple[UnclassifiedModule, ...]


def _reachable(edge: str, graph: AnyGraph[str] | None = None) -> set[str]:
    graph = _LAYER_DEPENDENCIES if graph is None else graph
    seen: set[str] = set()
    stack = list(graph.get(edge, frozenset()))

    while stack:
        if (node := stack.pop()) not in seen:
            seen.add(node)
            stack.extend(graph.get(node, frozenset()))

    return seen


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


def generate_report(root: Path) -> ArchitectureReport:
    modules = _get_modules(root)
    unclassified = tuple(
        UnclassifiedModule(module.name, module.path)
        for module in modules
        if _layer_for(module.name) is None
    )
    observed: Graph[str] = defaultdict(set)
    issues: list[ArchitectureViolation] = []

    for module in modules:
        if (source_layer := _layer_for(module.name)) is None:
            continue

        for ref in _collect_imports(module):
            if ref.kind != "module" or not ref.imported.startswith("riko"):
                continue

            if (target_layer := _layer_for(ref.imported)) is None:
                continue

            observed[source_layer].add(target_layer)
            reachable = _reachable(source_layer)

            if target_layer != source_layer and target_layer not in reachable:
                issues.append(
                    ArchitectureViolation(
                        path=ref.path,
                        line=ref.line,
                        source_name=module.name,
                        source_label=source_layer,
                        target_name=ref.imported,
                        target_label=target_layer,
                        reason="forbidden_layer_dependency",
                    )
                )

    ordered = sorted(observed, key=lambda layer: len(_reachable(layer)))
    frozen = freeze_graph({edge: observed[edge] for edge in ordered})
    return ArchitectureReport(_LAYER_DEPENDENCIES, frozen, tuple(issues), unclassified)


def _gen_remaining(
    source: str, target: AbstractSet[str], graph: AnyGraph[str] | None = None
) -> Iterator[str]:
    graph = _LAYER_DEPENDENCIES if graph is None else graph
    remaining = target - {source}

    yield from remaining - _reachable(source, graph)

    if counts := Counter({edge: len(_reachable(edge, graph)) for edge in remaining}):
        max_freq = counts.most_common(1)[0][1]

        for layer, freq in counts.items():
            if freq == max_freq:
                remaining -= _reachable(layer, graph)

        yield from remaining
    else:
        yield "<no layers>"


def gen_layers(graph: AnyGraph[str] | None = None) -> Iterator[str]:
    graph = _LAYER_DEPENDENCIES if graph is None else graph
    layers: dict[frozenset[str], set[str]] = defaultdict(set)

    for edge, nodes in graph.items():
        layers[frozenset(nodes)].add(edge)

    for layer in layers.values():
        if len(layer) > 1:
            yield f"{{{' | '.join(sorted(layer))}}}"
        else:
            yield next(iter(layer))


def render_architecture(report: ArchitectureReport) -> str:
    layers = gen_layers(report.declared)
    lines = [f"layers: {' < '.join(layers)}", "", "observed edges:"]

    for source, target in report.observed.items():
        _remaining = set(_gen_remaining(source, target))
        remaining = f"{{{', '.join(_remaining)}}}"
        lines.append(f"  {source} -> {remaining}")

    if report.unclassified:
        lines.extend(["", "unclassified modules:"])
        lines.extend(f"  {name}" for name in report.unclassified)

    if issues := report.violations:
        lines.extend(["", "upward imports:"])
        lines.extend(
            f"  {issue.source_name} -> {issue.target_name}" for issue in issues
        )

    return "\n".join(lines)


def check_import_architecture(root: Path, *, render: bool = True) -> int:
    report = generate_report(root)

    if render:
        print(render_architecture(report))

    for name in report.unclassified:
        print(f"IAR002 unclassified Riko module: {name}")

    for issue in report.violations:
        msg = f"{issue.path}:{issue.line}: ResourceViolation:\n  {issue.source_label}"
        msg += f" imports upward from {issue.target_name}"
        print(msg)

    return 1 if report.violations or report.unclassified else 0
