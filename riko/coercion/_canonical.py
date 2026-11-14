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
from functools import partial, update_wrapper
from hashlib import blake2b
from itertools import chain
from json.encoder import encode_basestring as _dump_str
from math import isinf, isnan
from pathlib import PurePath, PureWindowsPath
from time import struct_time
from typing import TYPE_CHECKING, NamedTuple
from uuid import UUID

import attrs

from riko.base._exceptions import CyclicIdentityError, IdentityEncodingError
from riko.base._guards import is_mapping
from riko.base._iterutils import sort_stably

from ._dates import resolve_aware_datetime, tt_to_datetime

if TYPE_CHECKING:
    from collections.abc import Hashable, Iterable

    from _typeshed import DataclassInstance
    from attrs import AttrsInstance

    from riko.types._wrappers import Func

type CanonicalValue = str | bool | list[CanonicalValue] | None
type Canonicalizer[V] = Callable[[V, set[int]], CanonicalValue]

_NATIVE_KEY_TYPES: frozenset[type] = frozenset(
    {str, bytes, int, float, bool, type(None)}
)

IDENTITY_FORMAT_VERSION = 1


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
    aware = resolve_aware_datetime(value, try_local_tz=False)
    return aware.astimezone(UTC).isoformat()


def _canon_struct_time(value: struct_time) -> str:
    return _canon_datetime(tt_to_datetime(value, def_tzinfo=UTC))


def _encode_utf8(dumped: str) -> bytes:
    try:
        encoded = dumped.encode("utf-8")
    except UnicodeEncodeError as e:
        raise IdentityEncodingError(str) from e

    return encoded


def canonical_json(canon: CanonicalValue) -> bytes:
    """
    Encode a canonical value into fixed canonical UTF-8 JSON bytes.

    Returns:

        Byte-stable JSON with no insignificant whitespace.

    Raises:

        IdentityEncodingError: If a string has no UTF-8 encoding.

    Examples:

        >>> canonical_json(canonicalize(1))
        b'["int","1"]'

    """
    dumped = json.dumps(
        canon, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )

    return _encode_utf8(dumped)


def _canon_seq(tag: str, values: Iterable[object], seen: set[int]) -> CanonicalValue:
    canon = [_canon(v, seen) for v in values]
    return [tag, canon]


def _canon_set(tag: str, value: AbstractSet[object], seen: set[int]) -> CanonicalValue:
    canon = sorted((_canon(v, seen) for v in value), key=canonical_json)
    return [tag, canon]


def _canon_map[K](value: Mapping[K, object], seen: set[int]) -> CanonicalValue:
    pairs = [(_canon(k, seen), _canon(v, seen)) for k, v in value.items()]
    ordered = sorted(pairs, key=lambda pair: canonical_json([pair[0], pair[1]]))
    return ["map", [[k, v] for k, v in ordered]]


def _canon_record(
    value: object, names: Iterable[str], seen: set[int]
) -> CanonicalValue:
    inner = sorted((name, _canon(getattr(value, name), seen)) for name in names)
    return ["record", _type_id(type(value)), [[name, canon] for name, canon in inner]]


def _canon_dataclass(value: DataclassInstance, seen: set[int]) -> CanonicalValue:
    return _canon_record(value, (f.name for f in fields(value)), seen)


def _canon_attrs(value: AttrsInstance, seen: set[int]) -> CanonicalValue:
    attributes = attrs.fields(type(value))
    return _canon_record(value, (a.name for a in attributes), seen)


def _guard[V](
    value: V, seen: set[int], canonicalizer: Canonicalizer[V]
) -> CanonicalValue:
    marker = id(value)

    if marker in seen:
        raise CyclicIdentityError

    seen.add(marker)
    result = canonicalizer(value, seen)
    seen.discard(marker)
    return result


def _canon(value: object, seen: set[int]) -> CanonicalValue:
    match value:
        case None:
            result: CanonicalValue = ["none", None]
        case Enum():
            result = ["enum", _type_id(type(value)), value.name]
        case bool():
            result = ["bool", value]
        case int():
            result = ["int", str(value)]
        case float():
            result = ["float", _canon_float(value)]
        case Decimal():
            result = ["dec", _canon_decimal(value)]
        case str():
            result = ["str", value]
        case bytes():
            result = ["bytes", value.hex()]
        case datetime():
            result = ["dt", _canon_datetime(value)]
        case struct_time():
            result = ["tt", _canon_struct_time(value)]
        case date():
            result = ["date", value.isoformat()]
        case PurePath():
            flavor = "windows" if isinstance(value, PureWindowsPath) else "posix"
            result = ["path", flavor, str(value)]
        case UUID():
            result = ["uuid", value.hex]
        case _ if is_mapping(value):
            result = _guard(value, seen, _canon_map)
        case frozenset():
            result = _guard(value, seen, partial(_canon_set, "fset"))
        case AbstractSet():
            result = _guard(value, seen, partial(_canon_set, "set"))
        case tuple():
            result = _guard(value, seen, partial(_canon_seq, "tup"))
        case list():
            result = _guard(value, seen, partial(_canon_seq, "list"))
        case _:
            if attrs.has(type(value)):
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


def _dump_simple(value: object) -> str | None:
    """
    Dumps a str, int, ``None``, or a (nested) tuple of them as canonical JSON text.

    The identity tuples a run builds are made of these. They skip the tagged
    intermediate structure and ``json.dumps``. The text is exactly what the general path
    produces. Any other value (a ``bool``, a subclass, a named tuple) returns ``None``
    so the caller takes the general path. ``_native_key`` is the process-local twin for
    ``repr_cache``: it keys on Python's own hashing, which durable bytes must never
    depend on.

    Args:

        value: The value to dump.

    Returns:

        The canonical JSON text, or ``None`` when the value needs the general path.

    """
    if type(value) is str:
        result = f'["str",{_dump_str(value)}]'
    elif type(value) is int:
        result = f'["int","{value}"]'
    elif value is None:
        result = '["none",null]'
    elif type(value) is tuple:
        dumped = map(_dump_simple, value)
        parts = [part for part in dumped if part is not None]
        complete = len(parts) == len(value)
        result = f'["tup",[{",".join(parts)}]]' if complete else None
    else:
        result = None

    return result


def canonical_bytes(value: object) -> bytes:
    """
    Canonicalize and encode a value into canonical UTF-8 JSON bytes.

    Returns:

        The canonical bytes for the value.

    Examples:

        >>> canonical_bytes('a')
        b'["str","a"]'
        >>> canonical_bytes(1)
        b'["int","1"]'
        >>> canonical_bytes(True)
        b'["bool",true]'

    """
    if (dumped := _dump_simple(value)) is None:
        result = canonical_json(canonicalize(value))
    else:
        result = _encode_utf8(dumped)

    return result


def _build_header(domain: IdentityDomain) -> bytes:
    return f"riko-identity:{IDENTITY_FORMAT_VERSION}:{domain.value}".encode()


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
    header = _build_header(domain)
    _bytes = canonical_bytes(value)
    return blake2b(header + b"\x00" + _bytes, digest_size=16).hexdigest()


@attrs.define(eq=False)
class IdentityAccumulator:
    """
    Folds values into one running domain-separated digest, one value at a time.

    Each added value extends the hash with a separator byte and the value's canonical
    bytes, under the same domain header ``digest`` uses. One added value digests exactly
    as ``digest`` does. The fold is order-sensitive.

    Args:

        domain: The identity domain that separates the running digest.

    Examples:

        >>> acc = IdentityAccumulator(IdentityDomain.GENERATION)
        >>> acc.add(1)
        >>> acc.digest() == digest(1, IdentityDomain.GENERATION)
        True
        >>> acc.add("a")
        >>> acc.digest() == digest(1, IdentityDomain.GENERATION)
        False

    """

    domain: IdentityDomain
    _hasher: blake2b = attrs.field(init=False, repr=False)

    def __attrs_post_init__(self) -> None:
        self._hasher = blake2b(_build_header(self.domain), digest_size=16)

    def add(self, value: object) -> None:
        """Adds a value's canonical bytes to the running digest."""
        self._hasher.update(b"\x00" + canonical_bytes(value))

    def digest(self) -> str:
        """Gets the digest of every value added so far while leaving the fold open."""
        return self._hasher.copy().hexdigest()


def _is_native_val(value: object) -> bool:
    """Reports whether a value's own hash and equality match its canonical identity."""
    is_native = type(value) in _NATIVE_KEY_TYPES

    if is_native and isinstance(value, float):
        is_native = not isnan(value)

    return is_native


def _native_key(*args: object, **kwargs: object) -> tuple[object, ...] | None:
    """
    Gets the process-local key for a call whose arguments are all exact-type scalars.

    Python's own hashing keys the call. This is cheaper than ``_dump_simple``'s durable
    bytes. It covers ``float``, ``bool``, and ``bytes``; and accepts a lone-surrogate
    string the durable encoder rejects. Any other argument returns ``None``.
    """
    if all(map(_is_native_val, chain(args, kwargs.values()))):
        tagged = tuple((type(a), a) for a in args)
        key = (tagged, sort_stably((k, type(v), v) for k, v in kwargs.items()))
    else:
        key = None

    return key


def _cache_key(*args: object, **kwargs: object) -> Hashable | None:
    if (key := _native_key(*args, **kwargs)) is None:
        try:
            key = canonical_bytes((args, sort_stably(kwargs.items())))
        except (IdentityEncodingError, CyclicIdentityError):
            key = None

    return key


class repr_cache[R]:  # noqa: N801
    """
    Memoizes a callable by the canonical encoding of its arguments.

    A call whose arguments are all plain scalars is keyed without the encoding step.
    Hits on such calls stay cheap. Arguments that cannot be canonically encoded bypass
    the cache so distinct instances never collide on a shared key. The store is
    unbounded and private to one decorated callable.

    Args:

        fn: The callable to memoize and carry over its name and docstring.

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
        >>> tally.cache_info()
        CacheInfo(hits=1, misses=3, maxsize=None, currsize=1)

    """

    def __init__(self, fn: Func[R]) -> None:
        self._fn = fn
        self._store: dict[Hashable, R] = {}
        self._hits = 0
        self._misses = 0
        update_wrapper(self, fn)

    def __call__(self, *args: object, **kwargs: object) -> R:
        key = _cache_key(*args, **kwargs)

        if key is None:
            self._misses += 1
            result = self._fn(*args, **kwargs)
        elif key in self._store:
            self._hits += 1
            result = self._store[key]
        else:
            self._misses += 1
            result = self._store[key] = self._fn(*args, **kwargs)

        return result

    def cache_clear(self) -> None:
        self._store.clear()
        self._hits = self._misses = 0

    def cache_info(self) -> CacheInfo:
        return CacheInfo(self._hits, self._misses, None, len(self._store))
