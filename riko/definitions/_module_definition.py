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

if TYPE_CHECKING:
    from riko.types._wrappers import (
        AnyModuleWrapper,
        AsyncModuleWrapper,
        Interface,
        SyncModuleWrapper,
    )

_UNNAMEABLE_PIPES = frozenset({"<lambda>", "pipe", "async_pipe"})


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

        sync_pipe: Sync interface callable.
        async_pipe: Async interface callable.
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
            name: Declared name (default: last component of module's ``__name__``).
            description: Summary (default: first non-blank line of module's docstring).

        Returns:

            The definition with the module's interface callables bound.

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

    @property
    def name(self) -> str:
        """
        The registry key, from the declared name or else a bound callable.

        A declared name wins. Otherwise the bound pipe callable's ``__name__`` is
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
        pipe = self.sync_pipe if self.sync_pipe is not None else self.async_pipe
        candidate = getattr(pipe, "__name__", "")

        if self.declared_name:
            name = self.declared_name
        elif candidate not in _UNNAMEABLE_PIPES:
            name = candidate
        else:
            name = ""

        return name

    def get_pipe(self, is_async: bool = False) -> AnyModuleWrapper | None:
        """
        Selects this definition's sync or async pipe callable.

        Args:

            is_async: Whether to return ``async_pipe`` instead of ``pipe``.

        Returns:

            The bound callable, or ``None`` when that interface is undefined.

        Examples:

            >>> def sync_pipe(*args, **kwargs):
            ...     return []
            >>> definition = ModuleDefinition(sync_pipe=sync_pipe)
            >>> definition.get_pipe() is sync_pipe
            True
            >>> definition.get_pipe(is_async=True) is None
            True

        """
        return self.async_pipe if is_async else self.sync_pipe

    @property
    def interfaces(self) -> frozenset[Interface]:
        """
        The sync and async interfaces this definition provides.

        Returns:

            The subset of ``pipe``/``async_pipe`` with a bound callable.

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
