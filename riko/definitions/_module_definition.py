"""
Module definitions shared by the extension API and runtime registry.

Examples:

    >>> from riko.ext import ModuleDefinition
    >>>
    >>> def pipe(*args, **kwargs):
    ...     return []
    >>>
    >>> definition = ModuleDefinition(name="example", sync_pipe=pipe)
    >>> definition.get_pipe() is pipe
    True

"""

from __future__ import annotations

from typing import TYPE_CHECKING

from attrs import define, field

from riko.base._strutils import get_doc_summary
from riko.types._enums import ModuleName, ModuleNameLike
from riko.types._wrappers import is_async_wrapper, is_sync_wrapper

if TYPE_CHECKING:
    from riko.types._frozendict import FrozenInputSchemas
    from riko.types._wrappers import (
        AnyModuleWrapper,
        AsyncModuleWrapper,
        Func,
        Interface,
        SyncModuleWrapper,
        WrapperMeta,
    )

_UNNAMEABLE_PIPES = frozenset({"<lambda>", "pipe", "async_pipe"})


def get_callable_name(fn: Func[object] | None, default: str = "") -> str:
    """Names a callable after its ``__name__``, or ``default`` for an unnamed one."""
    candidate: object = getattr(fn, "__name__", None)
    is_valid = candidate not in _UNNAMEABLE_PIPES

    if isinstance(candidate, str) and candidate.isidentifier() and is_valid:
        name = candidate
    else:
        name = default

    return name


@define(frozen=True, slots=True, kw_only=True)
class ModuleDefinition:
    """
    Defines a named module and its sync/async pipe callables.

    Callables are either passed directly, or read from a module exposing ``pipe``/
    ``async_pipe`` with ``from_module`` (the same convention a built-in follows).
    The definition is a snapshot: changes to the module or callables don't alter it.

    Attributes:

        declared_name: The identifier as given (the ``name`` constructor argument, or
            the last part of the Python module's ``__name__`` that ``from_module``
            read), the entry-point key, or an empty string when omitted. Required by
            ``ModuleRegistry.register`` unless ``name`` can derive one.

        sync_pipe: The module's ``pipe``.
        async_pipe: The module's ``async_pipe``.
        description: Summary used by module discovery.

    Examples:

        >>> from riko.ext import ModuleDefinition
        >>>
        >>> def pipe(*args, **kwargs):
        ...     return []
        >>>
        >>> definition = ModuleDefinition(name="example", sync_pipe=pipe)
        >>> definition.name, definition.declared_name
        ('example', 'example')
        >>> definition.get_pipe() is pipe
        True

    """

    declared_name: str = field(default="", alias="name")
    sync_pipe: SyncModuleWrapper | None = None
    async_pipe: AsyncModuleWrapper | None = None
    description: str | None = None

    @classmethod
    def from_module(
        cls, module: object, *, name: str = "", description: str | None = None
    ) -> ModuleDefinition:
        """
        Builds a definition from a module exposing ``pipe`` and/or ``async_pipe``.

        Args:

            module: Object having ``pipe``/``async_pipe``, e.g., a Python module import.

        Kwargs:

            name: Declared name (default: last component of module's ``__name__``).
            description: Summary (default: first non-blank line of module's docstring).

        Returns:

            The definition with the module's interface callables attached.

        Examples:

            >>> from types import SimpleNamespace
            >>>
            >>> def pipe(*args, **kwargs):
            ...     return []
            >>>
            >>> ns = SimpleNamespace(pipe=pipe, __name__="ext.shout", __doc__="Shouts.")
            >>> definition = ModuleDefinition.from_module(ns)
            >>> definition.name, definition.description
            ('shout', 'Shouts.')
            >>> definition.get_pipe() is pipe
            True

        """
        summary = get_doc_summary(module) if description is None else description
        module_name = getattr(module, "__name__", None)
        pipe = getattr(module, "pipe", None)
        async_pipe = getattr(module, "async_pipe", None)

        if name:
            declared = name
        elif module_name is None:
            declared = ""
        else:
            declared = module_name.rsplit(".", 1)[-1]

        return cls(
            name=declared, sync_pipe=pipe, async_pipe=async_pipe, description=summary
        )

    @classmethod
    def from_pipe(
        cls, pipe: WrapperMeta, *, description: str | None = None
    ) -> ModuleDefinition:
        """
        Builds a definition from one pipe callable, sync or async.

        The definition is named after the module name stamped on the pipe, so a
        stored workflow's generic ``pipe``/``async_pipe`` leaves ``name`` empty.

        Args:

            pipe: A pipe callable, e.g., a module's ``pipe`` or ``async_pipe``.

        Kwargs:

            description: Summary (default: first non-blank line of the pipe's
                docstring).

        Returns:

            The definition with ``pipe`` attached as its sync or async callable.

        Examples:

            >>> from riko.modules.hash import async_pipe
            >>>
            >>> definition = ModuleDefinition.from_pipe(async_pipe)
            >>> definition.name, definition.async_pipe is async_pipe
            ('hash', True)
            >>> definition.sync_pipe
            >>> definition.dependencies
            ()

        """
        summary = get_doc_summary(pipe) if description is None else description
        name = "" if pipe.name in _UNNAMEABLE_PIPES else pipe.name
        return cls(
            name=name,
            sync_pipe=pipe if is_sync_wrapper(pipe) else None,
            async_pipe=pipe if is_async_wrapper(pipe) else None,
            description=summary,
        )

    @property
    def _pipe(self) -> AnyModuleWrapper | None:
        """The sync pipe callable, else the async one."""
        return self.sync_pipe if self.sync_pipe is not None else self.async_pipe

    @property
    def name(self) -> str:
        """
        The registry key, from the declared name or else an interface callable.

        A declared name wins. Otherwise the pipe callable's ``__name__`` is
        used. Generic ``<lambda>``/``pipe``/``async_pipe`` names are considered
        un-nameable, so those require an explicit ``name``.

        Returns:

            The derived registry key, or an empty string when none can be derived.

        Examples:

            >>> def double(source, **kwargs):
            ...     return source
            >>> ModuleDefinition(sync_pipe=double).name
            'double'
            >>> ModuleDefinition(sync_pipe=lambda source, **_: source).name
            ''

        """
        return self.declared_name or get_callable_name(self._pipe)

    @property
    def input_schemas(self) -> FrozenInputSchemas | None:
        """
        The schemas of the inputs the pipe reads, keyed by input name.

        A module reads none. A workflow's pipe reports its ``Workflow``'s, and a hand-
        written one what ``@workflow`` declared.

        Returns:

            The schemas, empty for a module, or ``None`` when the pipe declares none.

        Examples:

            >>> from riko.ext import workflow
            >>>
            >>> @workflow(subtype="source", input_schemas={"q": "string"})
            ... def pipe(item=None, **kwargs):
            ...     return iter([])
            >>>
            >>> ModuleDefinition.from_pipe(pipe).input_schemas["q"]
            FrozenDict({'type': 'string'})

        """
        return getattr(self._pipe, "input_schemas", None)

    @property
    def dependencies(self) -> tuple[str, ...] | None:
        """
        The sorted module and stored-workflow names the pipe runs.

        A module runs none. A workflow's pipe reports its ``Workflow``'s, and a hand-
        written one what ``@workflow`` declared.

        Returns:

            The names, empty for a module, or ``None`` when the pipe declares none.

        Examples:

            >>> from riko.ext import workflow
            >>>
            >>> @workflow(subtype="source", dependencies=["fetch", "count"])
            ... def pipe(item=None, **kwargs):
            ...     return iter([])
            >>>
            >>> ModuleDefinition.from_pipe(pipe).dependencies
            ('count', 'fetch')

        """
        return getattr(self._pipe, "dependencies", None)

    def get_pipe(self, is_async: bool = False) -> AnyModuleWrapper | None:
        """
        Selects this definition's sync or async pipe callable.

        Kwargs:

            is_async: Whether to return ``async_pipe`` instead of ``pipe``.

        Returns:

            The interface callable, or ``None`` when that interface is undefined.

        Examples:

            >>> def sync_pipe(*args, **kwargs):
            ...     return []
            >>> definition = ModuleDefinition(sync_pipe=sync_pipe)
            >>> definition.get_pipe() is sync_pipe
            True
            >>> definition.get_pipe(is_async=True)

        """
        return self.async_pipe if is_async else self.sync_pipe

    @property
    def interfaces(self) -> frozenset[Interface]:
        """
        Which of ``pipe`` and ``async_pipe`` this definition provides.

        Returns:

            The subset of ``pipe``/``async_pipe`` with a callable.

        Examples:

            >>> def pipe(source, **kwargs):
            ...     return source
            >>>
            >>> sorted(ModuleDefinition(name="example", sync_pipe=pipe).interfaces)
            ['pipe']

        """
        available: set[Interface] = set()

        if self.get_pipe(False) is not None:
            available.add("pipe")

        if self.get_pipe(True) is not None:
            available.add("async_pipe")

        return frozenset(available)


def normalize_module_name(name: ModuleNameLike | None) -> str:
    """
    Normalizes a module name to its canonical string value.

    Args:

        name: String or ``ModuleName`` value, or ``None``.

    Returns:

        The underlying module-name string, or an empty string for ``None``.

    Examples:

        >>> normalize_module_name("fetch")
        'fetch'
        >>> normalize_module_name(None)
        ''

    """
    return name.value if isinstance(name, ModuleName) else name or ""
