# vim: sw=4:ts=4:expandtab
"""
Provides a scope that auto restores module, target, and workflow-store registrations.

Examples:

    Basic usage::

        >>> from riko import describe_module
        >>> from riko.ext import ModuleDefinition, register_module
        >>>
        >>> definition = ModuleDefinition(name="__doctest__", sync_pipe=lambda: [])
        >>> with temporary_registrations():
        ...     register_module(definition)
        ...     describe_module("__doctest__").name
        '__doctest__'
        >>> describe_module("__doctest__")

"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from typing import TYPE_CHECKING

from ._module_registry import module_registry
from ._target_registry import target_registry
from ._workflow_resolver import workflow_resolver

if TYPE_CHECKING:
    from collections.abc import Generator


@contextmanager
def temporary_registrations() -> Generator[None]:
    """
    Restores the registered modules, targets, and workflow stores when the block exits.

    Registrations made inside the block, including ones that replace an existing entry,
    last until it exits. Any previously registered items are then re-registered. Like
    ``warnings.catch_warnings``, the scope modifies global state and is not thread-safe.
    Scopes that overlap across threads restore each other's snapshots.

    Examples:

        >>> from pathlib import Path
        >>> from tempfile import TemporaryDirectory
        >>> from riko import Pipeline
        >>> from riko.ext import register_workflow_store
        >>>
        >>> conf = {"attrs": {"key": "greeting", "value": "hello"}}
        >>> greet = Pipeline.from_module("itembuilder", conf=conf)
        >>>
        >>> with TemporaryDirectory() as tmp, temporary_registrations():
        ...     path = Path(tmp) / "pipe_greet.json"
        ...     _ = path.write_bytes(greet.workflow.serialize())
        ...     register_workflow_store(directory=Path(tmp), replace=True)
        ...     list(Pipeline.from_module("pipe:greet"))
        [{'greeting': 'hello'}]

    """
    with ExitStack() as stack:
        for registry in (module_registry, target_registry, workflow_resolver):
            stack.enter_context(registry.restoring())

        yield


__all__ = ["temporary_registrations"]
