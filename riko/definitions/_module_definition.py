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

from attrs import Factory, define, field

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
_description = Factory(lambda self: get_doc_summary(self.module), takes_self=True)


@define(frozen=True, slots=True)
class ModuleDefinition:
    """
    Defines a named module and its sync/async pipe callables.

    Callables may be given directly, or read off ``module`` on demand. This lets an
    extension point at a module exposing ``pipe``/``async_pipe`` by the same convention
    as a built-in.

    An entry point may skip this object entirely and name the module itself. The
    registry then synthesizes a definition by reading the interface callables
    off the module and its ``description`` from the module docstring summary.

    Attributes:

        declared_name: The identifier as given (the ``name`` constructor argument),
            or an empty string when omitted. Required by ``register`` unless ``name``
            can derive one. This is optional for an entry-point definition because the
            registry determines it from the entry-point key. In that case the external
            declaration stays the single source of truth.

        sync_pipe: Sync interface callable. Wins over ``module``'s ``pipe``.

        async_pipe: Async interface callable. Wins over ``module``'s ``async_pipe``.

        module: Object to read the interface callables off of.

        description: Summary used by module discovery. Defaults to the first
            non-blank line of ``module``'s docstring.

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
        >>>
        >>> from types import SimpleNamespace
        >>>
        >>> module = SimpleNamespace(__doc__="Shouts each item.")
        >>> ModuleDefinition(module=module).description
        'Shouts each item.'
        >>> ModuleDefinition(module=module, description="Yells.").description
        'Yells.'

    """

    declared_name: str = field(default="", alias="name")
    sync_pipe: SyncModuleWrapper | None = None
    async_pipe: AsyncModuleWrapper | None = None
    module: object | None = None
    description: str | None = field(default=_description)

    @property
    def name(self) -> str:
        """
        The registry key, from the declared name or else a bound callable.

        A declared name wins. Otherwise the last component of ``module``'s
        ``__name__`` is used, then the bound pipe callable's ``__name__``.
        Generic ``<lambda>``/``pipe``/``async_pipe`` names are considered un-nameable,
        so those require an explicit ``name``.

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
        pipe = self.sync_pipe or self.async_pipe
        candidate = getattr(pipe, "__name__", "")
        module_name = getattr(self.module, "__name__", "")

        if self.declared_name:
            name = self.declared_name
        elif module_name:
            name = module_name.rsplit(".", 1)[-1]
        elif candidate not in _UNNAMEABLE_PIPES:
            name = candidate
        else:
            name = ""

        return name

    def get_pipe(self, is_async: bool = False) -> AnyModuleWrapper | None:
        """
        Resolves this definition's sync or async pipe callable.

        Args:

            is_async: Whether to resolve ``async_pipe`` instead of ``pipe``.

        Returns:

            The explicitly configured callable, the corresponding attribute from
            ``module``, or ``None`` when that interface is undefined.

        Examples:

            >>> def sync_pipe(*args, **kwargs):
            ...     return []
            >>> definition = ModuleDefinition(sync_pipe=sync_pipe)
            >>> definition.get_pipe() is sync_pipe
            True
            >>> definition.get_pipe(is_async=True) is None
            True

        """
        pipe = self.async_pipe if is_async else self.sync_pipe

        if pipe is None and self.module is not None:
            interface = "async_pipe" if is_async else "pipe"
            pipe = getattr(self.module, interface, None)

        return pipe

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
