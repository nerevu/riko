# vim: sw=4:ts=4:expandtab
"""Canonical value encoding and durable digests for identity."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from collections.abc import Set as AbstractSet
from dataclasses import fields, is_dataclass
from datetime import UTC, date, datetime
from decimal import Context, Decimal, localcontext
from enum import Enum, StrEnum
from functools import partial, wraps
from hashlib import blake2b
from math import isinf, isnan
from pathlib import PurePath, PureWindowsPath
from time import struct_time
from typing import TYPE_CHECKING, NamedTuple, Protocol, TypeVar, cast
from uuid import UUID

import attrs

from riko.base.exceptions import CyclicIdentityError, IdentityEncodingError

from ._dates import normalize_tzinfo, tt_to_datetime

if TYPE_CHECKING:
    from _typeshed import DataclassInstance
    from attrs import AttrsInstance

type CanonicalValue = str | bool | list[CanonicalValue] | None
type Canonicalizer = Callable[[object, set[int]], CanonicalValue]

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
    def __call__(self, *args: VT, **kwargs: VT) -> T_co: ...  # noqa: E704
    def cache_clear(self) -> None: ...  # noqa: E704
    def cache_info(self) -> CacheInfo: ...  # noqa: E704


def _type_id(cls: type) -> str:
    return f"{cls.__module__}.{cls.__qualname__}"


def _canon_float(value: float) -> str:
    if isnan(value):
        result = "nan"
    elif isinf(value):
        result = "inf" if value > 0 else "-inf"
    else:
        result = repr(value + 0.0)

    return result


def _canon_decimal(value: Decimal) -> str:
    if value.is_nan():
        result = "nan"
    elif value.is_infinite():
        result = "inf" if value > 0 else "-inf"
    else:
        digits = len(value.as_tuple().digits)

        with localcontext(Context(prec=max(digits, 1))):
            result = str(value.normalize())

    return result


def _canon_datetime(value: datetime) -> str:
    aware = value if value.tzinfo else normalize_tzinfo(value, try_local_tz=False)
    return aware.astimezone(UTC).isoformat()


def _canon_struct_time(value: struct_time) -> str:
    moment = tt_to_datetime(normalize_tzinfo(value, try_local_tz=False))
    return moment.astimezone(UTC).isoformat()


def _sort_key(canon: CanonicalValue) -> bytes:
    return canonical_json(canon)


def _canon_seq(tag: str, values: object, seen: set[int]) -> CanonicalValue:
    canon = [_canon(v, seen) for v in cast("tuple[object, ...]", values)]
    return [tag, canon]


def _canon_set(tag: str, value: object, seen: set[int]) -> CanonicalValue:
    values = cast("AbstractSet[object]", value)
    canon = sorted((_canon(v, seen) for v in values), key=_sort_key)
    return [tag, canon]


def _canon_map(value: object, seen: set[int]) -> CanonicalValue:
    mapping = cast("Mapping[object, object]", value)
    pairs = [(_canon(k, seen), _canon(v, seen)) for k, v in mapping.items()]
    ordered = sorted(pairs, key=lambda pair: _sort_key([pair[0], pair[1]]))
    return ["map", [[k, v] for k, v in ordered]]


def _canon_dataclass(value: object, seen: set[int]) -> CanonicalValue:
    instance = cast("DataclassInstance", value)
    _fields = fields(instance)
    inner = sorted((f.name, _canon(getattr(instance, f.name), seen)) for f in _fields)
    return ["record", _type_id(type(value)), [[name, value] for name, value in inner]]


def _canon_attrs(value: object, seen: set[int]) -> CanonicalValue:
    attributes = attrs.fields(cast("type[AttrsInstance]", type(value)))
    inner = sorted(
        (attribute.name, _canon(getattr(value, attribute.name), seen))
        for attribute in attributes
    )
    return ["record", _type_id(type(value)), [[name, value] for name, value in inner]]


def _guard(
    value: object, seen: set[int], canonicalizer: Canonicalizer
) -> CanonicalValue:
    marker = id(value)

    if marker in seen:
        raise CyclicIdentityError

    seen.add(marker)
    result = canonicalizer(value, seen)
    seen.discard(marker)
    return result


def _canon(value: object, seen: set[int]) -> CanonicalValue:
    if value is None:
        result: CanonicalValue = ["none", None]
    elif isinstance(value, Enum):
        result = ["enum", _type_id(type(value)), value.name]
    elif isinstance(value, bool):
        result = ["bool", value]
    elif isinstance(value, int):
        result = ["int", str(value)]
    elif isinstance(value, float):
        result = ["float", _canon_float(value)]
    elif isinstance(value, Decimal):
        result = ["dec", _canon_decimal(value)]
    elif isinstance(value, str):
        result = ["str", value]
    elif isinstance(value, bytes):
        result = ["bytes", value.hex()]
    elif isinstance(value, datetime):
        result = ["dt", _canon_datetime(value)]
    elif isinstance(value, struct_time):
        result = ["tt", _canon_struct_time(value)]
    elif isinstance(value, date):
        result = ["date", value.isoformat()]
    elif isinstance(value, PurePath):
        flavor = "windows" if isinstance(value, PureWindowsPath) else "posix"
        result = ["path", flavor, str(value)]
    elif isinstance(value, UUID):
        result = ["uuid", value.hex]
    elif isinstance(value, Mapping):
        result = _guard(value, seen, _canon_map)
    elif isinstance(value, frozenset):
        result = _guard(value, seen, partial(_canon_set, "fset"))
    elif isinstance(value, AbstractSet):
        result = _guard(value, seen, partial(_canon_set, "set"))
    elif isinstance(value, tuple):
        result = _guard(value, seen, partial(_canon_seq, "tup"))
    elif isinstance(value, list):
        result = _guard(value, seen, partial(_canon_seq, "list"))
    elif attrs.has(type(value)):
        result = _guard(value, seen, _canon_attrs)
    elif is_dataclass(value) and not isinstance(value, type):
        result = _guard(value, seen, _canon_dataclass)
    else:
        raise IdentityEncodingError(type(value))

    return result


def canonicalize(value: object) -> CanonicalValue:
    """
    Canonicalize a value into a deterministic tagged representation.

    Distinguishes types Python normally conflates (``bool``/``int``,
    ``int``/``float``/``Decimal``, ``list``/``tuple``) and canonicalizes
    temporal, path, UUID, enum, mapping, set, dataclass, and attrs values.
    Mappings and sets are order-independent; cyclic structures are rejected.

    Returns:
        A JSON-safe tagged structure suitable for canonical encoding.

    Examples:

        >>> canonicalize(True)
        ['bool', True]
        >>> canonicalize(1) == canonicalize(True)
        False
        >>> canonicalize({'b': 1, 'a': 2}) == canonicalize({'a': 2, 'b': 1})
        True

    """
    return _canon(value, set())


def canonical_json(canon: CanonicalValue) -> bytes:
    """
    Encode a canonical value into fixed canonical UTF-8 JSON bytes.

    Returns:

        Byte-stable JSON with no insignificant whitespace.

    Examples:

        >>> canonical_json(canonicalize(1))
        b'["int","1"]'

    """
    dumped = json.dumps(
        canon, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )
    return dumped.encode("utf-8")


def canonical_bytes(value: object) -> bytes:
    """
    Canonicalize and encode a value into canonical UTF-8 JSON bytes.

    Returns:

        The canonical bytes for the value.

    Examples:

        >>> canonical_bytes('a') == canonical_bytes('a')
        True

    """
    return canonical_json(canonicalize(value))


def digest(value: object, domain: IdentityDomain) -> str:
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
    _bytes = canonical_bytes(value)
    return blake2b(header + b"\x00" + _bytes, digest_size=16).hexdigest()


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
