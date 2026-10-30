# vim: sw=4:ts=4:expandtab
"""Provides internal tests for canonical encoding, casts, dates, parsing, and graphs."""

from __future__ import annotations

import copy
import pickle  # noqa: S403
import time
import typing
from dataclasses import dataclass, make_dataclass
from dataclasses import field as dataclass_field
from datetime import UTC, date, datetime, timedelta, timezone, tzinfo
from decimal import Decimal, localcontext
from enum import Enum, StrEnum
from graphlib import CycleError
from io import BytesIO, StringIO
from logging import ERROR, WARNING
from math import inf
from operator import methodcaller
from pathlib import PurePosixPath, PureWindowsPath
from time import struct_time
from types import MappingProxyType
from typing import (
    TYPE_CHECKING,
    ClassVar,
    Literal,
    NotRequired,
    Required,
    TypedDict,
    cast,
)
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from attrs import define
from dateutil.relativedelta import relativedelta
from feedparser import FeedParserDict

from riko.base import _exceptions as errors
from riko.base._config import load_settings
from riko.base._config import settings as config
from riko.base._dateutils import TZINFOS
from riko.base._exceptions import (
    CyclicIdentityError,
    IdentityEncodingError,
    InvalidPipelineError,
)
from riko.base._graph import cyclic_nodes, descendants, freeze_graph, topological_sort
from riko.base._guards import require_mapping, require_sequence
from riko.base._logging import get_logger, set_log_level
from riko.base._paths import get_path
from riko.base._recordutils import field_names
from riko.base._require_guards import (
    normalize_strs,
    require_finite,
    require_from_form,
    require_from_typed_dict,
    require_str,
    require_strlike,
    typed_dict_keys,
)
from riko.base._typing import resolve_enum
from riko.coercion import _canonical
from riko.coercion import cast as cast_module
from riko.coercion._canonical import (
    IdentityDomain,
    canonical_bytes,
    canonicalize,
    digest,
    repr_cache,
)
from riko.coercion._dataclass import fromdict
from riko.coercion._dates import (
    _parse_date_cached,
    date_to_tt,
    parse_date_string,
    resolve_aware_datetime,
    tt_to_datedict,
)
from riko.coercion.cast import cast_datetime, resolve_cast_type
from riko.definitions._nodes import ModuleNode, StreamEdge, WriteNode, require_binding
from riko.definitions._write import WriteMode
from riko.io._sync import Fetch
from riko.modules._sortutils import def_itemgetter
from riko.parsing._dotdict import DotDict, match_key, raw_get
from riko.parsing.config import get_skip, resolve_conf
from riko.parsing.documents import XML_PARSER, any2dict
from riko.rss.feeds import augment_entries, resolve_date
from riko.types import _workflow as workflow_types
from riko.types._enums import CastType, Executor
from riko.types._pipedef import Embed, PipeModule
from riko.types._rss import ParserRSSEntry
from riko.types._workflow import Edge as EdgeBase
from riko.types._workflow import Endpoint, GraphEdge, GraphIndex
from tests import run_python
from tests._execution import build_workflow

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from riko.types._frozendict import FrozenSetMapping
    from riko.types._scalars import BasicValue


_SEEDED_ORDER = """
from riko.base._graph import scc_sort, topological_sort
print(topological_sort({"a": {"b"}, "b": {"a"}, "c": set()}))
print(topological_sort({"a": {"b", "c", "d"}, "e": {"f", "g"}}))
print(scc_sort({"A": {"B", "C"}, "B": {"D"}, "C": {"D"}, "D": {"E"}}))
"""

_INVALID: list[tuple[Callable[..., object], object]] = [
    (require_str, 1),
    (require_strlike, 1),
    (require_finite, float("nan")),
    (require_mapping, "abc"),
    (require_sequence, "abc"),
]

NOON_UTC = datetime(2020, 6, 15, 12, tzinfo=UTC)
NOON_TT = time.struct_time((2020, 6, 15, 12, 0, 0, 0, 0, -1))
NOON_EST = datetime(2020, 6, 15, 7, tzinfo=timezone(timedelta(hours=-5)))

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
    "datetime": (NOON_UTC, b'["dt","2020-06-15T12:00:00+00:00"]'),
    "inf": (float("inf"), b'["float","inf"]'),
    "neg-inf": (float("-inf"), b'["float","-inf"]'),
    "nan": (float("nan"), b'["float","nan"]'),
}

REPEATABLE_VALUE = {"a": [1, 2], "b": (3, 4), "c": {5, 6}}

GOLDEN_DIGESTS = {
    "int": (1, IdentityDomain.FINGERPRINT, "ebb3c2ff18d2f89da7fdcf8e6f3a8afa"),
    "str": ("a", IdentityDomain.FINGERPRINT, "17755474b85323bc8d6356df37979b11"),
}

DIGEST_SCRIPT = """
from riko.coercion._canonical import IdentityDomain, digest

value = {
    "text": ["a", "b", "c"],
    "raw": (b"x", b"yz"),
    "tags": {"red", "green", "blue", "cyan"},
    "frozen": frozenset({"k1", "k2", "k3"}),
    "nested": {"inner": {"s": {"p", "q"}, "b": b"\\x00"}},
}
print(digest(value, IdentityDomain.FINGERPRINT))
"""

DOTTED_PATHS = ["a.b", "a.b.c", "author.name", "AUTHOR.NAME"]


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


DISTINCT_PAIRS = [
    pytest.param(1, 1.0, id="int-vs-float"),
    pytest.param(1.0, Decimal(1), id="float-vs-decimal"),
    pytest.param([1], (1,), id="list-vs-tuple"),
    pytest.param({1}, frozenset({1}), id="set-vs-frozenset"),
    pytest.param(NOON_UTC, date(2020, 6, 15), id="datetime-vs-date"),
    pytest.param(NOON_TT, NOON_UTC, id="struct-time-vs-datetime"),
    pytest.param(
        PureWindowsPath("a/b"), PurePosixPath("a/b"), id="windows-vs-posix-path"
    ),
    pytest.param(Color.RED, 1, id="enum-vs-int"),
    pytest.param(Flavor.SWEET, "sweet", id="strenum-vs-str"),
    pytest.param(Pin(1, 2), Point(1, 2), id="attrs-vs-dataclass"),
]

EQUIVALENT_PAIRS = [
    pytest.param(
        {1: "x", "a": "y", (2, 3): "z"},
        {(2, 3): "z", "a": "y", 1: "x"},
        id="mixed-key-order",
    ),
    pytest.param({1, 2, 3}, {3, 2, 1}, id="set-order"),
    pytest.param(-0.0, 0.0, id="negative-zero"),
    pytest.param(Decimal("1.0"), Decimal("1.000"), id="decimal-exponent"),
    pytest.param(datetime(2020, 6, 15, 12), NOON_UTC, id="naive-datetime-utc"),
    pytest.param(NOON_EST, NOON_UTC, id="aware-datetime-utc"),
    pytest.param(
        {(1, (2, 3)): "x", (1, 2, 3): "y"},
        {(1, 2, 3): "y", (1, (2, 3)): "x"},
        id="nested-tuple-keys",
    ),
    pytest.param(REPEATABLE_VALUE, REPEATABLE_VALUE, id="repeatable"),
]


class TestCanonicalBytes:
    @pytest.mark.parametrize(
        ("value", "expected"), GOLDEN_BYTES.values(), ids=GOLDEN_BYTES.keys()
    )
    def test_golden_canonical_bytes(self, value, expected):
        assert canonical_bytes(value) == expected

    @pytest.mark.parametrize(("left", "right"), DISTINCT_PAIRS)
    def test_conflatable_types_stay_distinct(self, left, right):
        assert canonical_bytes(left) != canonical_bytes(right)

    @pytest.mark.parametrize(("left", "right"), EQUIVALENT_PAIRS)
    def test_equivalent_values_encode_identically(self, left, right):
        assert canonical_bytes(left) == canonical_bytes(right)

    def test_distinct_nan_keys_sort_by_full_pair(self):
        first, second = float("nan"), float("nan")
        forward = {first: "x", second: "y"}
        reverse = {second: "y", first: "x"}
        assert len(forward) == len(reverse) == 2
        assert canonical_bytes(forward) == canonical_bytes(reverse)

    def test_decimal_encoding_ignores_ambient_context_precision(self):
        value = Decimal("123456.789")

        with localcontext() as ctx:
            ctx.prec = 1
            low = canonical_bytes(value)

        with localcontext() as ctx:
            ctx.prec = 60
            high = canonical_bytes(value)

        assert low == high == canonical_bytes(value)

    @pytest.mark.parametrize(
        "record", [pytest.param(Point, id="dataclass"), pytest.param(Pin, id="attrs")]
    )
    def test_record_encodes_by_type_and_fields(self, record):
        assert canonical_bytes(record(1, 2)) == canonical_bytes(record(1, 2))
        assert canonical_bytes(record(1, 2)) != canonical_bytes(record(2, 1))

    def test_cyclic_structure_is_rejected(self):
        data: list[object] = [1]
        data.append(data)

        with pytest.raises(CyclicIdentityError):
            canonicalize(data)

    def test_unsupported_value_raises(self):
        with pytest.raises(IdentityEncodingError):
            canonicalize(object())

    def test_lone_surrogate_string_raises_encoding_error(self):
        with pytest.raises(IdentityEncodingError):
            canonical_bytes("\ud800")


class TestDigest:
    @pytest.mark.parametrize(
        ("value", "domain", "expected"),
        GOLDEN_DIGESTS.values(),
        ids=GOLDEN_DIGESTS.keys(),
    )
    def test_golden_digests(self, value, domain, expected):
        result = digest(value, domain)
        assert result == expected
        assert len(result) == 32

    def test_digest_is_stable_across_processes_with_different_hash_seeds(self):
        runs = [run_python("-c", DIGEST_SCRIPT, hash_seed=s) for s in ("0", "4242")]
        digests = {run.stdout.strip() for run in runs}
        assert len(digests) == 1


class _Opaque:
    pass


def _counting_cache() -> tuple[list[object], repr_cache[int]]:
    calls: list[object] = []

    @repr_cache
    def tally(value: object) -> int:
        calls.append(value)
        return len(calls)

    return calls, tally


NATIVE_KEY_PAIRS = [
    pytest.param(1, True, id="int-bool"),
    pytest.param(1, 1.0, id="int-float"),
    pytest.param("x", b"x", id="str-bytes"),
    pytest.param(Flavor.SWEET, "sweet", id="strenum-str"),
    pytest.param(0, None, id="int-none"),
]


class TestReprCache:
    def test_repr_cache_memoizes_supported_arguments(self):
        calls, tally = _counting_cache()
        assert (tally({"a": 1}), tally({"a": 1})) == (1, 1)
        assert len(calls) == 1

    def test_scalar_arguments_skip_canonical_encoding(self, monkeypatch):
        encoded: list[object] = []
        spy = lambda value: encoded.append(value) or canonical_bytes(value)
        monkeypatch.setattr(_canonical, "canonical_bytes", spy)
        calls, tally = _counting_cache()
        assert (tally(42), tally(42), tally("42")) == (1, 1, 2)
        assert encoded == []
        assert (tally({"a": 1}), tally({"a": 1})) == (3, 3)
        assert len(encoded) == 2
        assert len(calls) == 3

    def test_fresh_nans_share_one_entry(self):
        _, tally = _counting_cache()
        assert (tally(float("nan")), tally(float("nan"))) == (1, 1)
        assert tally.cache_info().currsize == 1

    @pytest.mark.parametrize(("left", "right"), NATIVE_KEY_PAIRS)
    def test_native_keys_keep_distinct_types_apart(self, left, right):
        _, tally = _counting_cache()
        assert (tally(left), tally(right)) == (1, 2)
        assert (tally(left), tally(right)) == (1, 2)

    def test_repr_cache_memoizes_lone_surrogate_strings(self):
        _, tally = _counting_cache()
        assert (tally("\ud800"), tally("\ud800")) == (1, 1)

    def test_nested_unsupported_bypasses_cache_and_reaches_fn(self):
        """
        Bypass caching when a container holds an unsupported object.

        Distinct instances must neither collide nor be replaced by the sentinel.
        """
        calls, record = _counting_cache()
        first, second = _Opaque(), _Opaque()
        record({"x": first})
        record({"x": second})

        assert len(calls) == 2
        assert cast("dict", calls[0])["x"] is first
        assert cast("dict", calls[1])["x"] is second


class TestResolveConf:
    def test_each_call_parses_afresh(self):
        conf = {"field": {"type": "text", "value": "x"}}
        first, second = resolve_conf(None, conf=conf), resolve_conf(None, conf=conf)
        assert first == second
        assert first is not second


@pytest.fixture
def tokyo(monkeypatch):
    if not hasattr(time, "tzset"):
        pytest.skip("tzset is POSIX-only")

    monkeypatch.setenv("TZ", "Asia/Tokyo")
    time.tzset()
    yield
    time.tzset()


class TestCastDatetime:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("Jan. 12, 2001", (2001, 1, 12)),
            ("10/21/1958", (1958, 10, 21)),
            ("15 JUN 06", (2006, 6, 15)),
        ],
    )
    def test_absolute_date_strings(self, value, expected):
        result = cast_datetime(value)
        assert result is not None
        assert (result.year, result.month, result.day) == expected

    def test_plain_date_string_never_consults_the_clock(self, monkeypatch):
        zones: list[bool] = []
        load_local_tz = cast_module.load_local_tz
        spy = lambda **kwargs: zones.append(True) or load_local_tz(**kwargs)
        monkeypatch.setattr(cast_module, "load_local_tz", spy)
        assert cast_datetime("Jan. 12, 2001") is not None
        assert zones == []
        assert cast_datetime("today") is not None
        assert zones == [True]

    def test_relative_date_strings_offset_from_today(self):
        today = cast_datetime("today")
        assert today is not None
        assert cast_datetime("+3 days") == today + timedelta(days=3)
        assert cast_datetime("-10 weeks") == today - timedelta(weeks=10)
        assert cast_datetime("last year") == today - relativedelta(years=1)

    def test_epoch_seconds(self):
        result = cast_datetime(1181230100)
        assert result is not None
        assert int(result.timestamp()) == 1181230100

    @pytest.mark.usefixtures("tokyo")
    def test_defaults_to_utc(self):
        if dt := cast_datetime("now"):
            offset = dt.utcoffset()
        else:
            offset = None

        assert offset == timedelta(0)

    @pytest.mark.usefixtures("tokyo")
    def test_honors_local_tz(self):
        if dt := cast_datetime("now", try_local_tz=True):
            offset = dt.utcoffset()
        else:
            offset = None

        assert offset == timedelta(hours=9)

    def test_rejects_positional_flags(self):
        with pytest.raises(TypeError):
            cast_datetime("now", False, False, True)  # pyright: ignore[reportCallIssue]

    @pytest.mark.xfail(
        strict=True,
        reason="owned by the settable date timezone work: with try_local_tz, named "
        "days ('now') use the local zone but counted offsets ('+1 seconds') stay UTC",
    )
    @pytest.mark.usefixtures("tokyo")
    def test_relative_offsets_share_the_named_day_zone(self):
        named = cast_datetime("now", try_local_tz=True)
        offset = cast_datetime("+1 seconds", try_local_tz=True)
        assert named is not None
        assert offset is not None
        assert offset.utcoffset() == named.utcoffset()


class TestResolveCastType:
    def test_unknown_name_warns_once_and_passes(self, caplog):
        with caplog.at_level(WARNING, logger="riko"):
            resolved = resolve_cast_type("unknown")

        assert resolved == CastType.PASS
        assert [r.levelno for r in caplog.records] == [WARNING]


SORT_KEY_WARNINGS = [
    pytest.param("pass", 0, id="pass"),
    pytest.param("", 0, id="empty"),
    pytest.param("bogus", 1, id="unknown"),
]


INVALID_CAST_KEYS = [
    pytest.param("abc", "abc", id="str"),
    pytest.param(7, 7, id="int"),
    pytest.param(time.gmtime(0), time.gmtime(0), id="struct_time"),
    pytest.param({"a": 1}, "x", id="mapping"),
    pytest.param([1], "x", id="sequence"),
]


class TestDefItemgetter:
    @pytest.mark.parametrize(("type_", "warnings"), SORT_KEY_WARNINGS)
    def test_uncast_types_warn_at_most_once(self, type_, warnings, caplog):
        with caplog.at_level(WARNING, logger="riko"):
            keyfunc = def_itemgetter("n", type_=type_)
            keys = [keyfunc({"n": n}) for n in (3, 1, 2)]

        assert keys == [3, 1, 2]
        assert len(caplog.records) == warnings

    @pytest.mark.parametrize(("value", "expected"), INVALID_CAST_KEYS)
    def test_invalid_cast_type_keeps_scalars_and_defaults_containers(
        self, value, expected
    ):
        keyfunc = def_itemgetter("n", default="x", type_="location")
        assert keyfunc({"n": value}) == expected


@dataclass
class _Inner:
    n: int = 0


@dataclass
class _Other:
    m: int = 0


@dataclass
class _Either:
    val: _Inner | _Other | None = None


@dataclass
class _Sorted:
    dir: Literal["asc", "desc"] = "asc"


class TestFromdict:
    def test_an_ambiguous_union_field_stays_a_mapping(self):
        assert vars(fromdict(_Either, val={"m": 9}))["val"] == {"m": 9}

    def test_a_literal_field_rejects_a_value_outside_its_choices(self):
        with pytest.raises(ValueError, match="Invalid dir: 'up'"):
            fromdict(_Sorted, dir="up")


class TestParseDateString:
    def test_parsed_date_cache_is_bounded(self):
        _parse_date_cached.cache_clear()

        for second in range(config.parsed_date_cache_size + 1):
            parse_date_string(f"2015-02-01T00:00:00.{second:06d}+00:00")

        assert _parse_date_cached.cache_info().currsize == config.parsed_date_cache_size

    def test_ambiguous_cst_resolves_to_us_central(self):
        """
        Resolve ``CST`` to US Central time.

        The abbreviation is also used by China and Cuba, but the map is
        intentionally US-centric at UTC-6 rather than whichever zone sorts last.
        """
        parsed = parse_date_string("1 Feb 2015 12:00:00 CST")
        assert parsed.utcoffset() == timedelta(hours=-6)

    def test_tzinfos_capture_both_standard_and_daylight_names(self):
        """
        Preserve both standard and daylight timezone abbreviations.

        The map is built at import time, so sampling only ``now()`` can miss the
        out-of-season name. Both names must stably map to US Eastern regardless
        of import date.
        """
        assert str(TZINFOS["EST"]) == "America/New_York"
        assert str(TZINFOS["EDT"]) == "America/New_York"

    def test_non_us_abbreviation_resolves(self):
        """Abbreviations outside ``_PREFERRED_ZONES`` (e.g. ``JST``) must be present."""
        assert TZINFOS["JST"] == ZoneInfo("Asia/Tokyo")

        parsed = parse_date_string("1 Feb 2015 12:00:00 JST")
        assert parsed.utcoffset() == timedelta(hours=9)


class NamelessZone(tzinfo):
    def tzname(self, dt: datetime | None) -> None:
        return None

    def utcoffset(self, dt: datetime | None) -> timedelta:
        return timedelta(0)

    def dst(self, dt: datetime | None) -> timedelta:
        return timedelta(0)


class TestResolveAwareDatetime:
    def test_keeps_a_nameless_zone(self):
        zone = NamelessZone()
        result = resolve_aware_datetime(
            datetime(2020, 1, 1, tzinfo=zone), try_local_tz=False
        )
        assert isinstance(result, datetime)
        assert result.tzinfo is zone


class TestTtToDatedict:
    def test_utime_honors_aware_offset(self):
        """
        Convert aware ``+03:00`` times to the represented instant.

        Do not reinterpret the same wall-clock time as UTC.
        """
        tz = timezone(timedelta(hours=3))
        aware = datetime(2020, 6, 15, 9, 0, 0, tzinfo=tz)
        tt = date_to_tt(aware)

        result = tt_to_datedict(tt, aware.date())
        assert result["utime"] == int(aware.timestamp())


DOTDICT_DELETES = [
    pytest.param(
        {"author": "bar", "title": "foo"}, "author", {"title": "foo"}, id="root"
    ),
    pytest.param(
        {"author": {"name": "bar", "url": "x.com"}},
        "author.name",
        {"author": {"url": "x.com"}},
        id="nested",
    ),
    pytest.param(
        {"a": {"b": {"c": 1, "d": 2}}}, "a.b.c", {"a": {"b": {"d": 2}}}, id="deep"
    ),
    pytest.param(
        {"author": "bar", "title": "foo"},
        "AUTHOR",
        {"title": "foo"},
        id="root-case-insensitive",
    ),
    pytest.param(
        {"author": {"name": "bar", "url": "x.com"}},
        "Author.Name",
        {"author": {"url": "x.com"}},
        id="nested-case-insensitive",
    ),
    pytest.param(
        {"a": {"b": {"c": 1, "d": 2}}},
        "A.B.C",
        {"a": {"b": {"d": 2}}},
        id="deep-case-insensitive",
    ),
    pytest.param(
        {"author": "bar"}, "missing", {"author": "bar"}, id="missing-root-noop"
    ),
    pytest.param(
        {"author": {"name": "bar"}},
        "author.missing",
        {"author": {"name": "bar"}},
        id="missing-nested-key-noop",
    ),
    pytest.param(
        {"author": {"name": "bar"}},
        "missing.name",
        {"author": {"name": "bar"}},
        id="missing-intermediate-noop",
    ),
]


DOTDICT_CONTAINS = [
    pytest.param("title", True, id="plain"),
    pytest.param("TITLE", True, id="case-insensitive"),
    pytest.param("author.name", True, id="dotted-present"),
    pytest.param("author.url", False, id="dotted-absent"),
    pytest.param("missing", False, id="missing"),
    pytest.param({"subkey": "title"}, True, id="subkey-mapping"),
    pytest.param("AUTHOR.NAME", True, id="dotted-case-insensitive"),
    pytest.param(None, False, id="none"),
    pytest.param(("title",), False, id="tuple"),
    pytest.param({}, False, id="empty-mapping"),
    pytest.param({"subkey": 5}, False, id="non-str-subkey"),
    pytest.param({"subkey": ""}, False, id="empty-subkey"),
]

MATCH_KEYS = [
    pytest.param(DotDict, "TITLE", "Title", id="dotdict"),
    pytest.param(dict, "Title", "Title", id="exact"),
    pytest.param(dict, "author", None, id="missing"),
]


NESTED_WRITES = [
    pytest.param(methodcaller("__setitem__", "a.b.c", 2), id="set"),
    pytest.param(methodcaller("update", {"a.b.d": 3}), id="update"),
    pytest.param(methodcaller("delete", "A.B.C"), id="delete"),
]


class TestDotDict:
    @pytest.mark.parametrize(("key", "expected"), DOTDICT_CONTAINS)
    def test_contains(self, key, expected):
        d = DotDict({"Title": "foo", "author": {"name": "bar"}})
        assert (key in d) is expected

    @pytest.mark.parametrize(("make", "key", "expected"), MATCH_KEYS)
    def test_match_key_returns_the_stored_spelling(self, make, key, expected):
        assert match_key(make({"Title": 1}), key) == expected

    @pytest.mark.parametrize("key", DOTTED_PATHS)
    def test_dotted_getitem_matches_get(self, key):
        d = DotDict({"a": {"b": {"c": 1}}, "Author": {"Name": "x"}})
        assert d[key] == d.get(key)

    @pytest.mark.parametrize(("source", "key", "expected"), DOTDICT_DELETES)
    def test_delete(self, source, key, expected):
        d = DotDict(source)
        d.delete(key)
        assert d.asdict() == expected

    @pytest.mark.parametrize("nest", [dict, DotDict], ids=["dict", "dotdict"])
    @pytest.mark.parametrize("write", NESTED_WRITES)
    def test_nested_write_leaves_the_source_untouched(self, write, nest):
        typed = {"type": "text", "value": "hi"}
        source = {"a": nest({"b": {"c": 1}}), "v": typed}
        d = DotDict(source)
        write(d)
        assert source == {"a": {"b": {"c": 1}}, "v": {"type": "text", "value": "hi"}}
        assert raw_get(d, "v") is typed

    @pytest.mark.xfail(
        strict=True,
        reason="business data shaped like a typed value is still read as one",
    )
    def test_typed_value_shaped_business_data_reads_literally(self):
        detail = {"type": "text/html", "value": "<b>hi</b>"}
        assert DotDict({"summary_detail": detail}).asdict() == {
            "summary_detail": detail
        }


ANY2DICT_LISTS = [
    pytest.param([{"a": 1}, None, {"b": 0}], None, None, id="list-skips-null"),
    pytest.param('[{"a": 1}, null, {"b": 0}]', "json", None, id="json-array"),
    pytest.param('{"x": [{"a": 1}, {"b": 0}]}', "json", "x", id="json-path"),
]


class TestGetSkip:
    def test_get_skip_field_only_follows_presence_not_absent_text(self):
        """A truthy value is not skipped even when it reads like "no value"."""
        assert get_skip({"content": "none available"}, {"field": "content"}) is False


class TestAny2dict:
    def test_any2dict_strips_xhtml_namespace_from_keys(self):
        url = get_path("capnorth.xml")

        with Fetch(url, binary=True) as f:
            result = next(any2dict(f))
            assert sorted(result) == [
                "code",
                "identifier",
                "info",
                "msgType",
                "scope",
                "sender",
                "sent",
                "status",
            ]

            assert sorted(cast("dict", result.get("info"))) == [
                "area",
                "category",
                "certainty",
                "description",
                "expires",
                "headline",
                "parameter",
                "severity",
                "urgency",
            ]

    @pytest.mark.parametrize(("content", "ext", "path"), ANY2DICT_LISTS)
    def test_any2dict_yields_list_entries(self, content, ext, path):
        result = list(any2dict(content, ext=ext, path=path))
        assert result == [{"a": 1}, {"b": 0}]

    def test_any2dict_wraps_leaf_xml_root(self):
        assert list(any2dict(StringIO("<a>hi</a>"), ext="xml")) == [{"content": "hi"}]

    def test_any2dict_yields_a_dotdict_as_a_plain_dict(self):
        result = list(any2dict(DotDict({"a": {"b": 1}})))
        assert result == [{"a": {"b": 1}}]
        assert type(result[0]) is dict


class TestXmlParser:
    def test_xml_parser_does_not_resolve_entities(self):
        """
        Prevent ``XML_PARSER`` from expanding defined entities.

        With ``resolve_entities=False``, the XXE guard leaves ``&xxe;``
        unresolved instead of substituting its declared value.
        """
        etree = pytest.importorskip("lxml.etree")
        payload = b'<!DOCTYPE root [<!ENTITY xxe "SECRET">]><root>&xxe;</root>'
        tree = etree.parse(BytesIO(payload), XML_PARSER)
        assert tree.getroot().text != "SECRET"


AUGMENT_FALLBACKS = [
    pytest.param(
        {
            "content": [{"value": "from content"}],
            "link": "https://example.com/feed-item",
            "title": "fallback title",
        },
        "from content",
        id="from-content",
    ),
    pytest.param(
        {"link": "https://example.com/feed-item", "title": "fallback title"},
        "fallback title",
        id="from-title",
    ),
    pytest.param({"link": "https://example.com/feed-item"}, "", id="empty"),
]


class TestAugmentEntries:
    @pytest.mark.parametrize(("entry", "expected"), AUGMENT_FALLBACKS)
    def test_augment_entries_fallbacks(self, entry, expected):
        """Feed-entry augmentation fallbacks from ``riko.rss.feeds``."""
        item = next(augment_entries([ParserRSSEntry(entry)]))
        assert item.get("summary") == expected
        assert item.get("description") == expected

    def test_augment_entries_parses_date_the_parser_could_not(self):
        """A present-but-``None`` parsed date falls back to the raw date string."""
        raw = cast(
            "ParserRSSEntry",
            {
                "link": "https://example.com/feed-item",
                "published": "May 11, 2012 10:01:00 EST",
                "published_parsed": None,
                "updated": "May 12, 2012 08:30:00 EST",
                "updated_parsed": None,
            },
        )
        item: dict[str, object] = dict(next(augment_entries([raw])))

        for key in ("pubDate", "published_parsed", "y:published"):
            value = item.get(key)
            assert isinstance(value, struct_time), key
            assert value[:5] == (2012, 5, 11, 10, 1)

        updated = item.get("updated_parsed")
        assert isinstance(updated, struct_time)
        assert updated[:5] == (2012, 5, 12, 8, 30)

    @pytest.mark.filterwarnings("error::DeprecationWarning")
    def test_resolve_date_does_not_trigger_feedparser_updated_fallback(self):
        """Asking a feedparser entry for a missing ``updated`` key stays silent."""
        raw = FeedParserDict({"published": "2020-01-02", "published_parsed": None})
        entry = cast("ParserRSSEntry", raw)
        keys = ("updated_parsed", "updated", "published_parsed", "published")
        resolved = resolve_date(entry, *keys)
        assert isinstance(resolved, struct_time)
        assert resolved[:3] == (2020, 1, 2)
        item = dict(next(augment_entries([entry])))
        assert item["updated_parsed"] == resolved


class TestResolveDate:
    def test_resolve_date_skips_blank_and_unparseable_values(self):
        """A blank or unparseable candidate never raises; the next key is tried."""
        raw = cast(
            "ParserRSSEntry",
            {
                "published_parsed": None,
                "published": "not a date",
                "updated_parsed": None,
                "updated": "",
                "created": "2021-03-04",
            },
        )
        keys = ("published_parsed", "published", "updated_parsed", "updated")
        assert resolve_date(raw, *keys) is None
        resolved = resolve_date(raw, *keys, "created")
        assert isinstance(resolved, struct_time)
        assert resolved[:3] == (2021, 3, 4)


def _get_seeded_order(seed: str) -> list[str]:
    return run_python("-c", _SEEDED_ORDER, hash_seed=seed).stdout.splitlines()


DESCENDANT_CASES = [
    pytest.param("a", {"a": {"b"}, "b": {"c"}}, frozenset({"b", "c"}), id="transitive"),
    pytest.param("b", {"a": {"b"}}, frozenset(), id="referenced-only-node"),
    pytest.param("a", {"a": {"b"}, "b": {"a"}}, frozenset({"b"}), id="cycle"),
]


class TestGraph:
    @pytest.mark.parametrize(("node", "graph", "expected"), DESCENDANT_CASES)
    def test_descendants(self, node, graph, expected):
        assert descendants(node, graph) == expected

    def test_cyclic_nodes_accepts_a_frozen_graph(self):
        graph = freeze_graph({"a": {"b"}, "b": {"a"}, "c": set()})
        assert isinstance(graph, MappingProxyType)
        assert sorted(cyclic_nodes(graph)) == ["a", "b"]

    def test_topological_sort_key_orders_ready_nodes(self):
        graph = {"a": {"c"}, "b": {"c"}, "c": set()}
        ordered = topological_sort(graph, key=lambda node: node != "b")
        assert ordered == [("b",), ("a",), ("c",)]

    def test_topological_sort_groups_a_cycle_by_default(self):
        assert topological_sort({"a": {"b"}, "b": {"a"}}) == [("a", "b")]

    def test_graph_order_ignores_hash_seed(self):
        expected = [
            "[('c',), ('a', 'b')]",
            "[('e',), ('a',), ('g',), ('f',), ('d',), ('c',), ('b',)]",
            "[('A',), ('C',), ('B',), ('D',), ('E',)]",
        ]
        assert _get_seeded_order("1") == expected
        assert _get_seeded_order("2") == expected

    def test_descendants_rejects_unknown_node(self):
        with pytest.raises(KeyError):
            descendants("c", {"a": {"b"}})

    def test_topological_sort_strict_raises_on_a_cycle(self):
        with pytest.raises(CycleError):
            topological_sort({"a": {"b"}, "b": {"a"}}, strict=True)


class TestGraphIndex:
    def test_graph_index_derives_and_freezes_from_its_inputs(self) -> None:
        edge = GraphEdge("a", "b", "out", "in")
        index = GraphIndex(["a", "b", "c"], [edge], {"default": Endpoint("b", "out")})

        assert index.edges == (edge,)
        assert index.incoming["b"] == (edge,)
        assert index.upstream["b"] == frozenset({"a"})
        assert index.required["default"] == ("a", "b")
        assert index.roots == ("a", "c")

        with pytest.raises(TypeError):
            index.outputs["extra"] = Endpoint("a", "out")  # type: ignore[index]

    def test_graph_index_derives_on_first_use(self, monkeypatch) -> None:
        calls: list[str] = []

        def counting(source: str, graph: FrozenSetMapping) -> frozenset[str]:
            calls.append(source)
            return descendants(source, graph)

        monkeypatch.setattr(workflow_types, "descendants", counting)
        edge = GraphEdge("a", "b", "out", "in")
        outputs = {"default": Endpoint("b", "out")}
        index = GraphIndex(["a", "b"], [edge], outputs)

        assert index.cyclic == ()
        assert index.order == ("a", "b")
        assert calls == []
        assert index.required["default"] == ("a", "b")
        assert len(calls) == 1
        assert index == GraphIndex(["a", "b"], [edge], outputs)

    def test_only_a_default_port_edge_closes_a_node_to_a_seed(self) -> None:
        edges = (
            StreamEdge(Endpoint("a", "out"), Endpoint("named", "in:count")),
            StreamEdge(Endpoint("b", "out"), Endpoint("positional", "in:1")),
            StreamEdge(Endpoint("c", "out"), Endpoint("default", "in")),
        )
        ids = ["a", "b", "c", "named", "positional", "default"]
        nodes = [ModuleNode(id=node_id, name="hash") for node_id in ids]
        index = build_workflow(nodes, edges=edges).index

        assert [node_id for node_id in ids if index.is_open(node_id)] == ids[:-1]


ENV_OVERRIDES = [
    pytest.param("RIKO_NODE_THREADS", "-1", "node_threads", 40, id="int-below-min"),
    pytest.param("RIKO_CONCURRENCY_LIMIT", "0", "concurrency_limit", 16, id="limit-0"),
    pytest.param("RIKO_DISCOVERY_TIMEOUT", "0", "discovery_timeout", 10, id="disc-0"),
    pytest.param(
        "RIKO_STREAMING_THRESHOLD", "-5", "streaming_threshold", 1024**2, id="neg-int"
    ),
    pytest.param("RIKO_FETCH_TIMEOUT", "2.5", "fetch_timeout", 2.5, id="fetch"),
    pytest.param("RIKO_FETCH_TIMEOUT", "-1", "fetch_timeout", 30.0, id="fetch-neg"),
    pytest.param(
        "RIKO_PARSED_DATE_CACHE_SIZE", "0", "parsed_date_cache_size", 0, id="int-zero"
    ),
    pytest.param("RIKO_SHUTDOWN_TIMEOUT", "inf", "shutdown_timeout", inf, id="inf"),
    pytest.param("RIKO_SHUTDOWN_TIMEOUT", "-1", "shutdown_timeout", 30.0, id="neg"),
    pytest.param("RIKO_SHUTDOWN_TIMEOUT", "nan", "shutdown_timeout", 30.0, id="nan"),
    pytest.param(
        "RIKO_SHUTDOWN_TIMEOUT", "soon", "shutdown_timeout", 30.0, id="malformed"
    ),
]


class TestLoadSettings:
    @pytest.mark.parametrize(("key", "raw", "name", "expected"), ENV_OVERRIDES)
    def test_env_override_or_default(self, key, raw, name, expected) -> None:
        assert getattr(load_settings({key: raw}), name) == expected


class TestRequireGuards:
    @pytest.mark.parametrize(("require", "value"), _INVALID)
    def test_document_error_is_the_default(self, require, value):
        with pytest.raises(InvalidPipelineError, match="field"):
            require(value, "field")

    @pytest.mark.parametrize(("require", "value"), [*_INVALID, (require_binding, 1)])
    def test_caller_can_pick_the_error(self, require, value):
        with pytest.raises(ValueError, match="field"):
            require(value, "field", error=ValueError)


class TestRequireFromForm:
    def test_a_union_passes_any_class_member(self):
        assert require_from_form(int | str)("a") == "a"

    def test_a_literal_passes_one_of_its_values(self):
        assert require_from_form(Literal["a", "b"])("b") == "b"

    def test_a_mixed_union_passes_a_literal_value(self):
        assert require_from_form(int | Literal["auto"])("auto") == "auto"

    def test_a_lone_class_is_checked_by_instance(self):
        with pytest.raises(InvalidPipelineError, match="must be of type int, not str"):
            require_from_form(int)("1")

    def test_a_literal_value_must_match_by_type(self):
        with pytest.raises(InvalidPipelineError, match="Expected one of 1"):
            require_from_form(Literal[1])(True)

    def test_a_mixed_union_lists_its_literal_values(self):
        with pytest.raises(InvalidPipelineError, match="'auto', not str"):
            require_from_form(int | Literal["auto"], "limit")("all")

    def test_an_unsupported_form_raises_when_built(self):
        with pytest.raises(TypeError, match="not a class, TypedDict, or Literal"):
            require_from_form(list[str])

    def test_every_unsupported_form_is_named(self):
        with pytest.raises(TypeError, match="are not classes, TypedDicts, or Literals"):
            require_from_form(list[str] | dict[str, int])


class TestResolveEnum:
    @pytest.mark.parametrize("value", [None, "bogus"])
    def test_resolve_enum_defaults_to_the_document_error(self, value):
        with pytest.raises(InvalidPipelineError, match="WriteMode"):
            resolve_enum(WriteMode, value)

    def test_resolve_enum_lists_the_accepted_values(self):
        with pytest.raises(ValueError, match="'bogus'") as excinfo:
            resolve_enum(Executor, "bogus", error=ValueError)

        assert all(name in str(excinfo.value) for name in Executor)


class TestNormalizeStrs:
    def test_empty_key_rejected(self):
        with pytest.raises(InvalidPipelineError, match="non-empty"):
            normalize_strs(["id", ""])

    def test_duplicate_keys_rejected(self):
        with pytest.raises(InvalidPipelineError, match="duplicate"):
            normalize_strs(["id", "id"])

    @pytest.mark.parametrize("value", [[1, 2], ["a", 1], [None]])
    def test_non_string_keys_rejected(self, value):
        with pytest.raises(InvalidPipelineError, match="non-empty strings"):
            normalize_strs(value)

    def test_non_iterable_rejected(self):
        with pytest.raises(InvalidPipelineError, match="string or iterable"):
            normalize_strs(42)  # pyright: ignore[reportArgumentType]


def _runtime_record() -> type:
    # This module postpones annotations, so build a record whose ClassVar is an
    # evaluated annotation rather than a string.
    tag = ("tag", ClassVar[str], dataclass_field(default="point"))
    return make_dataclass(
        "_RuntimeRecord", [tag, ("x", int, dataclass_field(default=0))]
    )


class TestFieldNames:
    def test_field_names_includes_classvar_for_attrs_and_dataclass(self):
        assert "family" in field_names(EdgeBase)
        assert "family" in field_names(WriteNode)
        assert field_names(_runtime_record()) == frozenset({"tag", "x"})
        assert "family" not in field_names(Endpoint)


class Partial(TypedDict, total=False):
    kept: Required[BasicValue]
    loose: Sequence[BasicValue]


class Whole(TypedDict):
    plain: BasicValue
    dropped: NotRequired[BasicValue]
    qualified: typing.NotRequired[Sequence[BasicValue]]


class Inherited(Partial):
    added: BasicValue


class TestTypedDictKeys:
    def test_qualifiers_found_without_resolving_annotations(self):
        assert typed_dict_keys(Partial) == (frozenset({"kept"}), frozenset({"loose"}))
        assert typed_dict_keys(Whole) == (
            frozenset({"plain"}),
            frozenset({"dropped", "qualified"}),
        )

    def test_inherited_keys_keep_each_class_totality(self):
        assert typed_dict_keys(Inherited) == (
            frozenset({"kept", "added"}),
            frozenset({"loose"}),
        )

    def test_shipped_typed_dict_qualifiers_are_honored(self):
        assert typed_dict_keys(PipeModule)[0] == {"id", "type", "conf"}
        assert typed_dict_keys(Embed) == (
            frozenset({"conf", "name"}),
            frozenset({"id"}),
        )

    def test_rejects_a_plain_class(self):
        with pytest.raises(TypeError, match="is not a TypedDict"):
            typed_dict_keys(dict)

    def test_required_qualifier_is_enforced(self):
        require = require_from_typed_dict(PipeModule)

        with pytest.raises(
            InvalidPipelineError, match=r"missing PipeModule key\(s\): \['conf'\]"
        ):
            require({"id": "a", "type": "fetch"})


class TestLogging:
    """Every riko logger shares one configuration and follows one level knob."""

    def test_get_logger_reuses_the_named_logger(self):
        logger = get_logger("riko.modules.fetch")
        handlers = len(logger.handlers)
        assert get_logger("riko.modules.fetch") is logger
        assert len(logger.handlers) == handlers

    def test_default_level_is_warning(self):
        assert get_logger("riko.tests.default").getEffectiveLevel() == WARNING

    @pytest.mark.usefixtures("riko_level")
    def test_set_log_level_reaches_every_logger(self):
        before = get_logger("riko.tests.before")
        set_log_level(ERROR)
        after = get_logger("riko.tests.after")
        assert before.getEffectiveLevel() == ERROR
        assert after.getEffectiveLevel() == ERROR


ERRORS = [
    pytest.param(errors.RikoError(), id="riko"),
    pytest.param(errors.PipelineError("plain"), id="pipeline"),
    pytest.param(errors.InvalidPipelineError("bad"), id="invalid"),
    pytest.param(errors.EmptyPipelineError(), id="empty"),
    pytest.param(
        errors.PipelineStateError("closed", "read", subject="run"), id="state"
    ),
    pytest.param(
        errors.UnsupportedModuleError("trunkate", "why", candidates=iter(["truncate"])),
        id="module",
    ),
    pytest.param(errors.UnsupportedWorkflowError("pipe_x", "gone"), id="workflow"),
    pytest.param(errors.UnsupportedTargetError("ftp"), id="target"),
    pytest.param(errors.ReceiverUnavailableError("alerts"), id="receiver"),
    pytest.param(errors.DuplicateReceiverError("alerts"), id="duplicate"),
    pytest.param(errors.IdentityEncodingError(set), id="encoding"),
    pytest.param(errors.CyclicIdentityError(), id="cyclic"),
]
ROUND_TRIPS = [
    pytest.param(lambda error: pickle.loads(pickle.dumps(error)), id="pickle"),  # noqa: S301
    pytest.param(copy.copy, id="copy"),
    pytest.param(copy.deepcopy, id="deepcopy"),
]


class TestRikoError:
    @pytest.mark.parametrize("error", ERRORS)
    @pytest.mark.parametrize("round_trip", ROUND_TRIPS)
    def test_round_trip_keeps_message_and_attributes(self, error, round_trip):
        copied = round_trip(error)
        assert type(copied) is type(error)
        assert str(copied) == str(error)
        assert vars(copied) == vars(error)
