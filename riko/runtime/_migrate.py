# vim: sw=4:ts=4:expandtab
"""
Offline migration of released Workflow v1 pipe definitions to canonical v2.

``migrate_v1_to_v2`` converts a legacy ``PipeDef`` into a canonical ``WorkflowSpec``.
It is a rescue/conversion tool, not a live loader: v1 is not a maintained runtime
ingress, so migration warns and emits v2 only.

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

from typing import TYPE_CHECKING

import pygogo as gogo

from riko.base._config import INPUT_PORT, OUTPUT_MODULE, OUTPUT_PORT
from riko.base._iterutils import partition
from riko.base.exceptions import InvalidPipelineError
from riko.coercion._sequences import require_sequence
from riko.types._collections import require_str
from riko.types._guards import require_mapping
from riko.types._workflow import WORKFLOW_VERSION

from ._compile import _lower_keys
from ._normalize import normalize_workflow

if TYPE_CHECKING:
    from collections.abc import Mapping
    from logging import Logger

    from riko.definitions._workflow import WorkflowSpec
    from riko.types._compiler import PipeDefLike

_WRITE_TYPE = "write"
_WRITE_CONF_KEYS = frozenset({"dest", "fmt", "mode", "keys"})
_WRITE_MODES = {"w": "replace", "a": "append"}
_STRUCTURAL_KEYS = frozenset({"id", "type", "conf"})
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


def _migrate_module(**module: object) -> dict[str, object]:
    """Translates one v1 module mapping into a v2 authoring node mapping."""
    module_id = require_str(module.get("id"), "module 'id'")
    name = require_str(module.get("type"), "module 'type'")
    conf = _lower_keys(require_mapping(module.get("conf") or {}, "module conf"))
    extra = {k: v for k, v in module.items() if k not in _STRUCTURAL_KEYS}

    if name == _WRITE_TYPE:
        node = _migrate_write(module_id, name, conf, **extra)
    else:
        node = {"id": module_id, "name": name, "conf": {**extra, **conf}}

    return node


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
            target = {"node": tgt_node, "port": str(tgt.get("id", INPUT_PORT))}
            edges.append({"source": source, "target": target})

    return edges, outputs


def migrate_v1_to_v2(pipe_def: PipeDefLike) -> WorkflowSpec:
    """
    Migrates a released Workflow v1 pipe definition into a canonical v2 spec.

    Warns that a v1 document was migrated, then returns the canonical spec. Legacy
    ports, the ``write`` module, and the terminal ``_OUTPUT`` node are translated to
    their v2 equivalents; orphan and empty-graph rejection is left to validation. A v1
    ``write`` file-open mode maps to a canonical reconcile mode, and a ``write``
    carrying an option with no v2 equivalent is rejected rather than silently dropped.

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


__all__ = ["migrate_v1_to_v2"]
