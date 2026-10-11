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

from enum import StrEnum
from typing import (
    TYPE_CHECKING,
    ClassVar,
    Literal,
    Protocol,
    overload,
    runtime_checkable,
)

from riko.base.exceptions import InvalidPipelineError

if TYPE_CHECKING:
    from riko.definitions._write import WriteCapabilities

    from ._enums import Backends, FmtLike


@runtime_checkable
class Target(Protocol):
    """An endpoint identified by its backend."""

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


@overload
def resolve_enum[E: StrEnum](  # noqa: E704
    enum: type[E],
    value: E | str | None,
    what: str | None = ...,
    *,
    default: E | None = ...,
    strict: Literal[True] = ...,
    error: type[Exception] = ...,
) -> E: ...
@overload  # noqa: E302
def resolve_enum[E: StrEnum](  # noqa: E704
    enum: type[E],
    value: E | str | None,
    what: str | None = ...,
    *,
    default: E | None = ...,
    strict: Literal[False],
    error: type[Exception] = ...,
) -> E | None: ...
@overload  # noqa: E302
def resolve_enum[E: StrEnum](  # noqa: E704
    enum: type[E],
    value: E | str | None,
    what: str | None = ...,
    *,
    default: E | None = ...,
    strict: bool,
    error: type[Exception] = ...,
) -> E | None: ...
def resolve_enum[E: StrEnum](  # noqa: E302
    enum: type[E],
    value: E | str | None,
    what: str | None = None,
    *,
    default: E | None = None,
    strict: bool = True,
    error: type[Exception] = InvalidPipelineError,
) -> E | None:
    """Resolves a name or member into the given string enum, or raises ``error``."""
    what = enum.__name__ if what is None else what

    if value is None and default is None and strict:
        raise error(f"missing required {what}")
    elif value is None:
        result = default
    else:
        try:
            result = value if isinstance(value, enum) else enum(value)
        except ValueError as e:
            raise error(f"Invalid {what}: {value!r}") from e

    return result


__all__ = ["SupportsActions", "SupportsRead", "SupportsWrite", "Target", "resolve_enum"]
