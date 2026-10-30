# vim: sw=4:ts=4:expandtab
"""
Provides the workflow stores (``WorkflowStore`` implementations).

A ``WorkflowStore`` holds and loads a stored workflow by its ``pipe_<id>`` name. A
module store (``ModuleStore``) returns a ``ResolvedWorkflow``, a module
exposing ``pipe`` and/or ``async_pipe``. A document store (``DocumentStore``) returns
the ``Workflow`` a ``WorkflowDocument`` (serialized ``Workflow``) describes.

"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Protocol

from riko.base._iterutils import map_values
from riko.base._typing import import_or_else
from riko.definitions._workflow_definition import Workflow
from riko.types._enums import DocumentShape
from riko.types._workflow import ResolvedWorkflow

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path
    from types import ModuleType


class WorkflowStore[T](Protocol):
    """
    Loads a stored workflow (an entry looked up by its ``pipe_<id>`` name).

    ``T`` is what ``load`` returns: a ``ResolvedWorkflow`` (a module exposing ``pipe``
    and/or ``async_pipe``) for a ``ModuleStore``, or a ``Workflow`` (the in-memory
    graph) for a ``DocumentStore``. A store returns ``None`` when it holds no matching
    name.

    Examples:

        >>> class EmptyStore:
        ...     def load(self, name):
        ...         return None
        >>>
        >>> EmptyStore().load("pipe_demo")

    """

    def load(self, name: str) -> T | None:
        """
        Loads the stored workflow named ``name``.

        Args:

            name: The stored workflow's ``pipe_<id>`` name.

        Returns:

            What the store holds under ``name``, or ``None`` if it holds no matching
            name.

        """
        ...


type ModuleStore = WorkflowStore[ResolvedWorkflow]
type DocumentStore = WorkflowStore[Workflow]


class PackageStore:
    """
    Imports a package's ``pipe_<id>.py`` file as a ``ResolvedWorkflow`` on lookup.

    Each file must define ``pipe`` and/or ``async_pipe`` functions that take an item or
    a stream plus a ``context``. The package is imported when the store is built, so a
    mistyped import path fails then rather than when loading a package's file.

    Args:

        package: The package or its import path.

    Raises:

        ModuleNotFoundError: If ``package`` is an import path that does not exist.
        ValueError: If ``package`` is a module rather than a package.

    Examples:

        >>> store = PackageStore("examples.pyworkflows")
        >>> store.load("pipe_timezone").__name__
        'examples.pyworkflows.pipe_timezone'
        >>> store.load("pipe_missing")

    """

    def __init__(self, package: str | ModuleType) -> None:
        module = import_module(package) if isinstance(package, str) else package

        if not hasattr(module, "__path__"):
            raise ValueError(f"{module.__name__!r} is a module, not a package")

        self._package = module.__name__

    def load(self, name: str) -> ResolvedWorkflow | None:
        """
        Imports the package's file named ``name``.

        Args:

            name: The stored workflow's ``pipe_<id>`` name.

        Returns:

            The imported ``ResolvedWorkflow``, or ``None`` if the package has no such
            file.

        Raises:

            ModuleNotFoundError: If the file exists but a module it imports doesn't.

        """
        module = import_or_else(f"{self._package}.{name}", strict=True)
        return None if module is None else ResolvedWorkflow(module)


class MappingStore:
    """
    Looks up a ``ResolvedWorkflow`` in a mapping its caller supplies.

    Nothing is imported. Each ``ResolvedWorkflow`` (a module exposing ``pipe`` and/or
    ``async_pipe``) is returned as given.

    Args:

        modules: Each resolved workflow (a ``types.ModuleType``), keyed by its stored
            workflow's ``pipe_<id>`` name.

    Examples:

        >>> from types import ModuleType
        >>>
        >>> module = ModuleType("pipe_demo")
        >>> store = MappingStore({"pipe_demo": module})
        >>> store.load("pipe_demo") is module
        True
        >>> store.load("pipe_other")

    """

    def __init__(self, modules: Mapping[str, ModuleType]) -> None:
        self._modules = map_values(ResolvedWorkflow, modules)

    def load(self, name: str) -> ResolvedWorkflow | None:
        """
        Looks up ``name``.

        Args:

            name: The stored workflow's ``pipe_<id>`` name.

        Returns:

            The ``ResolvedWorkflow``, or ``None`` if ``name`` doesn't exist.

        """
        return self._modules.get(name)


class CompositeStore:
    """
    Combines several ``ModuleStore`` objects into one.

    ``load`` returns the ``ResolvedWorkflow`` (a module exposing ``pipe`` and/or
    ``async_pipe``) from the first store that has the name.

    Args:

        *stores: The ``ModuleStore`` objects, in priority order.

    Examples:

        >>> from types import ModuleType
        >>>
        >>> first = MappingStore({"pipe_a": ModuleType("pipe_a")})
        >>> second = MappingStore({"pipe_b": ModuleType("pipe_b")})
        >>> store = CompositeStore(first, second)
        >>> store.load("pipe_b").__name__
        'pipe_b'

    """

    def __init__(self, *stores: ModuleStore) -> None:
        self._stores = stores

    def load(self, name: str) -> ResolvedWorkflow | None:
        """
        Loads ``name`` from the first store that has it.

        Args:

            name: The stored workflow's ``pipe_<id>`` name.

        Returns:

            The ``ResolvedWorkflow``, or ``None`` if no store has ``name``.

        """
        found = None

        for store in self._stores:
            if (found := store.load(name)) is not None:
                break

        return found


class DirectoryStore:
    """
    Reads a ``WorkflowDocument``, stored as a ``pipe_<id>.json`` file, on lookup.

    As a ``DocumentStore``, ``load`` returns the ``Workflow`` a ``WorkflowDocument``
    (serialized ``Workflow``) describes. The ``Workflow`` has no ``pipe`` to call.
    Instead, ``WorkflowResolver`` creates a ``ResolvedWorkflow`` from it.

    Args:

        directory: The directory holding the ``pipe_<id>.json`` files.

    Examples:

        >>> from pathlib import Path
        >>> from tempfile import TemporaryDirectory
        >>>
        >>> document = '{"nodes": [{"name": "forever"}]}'
        >>>
        >>> with TemporaryDirectory() as tmp:
        ...     _ = (Path(tmp) / "pipe_demo.json").write_text(document)
        ...     store = DirectoryStore(Path(tmp))
        ...     flow = store.load("pipe_demo")
        ...     missing = store.load("pipe_missing")
        >>> [node.name for node in flow.nodes.values()], missing
        (['forever'], None)

    """

    def __init__(self, directory: Path) -> None:
        self._directory = directory

    def load(self, name: str) -> Workflow | None:
        """
        Reads the ``Workflow`` stored as ``<name>.json``.

        Args:

            name: The stored workflow's ``pipe_<id>`` name.

        Returns:

            The ``Workflow``, or ``None`` if the file does not exist.

        Raises:

            InvalidPipelineError: If the file is not a valid ``WorkflowDocument``.

        """
        try:
            text = (self._directory / f"{name}.json").read_text()
        except FileNotFoundError:
            parsed = None
        else:
            parsed = Workflow.parse(text, shape=DocumentShape.V2)

        return parsed


__all__ = [
    "CompositeStore",
    "DirectoryStore",
    "DocumentStore",
    "MappingStore",
    "ModuleStore",
    "PackageStore",
    "WorkflowStore",
]
