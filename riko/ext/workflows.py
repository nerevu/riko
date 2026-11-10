# vim: sw=4:ts=4:expandtab
"""
Provides workflow authoring for extension authors.

This namespace contains the workflow node and edge classes, stored-workflow
registration, and the dispatcher protocol. It is part of the SemVer-guaranteed
``riko.ext`` surface. Every name here is also re-exported from ``riko.ext``.

Examples:

    Basic usage::

        >>> from riko import Endpoint, Workflow
        >>> from riko.ext import ModuleNode, StreamEdge
        >>>
        >>> fetch = ModuleNode(id="fetch-1", name="fetch")
        >>> count = ModuleNode(id="count-1", name="count")
        >>> edge = StreamEdge(Endpoint("fetch-1", "out"), Endpoint("count-1", "in"))
        >>> flow = Workflow(nodes=[fetch, count], edges=[edge])
        >>> flow
        Workflow(fetch-1 -> count-1)
        >>> flow.dependencies
        ('count', 'fetch')

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
