# vim: sw=4:ts=4:expandtab
"""
Registers and resolves target classes by backend.

Examples:

    Basic usage::

        >>> from riko import Backends
        >>> from riko.ext import FileTarget, TargetRegistry
        >>>
        >>> registry = TargetRegistry()
        >>> registry.resolve(Backends.FILE) is FileTarget
        True
        >>> class S3Target:
        ...     backend = Backends.S3
        >>>
        >>> registry.register(S3Target)
        >>> registry.resolve(Backends.S3) is S3Target
        True

Attributes:

    target_registry: Process-global target registry.

"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Final

from riko.base._exceptions import UnsupportedTargetError
from riko.definitions._targets import FileTarget
from riko.types._enums import BackendLike, Backends
from riko.types._target_protocols import Target, is_target_class

from ._registry import Registry

if TYPE_CHECKING:
    from collections.abc import Mapping
    from importlib.metadata import EntryPoint

_BUILTIN_TARGETS: Final[Mapping[str, type[Target]]] = {Backends.FILE: FileTarget}


class TargetRegistry(Registry[type[Target]]):
    """
    Resolves a backend to its target class.

    Precedence is runtime registration, then entry point
    (``[project.entry-points."riko.targets"]``), then built-in. A runtime registration
    shadows an entry-point or built-in target only when registered with
    ``replace=True``. Each stored entry is a self-describing target class keyed by its
    ``backend``. The class is its own factory, so resolution returns config-agnostic
    behavior the caller then constructs.

    """

    entry_point_group = "riko.targets"
    label = "target"
    builtin_names: ClassVar[frozenset[str]] = frozenset(_BUILTIN_TARGETS)

    def _key(self, entry: type[Target]) -> str:
        return str(entry.backend)

    def _load(self, ep: EntryPoint) -> type[Target]:
        loaded = ep.load()

        if not is_target_class(loaded):
            msg = f"entry point {ep.name!r} must load a target class with a 'backend'"
            raise TypeError(msg)

        return loaded

    def _resolve_builtin(self, backend: BackendLike) -> type[Target]:
        if (target := _BUILTIN_TARGETS.get(str(backend))) is None:
            raise UnsupportedTargetError(str(backend))

        return target

    def resolve(self, backend: BackendLike) -> type[Target]:
        """
        Resolves a backend to its target class, honoring tier precedence.

        Args:

            backend: The backend to resolve.

        Returns:

            The target class registered or built in for ``backend``.

        Raises:

            UnsupportedTargetError: If no tier defines a target for ``backend``.

        Examples:

            >>> from riko import Backends
            >>> from riko.ext import FileTarget
            >>>
            >>> TargetRegistry().resolve(Backends.FILE) is FileTarget
            True

        """
        entry = self._load_entry(str(backend))

        if entry is None:
            entry = self._resolve_builtin(backend)

        return entry


target_registry: TargetRegistry = TargetRegistry()


def register_target[T: Target](target: type[T], *, replace: bool = False) -> type[T]:
    """
    Registers a target class on the process-global registry.

    Args:

        target: The self-describing target class, keyed by its ``backend``.

        replace: Whether the target may replace an existing runtime target for the same
            backend, or shadow an entry-point or built-in one.

    Returns:

        The registered class, so the function works as a class decorator.

    Raises:

        ValueError: If a target for the same backend is already registered, an
            entry-point, or built-in target; and ``replace`` is False.

    Examples:

        >>> from riko import Backends
        >>> from riko.ext import register_target, reset_target_registry
        >>>
        >>> @register_target
        ... class S3Target:
        ...     backend = Backends.S3
        >>>
        >>> target_registry.resolve(Backends.S3) is S3Target
        True
        >>> reset_target_registry()

    """
    target_registry.register(target, replace=replace)
    return target


def reset_target_registry() -> None:
    """Resets the process-global target registry, chiefly for test isolation."""
    target_registry.reset()


__all__ = [
    "TargetRegistry",
    "register_target",
    "reset_target_registry",
    "target_registry",
]
