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

from riko.base._strutils import replacer
from riko.base.exceptions import InvalidPipelineError

from ._scalars import BasicValueType, PrimitiveValueType
from ._sentinels import MISSING, SentinelValue, StreamState

if TYPE_CHECKING:
    from _typeshed import DataclassInstance

    from ._scalars import BasicValue
    from ._sentinels import MissingType, Sentinel
    from ._streams import AnyIterable, Item, StatefulItem
    from ._values import BasicList
    from .modules import AnyConfRule, Conf, ConfArg


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
    """Check runtime protocol membership and method call compatibility."""
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
                break

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


def is_conf_rule(value: object) -> TypeIs[AnyConfRule]:
    return is_dataclass_inst(value) and type(value).__name__.endswith("ConfRule")


@overload
def require_mapping(  # noqa: E704
    value: Conf | None,
    what: str | None = "value",
    *,
    error: type[Exception] = InvalidPipelineError,
    **_,
) -> Conf: ...
@overload  # noqa: E302
def require_mapping[K, V](  # noqa: E704
    value: Mapping[K, V] | object,
    what: str | None = "value",
    *,
    error: type[Exception] = InvalidPipelineError,
    **_,
) -> Mapping[K, V]: ...
def require_mapping[K, V](  # noqa: E302
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


def is_stateful_item(val: Item) -> TypeGuard[StatefulItem]:
    return isinstance(val.get("state"), StreamState) if is_mapping(val) else False


def is_missing_type(val: Item | MissingType | None) -> TypeIs[MissingType]:
    return val is MISSING


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


def is_sentinel[VT](val: Mapping[str, VT], **kwargs: object) -> TypeGuard[Sentinel]:
    if SentinelValue in val:
        sentinel = str(val[SentinelValue])
        key = replacer(sentinel, "")
    else:
        key = None

    return all([key, (len(val) in {2, 3}), key in kwargs])


def is_type_value(val: Mapping[Any, Any]) -> TypeGuard[ConfArg]:
    return len(val) == 2 and "type" in val and "value" in val


@overload
def is_async_callable[T](  # noqa: E704
    val: Callable[..., T | Awaitable[T]],
) -> TypeGuard[Callable[..., Awaitable[T]]]: ...
@overload  # noqa: E302
def is_async_callable(  # noqa: E704
    val: object,
) -> TypeGuard[Callable[..., Awaitable[object]]]: ...
def is_async_callable(val: object) -> bool:  # noqa: E302
    if callable(val):
        result = iscoroutinefunction(val) or iscoroutinefunction(type(val).__call__)
    else:
        result = False

    return result


def is_sync_callable[T](val: Callable[..., T] | object) -> TypeGuard[Callable[..., T]]:
    return callable(val) and not is_async_callable(val)
