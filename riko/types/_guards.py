# vim: sw=4:ts=4:expandtab
"""
Provides type guard functions for riko types.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Awaitable, Callable, Generator, Mapping
from contextlib import AbstractAsyncContextManager, AbstractContextManager
from inspect import (
    Parameter,
    Signature,
    getmembers_static,
    isasyncgenfunction,
    iscoroutinefunction,
    isfunction,
    isgeneratorfunction,
    signature,
    unwrap,
)
from typing import TYPE_CHECKING, Any, TypeGuard

from requests.structures import CaseInsensitiveDict
from typing_extensions import TypeIs

from riko._objectify import Objectify
from riko._strutils import replacer

from ._io import AsyncCloseable, SyncCloseable
from ._scalars import BasicValueType
from ._sentinels import MISSING, SentinelValue, StreamState

if TYPE_CHECKING:
    from ._collections import BasicList
    from ._io import Closeable
    from ._resource import (
        AnyContextManager,
        ContextManagerFactory,
        GeneratorFactory,
        LifecycleFactory,
        ValueFactory,
    )
    from ._scalars import BasicValue
    from ._sentinels import MissingType, Sentinel
    from ._streams import Item, StatefulItem
    from .compile import LoopModule, PipeModule
    from .modules import ConfArg


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


def isinstance_strict(obj: object, protocol: type, *methods: str) -> bool:
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


def is_mapping[D, VT](val: Mapping[D, VT] | object) -> TypeIs[Mapping[D, VT]]:
    failure = False

    # Delay calling isinstance(val, Mapping) as much as possible
    if not (success := isinstance(val, (dict, CaseInsensitiveDict, Objectify))):
        failure = isinstance(val, (str, int, float))

    return success or (False if failure else isinstance(val, Mapping))


def is_stateful_item(val: Item | StatefulItem) -> TypeGuard[StatefulItem]:
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


def is_sentinel[VT](val: Mapping[str, VT], **kwargs: object) -> TypeGuard[Sentinel]:
    if SentinelValue in val:
        sentinel = str(val[SentinelValue])
        key = replacer(sentinel, "")
    else:
        key = None

    return all([key, (len(val) in {2, 3}), key in kwargs])


def is_type_value(val: Mapping[Any, Any]) -> TypeGuard[ConfArg]:
    return len(val) == 2 and "type" in val and "value" in val


def is_loop_module(module: PipeModule) -> TypeGuard[LoopModule]:
    return module["type"] == "loop" and "embed" in module


def is_sync_gen_factory(
    val: object, candidate: object = None
) -> TypeGuard[Callable[..., Generator]]:
    if candidate is None:
        candidate = unwrap(val) if callable(val) else val

    return candidate is val and isgeneratorfunction(val)


def is_async_gen_factory(
    val: object, candidate: object = None
) -> TypeGuard[Callable[..., AsyncGenerator]]:
    if candidate is None:
        candidate = unwrap(val) if callable(val) else val

    return candidate is val and isasyncgenfunction(val)


def is_sync_context_manager(
    val: object, candidate: object = None
) -> TypeIs[AbstractContextManager]:
    if candidate is None:
        candidate = unwrap(val) if callable(val) else val

    return candidate is val and isinstance(val, AbstractContextManager)


def is_async_context_manager(
    val: object, candidate: object = None
) -> TypeIs[AbstractAsyncContextManager]:
    if candidate is None:
        candidate = unwrap(val) if callable(val) else val

    return candidate is val and isinstance(val, AbstractAsyncContextManager)


def is_async_callable(val: object) -> TypeGuard[Callable[..., Awaitable]]:
    if callable(val):
        result = iscoroutinefunction(val) or iscoroutinefunction(type(val).__call__)
    else:
        result = False

    return result


def is_sync_callable(val: object) -> TypeGuard[Callable[..., object]]:
    return callable(val) and not is_async_callable(val)


def is_sync_cm_factory(
    val: object, candidate: object = None
) -> TypeGuard[Callable[..., AbstractContextManager]]:
    if candidate is None:
        candidate = unwrap(val) if callable(val) else val

    return candidate is not val and isgeneratorfunction(candidate)


def is_async_cm_factory(
    val: object, candidate: object = None
) -> TypeGuard[Callable[..., AbstractAsyncContextManager]]:
    if candidate is None:
        candidate = unwrap(val) if callable(val) else val

    return candidate is not val and isasyncgenfunction(candidate)


def is_gen_factory(
    val: object, candidate: object = None
) -> TypeGuard[GeneratorFactory]:
    if candidate is None:
        candidate = unwrap(val) if callable(val) else val

    if candidate is val:
        result = isasyncgenfunction(val) or isgeneratorfunction(val)
    else:
        result = False

    return result


def is_context_manager(
    val: object, candidate: object = None
) -> TypeIs[AnyContextManager]:
    if candidate is None:
        candidate = unwrap(val) if callable(val) else val

    if candidate is val:
        result = isinstance(val, (AbstractContextManager, AbstractAsyncContextManager))
    else:
        result = False

    return result


def is_cm_factory(
    val: object, candidate: object = None
) -> TypeGuard[ContextManagerFactory]:
    if candidate is None:
        candidate = unwrap(val) if callable(val) else val

    if candidate is val:
        result = False
    else:
        result = isgeneratorfunction(candidate) or isasyncgenfunction(candidate)

    return result


def is_lifecycle_factory(
    val: object, candidate: object = None
) -> TypeGuard[LifecycleFactory]:
    if candidate is None:
        candidate = unwrap(val) if callable(val) else val

    return isasyncgenfunction(candidate) or isgeneratorfunction(candidate)


def is_value_factory(val: object) -> TypeGuard[ValueFactory]:
    return callable(val)


def is_sync_closeable(val: object) -> TypeIs[SyncCloseable]:
    return isinstance_strict(val, SyncCloseable)


def is_async_closeable(val: object) -> TypeIs[AsyncCloseable]:
    return isinstance_strict(val, AsyncCloseable)


def is_closeable(val: object) -> TypeIs[Closeable]:
    return is_sync_closeable(val) or is_async_closeable(val)
