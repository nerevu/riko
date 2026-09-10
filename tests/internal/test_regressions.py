# vim: sw=4:ts=4:expandtab

from datetime import datetime, timedelta, timezone
from io import BytesIO
from typing import cast
from zoneinfo import ZoneInfo

import pytest

from riko._date_utils import TZINFOS, date_to_tt, parse_date_string
from riko._io import Fetch
from riko._rssutils import augment_entries
from riko._serialize import repr_cache
from riko.dates import tt_to_datedict
from riko.modules._prepare import get_pieces_or_conf
from riko.modules.regex import pipe as regex
from riko.modules.rename import pipe as rename
from riko.modules.xpathfetchpage import pipe as xpathfetchpage
from riko.parsers import XML_PARSER, any2dict, get_skip
from riko.paths import get_path
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
        An aware ``+03:00`` struct_time must yield the epoch of that instant, not the
        epoch of the same wall-clock read as UTC.
        """
        tz = timezone(timedelta(hours=3))
        aware = datetime(2020, 6, 15, 9, 0, 0, tzinfo=tz)
        tt = date_to_tt(aware)

        result = tt_to_datedict(tt, aware.date())
        assert result["utime"] == int(aware.timestamp())

    def test_ambiguous_cst_resolves_to_us_central(self):
        """
        ``CST`` is shared by US Central, China, and Cuba. The abbreviation map
        must resolve it US-centrically (UTC-6), not to whichever zone happened
        to sort last (Asia/Taipei, UTC+8).
        """
        parsed = parse_date_string("1 Feb 2015 12:00:00 CST")
        assert parsed.utcoffset() == timedelta(hours=-6)

    def test_tzinfos_capture_both_standard_and_daylight_names(self):
        """
        The abbreviation map is built at import; sampling only ``now()`` dropped
        whichever of a zone's standard/daylight names was out of season. Both
        must be present and stably point at US Eastern regardless of import date.
        """
        assert str(TZINFOS["EST"]) == "America/New_York"
        assert str(TZINFOS["EDT"]) == "America/New_York"

    def test_non_us_abbreviation_resolves(self):
        """
        Abbreviations outside ``_PREFERRED_ZONES`` (e.g. ``JST``) must be present.
        """
        assert TZINFOS["JST"] == ZoneInfo("Asia/Tokyo")

        parsed = parse_date_string("1 Feb 2015 12:00:00 JST")
        assert parsed.utcoffset() == timedelta(hours=9)


class TestSerialize:
    def test_nested_unsupported_bypasses_cache_and_reaches_fn(self):
        """
        An unsupported object nested in a container arg must bypass the cache, so
        distinct instances neither collide nor get replaced by the sentinel.
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
        """
        A truthy value is not skipped even when it reads like "no value".
        """
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

            assert sorted(cast(dict, result.get("info"))) == [
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
        The hardened ``XML_PARSER`` must not expand a defined entity (XXE guard):
        ``resolve_entities=False`` leaves ``&xxe;`` unresolved rather than
        substituting its declared value.
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
        """Feed-entry augmentation fallbacks (``riko._rssutils.augment_entries``)."""
        item = next(augment_entries([FeedParserRSSEntry(entry)]))
        assert item.get("summary") == expected
        assert item.get("description") == expected


class TestPrepare:
    @pytest.mark.parametrize(
        ("value", "expected"), [(0, [0]), (False, [False]), ("", [""]), (None, [])]
    )
    def test_listize_wraps_falsy_extracted_value(self, value, expected):
        """A falsy (but non-None) extracted value is still list-wrapped."""
        conf = cast(Conf, {"n": value})
        pieces, _ = get_pieces_or_conf(conf, {}, {"extract": "n", "listize": True})
        assert pieces == expected
