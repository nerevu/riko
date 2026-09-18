"""Generates and validates Riko's static package dependency architecture."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from enum import StrEnum
from functools import partial
from typing import TYPE_CHECKING

from riko.base._config import EXACT_LAYERS as _EXACT_LAYERS
from riko.base._config import LAYER_DEPENDENCIES as _RAW_LAYER_DEPENDENCIES
from riko.base._config import PREFIX_LAYERS as _PREFIX_LAYERS
from riko.base.exceptions import InvalidArchitectureError
from riko.coercion._graph import (
    AnyGraph,
    FrozenGraph,
    SetGraph,
    descendants,
    freeze_graph,
    topological_sort,
)

from ._import_graph import (
    ModuleInfo,
    _get_modules,
    collect_imports,
    resolve_import_targets,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping
    from pathlib import Path

_LAYER_DEPENDENCIES: FrozenGraph[str] = freeze_graph(_RAW_LAYER_DEPENDENCIES)


class ViolationCodes(StrEnum):
    FORBIDDEN_LAYER_DEPENDENCY = "forbidden_layer_dependency"
    FORBIDDEN_SAME_LAYER_PUBLIC_IMPORT = "forbidden_same_layer_public_import"


@dataclass(frozen=True, slots=True)
class ArchitectureViolation:
    path: Path
    line: int
    source_name: str
    target_name: str
    source_label: str
    target_label: str
    code: ViolationCodes

    @property
    def reason(self):
        if self.code == ViolationCodes.FORBIDDEN_SAME_LAYER_PUBLIC_IMPORT:
            reason = "imports public same-layer module"
        else:
            reason = "imports forbidden layer"

        return reason

    @property
    def detail(self) -> str:
        return (
            f"{self.path}:{self.line}: IAR001 ResourceViolation: "
            f"{self.source_name} ({self.source_label}) {self.reason} "
            f"'{self.target_name}' ({self.target_label})"
        )


@dataclass(frozen=True, slots=True)
class UnclassifiedModule:
    module: str
    path: Path

    @property
    def detail(self) -> str:
        return f"IAR002 unclassified Riko module: {self.module}"


@dataclass(frozen=True, slots=True)
class ArchitectureReport:
    declared: FrozenGraph[str]
    observed: FrozenGraph[str]
    type_only: FrozenGraph[str]
    local_only: FrozenGraph[str]
    unclassified: tuple[UnclassifiedModule, ...]
    violations: tuple[ArchitectureViolation, ...]


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


def _is_private_module(module: str) -> bool:
    return any(part.startswith("_") for part in module.split(".")[1:])


def _is_init_module(module: ModuleInfo) -> bool:
    return module.path.name.endswith("__init__.py")


def _issue_sort_key(issue: ArchitectureViolation) -> tuple[str, int, str, str, str]:
    return (
        str(issue.path),
        issue.line,
        issue.source_name,
        issue.target_name,
        issue.code,
    )


def _module_sort_key(module: UnclassifiedModule) -> tuple[str, str]:
    return (str(module.path), module.module)


def _graph_sort_key(layer: str) -> int:
    return len(descendants(layer, _LAYER_DEPENDENCIES))


def _gen_remaining(
    source: str, target: set[str], graph: AnyGraph[str]
) -> Iterator[str]:
    remaining = target - {source}
    yield from remaining - descendants(source, graph)

    if counts := Counter({edge: len(descendants(edge, graph)) for edge in remaining}):
        max_freq = counts.most_common(1)[0][1]

        for layer, freq in counts.items():
            if freq == max_freq:
                remaining -= descendants(layer, graph)

        yield from remaining
    else:
        yield "<no layers>"


def _render_from(
    start: frozenset[str], layers: Mapping[frozenset[str], set[str]]
) -> Iterator[str]:
    visited: set[frozenset[str]] = set()
    parts = [_format_group(start)]
    current = start

    while current in layers and current not in visited:
        visited.add(current)
        current = frozenset(layers[frozenset(current)])
        parts.append(_format_group(current))

    return filter(None, parts)


def _format_group(nodes: Iterable[str]) -> str | None:
    if len(ordered := sorted(nodes)) > 1:
        formatted = f"{{{' | '.join(ordered)}}}"
    else:
        formatted = next(iter(ordered), None)

    return formatted


def _gen_layers(name: str, graph: AnyGraph[str], verbose=True) -> Iterator[str]:
    """Render the dependency DAG as compact chained expressions."""
    _validate_graph(name, graph)
    layers: dict[frozenset[str], set[str]] = defaultdict(set)

    for target, dependencies in graph.items():
        layers[frozenset(dependencies)].add(target)

    if verbose:
        # A layer starts a line unless its LHS is exactly the RHS of another layer,
        # in which case it can be chained onto that layer.
        chained_groups = map(frozenset, layers.values())
        starts = set(layers).difference(chained_groups)

        for start in sorted(starts, key=lambda group: tuple(sorted(group))):
            parts = _render_from(start, layers)
            yield " < ".join(parts)
    else:
        parts = map(_format_group, layers.values())
        yield " < ".join(filter(None, parts))


def _validate_graph(name: str, graph: AnyGraph[str]) -> None:
    declared = set(graph)
    referenced = {node for targets in graph.values() for node in targets}

    if dangling := referenced - declared:
        names = ", ".join(sorted(dangling))
        raise InvalidArchitectureError(f"undeclared layers: {names}")

    topological_sort(graph, strict=True, name=name)

    for source, targets in graph.items():
        for target in targets:
            others = set(targets) - {target}

            if any(target in descendants(other, graph) for other in others):
                msg = f"redundant dependency: {source} -> {target}"
                raise InvalidArchitectureError(msg)


def generate_report(
    root: Path, dependencies: FrozenGraph[str] | None = None
) -> ArchitectureReport:

    if dependencies is None:
        dependencies, name = _LAYER_DEPENDENCIES, "_LAYER_DEPENDENCIES"
    else:
        name = "custom"

    _validate_graph(name, dependencies)
    modules = _get_modules(root)
    module_names = {module.name for module in modules}
    unclassified = tuple(
        UnclassifiedModule(module.name, module.path)
        for module in modules
        if _layer_for(module.name) is None
    )
    observed: SetGraph[str] = {k: set() for k in dependencies}
    type_only: SetGraph[str] = {k: set() for k in dependencies}
    local_only: SetGraph[str] = {k: set() for k in dependencies}
    issues: list[ArchitectureViolation] = []

    for module in modules:
        if (source_layer := _layer_for(module.name)) is None:
            continue

        is_init_source = _is_init_module(module)

        for ref in collect_imports(module):
            for target in resolve_import_targets(ref, module_names):
                if (target_layer := _layer_for(target)) is None:
                    continue

                violation = partial(
                    ArchitectureViolation,
                    path=ref.path,
                    line=ref.line,
                    source_name=module.name,
                    source_label=source_layer,
                    target_name=ref.imported,
                    target_label=target_layer,
                )

                if target_layer == source_layer:
                    is_private_target = _is_private_module(target)

                    if ref.kind != "type" and not (is_private_target or is_init_source):
                        code = ViolationCodes.FORBIDDEN_SAME_LAYER_PUBLIC_IMPORT
                        issues.append(violation(code=code))
                elif ref.kind == "type":
                    type_only[source_layer].add(target_layer)
                    nodes = type_only[source_layer]
                    remaining = _gen_remaining(source_layer, nodes, dependencies)
                    type_only[source_layer] = set(remaining)
                elif ref.kind == "local":
                    local_only[source_layer].add(target_layer)
                    nodes = local_only[source_layer]
                    remaining = _gen_remaining(source_layer, nodes, dependencies)
                    local_only[source_layer] = set(remaining)
                else:
                    observed[source_layer].add(target_layer)
                    nodes = observed[source_layer]
                    remaining = _gen_remaining(source_layer, nodes, dependencies)
                    observed[source_layer] = set(remaining)
                    reachable = descendants(source_layer, dependencies)

                    if target_layer not in reachable:
                        code = ViolationCodes.FORBIDDEN_LAYER_DEPENDENCY
                        issues.append(violation(code=code))

    return ArchitectureReport(
        declared=dependencies,
        observed=freeze_graph(observed, key=_graph_sort_key),
        type_only=freeze_graph(type_only, key=_graph_sort_key),
        local_only=freeze_graph(local_only, key=_graph_sort_key),
        unclassified=tuple(sorted(unclassified, key=_module_sort_key)),
        violations=tuple(sorted(issues, key=_issue_sort_key)),
    )


def validate_architecture(report: ArchitectureReport) -> int:
    _validate_graph("declared", report.declared)
    _validate_graph("observed", report.observed)
    return 1 if report.violations or report.unclassified else 0


def func(msg, **nodes: frozenset[str]) -> Iterator[str]:
    yield ""
    yield msg

    for source, _remaining in nodes.items():
        remaining = f"{{{', '.join(_remaining)}}}" if _remaining else "NONE"
        yield f"  {source} > {remaining}"


def render_architecture(report: ArchitectureReport) -> str:
    layers = _gen_layers("declared", report.declared)
    lines = [f"layers: {'\n        '.join(layers)}"]

    lines.extend(func("observed dependency frontier:", **report.observed))
    lines.extend(func("typing-only dependencies:", **report.type_only))
    lines.extend(func("local-only dependencies:", **report.local_only))

    if report.unclassified:
        lines.extend(["", "unclassified modules:"])
        lines.extend(f"  {module}" for module in report.unclassified)

    if issues := report.violations:
        lines.extend(["", "architecture violations:"])

        for issue in issues:
            line = f"  {issue.source_name} ({issue.source_label}) -> "
            line += f"{issue.target_name} ({issue.target_label})"
            lines.append(line)

    if report.unclassified or report.violations:
        lines.append("\nviolation details:")
        lines.extend(f"  {module.detail}" for module in report.unclassified)
        lines.extend(f"  {issue.detail}" for issue in report.violations)

    lines.append("")
    return "\n".join(lines)
