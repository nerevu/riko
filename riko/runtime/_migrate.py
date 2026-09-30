# vim: sw=4:ts=4:expandtab
"""
Construction of canonical Workflow v2 specs from terser authoring documents.

``build_workflow`` expands a bare-bones DAG (``modules`` plus optional ``wires``)
into a validated canonical ``WorkflowSpec``. ``migrate_v1_to_v2`` converts a legacy
``PipeDef`` into the same canonical form; it is a rescue/conversion tool, not a live
loader, so migration warns and emits v2 only.

Examples:

    Basic usage::

        >>> from riko.runtime._migrate import migrate_v1_to_v2
        >>>
        >>> pipe_def = {
        ...     "modules": [
        ...         {"id": "sw-1", "type": "fetch", "conf": {}},
        ...         {"id": "_OUTPUT", "type": "output", "conf": {}},
        ...     ],
        ...     "wires": [
        ...         {
        ...             "id": "_w1",
        ...             "src": {"id": "_OUTPUT", "moduleid": "sw-1"},
        ...             "tgt": {"id": "_INPUT", "moduleid": "_OUTPUT"},
        ...         }
        ...     ],
        ... }
        >>> spec = migrate_v1_to_v2(pipe_def)
        >>> list(spec.nodes)
        ['sw-1']
        >>> spec.outputs["default"]
        Endpoint(node='sw-1', port='out')

"""

from __future__ import annotations

from itertools import pairwise
from typing import TYPE_CHECKING

import pygogo as gogo

from riko.base._config import INPUT_PORT, OUTPUT_MODULE, OUTPUT_PORT
from riko.base._iterutils import partition
from riko.base._strutils import pythonise
from riko.base.exceptions import InvalidPipelineError
from riko.coercion._sequences import lower_keys, require_sequence
from riko.types._collections import require_str
from riko.types._guards import require_mapping
from riko.types._workflow import WORKFLOW_VERSION
from riko.types.modules import ModuleOptions

from ._normalize import normalize_workflow

if TYPE_CHECKING:
    from collections.abc import Mapping
    from logging import Logger

    from riko.definitions._workflow import WorkflowSpec
    from riko.types._compiler import PipeDag, PipeDefLike

_WRITE_TYPE = "write"
_LOOP_TYPE = "loop"
_WRITE_CONF_KEYS = frozenset({"dest", "fmt", "mode", "keys"})
_WRITE_MODES = {"w": "replace", "a": "append"}
_STRUCTURAL_KEYS = frozenset({"id", "type", "conf"})
_OPTION_KEYS = frozenset(ModuleOptions.__annotations__)
_WARNING = "migrating a released Workflow v1 pipe definition to canonical v2"
logger: Logger = gogo.Gogo(__name__, monolog=True).logger


def _resolve_write_mode(mode: object) -> str:
    """Translates a v1 file-open write mode into its canonical v2 reconcile mode."""
    head = mode[:1].lower() if isinstance(mode, str) else ""

    if (canonical := _WRITE_MODES.get(head)) is None:
        raise InvalidPipelineError(f"cannot migrate v1 write mode: {mode!r}")

    return canonical


def _migrate_write(
    module_id: str, name: str, conf: Mapping[str, object], **extra: object
) -> dict[str, object]:
    """Translates a v1 ``write`` module into a v2 ``WriteNode`` authoring mapping."""
    if unsupported := sorted(set(extra) | (set(conf) - _WRITE_CONF_KEYS)):
        raise InvalidPipelineError(f"cannot migrate v1 write option(s): {unsupported}")

    preserved = {k: conf[k] for k in ("dest", "fmt", "keys") if conf.get(k) is not None}

    if conf.get("mode") is not None:
        preserved["mode"] = _resolve_write_mode(conf["mode"])

    return {
        "id": module_id,
        "name": name,
        "type": _WRITE_TYPE,
        "backend": "file",
        **preserved,
    }


def _migrate_embed(embed: object, conf: Mapping[str, object]) -> dict[str, object]:
    """Translates a v1 loop's embedded module reference into the v2 node embed."""
    mapping = require_mapping(embed, "loop 'embed'")
    name = require_str(mapping.get("type"), "loop embed 'type'")
    return {"name": name, "conf": conf}


def _migrate_pipe(
    module_id: str, name: str, conf: Mapping[str, object], **extra: object
) -> dict[str, object]:
    """Translates a v1 pipe module into a v2 module-node authoring mapping."""
    options = {k: extra.pop(k) for k in _OPTION_KEYS.intersection(extra)}
    embed = extra.pop("embed", None) if name == _LOOP_TYPE else None
    node: dict[str, object] = {"id": module_id, "name": name}

    if embed is None:
        node["conf"] = {**extra, **conf}
    else:
        node["conf"] = extra
        node["embed"] = _migrate_embed(embed, conf)

    if options:
        node["options"] = options

    return node


def _migrate_module(**module: object) -> dict[str, object]:
    """Translates one v1 module mapping into a v2 authoring node mapping."""
    module_id = require_str(module.get("id"), "module 'id'")
    name = require_str(module.get("type"), "module 'type'")
    conf = lower_keys(require_mapping(module.get("conf") or {}, "module conf"))
    extra = {k: v for k, v in module.items() if k not in _STRUCTURAL_KEYS}

    if name == _WRITE_TYPE:
        node = _migrate_write(module_id, name, conf, **extra)
    else:
        node = _migrate_pipe(module_id, name, conf, **extra)

    return node


def _migrate_target_port(port: str) -> str:
    """Sanitizes a v1 target port into the id the receiving module looks up."""
    return port if port.startswith("_") else pythonise(port)


def _migrate_wires(
    wires: object, output_ids: frozenset[str]
) -> tuple[list[dict[str, object]], dict[str, dict[str, str]]]:
    """Splits v1 wires into v2 stream edges and terminal-output references."""
    edges: list[dict[str, object]] = []
    outputs: dict[str, dict[str, str]] = {}

    for wire in require_sequence(wires, "wires"):
        mapping = require_mapping(wire, "wire")
        src = require_mapping(mapping.get("src"), "wire 'src'")
        tgt = require_mapping(mapping.get("tgt"), "wire 'tgt'")
        source = {
            "node": require_str(src.get("moduleid"), "wire 'src' moduleid"),
            "port": str(src.get("id", OUTPUT_PORT)),
        }
        tgt_node = require_str(tgt.get("moduleid"), "wire 'tgt' moduleid")

        if tgt_node in output_ids:
            name = "default" if not outputs else f"default-{len(outputs) + 1}"
            outputs[name] = source
        else:
            port = _migrate_target_port(str(tgt.get("id", INPUT_PORT)))
            target = {"node": tgt_node, "port": port}
            edges.append({"source": source, "target": target})

    return edges, outputs


def migrate_v1_to_v2(pipe_def: PipeDefLike) -> WorkflowSpec:
    """
    Migrates a released Workflow v1 pipe definition into a canonical v2 spec.

    Warns that a v1 document was migrated, then returns the canonical spec. Legacy
    ports, the ``write`` module, and the terminal ``_OUTPUT`` node are translated to
    their v2 equivalents; orphan and empty-graph rejection is left to validation. A
    module's call options become the node's ``options``, a loop's embedded module and
    its configuration become the node's ``embed``, and any other module-level key folds
    into the node's configuration. A v1 ``write`` file-open mode maps to a
    canonical reconcile mode, and a ``write`` carrying an option with no v2 equivalent
    is rejected rather than silently dropped.

    Args:

        pipe_def: A released v1 ``PipeDef`` with ``modules`` and ``src``/``tgt``
            ``wires``; editor ``layout``/``terminaldata`` are ignored.

    Returns:

        The canonical :class:`~riko.definitions._workflow.WorkflowSpec`.

    Examples:

        >>> pipe_def = {
        ...     "modules": [
        ...         {"id": "sw-1", "type": "fetch", "conf": {}},
        ...         {"id": "sw-2", "type": "write", "conf": {"fmt": "json"}},
        ...     ],
        ...     "wires": [
        ...         {
        ...             "id": "_w1",
        ...             "src": {"id": "_OUTPUT", "moduleid": "sw-1"},
        ...             "tgt": {"id": "_INPUT", "moduleid": "sw-2"},
        ...         }
        ...     ],
        ... }
        >>> spec = migrate_v1_to_v2(pipe_def)
        >>> node = spec.nodes["sw-2"]
        >>> node.backend.value, node.fmt.value
        ('file', 'json')
        >>> spec.outputs["default"]
        Endpoint(node='sw-2', port='out')

    """
    mapping = require_mapping(pipe_def, "pipe definition")
    raw_modules = require_sequence(mapping.get("modules", ()), "modules")
    modules = [require_mapping(m, "module") for m in raw_modules]
    outputs, inputs = partition(modules, lambda m: m.get("type") == OUTPUT_MODULE)

    output_ids = frozenset(require_str(m.get("id"), "module 'id'") for m in outputs)
    nodes = [_migrate_module(**m) for m in inputs]
    edges, outputs = _migrate_wires(mapping.get("wires", ()), output_ids)
    logger.warning(_WARNING)
    authoring: dict[str, object] = {
        "nodes": nodes,
        "edges": edges,
        "version": WORKFLOW_VERSION,
    }

    if outputs:
        authoring["outputs"] = outputs

    return normalize_workflow(authoring)


def _build_dag_node(index: int, **module: object) -> dict[str, object]:
    """Translates one bare-bones DAG module into a v2 authoring node mapping."""
    raw_id = module.pop("id", None)
    node_id = f"sw-{index}" if raw_id is None else require_str(raw_id, "module 'id'")
    name = require_str(module.pop("type", None), "module 'type'")
    return {"id": node_id, "name": name, **module}


def _build_dag_edge(*wire: object) -> dict[str, object]:
    """Translates one bare-bones DAG wire into a v2 authoring edge mapping."""
    if len(wire) not in {2, 3}:
        msg = "a wire must list a source id, a target id, and optionally a target "
        msg += f"port; got {len(wire)} of them"
        raise InvalidPipelineError(msg)

    source = require_str(wire[0], "wire source id")
    target = require_str(wire[1], "wire target id")
    port = "in" if len(wire) == 2 else require_str(wire[2], "wire target port")

    return {
        "source": {"node": source, "port": "out"},
        "target": {"node": target, "port": port},
    }


def build_workflow(dag: PipeDag) -> WorkflowSpec:
    """
    Builds a validated canonical workflow spec from a bare-bones DAG.

    A DAG lists ``modules`` and, optionally, ``wires``. Each module carries its module
    ``type``, an optional ``id`` defaulting to ``sw-{n}`` in listing order, an optional
    opaque ``conf``, and optional call ``options``; anything else it carries is offered
    to the workflow node as-is, so an unknown key is reported rather than dropped. When
    ``wires`` is omitted or empty the modules are chained in listing order, and the
    single leaf becomes the workflow's default output. A wire's optional third entry
    names the port it enters, so a fan-in operator such as ``union`` is expressible.

    Args:

        dag: A bare-bones DAG with ``modules`` and optional ``wires``, each wire a
            ``[source_id, target_id]`` or ``[source_id, target_id, target_port]``
            sequence.

    Returns:

        The canonical :class:`~riko.definitions._workflow.WorkflowSpec`.

    Raises:

        InvalidPipelineError: If ``modules`` is empty, a wire has the wrong number of
            entries, or the resulting workflow does not validate.

    Examples:

        >>> count = {"count": {"type": "int", "value": "3"}}
        >>> dag = {
        ...     "modules": [
        ...         {"type": "forever"},
        ...         {"type": "truncate", "conf": count},
        ...     ]
        ... }
        >>> spec = build_workflow(dag)
        >>> list(spec.nodes)
        ['sw-1', 'sw-2']
        >>> spec.outputs["default"]
        Endpoint(node='sw-2', port='out')
        >>>
        >>> # A fan-in wire naming the port it enters:
        >>>
        >>> dag = {
        ...     "modules": [
        ...         {"id": "a", "type": "fetch"},
        ...         {"id": "b", "type": "fetch"},
        ...         {"id": "u", "type": "union"},
        ...     ],
        ...     "wires": [["a", "u"], ["b", "u", "in:1"]],
        ... }
        >>> [edge.target.port for edge in build_workflow(dag).edges]
        ['in', 'in:1']

    """
    mapping = require_mapping(dag, "dag")
    _modules = require_sequence(mapping.get("modules", ()), "modules")
    modules = [require_mapping(m, "module") for m in _modules]
    nodes = [_build_dag_node(i, **m) for i, m in enumerate(modules, 1)]
    node_ids = [str(node["id"]) for node in nodes]
    linear = list(pairwise(node_ids))
    wires = require_sequence(mapping.get("wires") or linear, "wires")
    edges = [_build_dag_edge(*require_sequence(wire, "wire")) for wire in wires]
    spec = normalize_workflow({"nodes": nodes, "edges": edges})
    spec.validate()
    return spec


__all__ = ["build_workflow", "migrate_v1_to_v2"]
