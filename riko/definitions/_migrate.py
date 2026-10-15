# vim: sw=4:ts=4:expandtab
"""
Translation of terser module listings into shorthand workflow mappings.

A ``PipeDag`` (``modules`` plus optional ``wires``) and a pipe definition
(``PipeDef``) are each expanded into the ``RawWorkflow`` the normalization boundary
reads. Migrating a ``PipeDef`` is a rescue/conversion step, not a live loader, so it
warns.

"""

from __future__ import annotations

from itertools import chain, pairwise
from typing import TYPE_CHECKING, cast

import pygogo as gogo

from riko.base._config import INPUT_PORT, OUTPUT_MODULE, OUTPUT_PORT
from riko.base._iterutils import partition, unzip
from riko.base._strutils import pythonise
from riko.base.exceptions import InvalidPipelineError
from riko.types._collections import (
    def_from_require,
    require_from_typed_dict,
    require_str,
    typed_dict_keys,
)
from riko.types._compiler import DagModule, Embed, EmbedRef, PipeModule
from riko.types._guards import is_mapping, require_mapping, require_sequence
from riko.types._workflow import (
    WORKFLOW_VERSION,
    RawEdge,
    RawEndpoint,
    RawNode,
    RawWorkflow,
)
from riko.types.modules import Conf, RawCallOptions, WriteConf, require_module_conf

from ._nodes import optional_str
from ._normalize import resolve_port
from ._write import WriteMode

if TYPE_CHECKING:
    from logging import Logger

    from riko.types._compiler import PipeDag, PipeDefLike

_OPTIONS = frozenset(chain.from_iterable(typed_dict_keys(RawCallOptions)))
_WRITE = "write"
_LOOP = "loop"
_MODULE_FAMILY = "module"
_WARNING = "migrating a pipe definition to a workflow"
_WRITE_MODES = {"w": WriteMode.REPLACE, "a": WriteMode.APPEND}

logger: Logger = gogo.Gogo(__name__, monolog=True).logger

_optional_mapping = def_from_require(require_mapping)
_require_embed_ref = require_from_typed_dict(EmbedRef)

require_dag = require_from_typed_dict(DagModule)
require_pipe = require_from_typed_dict(PipeModule)
require_base_pipe = require_from_typed_dict(
    PipeModule, "write option", exclude=_OPTIONS
)
require_write_conf = require_from_typed_dict(WriteConf, extra={"keys"})


def _lower_keys[T](obj: T) -> T:
    """Lowercases every all-uppercase string key, at any depth."""
    if is_mapping(obj):
        result = {
            (k.lower() if isinstance(k, str) and k.isupper() else k): _lower_keys(v)
            for k, v in obj.items()
        }
    elif isinstance(obj, list):
        result = [_lower_keys(v) for v in obj]
    else:
        result = obj

    return cast("T", result)


def _parse_write_mode(mode: str) -> WriteMode:
    """Translates a ``PipeDef`` file-open write mode into a ``WriteMode``."""
    head = mode[:1].lower()

    if (write_mode := _WRITE_MODES.get(head)) is None:
        msg = f"cannot migrate pipe definition write mode: {mode!r}"
        raise InvalidPipelineError(msg)

    return write_mode


def _require_embed_ref_fields(value: EmbedRef, what: str = "embed") -> EmbedRef:
    """Validates an EmbedRef's keys."""
    require_str(value["type"], f"{what} 'type'")
    require_str(value["id"], f"{what} 'id'")
    return value


def _require_dag_name(value: DagModule, what: str = "dag module") -> str:
    """
    Requires a ``DagModule``'s module name, read from ``name`` or its older ``type``.

    Raises:

        InvalidPipelineError: If neither key is present, or both are and disagree.

    """
    name, type_ = value.get("name"), value.get("type")

    if name is None and type_ is None:
        raise InvalidPipelineError(f"{what} needs a 'name'")
    elif name is not None and type_ is not None and name != type_:
        msg = f"conflicting {what} 'name'/'type': {name!r} and {type_!r}"
        raise InvalidPipelineError(msg)

    return require_str(type_ if name is None else name, f"{what} 'name'")


def _require_dag_fields(value: DagModule, what: str = "dag module") -> DagModule:
    """Validates a ``DagModule``'s keys."""
    optional_str(value.get("id"))
    _require_dag_name(value, what)
    _optional_mapping(value.get("conf"))
    return value


def _get_write_mode(value: WriteConf) -> WriteMode | None:
    """Translates a ``WriteConf``'s mode into a ``WriteMode`` (``None`` when absent)."""
    mode = optional_str(value.get("mode"))
    return None if mode is None else _parse_write_mode(mode)


def _require_v1_pipe_fields(value: PipeModule, what: str = "module") -> PipeModule:
    """Validates a ``PipeModule``'s keys."""
    require_str(value["id"], f"{what} 'id'")
    require_str(value["type"], f"{what} 'type'")
    require_mapping(value["conf"], f"{what} 'conf'")
    return value


def _require_v1_loop_fields(value: PipeModule, what: str = "loop module") -> PipeModule:
    """Validates a ``loop`` ``PipeModule``'s embed."""
    embed = require_mapping(value.get("embed"), f"{what} 'embed'")
    _require_embed_ref_fields(_require_embed_ref(embed))
    return value


def _build_embed(embed: EmbedRef, conf: Conf | None = None) -> Embed:
    return Embed({"name": embed["type"], "conf": conf or {}})


def _migrate_pipe_module(module: PipeModule) -> RawNode:
    """Translates a ``PipeModule`` into a ``RawNode``."""
    _require_v1_pipe_fields(module, "module")
    module_id = module["id"]
    conf = _lower_keys(module["conf"])

    if (name := module["type"]) == _WRITE:
        write_conf = require_write_conf(require_module_conf(conf))
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

        if mode := _get_write_mode(write_conf):
            node["mode"] = mode

    elif name == _LOOP:
        loop = _require_v1_loop_fields(module, "module")
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
    _require_dag_fields(module, "module")
    raw_id = module.get("id")
    name = _require_dag_name(module, "module")
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


def migrate_pipe_def(pipe_def: PipeDefLike) -> RawWorkflow:
    """
    Migrates a ``PipeDef`` into the shorthand workflow mapping it describes.

    Warns that a ``PipeDef`` was migrated. Legacy ports, the ``write`` module, and the
    ``PipeDef`` ``output`` node (``_OUTPUT``) are translated to their ``Workflow``
    equivalents.

    Args:

        pipe_def: A ``PipeDef`` with ``modules`` and ``src``/``tgt`` ``wires``.

    Returns:

        The ``RawWorkflow`` for the normalization boundary.

    Raises:

        InvalidPipelineError: If a module or wire is malformed, or a module key has
            no ``Workflow`` equivalent.

    """
    mapping = require_mapping(pipe_def, "pipe definition")
    raw_modules = require_sequence(mapping.get("modules", ()), "modules")
    modules = [require_mapping(m, "module") for m in raw_modules]
    outputs, inputs = partition(modules, lambda m: m.get("type") == OUTPUT_MODULE)

    output_ids = frozenset(require_str(m.get("id"), "module 'id'") for m in outputs)
    nodes = [_migrate_pipe_module(require_pipe(m)) for m in inputs]
    edges, endpoints = _migrate_wires(mapping.get("wires", ()), output_ids)
    logger.warning(_WARNING)
    raw = RawWorkflow({"nodes": nodes, "edges": edges, "version": WORKFLOW_VERSION})

    if endpoints:
        raw["outputs"] = endpoints

    return raw


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


def parse_dag_graph(dag: PipeDag) -> RawWorkflow:
    """
    Expands a ``PipeDag`` into the shorthand workflow mapping it describes.

    When ``wires`` is omitted or empty the modules are chained in listing order.

    Args:

        dag: A ``PipeDag`` with ``modules`` and optional ``wires``.

    Returns:

        The ``RawWorkflow`` for the normalization boundary.

    Raises:

        InvalidPipelineError: If a module carries a key its workflow node does not
            accept, or a wire has the wrong number of entries.

    """
    mapping = require_mapping(dag, "dag")
    _modules = require_sequence(mapping.get("modules", ()), "modules")
    modules = [require_mapping(m, "module") for m in _modules]
    pairs = [_migrate_dag_module(i, require_dag(m)) for i, m in enumerate(modules, 1)]
    node_ids, nodes = unzip(pairs)
    linear = list(pairwise(node_ids))
    wires = require_sequence(mapping.get("wires") or linear, "wires")
    edges = [_raw_edge(*require_sequence(wire, "wire")) for wire in wires]
    return RawWorkflow({"nodes": nodes, "edges": edges})


__all__ = ["migrate_pipe_def", "parse_dag_graph"]
