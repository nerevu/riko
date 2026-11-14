# vim: sw=4:ts=4:expandtab
"""Provides type guard functions over generic shapes."""

from __future__ import annotations

from collections.abc import (
    AsyncIterable,
    Awaitable,
    Callable,
    Iterable,
    Iterator,
    Mapping,
    Sequence,
)
from dataclasses import is_dataclass
from functools import lru_cache, partial
from inspect import (
    Parameter,
    Signature,
    getattr_static,
    getmembers_static,
    isawaitable,
    iscoroutinefunction,
    isfunction,
    signature,
)
from itertools import filterfalse, repeat
from types import MemberDescriptorType, MethodType
from typing import TYPE_CHECKING, TypeGuard, overload

import attrs
from requests.structures import CaseInsensitiveDict
from typing_extensions import TypeIs, TypeVar

from ._config import settings
from ._exceptions import InvalidPipelineError
from ._sentinels import MISSING
from ._typing import BasicValueType, PrimitiveValueType

if TYPE_CHECKING:
    from _typeshed import DataclassInstance

    from riko.types._scalars import BasicValue
    from riko.types._streams import AnyIterable
    from riko.types._values import BasicList
    from riko.types._wrappers import AsyncFunc, Func
    from riko.types.modules import Conf

_KT = TypeVar("_KT", default=str)
_VT = TypeVar("_VT", default=object)


def _protocol_signature(method: Func[object]) -> Signature:
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


def _is_public_function(value: object) -> bool:
    return isfunction(value) and not value.__name__.startswith("_")


@lru_cache(maxsize=settings.strict_check_cache_size)
def _get_protocol_members(protocol: type) -> tuple[tuple[str, Func[object]], ...]:
    return tuple(getmembers_static(protocol, _is_public_function))


@lru_cache(maxsize=settings.strict_check_cache_size)
def _is_type_bound_static(cls: type, *names: str) -> bool:
    """Whether ``cls`` has no ``__getattr__`` and none of ``names`` is a slot."""
    get_cls_attr_static = partial(getattr_static, cls)
    static_attrs = map(get_cls_attr_static, names, repeat(None))
    has_static = map(isinstance, static_attrs, repeat(MemberDescriptorType))
    return not (get_cls_attr_static("__getattr__", None) is not None or any(has_static))


def is_type_bound(obj: object, *names: str) -> bool:
    """
    Whether ``obj``'s methods named ``names`` come from its type alone.

    That holds when the instance has no ``__dict__``, its type has no ``__getattr__``,
    and none of the names is a slot. It means no instance can add or replace them.
    """
    return not hasattr(obj, "__dict__") and _is_type_bound_static(type(obj), *names)


def _get_bound_method(cls: type, name: str) -> object:
    """Gets ``cls``'s method ``name`` as an instance of ``cls`` would see it."""
    attr = getattr(cls, name, None)

    if isfunction(attr) and isfunction(getattr_static(cls, name, None)):
        method: object = MethodType(attr, MISSING)
    else:
        method = attr

    return method


def _check_strict(
    is_member: bool, protocol: type, get_method: Callable[[str], object], *methods: str
) -> bool:
    available, selected = _get_instance_methods(protocol, *methods)
    match = False

    if is_member:
        for name, member in available:
            if selected and name not in selected:
                continue

            method = get_method(name)

            if not callable(method):
                break

            try:
                actual = signature(method)
            except (TypeError, ValueError):
                continue

            expected = _protocol_signature(member)

            if not _signature_compatible(expected, actual):
                break
        else:
            match = True

    return match


def _get_instance_methods(
    protocol: type, *methods: str
) -> tuple[Iterator[tuple[str, Func[object]]], set[str]]:
    """Gets the protocol's instance methods and the selected names, checking both."""
    available = _get_protocol_members(protocol)
    available_names = {name for name, _ in available}
    selected = set(methods)

    if selected and (unknown := selected - available_names):
        unknown_names = ", ".join(sorted(unknown))
        raise TypeError(f"{protocol.__name__} has unknown method(s): {unknown_names}")

    def isnt_instance_method(pair: tuple[str, Func[object]]) -> bool:
        return isinstance(pair[1], (staticmethod, classmethod))

    for name, _ in filter(isnt_instance_method, available):
        if not selected or name in selected:
            msg = f"{protocol.__name__}.{name} must be an instance method"
            raise TypeError(msg)

    return filterfalse(isnt_instance_method, available), selected


def _check_strict_protocol(obj: object, protocol: type, *methods: str) -> bool:
    get_method = partial(getattr, obj)
    return _check_strict(isinstance(obj, protocol), protocol, get_method, *methods)


@lru_cache(maxsize=settings.strict_check_cache_size)
def _check_strict_type(cls: type, protocol: type, *methods: str) -> bool:
    get_method = partial(_get_bound_method, cls)
    return _check_strict(issubclass(cls, protocol), protocol, get_method, *methods)


def isinstance_strict[P](obj: object, protocol: type[P], *methods: str) -> TypeIs[P]:
    """
    Checks runtime protocol membership and method call compatibility.

    A callable built-in method whose signature cannot be inspected (e.g., a generator's
    ``close``) counts as compatible.
    """
    names = (name for name, _ in _get_protocol_members(protocol))
    by_type = not getattr(protocol, "__non_callable_proto_members__", None)

    if by_type and is_type_bound(obj, *names):
        match = _check_strict_type(type(obj), protocol, *methods)
    else:
        match = _check_strict_protocol(obj, protocol, *methods)

    return match


def is_mapping(val: Mapping[_KT, _VT] | object) -> TypeIs[Mapping[_KT, _VT]]:
    return isinstance(val, (dict, CaseInsensitiveDict)) or (
        not isinstance(val, (str, int, float)) and isinstance(val, Mapping)
    )


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
        raise error(f"{what} must be a mapping, not {type(value).__name__}")

    return value


def is_known_sequence(
    val: list[_VT] | tuple[_VT, ...] | object,
) -> TypeIs[list[_VT] | tuple[_VT, ...]]:
    return isinstance(val, (list, tuple))


def is_mapping_seq(
    val: list[object] | tuple[object, ...],
) -> TypeGuard[list[Mapping[object, object]] | tuple[Mapping[object, object], ...]]:
    return bool(val and is_mapping(val[0]))


def is_value_seq(
    val: list[object] | tuple[object, ...],
) -> TypeGuard[BasicList | tuple[BasicValue, BasicValue]]:
    return bool(val and isinstance(val[0], BasicValueType))


@overload
def is_listlike[T](value: Iterable[T] | None) -> TypeGuard[Iterable[T]]: ...
@overload
def is_listlike[T](value: Iterable[T] | T) -> TypeGuard[Iterable[T]]: ...
def is_listlike(value: object) -> bool:
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
    return not (
        value is None
        or isinstance(
            value, (PrimitiveValueType, bytes, dict, CaseInsensitiveDict, Mapping)
        )
    ) and isinstance(value, Iterable)


def is_sequence(val: object) -> TypeIs[Sequence[object]]:
    return isinstance(val, (list, tuple)) or (
        not isinstance(val, (int, float)) and isinstance(val, Sequence)
    )


@overload
def require_listlike[T](
    value: Iterable[T], what: str, *, error: type[Exception] = ..., **_: object
) -> Iterable[T]: ...
@overload
def require_listlike(
    value: object, what: str, *, error: type[Exception] = ..., **_: object
) -> Iterable[object]: ...
def require_listlike(
    value: object, what: str, *, error: type[Exception] = InvalidPipelineError, **_
) -> Iterable[object]:
    """Narrows a value to a non-string iterable or raises ``error``."""
    if not is_listlike(value):
        raise error(f"{what} must be a list")

    return value


def require_sequence(
    value: _VT,
    what: str | Callable[[_VT], str],
    *,
    error: type[Exception] = InvalidPipelineError,
    **_,
) -> Sequence[object]:
    """Narrows a value to a Sequence or raises ``error``."""
    if not is_sequence(value):
        msg = what(value) if callable(what) else what
        raise error(f"{msg} must be a Sequence")

    return value


@overload
def is_streamlike[T](value: AnyIterable[T] | None) -> TypeGuard[AnyIterable[T]]: ...
@overload
def is_streamlike[T](value: AnyIterable[T] | T) -> TypeGuard[AnyIterable[T]]: ...
def is_streamlike(value: object) -> bool:
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
def is_async_callable[T](val: Func[T | Awaitable[T]]) -> TypeGuard[AsyncFunc[T]]: ...
@overload
def is_async_callable(val: object) -> TypeGuard[AsyncFunc[object]]: ...
def is_async_callable(val: object) -> bool:
    if callable(val):
        result = iscoroutinefunction(val) or iscoroutinefunction(type(val).__call__)
    else:
        result = False

    return result


def is_awaitable[T](value: T | Awaitable[T]) -> TypeIs[Awaitable[T]]:
    """
    Reports whether ``value`` is awaitable.

    Args:

        value: A value or an awaitable that resolves to one.

    Returns:

        Whether ``value`` must be awaited to get its result.

    Examples:

        >>> async def answer():
        ...     return 42
        >>>
        >>> coro = answer()
        >>> is_awaitable(coro), is_awaitable(42)
        (True, False)
        >>> coro.close()

    """
    return isawaitable(value)


@overload
def is_sync_callable[T](val: Func[T] | None) -> TypeGuard[Func[T]]: ...
@overload
def is_sync_callable(val: object) -> TypeGuard[Func[object]]: ...
def is_sync_callable(val: object) -> bool:
    return callable(val) and not is_async_callable(val)


@overload
def is_callable[T](val: Func[T] | None) -> TypeGuard[Func[T]]: ...
@overload
def is_callable(val: object) -> TypeGuard[Func[object]]: ...
def is_callable(val: object) -> bool:
    return callable(val)
