"""
Module definitions shared by the extension API and runtime registry.

Examples:

    >>> from riko.ext import ModuleDefinition
    >>>
    >>> def pipe(*args, **kwargs):
    ...     return []
    >>> definition = ModuleDefinition(name="example", sync_pipe=pipe)
    >>> definition.get_pipe() is pipe
    True

"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from riko.types._enums import ModuleName, ModuleNameLike

_UNNAMEABLE_PIPES = frozenset({"<lambda>", "pipe", "async_pipe"})

if TYPE_CHECKING:
    from riko.types._wrappers import (
        AsyncPipeCallable,
        Pipe,
        PipeCallable,
        SyncPipeCallable,
    )


@dataclass(frozen=True, slots=True)
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

        name: Canonical identifier. Required by ``register``, but optional for an
            entry-point definition. The registry stamps it from the entry-point key
            so the external declaration stays the single source of truth.

        sync_pipe: Sync interface callable. Wins over ``module``'s ``pipe``.

        async_pipe: Async interface callable. Wins over ``module``'s ``async_pipe``.

        module: Object to read the interface callables off of.

        description: Summary used by module discovery. Defaults to ``module.__doc__``'s
            first non-blank line if ``module`` is given.

    Examples:

        >>> from riko.ext import ModuleDefinition
        >>>
        >>> def pipe(*args, **kwargs):
        ...     return []
        >>> definition = ModuleDefinition(name="example", sync_pipe=pipe)
        >>> definition.name
        'example'
        >>> definition.get_pipe() is pipe
        True

    """

    name: str = ""
    sync_pipe: SyncPipeCallable | None = None
    async_pipe: AsyncPipeCallable | None = None
    module: object | None = None
    description: str | None = None

    @property
    def resolved_name(self) -> str:
        """
        Derives the registry key from the explicit name or a bound callable.

        An explicit ``name`` wins. Otherwise the last component of ``module``'s
        ``__name__`` is used, then the bound pipe callable's ``__name__`` — treating
        the generic ``<lambda>``/``pipe``/``async_pipe`` names as un-nameable, so
        those require an explicit ``name``.

        Returns:

            The derived registry key, or an empty string when none can be derived.

        Examples:

            >>> def double(source, **kwargs):
            ...     return source
            >>> ModuleDefinition(sync_pipe=double).resolved_name
            'double'
            >>> ModuleDefinition(sync_pipe=lambda source, **_: source).resolved_name
            ''

        """
        pipe = self.sync_pipe or self.async_pipe
        candidate = getattr(pipe, "__name__", "")
        module_name = getattr(self.module, "__name__", "")

        if self.name:
            name = self.name
        elif module_name:
            name = module_name.rsplit(".", 1)[-1]
        elif candidate not in _UNNAMEABLE_PIPES:
            name = candidate
        else:
            name = ""

        return name

    def get_pipe(self, is_async: bool = False) -> PipeCallable | Pipe | None:
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
        pipe: PipeCallable | Pipe | None = (
            self.async_pipe if is_async else self.sync_pipe
        )

        if pipe is None and self.module is not None:
            interface = "async_pipe" if is_async else "pipe"
            pipe = getattr(self.module, interface, None)

        return pipe


def resolve_module_name(name: ModuleNameLike | None) -> str:
    """
    Normalizes a module name to its canonical string value.

    Args:

        name: String or ``ModuleName`` value, or ``None``.

    Returns:

        The underlying module-name string, or an empty string for ``None``.

    Examples:

        >>> resolve_module_name("fetch")
        'fetch'
        >>> resolve_module_name(None)
        ''

    """
    return name.value if isinstance(name, ModuleName) else name or ""
