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
from math import isfinite
from typing import TYPE_CHECKING, cast

from fastjsonschema import JsonSchemaValueException
from fastjsonschema import compile as fjs_compile

from riko.base._config import DEFAULT_OUTPUT, INPUT_PORT, OUTPUT_MODULE, OUTPUT_PORT
from riko.base._exceptions import InvalidPipelineError
from riko.base._funcutils import map_keys_and_values, map_values
from riko.base._guards import is_mapping, require_listlike, require_mapping
from riko.base._iterutils import gen_non_null, partition, unzip
from riko.base._logging import get_logger
from riko.base._require_guards import (
    def_from_require,
    require_from_typed_dict,
    require_str,
    typed_dict_keys,
)
from riko.base._strutils import pythonise
from riko.types._options import RawCallOptions
from riko.types._pipedef import (
    DagModule,
    Embed,
    EmbedRef,
    ModuleLike,
    OutputModule,
    PipeDag,
    PipeDagLike,
    PipeDef,
    PipeModule,
    Wire,
    WireEndpoint,
)
from riko.types._workflow import (
    WORKFLOW_VERSION,
    RawEdge,
    RawEndpoint,
    RawNode,
    RawWorkflow,
)
from riko.types.modules import WriteConf, is_type_value, require_module_conf

from ._nodes import optional_str
from ._normalize import resolve_port
from ._write import WriteMode

if TYPE_CHECKING:
    from logging import Logger

    from riko.types._frozendict import InputSchema, InputSchemas, JSONValue
    from riko.types._pipedef import PipeDefLike, Wires
    from riko.types.modules import Conf, InputRawConf

    from ._workflow_definition import RawOutputs, RawPortEdges

logger: Logger = get_logger(__name__)

_OPTIONS = frozenset(chain.from_iterable(typed_dict_keys(RawCallOptions)))
_WRITE = "write"
_LOOP = "loop"
_INPUT = "input"
_DEFAULT_INPUT_NAME = "content"
_MODULE_FAMILY = "module"
_WARNING = "migrating a pipe definition to a workflow"
_WRITE_MODES = {"w": WriteMode.REPLACE, "a": WriteMode.APPEND}
_STRING_SCHEMA: InputSchema = {"type": "string"}
_NUMBER_SCHEMA: InputSchema = {"type": "number"}
_V1_BOOLEANS = {
    "true": True,
    "yes": True,
    "1": True,
    "false": False,
    "no": False,
    "0": False,
}

_V1_INPUT_SCHEMAS: dict[str, InputSchema] = {
    "int": {"type": "integer"},
    "float": _NUMBER_SCHEMA,
    "decimal": _NUMBER_SCHEMA,
    "bool": {"type": "boolean"},
    "url": {"type": "string", "format": "uri"},
}

_optional_mapping = def_from_require(require_mapping)
_require_embed_ref = require_from_typed_dict(EmbedRef)

require_dag = require_from_typed_dict(DagModule)
require_pipe = require_from_typed_dict(PipeModule)
require_base_pipe = require_from_typed_dict(
    PipeModule, "write option", exclude=_OPTIONS
)
require_write_conf = require_from_typed_dict(WriteConf, extra={"keys"})
_require_pipe_def = require_from_typed_dict(PipeDef, "pipe definition")
_require_pipe_dag = require_from_typed_dict(PipeDag, "dag")
_require_wire = require_from_typed_dict(Wire, "wire")
_require_wire_endpoint = require_from_typed_dict(WireEndpoint, "wire endpoint")
_require_output_module = require_from_typed_dict(OutputModule, "`PipeDef` output node")


def _lower_key[K](key: K) -> K | str:
    """Lowercases a key when it is an all-uppercase string."""
    return key.lower() if isinstance(key, str) and key.isupper() else key


def _lower_keys[T](obj: T) -> T:
    """
    Lowercases every all-uppercase string key at any depth.

    Raises:

        InvalidPipelineError: If lowercasing makes two keys of one mapping collide.

    """
    if is_mapping(obj):
        result = map_keys_and_values(_lower_key, _lower_keys, obj)

        if len(result) < len(obj):
            msg = f"keys that differ only in case collide: {sorted(map(str, obj))}"
            raise InvalidPipelineError(msg)
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
    """Requires an EmbedRef's keys to be well-formed."""
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
    """Requires a ``DagModule``'s keys to be well-formed."""
    optional_str(value.get("id"))
    _require_dag_name(value, what)
    _optional_mapping(value.get("conf"))
    return value


def _get_write_mode(value: WriteConf) -> WriteMode | None:
    """Translates a ``WriteConf``'s mode into a ``WriteMode`` (``None`` when absent)."""
    mode = optional_str(value.get("mode"))
    return None if mode is None else _parse_write_mode(mode)


def _require_v1_pipe_fields(value: PipeModule, what: str = "module") -> PipeModule:
    """Requires a ``PipeModule``'s keys to be well-formed."""
    require_str(value["id"], f"{what} 'id'")
    require_str(value["type"], f"{what} 'type'")
    require_mapping(value["conf"], f"{what} 'conf'")
    return value


def _require_v1_loop_embed(value: PipeModule, what: str = "loop module") -> EmbedRef:
    """Requires a ``loop`` ``PipeModule``'s embed to be well-formed."""
    embed = require_mapping(value.get("embed"), f"{what} 'embed'")
    return _require_embed_ref_fields(_require_embed_ref(embed))


def _build_embed(embed: EmbedRef, conf: Conf | None = None) -> Embed:
    return Embed({"name": embed["type"], "conf": conf or {}})


def _get_conf_value(value: object) -> object:
    """Gets a ``PipeDef`` configuration value from its ``ConfArg`` form or as given."""
    return value["value"] if is_mapping(value) and is_type_value(value) else value


def _parse_v1_default(json_type: JSONValue, text: str) -> JSONValue:
    """Parses a ``PipeDef`` input default as a JSON type, or ``None`` if it can't."""
    try:
        match json_type:
            case "integer":
                parsed: JSONValue = int(text)
            case "number":
                parsed = number if isfinite(number := float(text)) else None
            case "boolean":
                parsed = _V1_BOOLEANS.get(text.lower())
            case _:
                parsed = text
    except ValueError:
        parsed = None

    return parsed


def _is_accepted(schema: InputSchema, value: JSONValue) -> bool:
    """Whether ``schema`` accepts ``value``."""
    try:
        fjs_compile(schema)(value)
    except JsonSchemaValueException:
        accepted = False
    else:
        accepted = True

    return accepted


def _build_v1_input_schema(v1_type: object, default: object) -> InputSchema:
    """
    Builds an input's schema from a ``PipeDef`` input type and default.

    An unknown type, or a default that does not fit the type, produces a string schema.

    """
    typed = _V1_INPUT_SCHEMAS.get(str(v1_type), _STRING_SCHEMA)

    if default is None:
        schema = typed
    elif (parsed := _parse_v1_default(typed["type"], str(default))) is None:
        schema = {**_STRING_SCHEMA, "default": str(default)}
    elif _is_accepted(typed, parsed):
        schema = {**typed, "default": parsed}
    else:
        schema = {**_STRING_SCHEMA, "default": str(default)}

    return schema


def migrate_input_conf(conf: Conf) -> tuple[str, InputSchema, InputRawConf]:
    """
    Migrates a ``PipeDef`` ``input`` module's configuration into a workflow input.

    Converts the module's ``type`` as follows: ``int`` to integer, ``float`` and
    ``decimal`` to number, ``bool`` to boolean, and ``url`` to URI string. Converts the
    default to match. Any other type, or a default that does not convert, produces a
    string schema. The node keeps its ``type``.

    Args:

        conf: The module configuration (bare or in ``ConfArg`` form).

    Returns:

        The input name, the input's schema, and the node configuration (dict with
        ``input_key`` and ``type`` keys).

    Raises:

        InvalidPipelineError: If the input name or prompt is not a string, or the
            ``type`` is a mapping but not a ``ConfArg``.

    Examples:

        >>> _name = {"type": "text", "value": "q"}
        >>> conf = {"name": _name, "default": "5", "prompt": "Count:", "type": "int"}
        >>> name, schema, node_conf = migrate_input_conf(conf)
        >>> name
        'q'
        >>> schema
        {'type': 'integer', 'default': 5, 'description': 'Count:'}
        >>> sorted(node_conf)
        ['input_key', 'type']

    """
    values = map_values(_get_conf_value, conf)
    names = (values.get(key) for key in ("name", "input_key"))
    found = next(gen_non_null(names), _DEFAULT_INPUT_NAME)
    name = require_str(found, "input 'name'")
    node_conf: InputRawConf = {"input_key": {"type": "text", "value": name}}

    if (type_ := conf.get("type")) is not None:
        if is_mapping(type_) and is_type_value(type_):
            node_conf["type"] = type_
        elif is_mapping(type_):
            raise InvalidPipelineError("input 'type' must be a string or a ConfArg")
        else:
            node_conf["type"] = {"type": "text", "value": type_}

    schema = dict(_build_v1_input_schema(values.get("type"), values.get("default")))

    if (prompt := values.get("prompt")) is not None:
        schema["description"] = require_str(prompt, "input 'prompt'")

    return name, schema, node_conf


def _migrate_pipe_module(module: PipeModule) -> tuple[RawNode, InputSchemas]:
    """Translates a ``PipeModule`` into a ``RawNode`` and its inputs' schemas."""
    _require_v1_pipe_fields(module, "module")
    mid = module["id"]
    conf = _lower_keys(module["conf"])
    schemas: InputSchemas = {}

    if (name := module["type"]) == _WRITE:
        write_conf = require_write_conf(require_module_conf(conf))
        require_base_pipe(module)
        node = RawNode(
            {**write_conf, "id": mid, "name": name, "family": _WRITE, "backend": "file"}
        )

        if mode := _get_write_mode(write_conf):
            node["mode"] = mode

    elif name == _LOOP:
        embed = _build_embed(_require_v1_loop_embed(module, "module"), conf)
        node = RawNode({"id": mid, "name": name, "embed": embed})
    elif name == _INPUT:
        input_name, schema, input_conf = migrate_input_conf(conf)
        schemas[input_name] = schema
        node = RawNode({"id": mid, "name": name, "conf": input_conf})
    else:
        node = RawNode({"id": mid, "name": name, "conf": conf})

    if options := {k: v for k, v in module.items() if k in _OPTIONS and v is not None}:
        node["options"] = options

    return node, schemas


def _merge_input_schemas(*schemas: InputSchemas) -> InputSchemas:
    """
    Merges the input schemas of several modules into one.

    Raises:

        InvalidPipelineError: If two modules give the same input different schemas.

    """
    merged: InputSchemas = {}

    for name, schema in chain.from_iterable(s.items() for s in schemas):
        if merged.setdefault(name, schema) != schema:
            msg = f"pipe definition gives input {name!r} two different schemas"
            raise InvalidPipelineError(msg)

    return merged


def _migrate_dag_module(index: int, module: DagModule) -> tuple[str, RawNode]:
    """Translates a ``DagModule`` into a RawNode."""
    _require_dag_fields(module, "module")
    mid = module.get("id")
    name = _require_dag_name(module, "module")
    node_id = f"sw-{index}" if mid is None else require_str(mid, "module 'id'")
    fields = DagModule(module)
    fields.pop("type", None)
    node = RawNode({**fields, "id": node_id, "name": name, "family": _MODULE_FAMILY})
    return node_id, node


def _migrate_target_port(port: str) -> str:
    """Sanitizes a ``PipeDef`` target port into the id the receiving module looks up."""
    return port if port.startswith("_") else pythonise(port)


def _migrate_wires(wires: Wires, *output_ids: str) -> tuple[RawPortEdges, RawOutputs]:
    """Splits ``PipeDef`` wires into stream edges and ``output``-node references."""
    edges: RawPortEdges = []
    endpoints: RawOutputs = {}
    ids = frozenset(output_ids)

    for _wire in require_listlike(wires, "wires"):
        wire = _require_wire(require_mapping(_wire, "wire"))
        src = _require_wire_endpoint(require_mapping(wire["src"], "wire 'src'"))
        tgt = _require_wire_endpoint(require_mapping(wire["tgt"], "wire 'tgt'"))
        src_node = require_str(src.get("moduleid"), "wire 'src' moduleid")
        src_port = resolve_port(src.get("id"), OUTPUT_PORT)
        endpoint = RawEndpoint({"node": src_node, "port": src_port})
        tgt_node = require_str(tgt.get("moduleid"), "wire 'tgt' moduleid")

        if tgt_node in ids:
            suffix = f"-{len(endpoints) + 1}" if endpoints else ""
            name = f"{DEFAULT_OUTPUT}{suffix}"
            endpoints[name] = endpoint
        else:
            port = _migrate_target_port(resolve_port(tgt.get("id"), INPUT_PORT))
            target = RawEndpoint({"node": tgt_node, "port": port})
            edges.append(RawEdge({"source": endpoint, "target": target}))

    return edges, endpoints


def _require_output_id(module: ModuleLike) -> str:
    """Requires a ``PipeDef`` ``output`` module to be bare and gets its id."""
    output = _require_output_module(module)

    if output.get("conf"):
        raise InvalidPipelineError("the `PipeDef` output node takes no 'conf'")

    return require_str(output["id"], "module 'id'")


def parse_pipedef(_pipe_def: PipeDefLike) -> RawWorkflow:
    """
    Migrates a ``PipeDef`` into the shorthand workflow mapping it describes.

    Warns that a ``PipeDef`` was migrated. Legacy ports, the ``write`` module, and the
    ``PipeDef`` ``output`` node (``_OUTPUT``) are translated to their ``Workflow``
    equivalents. Each ``input`` module becomes a workflow input named by its ``name``.
    The node keeps ``input_key`` and ``type``.

    Args:

        pipe_def: A ``PipeDef`` with ``modules`` and ``src``/``tgt`` ``wires``.

    Returns:

        The ``RawWorkflow`` for the normalization boundary.

    Raises:

        InvalidPipelineError: If a module or wire is malformed, a key has no
            ``Workflow`` equivalent, two configuration keys differ only in case, or two
            ``input`` modules give one input different schemas.

    """
    pipe_def = _require_pipe_def(require_mapping(_pipe_def, "pipe definition"))
    _modules = require_listlike(pipe_def["modules"], "modules")
    modules = [require_mapping(m, "module") for m in _modules]

    outputs, others = partition(modules, lambda m: m.get("type") == OUTPUT_MODULE)
    output_ids = map(_require_output_id, outputs)
    nodes, schemas = unzip(_migrate_pipe_module(require_pipe(m)) for m in others)
    input_schemas = _merge_input_schemas(*schemas)
    edges, endpoints = _migrate_wires(pipe_def.get("wires", ()), *output_ids)
    logger.warning(_WARNING)
    raw = RawWorkflow({"nodes": nodes, "edges": edges, "version": WORKFLOW_VERSION})

    if endpoints:
        raw["outputs"] = endpoints

    if input_schemas:
        raw["input_schemas"] = input_schemas

    return raw


def _raw_edge(*wire: str) -> RawEdge:
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


def parse_pipedag(_dag: PipeDagLike) -> RawWorkflow:
    """
    Expands a ``PipeDag`` into the shorthand workflow mapping it describes.

    When ``wires`` is omitted or empty the modules are chained in listing order.

    Args:

        dag: A ``PipeDag`` with ``modules`` and optional ``wires``.

    Returns:

        The ``RawWorkflow`` for the normalization boundary.

    Raises:

        InvalidPipelineError: If the input or a module carries a key its workflow
            doesn't accept, or a wire has the wrong number of entries.

    """
    dag = _require_pipe_dag(require_mapping(_dag, "dag"))
    _modules = require_listlike(dag["modules"], "modules")
    modules = [require_mapping(m, "module") for m in _modules]

    pairs = [_migrate_dag_module(i, require_dag(m)) for i, m in enumerate(modules, 1)]
    node_ids, nodes = unzip(pairs)
    linear = list(pairwise(node_ids))
    wires = require_listlike(dag.get("wires") or linear, "wires")
    edges = [_raw_edge(*require_listlike(wire, "wire")) for wire in wires]
    return RawWorkflow({"nodes": nodes, "edges": edges})


__all__ = ["migrate_input_conf", "parse_pipedag", "parse_pipedef"]
