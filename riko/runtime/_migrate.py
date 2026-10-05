# vim: sw=4:ts=4:expandtab
"""
Construction of Workflows from terser module listings.

``parse_dag`` expands a ``PipeDag`` (``modules`` plus optional ``wires``) into a
validated ``Workflow``. ``migrate_v1_to_v2`` converts a pipe definition (``PipeDef``)
into a ``Workflow`` too; it is a rescue/conversion tool, not a live loader, so
migration warns and only ever returns a ``Workflow``.

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
        >>> workflow = migrate_v1_to_v2(pipe_def)
        >>> list(workflow.nodes)
        ['sw-1']
        >>> workflow.outputs["default"]
        Endpoint(node='sw-1', port='out')

"""

from __future__ import annotations

from itertools import pairwise
from typing import TYPE_CHECKING, cast

import pygogo as gogo

from riko.base._config import INPUT_PORT, OUTPUT_MODULE, OUTPUT_PORT
from riko.base._iterutils import partition
from riko.base._strutils import pythonise
from riko.base.exceptions import InvalidPipelineError
from riko.coercion._sequences import lower_keys, require_sequence
from riko.parsing._dotdict import DotDict
from riko.types._collections import require_str
from riko.types._guards import require_mapping
from riko.types._workflow import (
    WORKFLOW_VERSION,
    RawEdge,
    RawEndpoint,
    RawNode,
    RawWorkflow,
)
from riko.types.modules import AnyModuleConf, Embed, ModuleOptions

from ._normalize import normalize_workflow

if TYPE_CHECKING:
    from logging import Logger

    from riko.definitions._workflow import Workflow
    from riko.types._compiler import DagModule, PipeDag, PipeDefLike
    from riko.types.modules import Conf

_WRITE_TYPE = "write"
_LOOP_TYPE = "loop"
_MODULE_TYPE = "module"
_WRITE_CONF_KEYS = frozenset({"dest", "fmt", "mode", "keys"})
_WRITE_MODES = {"w": "replace", "a": "append"}
_STRUCTURAL_KEYS = frozenset({"id", "type", "conf"})
_OPTION_KEYS = frozenset(ModuleOptions.__annotations__)
_WARNING = "migrating a pipe definition to a workflow"
logger: Logger = gogo.Gogo(__name__, monolog=True).logger


def _migrate_write_mode(mode: object) -> str:
    """Translates a ``PipeDef`` file-open write mode into a reconcile mode."""
    head = mode[:1].lower() if isinstance(mode, str) else ""

    if (canonical := _WRITE_MODES.get(head)) is None:
        msg = f"cannot migrate pipe definition write mode: {mode!r}"
        raise InvalidPipelineError(msg)

    return canonical


def _migrate_write(
    module_id: str, name: str, conf: AnyModuleConf, **extra: object
) -> RawNode:
    """Translates a ``PipeDef`` ``write`` module into a shorthand ``WriteNode``."""
    if unsupported := sorted(set(extra) | (set(conf) - _WRITE_CONF_KEYS)):
        msg = f"cannot migrate pipe definition write option(s): {unsupported}"
        raise InvalidPipelineError(msg)

    node = RawNode(
        {"id": module_id, "name": name, "type": _WRITE_TYPE, "backend": "file"}
    )

    if (mode := conf.get("mode")) is not None:
        node["mode"] = _migrate_write_mode(mode)

    for k in ("dest", "fmt", "keys"):
        if (value := conf.get(k)) is not None:
            node[k] = value

    return node


def _migrate_embed(embed: object, conf: Conf | None = None) -> Embed:
    """Translates a ``PipeDef`` loop's embedded module reference into a node embed."""
    mapping = require_mapping(embed, "loop 'embed'")
    name = require_str(mapping.get("type"), "loop embed 'type'")
    return Embed({"name": name, "conf": conf or {}})


def _migrate_pipe(
    module_id: str, name: str, conf: Conf | None = None, **extra: object
) -> RawNode:
    """Translates a ``PipeDef`` pipe module into a shorthand module ``RawNode``."""
    options = {k: extra.pop(k) for k in _OPTION_KEYS.intersection(extra)}
    embed = extra.pop("embed", None) if name == _LOOP_TYPE else None
    node = RawNode({"id": module_id, "name": name})
    node["conf"] = extra

    if embed is None:
        node["conf"].update(conf or {})
    else:
        node["embed"] = _migrate_embed(embed, conf)

    if options:
        node["options"] = options

    return node


def _migrate_module(module: DagModule) -> RawNode:
    """Translates one ``PipeDef`` module mapping into a ``RawNode``."""
    module_id = require_str(module.get("id"), "module 'id'")
    name = require_str(module.get("type"), "module 'type'")
    extra = {k: v for k, v in module.items() if k not in _STRUCTURAL_KEYS}

    if conf := module.get("conf"):
        conf = lower_keys(require_mapping(conf, "module conf"))

    if name == _WRITE_TYPE:
        conf = cast("AnyModuleConf", DotDict(conf or {}))
        node = _migrate_write(module_id, name, conf, **extra)
    else:
        node = _migrate_pipe(module_id, name, conf, **extra)

    return node


def _migrate_target_port(port: str) -> str:
    """Sanitizes a ``PipeDef`` target port into the id the receiving module looks up."""
    return port if port.startswith("_") else pythonise(port)


def _resolve_port(port: object, default: str) -> str:
    """Resolves a ``PipeDef`` wire endpoint port."""
    return default if port is None else str(port)


def _migrate_wires(
    wires: object, output_ids: frozenset[str]
) -> tuple[list[RawEdge], dict[str, RawEndpoint]]:
    """Splits ``PipeDef`` wires into stream edges and terminal-output references."""
    edges: list[RawEdge] = []
    endpoints: dict[str, RawEndpoint] = {}

    for wire in require_sequence(wires, "wires"):
        mapping = require_mapping(wire, "wire")
        src = require_mapping(mapping.get("src"), "wire 'src'")
        tgt = require_mapping(mapping.get("tgt"), "wire 'tgt'")
        endpoint = RawEndpoint(
            {
                "node": require_str(src.get("moduleid"), "wire 'src' moduleid"),
                "port": _resolve_port(src.get("id"), OUTPUT_PORT),
            }
        )
        tgt_node = require_str(tgt.get("moduleid"), "wire 'tgt' moduleid")

        if tgt_node in output_ids:
            name = "default" if not endpoints else f"default-{len(endpoints) + 1}"
            endpoints[name] = endpoint
        else:
            port = _migrate_target_port(_resolve_port(tgt.get("id"), INPUT_PORT))
            target = RawEndpoint({"node": tgt_node, "port": port})
            edges.append(RawEdge({"source": endpoint, "target": target}))

    return edges, endpoints


def migrate_v1_to_v2(pipe_def: PipeDefLike) -> Workflow:
    """
    Migrates a ``PipeDef`` into a ``Workflow``.

    Warns that a ``PipeDef`` was migrated, then returns the ``Workflow``. Legacy
    ports, the ``write`` module, and the terminal ``_OUTPUT`` node are translated to
    their ``Workflow`` equivalents. Orphan and empty-graph rejection is left to
    validation.

    A module's call options become the node's ``options``, a loop's embedded module and
    its configuration become the node's ``embed``, and any other module-level key folds
    into the node's configuration. A ``write`` module's file-open mode maps to a
    reconcile mode, and a ``write`` carrying an option with no ``Workflow`` equivalent
    is rejected rather than silently dropped.

    Args:

        pipe_def: A ``PipeDef`` with ``modules`` and ``src``/``tgt`` ``wires``;
            editor ``layout``/``terminaldata`` are ignored.

    Returns:

        The :class:`~riko.definitions._workflow.Workflow`.

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
        >>> workflow = migrate_v1_to_v2(pipe_def)
        >>> node = workflow.nodes["sw-2"]
        >>> node.backend.value, node.fmt.value
        ('file', 'json')
        >>> workflow.outputs["default"]
        Endpoint(node='sw-2', port='out')

    """
    mapping = require_mapping(pipe_def, "pipe definition")
    raw_modules = require_sequence(mapping.get("modules", ()), "modules")
    modules = [require_mapping(m, "module") for m in raw_modules]
    ouputs, inputs = partition(modules, lambda m: m.get("type") == OUTPUT_MODULE)

    output_ids = frozenset(require_str(m.get("id"), "module 'id'") for m in ouputs)
    nodes = [_migrate_module(cast("DagModule", m)) for m in inputs]
    edges, endpoints = _migrate_wires(mapping.get("wires", ()), output_ids)
    logger.warning(_WARNING)
    raw_workflow = RawWorkflow(
        {"nodes": nodes, "edges": edges, "version": WORKFLOW_VERSION}
    )

    if endpoints:
        raw_workflow["outputs"] = endpoints

    return normalize_workflow(raw_workflow)


def _raw_node(index: int, module: DagModule) -> tuple[str, RawNode]:
    """Translates one ``PipeDag`` module into a RawNode."""
    raw_id = module.get("id")
    node_id = f"sw-{index}" if raw_id is None else require_str(raw_id, "module 'id'")
    name = require_str(module.get("type"), "module 'type'")
    node = RawNode(
        {
            "id": node_id,
            "name": name,
            "type": _MODULE_TYPE,
            "conf": module.get("conf", {}),
            "options": module.get("options", {}),
        }
    )
    return node_id, node


def _raw_edge(*wire: object) -> RawEdge:
    """Translates one ``PipeDag`` wire into a ``RawEdge``."""
    if len(wire) not in {2, 3}:
        msg = "a wire must list a source id, a target id, and optionally a target "
        msg += f"port; got {len(wire)} of them"
        raise InvalidPipelineError(msg)

    source = require_str(wire[0], "wire source id")
    target = require_str(wire[1], "wire target id")
    port = "in" if len(wire) == 2 else require_str(wire[2], "wire target port")

    return RawEdge(
        {
            "source": {"node": source, "port": "out"},
            "target": {"node": target, "port": port},
        }
    )


def parse_dag(dag: PipeDag) -> Workflow:
    """
    Builds a validated ``Workflow`` from a ``PipeDag``.

    A DAG lists ``modules`` and, optionally, ``wires``. Each module carries its module
    ``type``, an optional ``id`` defaulting to ``sw-{n}`` in listing order, an optional
    opaque ``conf``, and optional call ``options``; anything else it carries is offered
    to the workflow node as-is, so an unknown key is reported rather than dropped. When
    ``wires`` is omitted or empty the modules are chained in listing order, and the
    single leaf becomes the workflow's default output. A wire's optional third entry
    names the port it enters, so a fan-in operator such as ``union`` is expressible.

    Args:

        dag: A ``PipeDag`` with ``modules`` and optional ``wires``, each wire a
            ``[source_id, target_id]`` or ``[source_id, target_id, target_port]``
            sequence.

    Returns:

        The :class:`~riko.definitions._workflow.Workflow`.

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
        >>> workflow = parse_dag(dag)
        >>> list(workflow.nodes)
        ['sw-1', 'sw-2']
        >>> workflow.outputs["default"]
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
        >>> [edge.target.port for edge in parse_dag(dag).edges]
        ['in', 'in:1']

    """
    mapping = require_mapping(dag, "dag")
    _modules = require_sequence(mapping.get("modules", ()), "modules")
    modules = [require_mapping(m, "module") for m in _modules]
    pairs = [_raw_node(i, cast("DagModule", m)) for i, m in enumerate(modules, 1)]

    try:
        node_ids, nodes = zip(*pairs, strict=True)
    except ValueError:
        node_ids, nodes = (), ()

    linear = list(pairwise(node_ids))
    wires = require_sequence(mapping.get("wires") or linear, "wires")
    edges = [_raw_edge(*require_sequence(wire, "wire")) for wire in wires]
    workflow = normalize_workflow({"nodes": nodes, "edges": edges})
    workflow.validate()
    return workflow


__all__ = ["migrate_v1_to_v2", "parse_dag"]
