# vim: sw=4:ts=4:expandtab
"""
Resolves a backend to its target class.

A target is a self-describing class keyed by its ``backend`` (a
:class:`Backends` member): registering the class is enough, and resolving a backend
returns the target class, which is its own factory. ``FileTarget`` is the one
built-in, keyed to :attr:`Backends.FILE`. External providers register their own
targets at runtime or through the ``riko.targets`` entry-point group, so a new
backend needs no core edit.

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

    target_registry: Process-global registry backing ``register_target`` and target
        resolution.

"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from riko.base.exceptions import UnsupportedTargetError
from riko.definitions._targets import FileTarget
from riko.types._enums import BackendLike, Backends
from riko.types._targets import Target

from ._registry import Registry

if TYPE_CHECKING:
    from importlib.metadata import EntryPoint


class TargetRegistry(Registry[type[Target]]):
    """
    Resolves a backend to its target class.

    Precedence is runtime registration, then entry point
    (``[project.entry-points."riko.targets"]``), then built-in. Each stored entry is a
    self-describing target class keyed by its ``backend``. The class is its own
    factory, so resolution returns config-agnostic behavior the caller then constructs.

    """

    entry_point_group = "riko.targets"
    label = "target"

    def _key(self, entry: type[Target]) -> str:
        return str(entry.backend)

    def _load(self, ep: EntryPoint) -> type[Target]:
        loaded = ep.load()

        if not (isinstance(loaded, type) and hasattr(loaded, "backend")):
            raise TypeError(
                f"entry point {ep.name!r} must load a target class with a 'backend'"
            )

        return cast("type[Target]", loaded)

    def _resolve_builtin(self, backend: BackendLike) -> type[Target]:
        if str(backend) == Backends.FILE:
            target: type[Target] = FileTarget
        else:
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

            >>> from riko.definitions._targets import FileTarget
            >>> from riko.types._enums import Backends
            >>>
            >>> TargetRegistry().resolve(Backends.FILE) is FileTarget
            True

        """
        entry = self._registered(str(backend))

        if entry is None:
            entry = self._resolve_builtin(backend)

        return entry


target_registry: TargetRegistry = TargetRegistry()


def register_target(target: type[Target], *, replace: bool = False) -> None:
    """
    Registers a target class on the process-global registry.

    Args:

        target: The self-describing target class, keyed by its ``backend``.
        replace: Whether an existing runtime target for the same backend may be
            replaced.

    Raises:

        ValueError: If a target for the same backend is already registered and
            ``replace`` is False.

    """
    target_registry.register(target, replace=replace)


def reset_target_registry() -> None:
    """Resets the process-global target registry, chiefly for test isolation."""
    target_registry.reset()


__all__ = [
    "TargetRegistry",
    "register_target",
    "reset_target_registry",
    "target_registry",
]
