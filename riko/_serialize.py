# vim: sw=4:ts=4:expandtab
"""
riko._serialize
~~~~~~~~~~~~~~~
Dataclass construction (``fromdict``) and hashable round-tripping for the
argument-repr memoization cache (``repr_cache``).
"""

import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, fields, is_dataclass
from functools import cache, wraps
from logging import Logger
from time import struct_time
from types import UnionType
from typing import (
    TYPE_CHECKING,
    Any,
    Literal,
    Protocol,
    TypeGuard,
    TypeVar,
    Union,
    cast,
    get_args,
    get_origin,
    get_type_hints,
)

import pygogo as gogo

import riko.cast as cast_module
from riko._objectify import Objectify
from riko.dotdict import DotDict
from riko.types.values import (
    Hashable,
    HashableType,
    RikoDict,
    RikoList,
    RikoValue,
    StringyDict,
    StringyList,
)

if TYPE_CHECKING:
    from _typeshed import DataclassInstance

logger: Logger = gogo.Gogo(__name__, monolog=True).logger

T_co = TypeVar("T_co", covariant=True)
VT = TypeVar("VT")

type TuplePair = tuple[str, HashableOrTuple]
type InnerPairs = tuple[TuplePair, ...]
type DataclassTuple = tuple[str, tuple[type, InnerPairs]]
type CollectionTuple = tuple[type, InnerPairs | tuple[HashableOrTuple, ...]]
type HashableOrTuple = Hashable | CollectionTuple | DataclassTuple


def is_dataclass_tuple(obj: tuple[Any, ...]) -> TypeGuard[DataclassTuple]:
    return obj[0] == "dataclass"


class ReprCacheWrapper(Protocol[T_co]):
    def __call__(  # noqa: E704
        self, *args: VT, **kwargs: VT
    ) -> T_co: ...
    def cache_clear(self) -> None: ...  # noqa: E704
    def cache_info(self) -> object: ...  # noqa: E704


def fromdict(
    cls: type["DataclassInstance"],
    **data: Union["DataclassInstance", RikoValue, StringyList, StringyDict],
) -> "DataclassInstance":
    """
    Examples:
        >>> from dataclasses import dataclass
        >>> @dataclass
        ... class Inner:
        ...     n: int = 0
        >>> @dataclass
        ... class Outer:
        ...     inner: Inner | None = None
        >>> fromdict(Outer, inner={'n': 5}).inner
        Inner(n=5)

    """
    module = sys.modules[cls.__module__]
    localns = {**vars(module), **vars(cast_module)}
    hints = get_type_hints(cls, localns=localns, include_extras=True)

    for f in fields(cls):
        if f.name not in data:
            continue

        ftype = hints[f.name]
        val = data[f.name]
        origin = get_origin(ftype)

        if origin is Union or origin is UnionType:
            args = [a for a in get_args(ftype) if a is not type(None)]
            ftype = args[0] if args else ftype
            origin = get_origin(ftype)

        if origin is Literal:
            valid = get_args(ftype)

            if val not in valid:
                raise ValueError(f"Invalid {f.name}={val!r}, expected one of {valid}")
        elif is_dataclass(ftype) and isinstance(ftype, type) and isinstance(val, dict):
            val = fromdict(ftype, **val)

        data[f.name] = val

    return cls(**data)


def _to_hashable(obj: object) -> HashableOrTuple:
    hashed: HashableOrTuple = None

    if obj is None:
        pass
    elif isinstance(obj, HashableType):
        hashed = cast(Hashable, obj)
    elif isinstance(obj, DotDict):
        inner = sorted((k, _to_hashable(v)) for k, v in obj._store.values())
        hashed = (DotDict, tuple(inner))
    elif isinstance(obj, Mapping):
        inner = sorted((k, _to_hashable(v)) for k, v in obj.items())
        typ = Objectify if isinstance(obj, Objectify) else dict
        hashed = (typ, tuple(inner))
    elif isinstance(obj, Sequence):
        hashed = (list, tuple(_to_hashable(v) for v in obj))
    elif is_dataclass(obj):
        items = asdict(cast("DataclassInstance", obj)).items()
        inner = tuple(sorted((k, _to_hashable(v)) for k, v in items))
        hashed = ("dataclass", (type(obj), inner))
    else:
        logger.error(f"Unsupported {type(obj)=}")

    return hashed


@cache
def _from_hashable(
    obj: HashableOrTuple,
) -> Union[RikoValue, Objectify, "DataclassInstance", CollectionTuple, DataclassTuple]:
    if not isinstance(obj, struct_time) and isinstance(obj, tuple) and len(obj) == 2:
        if is_dataclass_tuple(obj):
            typ, (cls, inner) = obj
        else:
            typ, inner = cast(CollectionTuple, obj)
            cls = None

        if typ in (Objectify, DotDict, dict, "dataclass"):
            _arg = {k: _from_hashable(v) for k, v in cast(InnerPairs, inner)}
            arg = cast(RikoDict, _arg)

            if (typ is Objectify) or (typ is DotDict):
                arg = typ(arg)
            elif cls and typ == "dataclass":
                arg = fromdict(cls, **arg)
        elif typ is list:
            _arg = [_from_hashable(v) for v in cast(tuple[HashableOrTuple, ...], inner)]
            arg = cast(RikoList, _arg)
        else:
            arg = obj
    else:
        arg = obj

    return arg


def repr_cache[R](fn: Callable[..., R]) -> ReprCacheWrapper[R]:
    @cache
    def _cached(hashable_args: tuple, hashable_kwargs: tuple) -> R:
        args = tuple(_from_hashable(a) for a in hashable_args)
        kwargs = {k: _from_hashable(v) for k, v in hashable_kwargs}
        return fn(*args, **kwargs)

    @wraps(fn)
    def wrapper(*args: VT, **kwargs: VT) -> R:
        return _cached(
            tuple(_to_hashable(a) for a in args),
            tuple(sorted((k, _to_hashable(v)) for k, v in kwargs.items())),
        )

    setattr(wrapper, "cache_clear", _cached.cache_clear)  # noqa: B010
    setattr(wrapper, "cache_info", _cached.cache_info)  # noqa: B010
    return cast(ReprCacheWrapper[R], wrapper)


# https://trac.edgewall.org/ticket/2066#comment:1
# http://stackoverflow.com/a/22675049/408556
