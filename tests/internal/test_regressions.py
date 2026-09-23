# vim: sw=4:ts=4:expandtab
"""Regression tests guarding previously fixed bugs."""

from datetime import datetime, timedelta, timezone
from io import BytesIO
from typing import cast
from zoneinfo import ZoneInfo

import pytest

from riko.base._dateutils import TZINFOS
from riko.base._paths import get_path
from riko.coercion._canonical import repr_cache
from riko.coercion._dates import date_to_tt, parse_date_string, tt_to_datedict
from riko.io._sync import Fetch
from riko.modules._prepare import get_pieces_or_conf
from riko.modules.regex import pipe as regex
from riko.modules.rename import pipe as rename
from riko.modules.xpathfetchpage import pipe as xpathfetchpage
from riko.parsing.config import get_skip
from riko.parsing.documents import XML_PARSER, any2dict
from riko.rss.entries import augment_entries
from riko.types._rss import FeedParserRSSEntry
from riko.types.modules import (
    Conf,
    RegexConf,
    RegexConfRule,
    RenameConf,
    RenameConfRule,
    XpathFetchPageConf,
)


class _Opaque:
    pass


class TestDates:
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


class TestSerialize:
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


class TestModules:
    def test_rename_skips_absent_field(self):
        """A rename rule naming an absent field leaves the item untouched."""
        conf = RenameConf({"rule": RenameConfRule(field="content", newval="greeting")})
        assert next(rename({"title": "hi"}, conf=conf)) == {"title": "hi"}

    def test_rename_renames_present_falsy_field(self):
        """A present-but-falsy value is still renamed (absent ≠ present-``None``)."""
        conf = RenameConf({"rule": RenameConfRule(field="content", newval="greeting")})
        assert next(rename({"content": ""}, conf=conf)) == {"greeting": ""}

    def test_regex_skips_absent_field(self):
        """A regex rule naming an absent field leaves the item untouched."""
        conf = RegexConf(
            {"rule": RegexConfRule(field="content", match="l", replace="L")}
        )
        assert next(regex({"title": "hi"}, conf=conf)) == {"title": "hi"}


class TestRSSUtils:
    @pytest.mark.parametrize(
        ("entry", "expected"),
        [
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
        ],
    )
    def test_augment_entries_fallbacks(self, entry, expected):
        """Feed-entry augmentation fallbacks from ``riko.utils._rssutils``."""
        item = next(augment_entries([FeedParserRSSEntry(entry)]))
        assert item.get("summary") == expected
        assert item.get("description") == expected


class TestPrepare:
    @pytest.mark.parametrize(
        ("value", "expected"), [(0, [0]), (False, [False]), ("", [""]), (None, [])]
    )
    def test_listize_wraps_falsy_extracted_value(self, value, expected):
        """A falsy (but non-None) extracted value is still list-wrapped."""
        conf = cast("Conf", {"n": value})
        pieces, _ = get_pieces_or_conf(conf, {}, {"extract": "n", "listize": True})
        assert pieces == expected
