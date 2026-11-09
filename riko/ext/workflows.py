# vim: sw=4:ts=4:expandtab
"""
Provides workflow authoring for extension authors.

This namespace contains the workflow node and edge classes, stored-workflow
registration, and the dispatcher protocol. It is part of the SemVer-guaranteed
``riko.ext`` surface. Every name here is also re-exported from ``riko.ext``.

Examples:

    Basic usage::

        >>> from riko import Workflow
        >>>
        >>> flow = Workflow.from_raw(
        ...     {
        ...         "nodes": [
        ...             {"id": "fetch-1", "name": "fetch"},
        ...             {"name": "write", "family": "write", "backend": "file"},
        ...         ],
        ...         "edges": [
        ...             {"source": {"node": "fetch-1"}, "target": {"node": "write-1"}}
        ...         ],
        ...     }
        ... )
        >>> flow.nodes["write-1"].backend.value
        'file'
        >>> flow.outputs["default"]
        Endpoint(node='write-1', port='out')

"""

from riko.definitions._nodes import (
    ActionNode,
    CacheNode,
    CallableNode,
    ModuleNode,
    PublishEdge,
    ReadNode,
    StreamEdge,
    SubscribeNode,
    WriteNode,
)
from riko.runtime._workflow_resolver import (
    register_workflow_store,
    reset_workflow_resolver,
)
from riko.types._wrappers import Dispatcher

__all__ = [
    "ActionNode",
    "CacheNode",
    "CallableNode",
    "Dispatcher",
    "ModuleNode",
    "PublishEdge",
    "ReadNode",
    "StreamEdge",
    "SubscribeNode",
    "WriteNode",
    "register_workflow_store",
    "reset_workflow_resolver",
]
