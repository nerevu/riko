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
from riko.base._iterutils import partition, unzip
from riko.base._strutils import pythonise
from riko.base.exceptions import InvalidPipelineError
from riko.coercion._sequences import lower_keys
from riko.definitions._workflow import (
    require_dag_fields,
    require_dag_name,
    require_v1_loop_fields,
    require_v1_pipe_fields,
    resolve_write_mode,
)
from riko.types._collections import require_from_typed_dict, require_str
from riko.types._compiler import DagModule, Embed, EmbedRef, PipeModule
from riko.types._guards import require_mapping, require_sequence
from riko.types._workflow import (
    WORKFLOW_VERSION,
    RawEdge,
    RawEndpoint,
    RawNode,
    RawWorkflow,
)
from riko.types.modules import AnyModuleConf, CallOptions, Conf, WriteConf

from ._normalize import normalize_workflow, resolve_port

if TYPE_CHECKING:
    from logging import Logger

    from riko.definitions._workflow import Workflow
    from riko.types._compiler import PipeDag, PipeDefLike

_OPTIONS = frozenset(CallOptions.__annotations__)
_WRITE = "write"
_LOOP = "loop"
_MODULE_FAMILY = "module"
_WARNING = "migrating a pipe definition to a workflow"
logger: Logger = gogo.Gogo(__name__, monolog=True).logger

require_dag = require_from_typed_dict(DagModule)
require_pipe = require_from_typed_dict(PipeModule)
require_base_pipe = require_from_typed_dict(
    PipeModule, "write option", exclude=_OPTIONS
)
require_write_conf = require_from_typed_dict(WriteConf, extra={"keys"})


def _build_embed(embed: EmbedRef, conf: Conf | None = None) -> Embed:
    return Embed({"name": embed["type"], "conf": conf or {}})


def _migrate_pipe_module(module: PipeModule) -> RawNode:
    """Translates a ``PipeModule`` into a ``RawNode``."""
    require_v1_pipe_fields(module, "module")
    module_id = module["id"]
    conf = lower_keys(module["conf"])

    if (name := module["type"]) == _WRITE:
        write_conf = require_write_conf(cast("AnyModuleConf", conf))
        require_base_pipe(module)
        node = RawNode(
            {
                **write_conf,
                "id": module_id,
                "name": name,
                "family": _WRITE,
                "backend": "file",
            }
        )

        if mode := resolve_write_mode(write_conf):
            node["mode"] = mode

    elif name == _LOOP:
        loop = require_v1_loop_fields(module, "module")
        _embed = cast("EmbedRef", loop.get("embed", {}))
        embed = _build_embed(_embed, conf)
        node = RawNode({"id": loop["id"], "name": name, "embed": embed})
    else:
        node = RawNode({"id": module_id, "name": name, "conf": conf})

    if options := {k: v for k, v in module.items() if k in _OPTIONS and v is not None}:
        node["options"] = options

    return node


def _migrate_dag_module(index: int, module: DagModule) -> tuple[str, RawNode]:
    """Translates a ``DagModule`` into a RawNode."""
    require_dag_fields(module, "module")
    raw_id = module.get("id")
    name = require_dag_name(module, "module")
    node_id = f"sw-{index}" if raw_id is None else require_str(raw_id, "module 'id'")
    fields = DagModule(module)
    fields.pop("type", None)
    node = RawNode({**fields, "id": node_id, "name": name, "family": _MODULE_FAMILY})
    return node_id, node


def _migrate_target_port(port: str) -> str:
    """Sanitizes a ``PipeDef`` target port into the id the receiving module looks up."""
    return port if port.startswith("_") else pythonise(port)


def _migrate_wires(
    wires: object, output_ids: frozenset[str]
) -> tuple[list[RawEdge], dict[str, RawEndpoint]]:
    """Splits ``PipeDef`` wires into stream edges and ``output``-node references."""
    edges: list[RawEdge] = []
    endpoints: dict[str, RawEndpoint] = {}

    for wire in require_sequence(wires, "wires"):
        mapping = require_mapping(wire, "wire")
        src = require_mapping(mapping.get("src"), "wire 'src'")
        tgt = require_mapping(mapping.get("tgt"), "wire 'tgt'")
        src_node = require_str(src.get("moduleid"), "wire 'src' moduleid")
        src_port = resolve_port(src.get("id"), OUTPUT_PORT)
        endpoint = RawEndpoint({"node": src_node, "port": src_port})
        tgt_node = require_str(tgt.get("moduleid"), "wire 'tgt' moduleid")

        if tgt_node in output_ids:
            name = "default" if not endpoints else f"default-{len(endpoints) + 1}"
            endpoints[name] = endpoint
        else:
            port = _migrate_target_port(resolve_port(tgt.get("id"), INPUT_PORT))
            target = RawEndpoint({"node": tgt_node, "port": port})
            edges.append(RawEdge({"source": endpoint, "target": target}))

    return edges, endpoints


def migrate_v1_to_v2(pipe_def: PipeDefLike) -> Workflow:
    """
    Migrates a ``PipeDef`` into a ``Workflow``.

    Warns that a ``PipeDef`` was migrated, then returns the ``Workflow``. Legacy
    ports, the ``write`` module, and the ``PipeDef`` ``output`` node (``_OUTPUT``) are
    translated to their ``Workflow`` equivalents. Orphan and empty-graph rejection is
    left to validation.

    A module's call options become the node's ``options``, a loop's embedded module and
    its configuration become the node's ``embed``, and a ``write`` module's file-open
    mode maps to a reconcile mode. A module key with no ``Workflow`` equivalent is
    rejected rather than silently dropped.

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
    nodes = [_migrate_pipe_module(require_pipe(m)) for m in inputs]
    edges, endpoints = _migrate_wires(mapping.get("wires", ()), output_ids)
    logger.warning(_WARNING)
    raw_workflow = RawWorkflow(
        {"nodes": nodes, "edges": edges, "version": WORKFLOW_VERSION}
    )

    if endpoints:
        raw_workflow["outputs"] = endpoints

    return normalize_workflow(raw_workflow)


def _raw_edge(*wire: object) -> RawEdge:
    """Translates one ``PipeDag`` wire into a ``RawEdge``."""
    if len(wire) not in {2, 3}:
        msg = "a wire must list a source id, a target id, and optionally a target "
        msg += f"port; got {len(wire)} of them"
        raise InvalidPipelineError(msg)

    source = require_str(wire[0], "wire source id")
    target = require_str(wire[1], "wire target id")
    port = "in" if len(wire) == 2 else require_str(wire[2], "wire target port")
    source_endpoint = RawEndpoint({"node": source, "port": "out"})
    target_endpoint = RawEndpoint({"node": target, "port": port})
    return RawEdge({"source": source_endpoint, "target": target_endpoint})


def parse_dag(dag: PipeDag) -> Workflow:
    """
    Builds a validated ``Workflow`` from a ``PipeDag``.

    A DAG lists ``modules`` and, optionally, ``wires``. Each module carries its module
    ``name`` (older DAGs spell it ``type``), an optional ``id`` defaulting to ``sw-{n}``
    in listing order, an optional opaque ``conf``, and optional call ``options``.
    Anything else it carries is offered to the workflow node as-is. An unknown key is
    reported rather than dropped.

    When ``wires`` is omitted or empty the modules are chained in listing order, and the
    single leaf becomes the workflow's default output. A wire's optional third entry
    names the port it enters, so a fan-in operator such as ``union`` is expressible.

    Args:

        dag: A ``PipeDag`` with ``modules`` and optional ``wires``, each wire a
            ``[source_id, target_id]`` or ``[source_id, target_id, target_port]``
            sequence.

    Returns:

        The :class:`~riko.definitions._workflow.Workflow`.

    Raises:

        InvalidPipelineError: If ``modules`` is empty, a module carries a key its
            workflow node does not accept, a wire has the wrong number of entries, or
            the resulting workflow does not validate.

    Examples:

        >>> count = {"count": {"type": "int", "value": "3"}}
        >>> dag = {
        ...     "modules": [
        ...         {"name": "forever"},
        ...         {"name": "truncate", "conf": count},
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
        ...         {"id": "a", "name": "fetch"},
        ...         {"id": "b", "name": "fetch"},
        ...         {"id": "u", "name": "union"},
        ...     ],
        ...     "wires": [["a", "u"], ["b", "u", "in:1"]],
        ... }
        >>> [edge.target.port for edge in parse_dag(dag).edges]
        ['in', 'in:1']

    """
    mapping = require_mapping(dag, "dag")
    _modules = require_sequence(mapping.get("modules", ()), "modules")
    modules = [require_mapping(m, "module") for m in _modules]
    pairs = [_migrate_dag_module(i, require_dag(m)) for i, m in enumerate(modules, 1)]
    node_ids, nodes = unzip(pairs)
    linear = list(pairwise(node_ids))
    wires = require_sequence(mapping.get("wires") or linear, "wires")
    edges = [_raw_edge(*require_sequence(wire, "wire")) for wire in wires]
    workflow = normalize_workflow({"nodes": nodes, "edges": edges})
    workflow.validate()
    return workflow


__all__ = ["migrate_v1_to_v2", "parse_dag"]
