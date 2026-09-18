# vim: sw=4:ts=4:expandtab
"""
Target capability protocols for extension backends.

Examples:

    Basic usage::

        >>> from riko.ext import FileTarget, SupportsWrite
        >>>
        >>> isinstance(FileTarget("out.csv"), SupportsWrite)
        True

"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Protocol, runtime_checkable

if TYPE_CHECKING:
    from riko.definitions._write import WriteCapabilities

    from ._enums import Backends, FmtLike


@runtime_checkable
class Target(Protocol):
    """A destination identified by its backend."""

    backend: ClassVar[Backends]


class SupportsRead(Target, Protocol):
    """
    A target that acquires and interprets records from its backend.

    The concrete acquisition methods are defined when read targets gain a runtime.
    """


@runtime_checkable
class SupportsWrite(Target, Protocol):
    """A destination that reports its write capabilities."""

    def capabilities(self, fmt: FmtLike | None = None) -> WriteCapabilities:
        """
        Reports the modes and serialization behavior the target supports.

        Format-dependent behavior (which modes are appendable, whether delivery is
        incremental) is a ``target × format`` fact the target itself decides; the
        returned capabilities merely report that decision. A native target ignores
        ``fmt``.

        Args:

            fmt: The serialization format, used by a serializing target to resolve
                its capabilities; ignored by a native target.

        Returns:

            The modes and serialization behavior the target supports.

        """
        ...


class SupportsActions(Target, Protocol):
    """
    A target that runs provider commands that are not data writes.

    The concrete command methods are defined when action targets gain a runtime.
    """


__all__ = ["SupportsActions", "SupportsRead", "SupportsWrite", "Target"]
