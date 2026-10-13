# vim: sw=4:ts=4:expandtab
"""Provides internal tests for canonical encoding, casts, dates, parsing, and graphs."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone, tzinfo
from decimal import Decimal, localcontext
from enum import Enum, StrEnum
from graphlib import CycleError
from io import BytesIO
from pathlib import PurePosixPath, PureWindowsPath
from time import struct_time
from types import MappingProxyType
from typing import TYPE_CHECKING, cast
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from attrs import define
from dateutil.relativedelta import relativedelta
from feedparser import FeedParserDict

from riko.base._dateutils import TZINFOS
from riko.base._graph import cyclic_nodes, descendants, freeze_graph, topological_sort
from riko.base._paths import ROOT_DIR, get_path
from riko.base.exceptions import CyclicIdentityError, IdentityEncodingError
from riko.coercion._canonical import (
    IdentityDomain,
    canonical_bytes,
    canonicalize,
    digest,
    repr_cache,
)
from riko.coercion._dates import (
    date_to_tt,
    parse_date_string,
    resolve_aware_datetime,
    tt_to_datedict,
)
from riko.coercion.cast import cast_datetime
from riko.definitions._nodes import ModuleNode, StreamEdge
from riko.definitions._workflow import Workflow
from riko.io._sync import Fetch
from riko.modules.xpathfetchpage import pipe as xpathfetchpage
from riko.parsing._dotdict import DotDict
from riko.parsing.config import get_skip
from riko.parsing.documents import XML_PARSER, any2dict
from riko.rss.entries import augment_entries, resolve_date
from riko.types import _workflow as workflow_types
from riko.types._rss import FeedParserRSSEntry
from riko.types._workflow import Endpoint, GraphEdge, GraphIndex
from riko.types.modules import XpathFetchPageConf

if TYPE_CHECKING:
    from riko.types._collections import FrozenSetMapping

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


class TestCanonicalBytes:
    @pytest.mark.parametrize(
        ("value", "expected"), GOLDEN_BYTES.values(), ids=GOLDEN_BYTES.keys()
    )
    def test_golden_canonical_bytes(self, value, expected):
        assert canonical_bytes(value) == expected

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
    def test_conflatable_types_stay_distinct(self, left, right):
        assert canonical_bytes(left) != canonical_bytes(right)

    def test_mapping_is_order_independent(self):
        assert canonical_bytes({"a": 1, "b": 2}) == canonical_bytes({"b": 2, "a": 1})

    def test_heterogeneous_mapping_keys_sort_deterministically(self):
        first = canonical_bytes({1: "x", "a": "y", (2, 3): "z"})
        second = canonical_bytes({(2, 3): "z", "a": "y", 1: "x"})
        assert first == second

    def test_set_is_order_independent(self):
        assert canonical_bytes({1, 2, 3}) == canonical_bytes({3, 2, 1})

    def test_distinct_nan_keys_sort_by_full_pair(self):
        first, second = float("nan"), float("nan")
        forward = {first: "x", second: "y"}
        reverse = {second: "y", first: "x"}
        assert len(forward) == len(reverse) == 2
        assert canonical_bytes(forward) == canonical_bytes(reverse)

    def test_negative_zero_canonicalizes_with_positive_zero(self):
        assert canonical_bytes(-0.0) == canonical_bytes(0.0)

    def test_float_infinities_and_nan_have_stable_tags(self):
        assert canonical_bytes(float("inf")) == b'["float","inf"]'
        assert canonical_bytes(float("-inf")) == b'["float","-inf"]'
        assert canonical_bytes(float("nan")) == b'["float","nan"]'

    def test_decimal_equivalent_representations_normalize(self):
        assert canonical_bytes(Decimal("1.0")) == canonical_bytes(Decimal("1.000"))

    def test_decimal_encoding_ignores_ambient_context_precision(self):
        value = Decimal("123456.789")

        with localcontext() as ctx:
            ctx.prec = 1
            low = canonical_bytes(value)

        with localcontext() as ctx:
            ctx.prec = 60
            high = canonical_bytes(value)

        assert low == high == canonical_bytes(value)

    def test_naive_datetime_uses_utc_fallback(self):
        assert canonical_bytes(datetime(2020, 6, 15, 12)) == canonical_bytes(
            datetime(2020, 6, 15, 12, tzinfo=UTC)
        )

    def test_aware_datetime_normalizes_to_utc(self):
        est = timezone(timedelta(hours=-5))
        assert canonical_bytes(datetime(2020, 6, 15, 7, tzinfo=est)) == canonical_bytes(
            datetime(2020, 6, 15, 12, tzinfo=UTC)
        )

    def test_struct_time_is_distinct_from_datetime(self):
        tt = time.struct_time((2020, 6, 15, 12, 0, 0, 0, 0, -1))
        assert canonical_bytes(tt) != canonical_bytes(
            datetime(2020, 6, 15, 12, tzinfo=UTC)
        )

    def test_path_flavor_is_preserved(self):
        assert canonical_bytes(PureWindowsPath("a/b")) != canonical_bytes(
            PurePosixPath("a/b")
        )

    def test_enum_includes_type_identity(self):
        assert canonical_bytes(Color.RED) != canonical_bytes(1)
        assert canonical_bytes(Flavor.SWEET) != canonical_bytes("sweet")

    def test_dataclass_freezes_by_type_and_fields(self):
        assert canonical_bytes(Point(1, 2)) == canonical_bytes(Point(1, 2))
        assert canonical_bytes(Point(1, 2)) != canonical_bytes(Point(2, 1))

    def test_attrs_freezes_by_type_and_fields(self):
        assert canonical_bytes(Pin(1, 2)) == canonical_bytes(Pin(1, 2))
        assert canonical_bytes(Pin(1, 2)) != canonical_bytes(Pin(2, 1))

    def test_attrs_and_dataclass_stay_distinct(self):
        assert canonical_bytes(Pin(1, 2)) != canonical_bytes(Point(1, 2))

    def test_recursive_tuple_keys_are_supported(self):
        assert canonical_bytes((1, (2, (3, 4)))) == canonical_bytes((1, (2, (3, 4))))

    def test_encoding_is_repeatable(self):
        value = {"a": [1, 2], "b": (3, 4), "c": {5, 6}}
        assert canonical_bytes(value) == canonical_bytes(value)

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


def _get_subprocess_digest(hash_seed: str) -> str:
    env = {**os.environ, "PYTHONHASHSEED": hash_seed}
    args = [sys.executable, "-c", DIGEST_SCRIPT]
    done = subprocess.run(args, env=env, capture_output=True, check=True, text=True)
    return done.stdout.strip()


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

    def test_domain_separates_digests(self):
        assert digest(1, IdentityDomain.FINGERPRINT) != digest(
            1, IdentityDomain.IDEMPOTENCY
        )

    def test_digest_is_stable_across_processes_with_different_hash_seeds(self):
        digests = {_get_subprocess_digest(seed) for seed in ("0", "1", "4242")}
        assert len(digests) == 1


class _Opaque:
    pass


class TestReprCache:
    def test_repr_cache_memoizes_supported_arguments(self):
        calls: list[object] = []

        @repr_cache
        def tally(value):
            calls.append(value)
            return len(calls)

        assert (tally({"a": 1}), tally({"a": 1})) == (1, 1)
        assert len(calls) == 1

    def test_repr_cache_bypasses_unsupported_arguments(self):
        calls: list[object] = []

        @repr_cache
        def tally(value):
            calls.append(value)
            return len(calls)

        tally(object())
        tally(object())
        assert len(calls) == 2

    def test_repr_cache_bypasses_lone_surrogate_strings(self):
        calls: list[object] = []

        @repr_cache
        def tally(value):
            calls.append(value)
            return len(calls)

        assert (tally("\ud800"), tally("\ud800")) == (1, 2)

    def test_nested_unsupported_bypasses_cache_and_reaches_fn(self):
        """
        Bypass caching when a container holds an unsupported object.

        Distinct instances must neither collide nor be replaced by the sentinel.
        """
        calls = []

        @repr_cache
        def record(arg):
            calls.append(arg)
            return len(calls)

        first, second = _Opaque(), _Opaque()
        record({"x": first})
        record({"x": second})

        assert len(calls) == 2
        assert calls[0]["x"] is first
        assert calls[1]["x"] is second


class TestCastDatetime:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("Jan. 12, 2001", (2001, 1, 12)),
            ("10/21/1958", (1958, 10, 21)),
            ("15 JUN 06", (2006, 6, 15)),
        ],
    )
    def test_documented_absolute_date_strings(self, value, expected):
        result = cast_datetime(value)
        assert result is not None
        assert (result.year, result.month, result.day) == expected

    def test_documented_relative_date_strings(self):
        today = cast_datetime("today")
        assert today is not None
        assert cast_datetime("+3 days") == today + timedelta(days=3)
        assert cast_datetime("-10 weeks") == today - timedelta(weeks=10)
        assert cast_datetime("last year") == today - relativedelta(years=1)

    def test_documented_epoch_value(self):
        result = cast_datetime(1181230100)
        assert result is not None
        assert int(result.timestamp()) == 1181230100


@pytest.fixture
def tokyo(monkeypatch):
    if not hasattr(time, "tzset"):
        pytest.skip("tzset is POSIX-only")

    monkeypatch.setenv("TZ", "Asia/Tokyo")
    time.tzset()
    yield
    time.tzset()


class TestTryLocalTz:
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

    def test_keyword_only(self):
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


class NamelessZone(tzinfo):
    def tzname(self, dt: datetime | None) -> None:
        return None

    def utcoffset(self, dt: datetime | None) -> timedelta:
        return timedelta(0)

    def dst(self, dt: datetime | None) -> timedelta:
        return timedelta(0)


class TestDates:
    def test_resolve_aware_datetime_keeps_a_nameless_zone(self):
        zone = NamelessZone()
        result = resolve_aware_datetime(
            datetime(2020, 1, 1, tzinfo=zone), try_local_tz=False
        )
        assert isinstance(result, datetime)
        assert result.tzinfo is zone

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


class TestDotDict:
    @pytest.mark.parametrize(("source", "key", "expected"), DOTDICT_DELETES)
    def test_delete(self, source, key, expected):
        d = DotDict(source)
        d.delete(key)
        assert d.asdict() == expected


class TestParsers:
    def test_get_skip_field_only_follows_presence_not_absent_text(self):
        """A truthy value is not skipped even when it reads like "no value"."""
        assert get_skip({"content": "none available"}, {"field": "content"}) is False

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

    def test_xpathfetchpage_strips_xhtml_namespace_from_nested_keys(self):
        conf = XpathFetchPageConf(
            {"url": get_path("users.jyu.fi.html"), "xpath": "/html/body/p/a"}
        )

        assert next(xpathfetchpage(conf=conf)) == {
            "href": "http://www.w3.org/",
            "img": {"src": "http://www.w3.org/Icons/w3c_home", "alt": "W3C"},
        }

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


class TestRSSUtils:
    @pytest.mark.parametrize(("entry", "expected"), AUGMENT_FALLBACKS)
    def test_augment_entries_fallbacks(self, entry, expected):
        """Feed-entry augmentation fallbacks from ``riko.rss.entries``."""
        item = next(augment_entries([FeedParserRSSEntry(entry)]))
        assert item.get("summary") == expected
        assert item.get("description") == expected

    def test_augment_entries_parses_date_the_parser_could_not(self):
        """A present-but-``None`` parsed date falls back to the raw date string."""
        raw = cast(
            "FeedParserRSSEntry",
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

    def test_resolve_date_skips_blank_and_unparseable_values(self):
        """A blank or unparseable candidate never raises; the next key is tried."""
        raw = cast(
            "FeedParserRSSEntry",
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

    @pytest.mark.filterwarnings("error::DeprecationWarning")
    def test_resolve_date_does_not_trigger_feedparser_updated_fallback(self):
        """Asking a feedparser entry for a missing ``updated`` key stays silent."""
        raw = FeedParserDict({"published": "2020-01-02", "published_parsed": None})
        entry = cast("FeedParserRSSEntry", raw)
        keys = ("updated_parsed", "updated", "published_parsed", "published")
        resolved = resolve_date(entry, *keys)
        assert isinstance(resolved, struct_time)
        assert resolved[:3] == (2020, 1, 2)
        item = dict(next(augment_entries([entry])))
        assert item["updated_parsed"] == resolved


_SEEDED_ORDER = """
from riko.base._graph import scc_sort, topological_sort
print(topological_sort({"a": {"b"}, "b": {"a"}, "c": set()}))
print(topological_sort({"a": {"b", "c", "d"}, "e": {"f", "g"}}))
print(scc_sort({"A": {"B", "C"}, "B": {"D"}, "C": {"D"}, "D": {"E"}}))
"""


def _get_seeded_order(seed: str) -> list[str]:
    env = {**os.environ, "PYTHONHASHSEED": seed}
    args = [sys.executable, "-c", _SEEDED_ORDER]
    run = subprocess.run(
        args, capture_output=True, check=True, cwd=ROOT_DIR, env=env, text=True
    )
    return run.stdout.splitlines()


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
        assert index.required["default"] == frozenset({"a", "b"})
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
        assert index.required["default"] == frozenset({"a", "b"})
        assert len(calls) == 1
        assert index == GraphIndex(["a", "b"], [edge], outputs)

    def test_workflow_index_orders_and_indexes(self) -> None:
        a = ModuleNode(id="a", name="m")
        b = ModuleNode(id="b", name="m")
        c = ModuleNode(id="c", name="m")
        edge = StreamEdge(Endpoint("a", "out"), Endpoint("b", "in"))
        outputs = {"default": Endpoint("b", "out"), "extra": Endpoint("c", "out")}
        workflow = Workflow(
            nodes=[a, b, c], outputs=outputs, inputs={}, edges=(edge,), resources=()
        )
        index = workflow.index

        assert set(index.order) == {"a", "b", "c"}
        assert index.order.index("a") < index.order.index("b")
        assert set(index.roots) == {"a", "c"}
        assert set(index.leaves) == {"b", "c"}
        assert index.upstream["b"] == frozenset({"a"})
        assert index.downstream["a"] == frozenset({"b"})
        assert index.incoming["b"][0].source == "a"
        assert index.outgoing["a"][0].target == "b"
        assert set(index.outputs) == {"default", "extra"}
        assert index.required == {"default": {"a", "b"}, "extra": {"c"}}

    def test_cycle_names_only_the_nodes_on_the_cycle(self):
        src = ModuleNode(id="src", name="fetch")
        a = ModuleNode(id="a", name="sort")
        b = ModuleNode(id="b", name="sort")
        after = ModuleNode(id="after", name="sort")
        edges = (
            StreamEdge(Endpoint("src", "out"), Endpoint("a", "in")),
            StreamEdge(Endpoint("a", "out"), Endpoint("b", "in")),
            StreamEdge(Endpoint("b", "out"), Endpoint("a", "in:1")),
            StreamEdge(Endpoint("b", "out"), Endpoint("after", "in")),
        )
        workflow = Workflow(
            nodes=[src, a, b, after],
            edges=edges,
            outputs={"default": Endpoint("after", "out")},
            inputs={},
            resources=(),
            version="2",
        )
        assert workflow.index.cyclic == ("a", "b")
