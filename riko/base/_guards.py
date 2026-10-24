# vim: sw=4:ts=4:expandtab
"""Provides type guard functions over generic shapes."""

from __future__ import annotations

from collections.abc import AsyncIterable, Awaitable, Callable, Iterable, Mapping
from dataclasses import is_dataclass
from inspect import (
    Parameter,
    Signature,
    getmembers_static,
    iscoroutinefunction,
    isfunction,
    signature,
)
from typing import TYPE_CHECKING, Any, TypeGuard, overload

import attrs
from requests.structures import CaseInsensitiveDict
from typing_extensions import TypeIs

from ._exceptions import InvalidPipelineError
from ._sentinels import MISSING
from ._typing import BasicValueType, PrimitiveValueType

if TYPE_CHECKING:
    from _typeshed import DataclassInstance

    from riko.types._scalars import BasicValue
    from riko.types._streams import AnyIterable
    from riko.types._values import BasicList
    from riko.types.modules import Conf


def _protocol_signature(method: Callable) -> Signature:
    sig = signature(method)
    params = list(sig.parameters.values())

    if not params or params[0].name != "self":
        raise TypeError("protocol methods must be instance methods")

    params = params[1:]

    for param in params:
        if param.kind is not Parameter.POSITIONAL_OR_KEYWORD:
            msg = "protocol methods may only use positional-or-keyword parameters"
            raise TypeError(msg)

    return sig.replace(parameters=params)


def _signature_compatible(expected: Signature, actual: Signature) -> bool:
    params = list(expected.parameters.values())
    required = sum(param.default is Parameter.empty for param in params)

    try:
        # Smallest positional call promised by the protocol.
        actual.bind(*([MISSING] * required))

        # Largest positional call promised by the protocol.
        actual.bind(*([MISSING] * len(params)))
    except TypeError:
        result = False
    else:
        result = True

    return result


def isinstance_strict[P](obj: object, protocol: type[P], *methods: str) -> TypeIs[P]:
    """
    Checks runtime protocol membership and method call compatibility.

    A callable built-in method whose signature cannot be inspected (e.g., a
    generator's ``close``) counts as compatible.
    """
    match = False

    if isinstance(obj, protocol):
        predicate = lambda v: isfunction(v) and not v.__name__.startswith("_")
        available = getmembers_static(protocol, predicate)
        available_names = {name for name, _ in available}
        selected = set(methods)

        if selected and (unknown := selected - available_names):
            unknown_names = ", ".join(sorted(unknown))
            msg = f"{protocol.__name__} has no instance method(s): {unknown_names}"
            raise TypeError(msg)

        for name, member in available:
            if isinstance(member, (staticmethod, classmethod)):
                if not selected or name in selected:
                    msg = f"{protocol.__name__}.{name} must be an instance method"
                    raise TypeError(msg)

                continue
            elif selected and name not in selected:
                continue

            expected = _protocol_signature(member)
            obj_method = getattr(obj, name, None)

            if not callable(obj_method):
                break

            try:
                actual = signature(obj_method)
            except (TypeError, ValueError):
                continue

            if not _signature_compatible(expected, actual):
                break
        else:
            match = True

    return match


def is_mapping[K, V](val: Mapping[K, V] | object) -> TypeIs[Mapping[K, V]]:
    failure = False

    # Delay calling isinstance(val, Mapping) as much as possible
    if not (success := isinstance(val, (dict, CaseInsensitiveDict))):
        failure = isinstance(val, (str, int, float))

    return success or (False if failure else isinstance(val, Mapping))


def is_dataclass_inst(value: object) -> TypeIs[DataclassInstance]:
    return is_dataclass(value) and not isinstance(value, type)


def is_attrs_inst(value: object) -> TypeIs[attrs.AttrsInstance]:
    return attrs.has(type(value)) and not is_mapping(value)


@overload
def require_mapping(
    value: Conf | None,
    what: str | None = "value",
    *,
    error: type[Exception] = InvalidPipelineError,
    **_,
) -> Conf: ...
@overload
def require_mapping[K, V](
    value: Mapping[K, V] | object,
    what: str | None = "value",
    *,
    error: type[Exception] = InvalidPipelineError,
    **_,
) -> Mapping[K, V]: ...
def require_mapping[K, V](
    value: Mapping[K, V] | object,
    what: str | None = "value",
    *,
    error: type[Exception] = InvalidPipelineError,
    **_,
) -> Mapping[K, V]:
    """Narrows a value to a mapping or raises ``error`` as malformed structure."""
    if not is_mapping(value):
        raise error(f"{what} must be a mapping")

    return value


def is_known_sequence[VT](val: object) -> TypeIs[list[VT] | tuple[VT, ...]]:
    return isinstance(val, (list, tuple))


def is_mapping_seq(
    val: list[Any] | tuple[Any, ...],
) -> TypeGuard[list[Mapping[Any, object]] | tuple[Mapping[Any, object], ...]]:
    return bool(val and is_mapping(val[0]))


def is_value_seq(
    val: list[Any] | tuple[Any, ...],
) -> TypeGuard[BasicList | tuple[BasicValue, BasicValue]]:
    return bool(val and isinstance(val[0], BasicValueType))


def is_listlike[T](value: Iterable[T] | object) -> TypeGuard[Iterable[T]]:
    """
    Reports whether a value is listlike (a multi-item iterable).

    A listlike value is any iterable that is not a mapping, primitive, or ``None``.

    Args:

        value: The object to classify.

    Returns:

        True when ``value`` maps over items, False when it is one item.

    Examples:

        >>> is_listlike([1, 2])
        True
        >>> is_listlike((1, 2))
        True
        >>> is_listlike(iter([1, 2]))
        True
        >>> is_listlike(range(3))
        True
        >>> is_listlike({"a": 1})
        False
        >>> is_listlike("ab")
        False
        >>> is_listlike(0)
        False
        >>> is_listlike(None)
        False

    """
    if value is None or isinstance(
        value, (PrimitiveValueType, bytes, dict, CaseInsensitiveDict, Mapping)
    ):
        result = False
    else:
        result = isinstance(value, Iterable)

    return result


def require_sequence(
    value: object, what: str, *, error: type[Exception] = InvalidPipelineError, **_
) -> Iterable[object]:
    """Narrows a value to a non-string iterable or raises ``error``."""
    if not is_listlike(value):
        raise error(f"{what} must be a list")

    return value


def is_streamlike[T](value: AnyIterable[T] | object) -> TypeGuard[AnyIterable[T]]:
    """
    Reports whether a value represents a sync or async stream of values.

    A streamlike value is listlike or any async iterable. Mappings, primitives, and
    ``None`` are one item.

    Args:

        value: The object to classify.

    Returns:

        True when ``value`` streams values (sync or async), False when it is one value.

    Examples:

        >>> async def agen():
        ...     yield 1
        >>>
        >>> is_streamlike(agen())
        True
        >>> is_streamlike([1, 2])
        True
        >>> is_streamlike({"a": 1})
        False
        >>> is_streamlike("ab")
        False

    """
    return is_listlike(value) or isinstance(value, AsyncIterable)


@overload
def is_async_callable[T](
    val: Callable[..., T | Awaitable[T]],
) -> TypeGuard[Callable[..., Awaitable[T]]]: ...
@overload
def is_async_callable(val: object) -> TypeGuard[Callable[..., Awaitable[object]]]: ...
def is_async_callable(val: object) -> bool:
    if callable(val):
        result = iscoroutinefunction(val) or iscoroutinefunction(type(val).__call__)
    else:
        result = False

    return result


def is_sync_callable[T](val: Callable[..., T] | object) -> TypeGuard[Callable[..., T]]:
    return callable(val) and not is_async_callable(val)
