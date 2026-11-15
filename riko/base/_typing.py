# vim: sw=4:ts=4:expandtab
"""
Runtime typing helpers.

Resolves PEP 563 hints, type aliases, union members, enum members, and optional modules,
and holds the ``isinstance`` tuples behind the scalar type aliases.
"""

from __future__ import annotations

from collections import ChainMap
from contextlib import suppress
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from importlib import import_module
from pathlib import PurePath
from time import struct_time
from types import ModuleType, UnionType
from typing import (
    TYPE_CHECKING,
    Annotated,
    TypeAliasType,
    Union,
    get_args,
    get_origin,
    get_type_hints,
)
from uuid import UUID

from typing_extensions import TypeForm

from ._exceptions import InvalidPipelineError

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping


def resolve_alias(annotation: object) -> object:
    """
    Resolves a ``type`` alias to the annotation it names.

    Follows alias chains to their end (e.g., ``type A = B``; ``type B = int``). Any
    other annotation passes through. As does an alias whose value names something
    missing at runtime (e.g., a name imported only for type checking). The chain stops
    at the last resolvable alias.

    Args:

        annotation: The annotation to resolve.

    Returns:

        The annotation the alias chain ends at, or ``annotation`` itself.

    Examples:

        >>> type Count = int
        >>> type Total = Count
        >>> resolve_alias(Total), resolve_alias(str)
        (<class 'int'>, <class 'str'>)
        >>> type Unknown = Missing
        >>> resolve_alias(Unknown)
        Unknown

    """
    with suppress(NameError):
        while isinstance(annotation, TypeAliasType):
            annotation = annotation.__value__

    return annotation


def gen_union_members(annotation: object) -> Iterator[object]:
    """
    Generates the arms of an annotation once aliases, unions, and ``Annotated`` go.

    Aliases are resolved and unions flattened at every level, and ``Annotated[T, ...]``
    yields the arms of ``T``. Anything else is one arm, as is an alias whose value names
    something missing at runtime (e.g., a name imported only for type checking).

    Args:

        annotation: The annotation to decompose.

    Yields:

        Each arm in declaration order.

    Examples:

        >>> from typing import Annotated
        >>>
        >>> type Number = int | float
        >>> list(gen_union_members(Annotated[Number, "units"] | str))
        [<class 'int'>, <class 'float'>, <class 'str'>]

    """
    annotation = resolve_alias(annotation)
    origin = get_origin(annotation)

    if origin is Union or origin is UnionType:
        for arg in get_args(annotation):
            yield from gen_union_members(arg)
    elif origin is Annotated:
        yield from gen_union_members(get_args(annotation)[0])
    else:
        yield annotation


def resolve_type_hints(
    obj: object,
    *namespaces: ModuleType | Mapping[str, object],
    include_extras: bool = False,
) -> dict[str, TypeForm[object]]:
    """
    Resolves an object's type hints, supplementing the lookup namespace.

    ``get_type_hints`` evaluates PEP 563 (``from __future__ import annotations``)
    string annotations against the defining module's globals, so a name imported
    only under ``TYPE_CHECKING`` fails to resolve. Each entry in ``namespaces``,
    a module or a mapping, is merged into the local namespace in order (later
    entries win) so those forward references resolve.

    Args:

        obj: The module, class, or callable whose hints to resolve.
        namespaces: Modules or mappings whose names supplement the local namespace.

    Kwargs:

        include_extras: Whether to keep ``Annotated`` metadata.

    Returns:

        The resolved ``name -> type`` mapping.

    Examples:

        >>> from collections.abc import Iterator
        >>> import collections.abc as abc
        >>>
        >>> def pipe(items) -> "Iterator[int]":
        ...     return iter(items)
        >>>
        >>> resolve_type_hints(pipe, abc)["return"]
        collections.abc.Iterator[int]

    """
    localns = ChainMap(
        *(vars(ns) if isinstance(ns, ModuleType) else dict(ns) for ns in namespaces)
    )
    return get_type_hints(obj, localns=localns, include_extras=include_extras)


AnyStrType: tuple[type[str], type[bytes]] = (str, bytes)
BasicValueType: tuple[type[str], type[int]] = (str, int)
TemporalType: tuple[type, ...] = (datetime, date, struct_time)
DateLikeType: tuple[type, ...] = (str, int, datetime, date, struct_time)
NumLikeType: tuple[type, ...] = (float, int, Decimal)


PrimitiveValueType: tuple[type, ...] = (
    str,
    int,
    float,
    Decimal,
    datetime,
    date,
    struct_time,
)


HashableType: tuple[type, ...] = (
    str,
    int,
    float,
    Decimal,
    date,
    struct_time,
    PurePath,
    bytes,
    UUID,
    tuple,
)


def require_enum[E: StrEnum](
    cls: type[E],
    value: E | str | None,
    what: str | None = None,
    *,
    error: type[Exception] = InvalidPipelineError,
) -> E:
    """
    Requires a member or member value of the given string enum.

    Args:

        cls: The string enum to read ``value`` as.
        value: A member or member value, or ``None`` when absent.

    Kwargs:

        what: How error messages name the value (default: the enum's name).
        error: The exception class raised for a missing or invalid ``value``.

    Returns:

        The matching member.

    Raises:

        error: If ``value`` is missing or not one of the enum's values. The
            invalid-value message lists every accepted value.

    Examples:

        >>> class Color(StrEnum):
        ...     RED = "red"
        ...     BLUE = "blue"
        >>>
        >>> require_enum(Color, "red")
        <Color.RED: 'red'>
        >>> require_enum(Color, None, "color")
        Traceback (most recent call last):
        ...
        riko.exceptions.InvalidPipelineError: ...missing required color

    """
    what = cls.__name__ if what is None else what

    if value is None:
        raise error(f"missing required {what}")

    try:
        result = value if isinstance(value, cls) else cls(value)
    except ValueError as e:
        accepted = ", ".join(cls)
        raise error(f"Invalid {what}: {value!r}. Expected one of {accepted}") from e

    return result


def resolve_enum[E: StrEnum](
    enum: type[E],
    value: E | str | None,
    default: E,
    what: str | None = None,
    *,
    error: type[Exception] = InvalidPipelineError,
) -> E:
    """
    Resolves a member or member value of the given string enum, or ``default``.

    Args:

        enum: The string enum to read ``value`` as.
        value: A member or member value.
        default: The member a missing ``value`` resolves to.

    Kwargs:

        what: How error messages name the value (default: the enum's name).
        error: The exception class raised for an invalid ``value``.

    Returns:

        The matching member, or ``default`` when ``value`` is missing.

    Raises:

        error: If ``value`` is not one of the enum's values. The message lists every
            accepted value.

    Examples:

        >>> class Color(StrEnum):
        ...     RED = "red"
        ...     BLUE = "blue"
        >>>
        >>> resolve_enum(Color, "red", Color.BLUE)
        <Color.RED: 'red'>
        >>> resolve_enum(Color, None, Color.BLUE)
        <Color.BLUE: 'blue'>

    """
    return default if value is None else require_enum(enum, value, what, error=error)


def import_or_else(target: str, *, strict: bool = False) -> ModuleType | None:
    """
    Attempts to import ``target``.

    Args:

        target: Fully qualified module name to import.

    Kwargs:

        strict: Whether a missing parent package raises instead of returning ``None``.
            When set, only ``target`` itself may be missing.

    Returns:

        The imported module, or ``None`` when ``target`` (or, unless ``strict``, one
        of its parent packages) does not exist.

    Raises:

        ModuleNotFoundError: If a module other than ``target`` is missing, and either:

            - it is not a parent package of ``target`` (such as a dependency ``target``
                imports), or
            - ``strict`` is set, so a missing parent package raises too.

            An error that names no missing module is re-raised, since nothing shows
            the missing module was ``target``.

    Examples:

        >>> import_or_else("math").__name__
        'math'
        >>> import_or_else("riko.__definitely_missing__")
        >>> import_or_else("riko.__missing__.pipe_x")
        >>> import_or_else("riko.__missing__.pipe_x", strict=True)
        Traceback (most recent call last):
        ...
        ModuleNotFoundError: No module named 'riko.__missing__'

    """
    try:
        module = import_module(target)
    except ModuleNotFoundError as e:
        module = None
        missing_name = e.name
        not_target = target != missing_name
        is_parent = missing_name is not None and target.startswith(f"{missing_name}.")

        if not_target and (strict or not is_parent):
            raise

    return module
