# vim: sw=4:ts=4:expandtab
"""Canonical value freezing, encoding, and durable digests for identity."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from collections.abc import Set as AbstractSet
from dataclasses import fields, is_dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum, StrEnum
from functools import wraps
from hashlib import blake2b
from math import isinf, isnan
from pathlib import PurePath, PureWindowsPath
from time import struct_time
from typing import TYPE_CHECKING, NamedTuple, Protocol, TypeVar, cast
from uuid import UUID

from riko.base.exceptions import CyclicIdentityError, IdentityEncodingError

from ._dates import normalize_tzinfo, tt_to_datetime

if TYPE_CHECKING:
    from _typeshed import DataclassInstance

type FrozenValue = str | bool | list[FrozenValue] | None
type Freezer = Callable[[object, set[int]], FrozenValue]

IDENTITY_FORMAT_VERSION = 1

T_co = TypeVar("T_co", covariant=True)
VT = TypeVar("VT")


class IdentityDomain(StrEnum):
    """Fixed Riko-owned domains that separate durable digests."""

    FINGERPRINT = "fingerprint"
    GENERATION = "generation"
    IDEMPOTENCY = "idempotency"
    STATE_KEY = "state-key"


class CacheInfo(NamedTuple):
    hits: int
    misses: int
    maxsize: int | None
    currsize: int


class ReprCacheWrapper(Protocol[T_co]):
    def __call__(  # noqa: E704
        self, *args: VT, **kwargs: VT
    ) -> T_co: ...
    def cache_clear(self) -> None: ...  # noqa: E704
    def cache_info(self) -> CacheInfo: ...  # noqa: E704


def _type_id(cls: type) -> str:
    return f"{cls.__module__}.{cls.__qualname__}"


def _freeze_float(value: float) -> str:
    if isnan(value):
        result = "nan"
    elif isinf(value):
        result = "inf" if value > 0 else "-inf"
    else:
        result = repr(value + 0.0)

    return result


def _freeze_decimal(value: Decimal) -> str:
    if value.is_nan():
        result = "nan"
    elif value.is_infinite():
        result = "inf" if value > 0 else "-inf"
    else:
        result = str(value.normalize())

    return result


def _freeze_datetime(value: datetime) -> str:
    aware = value if value.tzinfo else normalize_tzinfo(value, try_local_tz=False)
    return aware.astimezone(UTC).isoformat()


def _freeze_struct_time(value: struct_time) -> str:
    moment = tt_to_datetime(normalize_tzinfo(value, try_local_tz=False))
    return moment.astimezone(UTC).isoformat()


def _sort_key(frozen: FrozenValue) -> bytes:
    return canonical_json(frozen)


def _freeze_seq(values: object, tag: str, seen: set[int]) -> FrozenValue:
    frozen = [_freeze(v, seen) for v in cast("tuple[object, ...]", values)]
    return [tag, frozen]


def _freeze_set(values: object, tag: str, seen: set[int]) -> FrozenValue:
    frozen = sorted(
        (_freeze(v, seen) for v in cast("AbstractSet[object]", values)), key=_sort_key
    )
    return [tag, frozen]


def _freeze_map(obj: object, seen: set[int]) -> FrozenValue:
    mapping = cast("Mapping[object, object]", obj)
    pairs = [(_freeze(k, seen), _freeze(v, seen)) for k, v in mapping.items()]
    ordered = sorted(pairs, key=lambda pair: _sort_key(pair[0]))
    return ["map", [[k, v] for k, v in ordered]]


def _freeze_dataclass(obj: object, seen: set[int]) -> FrozenValue:
    instance = cast("DataclassInstance", obj)
    inner = sorted(
        (f.name, _freeze(getattr(instance, f.name), seen)) for f in fields(instance)
    )
    return ["dc", _type_id(type(obj)), [[name, value] for name, value in inner]]


def _guard(obj: object, seen: set[int], freezer: Freezer) -> FrozenValue:
    marker = id(obj)

    if marker in seen:
        raise CyclicIdentityError

    seen.add(marker)
    result = freezer(obj, seen)
    seen.discard(marker)
    return result


def _freeze(obj: object, seen: set[int]) -> FrozenValue:
    if obj is None:
        result: FrozenValue = ["none", None]
    elif isinstance(obj, Enum):
        result = ["enum", _type_id(type(obj)), obj.name]
    elif isinstance(obj, bool):
        result = ["bool", obj]
    elif isinstance(obj, int):
        result = ["int", str(obj)]
    elif isinstance(obj, float):
        result = ["float", _freeze_float(obj)]
    elif isinstance(obj, Decimal):
        result = ["dec", _freeze_decimal(obj)]
    elif isinstance(obj, str):
        result = ["str", obj]
    elif isinstance(obj, bytes):
        result = ["bytes", obj.hex()]
    elif isinstance(obj, datetime):
        result = ["dt", _freeze_datetime(obj)]
    elif isinstance(obj, struct_time):
        result = ["tt", _freeze_struct_time(obj)]
    elif isinstance(obj, date):
        result = ["date", obj.isoformat()]
    elif isinstance(obj, PurePath):
        flavor = "windows" if isinstance(obj, PureWindowsPath) else "posix"
        result = ["path", flavor, str(obj)]
    elif isinstance(obj, UUID):
        result = ["uuid", obj.hex]
    elif isinstance(obj, Mapping):
        result = _guard(obj, seen, _freeze_map)
    elif isinstance(obj, frozenset):
        result = _guard(obj, seen, lambda o, s: _freeze_set(o, "fset", s))
    elif isinstance(obj, AbstractSet):
        result = _guard(obj, seen, lambda o, s: _freeze_set(o, "set", s))
    elif isinstance(obj, tuple):
        result = _guard(obj, seen, lambda o, s: _freeze_seq(o, "tup", s))
    elif isinstance(obj, list):
        result = _guard(obj, seen, lambda o, s: _freeze_seq(o, "list", s))
    elif is_dataclass(obj) and not isinstance(obj, type):
        result = _guard(obj, seen, _freeze_dataclass)
    else:
        raise IdentityEncodingError(type(obj))

    return result


def freeze(obj: object) -> FrozenValue:
    """
    Canonicalize a value into a deterministic tagged representation.

    Distinguishes types Python normally conflates (``bool``/``int``,
    ``int``/``float``/``Decimal``, ``list``/``tuple``) and canonicalizes
    temporal, path, UUID, enum, mapping, set, and dataclass values. Mappings
    and sets are order-independent; cyclic structures are rejected.

    Returns:
        A JSON-safe tagged structure suitable for canonical encoding.

    Examples:

        >>> freeze(True)
        ['bool', True]
        >>> freeze(1) == freeze(True)
        False
        >>> freeze({'b': 1, 'a': 2}) == freeze({'a': 2, 'b': 1})
        True

    """
    return _freeze(obj, set())


def canonical_json(frozen: FrozenValue) -> bytes:
    """
    Encode a frozen value into fixed canonical UTF-8 JSON bytes.

    Returns:
        Byte-stable JSON with no insignificant whitespace.

    Examples:

        >>> canonical_json(freeze(1))
        b'["int","1"]'

    """
    dumped = json.dumps(
        frozen, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )
    return dumped.encode("utf-8")


def canonical_bytes(obj: object) -> bytes:
    """
    Freeze and encode a value into canonical UTF-8 JSON bytes.

    Returns:
        The canonical bytes for the frozen value.

    Examples:

        >>> canonical_bytes('a') == canonical_bytes('a')
        True

    """
    return canonical_json(freeze(obj))


def digest(obj: object, domain: IdentityDomain) -> str:
    """
    Compute a domain-separated durable digest of a value.

    Returns:
        A 32-character lowercase hex BLAKE2b-128 digest.

    Examples:

        >>> a = digest(1, IdentityDomain.FINGERPRINT)
        >>> len(a)
        32
        >>> a == digest(1, IdentityDomain.IDEMPOTENCY)
        False

    """
    header = f"riko-identity:{IDENTITY_FORMAT_VERSION}:{domain.value}".encode()
    return blake2b(header + b"\x00" + canonical_bytes(obj), digest_size=16).hexdigest()


def _cache_key(args: tuple[object, ...], kwargs: Mapping[str, object]) -> bytes | None:
    try:
        key = canonical_bytes((args, tuple(sorted(kwargs.items()))))
    except (IdentityEncodingError, CyclicIdentityError):
        key = None

    return key


def repr_cache[R](fn: Callable[..., R]) -> ReprCacheWrapper[R]:
    """
    Memoize a callable by the canonical encoding of its arguments.

    Arguments that cannot be canonically encoded bypass the cache so distinct
    instances never collide on a shared key.

    Returns:
        A wrapper exposing ``cache_clear`` and ``cache_info``.

    Examples:

        >>> calls = []
        >>> @repr_cache
        ... def tally(x):
        ...     calls.append(x)
        ...     return len(calls)
        >>> tally(5), tally(5)
        (1, 1)
        >>> class Opaque: pass
        >>> _ = (tally(Opaque()), tally(Opaque()))
        >>> len(calls)
        3

    """
    store: dict[bytes, R] = {}
    stats = {"hits": 0, "misses": 0}

    @wraps(fn)
    def wrapper(*args: VT, **kwargs: VT) -> R:
        key = _cache_key(args, kwargs)

        if key is None:
            stats["misses"] += 1
            result = fn(*args, **kwargs)
        elif key in store:
            stats["hits"] += 1
            result = store[key]
        else:
            stats["misses"] += 1
            result = store[key] = fn(*args, **kwargs)

        return result

    def cache_clear() -> None:
        store.clear()
        stats.update(hits=0, misses=0)

    def cache_info() -> CacheInfo:
        return CacheInfo(stats["hits"], stats["misses"], None, len(store))

    setattr(wrapper, "cache_clear", cache_clear)  # noqa: B010
    setattr(wrapper, "cache_info", cache_info)  # noqa: B010
    return cast("ReprCacheWrapper[R]", wrapper)
