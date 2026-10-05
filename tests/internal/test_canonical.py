# vim: sw=4:ts=4:expandtab
"""Tests the canonical value encoder, golden digests, and repr cache."""

import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal, localcontext
from enum import Enum, StrEnum
from pathlib import PurePosixPath, PureWindowsPath
from uuid import UUID

import pytest
from attrs import define

from riko.base.exceptions import CyclicIdentityError, IdentityEncodingError
from riko.coercion._canonical import (
    IdentityDomain,
    canonical_bytes,
    canonicalize,
    digest,
    repr_cache,
)

GOLDEN_BYTES = {
    "none": (None, b'["none",null]'),
    "bool": (True, b'["bool",true]'),
    "int": (1, b'["int","1"]'),
    "float": (1.0, b'["float","1.0"]'),
    "decimal": (Decimal("1.00"), b'["dec","1"]'),
    "str": ("a", b'["str","a"]'),
    "bytes": (b"\x00\xff", b'["bytes","00ff"]'),
    "list": ([1, 2], b'["list",[["int","1"],["int","2"]]]'),
    "tuple": ((1, 2), b'["tup",[["int","1"],["int","2"]]]'),
    "set": ({3, 1, 2}, b'["set",[["int","1"],["int","2"],["int","3"]]]'),
    "map": (
        {"b": 1, "a": 2},
        b'["map",[[["str","a"],["int","2"]],[["str","b"],["int","1"]]]]',
    ),
    "uuid": (
        UUID("12345678-1234-5678-1234-567812345678"),
        b'["uuid","12345678123456781234567812345678"]',
    ),
    "path": (PurePosixPath("a/b"), b'["path","posix","a/b"]'),
    "date": (date(2020, 6, 15), b'["date","2020-06-15"]'),
    "datetime": (
        datetime(2020, 6, 15, 12, tzinfo=UTC),
        b'["dt","2020-06-15T12:00:00+00:00"]',
    ),
}

GOLDEN_DIGESTS = {
    "int": (1, IdentityDomain.FINGERPRINT, "ebb3c2ff18d2f89da7fdcf8e6f3a8afa"),
    "str": ("a", IdentityDomain.FINGERPRINT, "17755474b85323bc8d6356df37979b11"),
}


class Color(Enum):
    RED = 1
    GREEN = 2


class Flavor(StrEnum):
    SWEET = "sweet"


@dataclass(frozen=True)
class Point:
    x: int
    y: int


@define(frozen=True)
class Pin:
    x: int
    y: int


@pytest.mark.parametrize(
    ("value", "expected"), GOLDEN_BYTES.values(), ids=GOLDEN_BYTES.keys()
)
def test_golden_canonical_bytes(value, expected):
    assert canonical_bytes(value) == expected


@pytest.mark.parametrize(
    ("value", "domain", "expected"), GOLDEN_DIGESTS.values(), ids=GOLDEN_DIGESTS.keys()
)
def test_golden_digests(value, domain, expected):
    result = digest(value, domain)
    assert result == expected
    assert len(result) == 32


@pytest.mark.parametrize(
    ("left", "right"),
    [
        (True, 1),
        (1, 1.0),
        (1.0, Decimal(1)),
        ([1], (1,)),
        ({1}, frozenset({1})),
        (datetime(2020, 6, 15, 12, tzinfo=UTC), date(2020, 6, 15)),
    ],
)
def test_conflatable_types_stay_distinct(left, right):
    assert canonical_bytes(left) != canonical_bytes(right)


def test_mapping_is_order_independent():
    assert canonical_bytes({"a": 1, "b": 2}) == canonical_bytes({"b": 2, "a": 1})


def test_heterogeneous_mapping_keys_sort_deterministically():
    first = canonical_bytes({1: "x", "a": "y", (2, 3): "z"})
    second = canonical_bytes({(2, 3): "z", "a": "y", 1: "x"})
    assert first == second


def test_set_is_order_independent():
    assert canonical_bytes({1, 2, 3}) == canonical_bytes({3, 2, 1})


def test_distinct_nan_keys_sort_by_full_pair():
    first, second = float("nan"), float("nan")
    forward = {first: "x", second: "y"}
    reverse = {second: "y", first: "x"}
    assert len(forward) == len(reverse) == 2
    assert canonical_bytes(forward) == canonical_bytes(reverse)


def test_negative_zero_canonicalizes_with_positive_zero():
    assert canonical_bytes(-0.0) == canonical_bytes(0.0)


def test_float_infinities_and_nan_have_stable_tags():
    assert canonical_bytes(float("inf")) == b'["float","inf"]'
    assert canonical_bytes(float("-inf")) == b'["float","-inf"]'
    assert canonical_bytes(float("nan")) == b'["float","nan"]'


def test_decimal_equivalent_representations_normalize():
    assert canonical_bytes(Decimal("1.0")) == canonical_bytes(Decimal("1.000"))


def test_decimal_encoding_ignores_ambient_context_precision():
    value = Decimal("123456.789")

    with localcontext() as ctx:
        ctx.prec = 1
        low = canonical_bytes(value)

    with localcontext() as ctx:
        ctx.prec = 60
        high = canonical_bytes(value)

    assert low == high == canonical_bytes(value)


def test_naive_datetime_uses_utc_fallback():
    assert canonical_bytes(datetime(2020, 6, 15, 12)) == canonical_bytes(
        datetime(2020, 6, 15, 12, tzinfo=UTC)
    )


def test_aware_datetime_normalizes_to_utc():
    est = timezone(timedelta(hours=-5))
    assert canonical_bytes(datetime(2020, 6, 15, 7, tzinfo=est)) == canonical_bytes(
        datetime(2020, 6, 15, 12, tzinfo=UTC)
    )


def test_struct_time_is_distinct_from_datetime():
    tt = time.struct_time((2020, 6, 15, 12, 0, 0, 0, 0, -1))
    assert canonical_bytes(tt) != canonical_bytes(datetime(2020, 6, 15, 12, tzinfo=UTC))


def test_path_flavor_is_preserved():
    assert canonical_bytes(PureWindowsPath("a/b")) != canonical_bytes(
        PurePosixPath("a/b")
    )


def test_enum_includes_type_identity():
    assert canonical_bytes(Color.RED) != canonical_bytes(1)
    assert canonical_bytes(Flavor.SWEET) != canonical_bytes("sweet")


def test_dataclass_freezes_by_type_and_fields():
    assert canonical_bytes(Point(1, 2)) == canonical_bytes(Point(1, 2))
    assert canonical_bytes(Point(1, 2)) != canonical_bytes(Point(2, 1))


def test_attrs_freezes_by_type_and_fields():
    assert canonical_bytes(Pin(1, 2)) == canonical_bytes(Pin(1, 2))
    assert canonical_bytes(Pin(1, 2)) != canonical_bytes(Pin(2, 1))


def test_attrs_and_dataclass_stay_distinct():
    assert canonical_bytes(Pin(1, 2)) != canonical_bytes(Point(1, 2))


def test_recursive_tuple_keys_are_supported():
    assert canonical_bytes((1, (2, (3, 4)))) == canonical_bytes((1, (2, (3, 4))))


def test_domain_separates_digests():
    assert digest(1, IdentityDomain.FINGERPRINT) != digest(
        1, IdentityDomain.IDEMPOTENCY
    )


def test_encoding_is_repeatable():
    value = {"a": [1, 2], "b": (3, 4), "c": {5, 6}}
    assert canonical_bytes(value) == canonical_bytes(value)


def test_cyclic_structure_is_rejected():
    data: list[object] = [1]
    data.append(data)

    with pytest.raises(CyclicIdentityError):
        canonicalize(data)


def test_unsupported_value_raises():
    with pytest.raises(IdentityEncodingError):
        canonicalize(object())


def test_repr_cache_memoizes_supported_arguments():
    calls: list[object] = []

    @repr_cache
    def tally(value):
        calls.append(value)
        return len(calls)

    assert (tally({"a": 1}), tally({"a": 1})) == (1, 1)
    assert len(calls) == 1


def test_repr_cache_bypasses_unsupported_arguments():
    calls: list[object] = []

    @repr_cache
    def tally(value):
        calls.append(value)
        return len(calls)

    tally(object())
    tally(object())
    assert len(calls) == 2
