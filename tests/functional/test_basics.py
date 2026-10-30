"""Provides functional tests that run stored workflows and fixtures end to end."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from itertools import islice
from time import struct_time
from typing import TYPE_CHECKING, cast

import pytest

from riko.base._dateutils import get_tzname
from riko.base._exceptions import UnsupportedModuleError
from riko.base._guards import is_mapping
from riko.coercion._sequences import listize, truncate_content
from riko.definitions._context import Context
from riko.runtime._resolver import dispatcher
from riko.runtime._workflow_resolver import workflow_resolver
from riko.types._streams import AsyncStream, StatefulItem
from riko.types._wrappers import ParserMaterializedOutput, ParserOutput, is_subpipe
from tests import TESTS_DIR, async_test
from tests._workflows import SPLIT_PENDING, run_workflow

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

type Items = ParserOutput | StatefulItem

COMPARISONS = {Decimal(1): ">", Decimal(-1): "<", Decimal(0): "=="}

KAZEEKI1_EXAMPLE = {
    "author": {"name": "riko", "uri": "https://github.com/nerevu/riko"},
    "dc:creator": "riko",
    "k:author": "Homepage for a germansocial organization",
    "k:budget_raw": "0 - $250",
    "k:client_location": "unknown",
    "k:due": "unknown",
    "k:job_type": "fixed",
    "k:marketplace": "guru.com",
    "updated": "Tue, 06 Jan 2015 17:13:47 GMT",
    "k:submissions": "unknown",
    "k:tags": "Web,Software,IT",
    "k:work_location": " Worldwide",
}

KAZEEKI1_CONTENT = (
    " With this specification sheet we",
    "for implementing a website for a german...",
)

KAZEEKI2_EXAMPLE = {
    "author": None,
    "dc:creator": None,
    "k:author": "Need to fix Ionic Rss Reader Application - oDesk",
    "k:budget_raw": "0 - 10 EUR",
    "k:client_location": " Israel",
    "k:due": "unknown",
    "k:job_type": "unknown",
    "k:marketplace": "odesk.com",
    "k:posted": None,
    "k:submissions": "unknown",
    "k:tags": "Web-Development,Web-Programming",
    "k:work_location": "unknown",
}

KAZEEKI2_CONTENT = (
    "<p>Hello, I need to fix an application",
    "are welcome to this project.<br><br><b>",
)

NATIVE_TITLE = "Running “Native” Data Wrangling Applicat"

CSV_DESCRIPTION = (
    "Total allowances claimed, inc travel: "
    "151619<br>Total basic allowances claimed, ex travel: "
    "146282<br>Total Travel claimed: 5337<br>MP Mileage: "
    "3358<br>MP Rail Travel: 1473<br>MP Air Travel: 0<br>"
    "Cost of staying away from main home: 22541<br>London "
    "Supplement: 0<br>Office Running Costs: 19848<br>"
    "Staffing Costs: 88283"
)

CSV_ITEM = {
    "FamilyNumOfJourneys": "0",
    "Member": "Lancaster",
    "MPOtherEuropean": "0",
    "FamilyTotal": "0",
    "OfficeRunningCosts": "19848",
    "MPOtherRail": "233",
    "CostofStayingAwayFromMainHome": "22541",
    "StationeryAssocdPostageCosts": "3471",
    "CommsAllowance": "9767",
    "Mileage": "3358",
    "MPMisc": "20",
    "title": "Mr Mark Lancaster",
    "description": CSV_DESCRIPTION,
    "TotalAllowancesClaimedIncTravel": "151619",
    "SpouseTotal": "31",
    "EmployeeTotal": "222",
    "MPRail": "1473",
    "LondonSupplement": "0",
    "StaffingCosts": "88283",
    "EmployeeNumOfJourneys": "21",
    "CentrallyPurchasedStationery": "1149",
    "TotalBasicAllowancesExcTravel": "146282",
    "CentralITProvision": "1223",
    "StaffCoverAndOtherCosts": "0",
    "firstName": "Mr Mark",
    "MPOtherAir": "0",
    "MPOtherMileage": "0",
    "TotalTravelClaimed": "5337",
    "MPAir": "0",
    "SpouseNumOfJourneys": "1",
}

ITEMBUILDER_ITEMS = [
    {
        "attr1": "val1",
        "attrpath": {"attr2": "val2", "attr3": "extVal"},
        "longpath": {"attrpath": {"attr3": "val3"}},
    },
    {"attr1": "VAL1", "attrpath": {"attr2": "VAL2"}},
]

ASSIGNED = [{"title": "a b c", "tokens": {"content": c}} for c in "abc"]
EMBEDDED = [{"title": "hello", "strconcat": "hello!"}]


def _assert_kazeeki(item: Mapping, example: Mapping, content: tuple[str, str]) -> None:
    for key, expected in example.items():
        got = item.get(key)
        assert got == expected, f"Expected {expected} for key {key}, but got {got}"

    start, end = content
    assert item["k:content"].startswith(start)
    assert item["k:content"].endswith(end)


def _document(pipe_name: str) -> Path | None:
    """Supplies the committed workflow document for a ``pipe_<id>`` name, if any."""
    path = TESTS_DIR / "workflows" / f"{pipe_name}.json"
    return path if path.exists() else None


def _check_results(items: Sequence[Items], value=0, check=1):
    _check = Decimal(check)
    compared = Decimal(len(items)).compare(Decimal(value))
    actual, desired = COMPARISONS[compared], COMPARISONS[_check]
    msg = f"output length {actual} {value}, but expected {desired} {value}. Got "

    try:
        first = items[0]
    except IndexError:
        msg += f"{type(items)=}"
    else:
        msg += f"{len(items)} items. First item is {truncate_content(first)}"

    assert compared == _check, msg


def _check_dates[T: datetime | struct_time | date](*dates: T | object) -> tuple[T, ...]:
    for _class in (datetime, struct_time, date):
        if all(isinstance(_date, _class) for _date in dates):
            if _class is datetime or _class is struct_time:
                for _date in dates:
                    assert get_tzname(cast("datetime", _date))

            break
    else:
        msg = f"Expected all dates to be of the same type, but got {dates}"
        raise AssertionError(msg)

    return cast("tuple[T, ...]", dates)


FIRST_ITEM_FIELDS = [
    pytest.param(
        "pipe_HrX5bjkv3BGEp9eSy6ky6g",
        15,
        "link",
        "http://sz.de/1.2104731",
        id="feeddiscovery",
    ),
    pytest.param(
        "pipe_404411a8d22104920f3fc1f428f33642",
        3,
        "title",
        "Markitekt - Architects of Marketing",
        id="wired-count-truncate",
    ),
    pytest.param(
        "pipe_eb3e27f8f1841835fdfd279cd96ff9d8",
        3,
        "ctime",
        "&time=00:01:41&time=",
        id="twitter-caption-search",
    ),
    pytest.param(
        "pipe_zKJifuNS3BGLRQK_GsevXg",
        6,
        "title",
        "Open researcher open course",
        id="simplemath",
        marks=SPLIT_PENDING,
    ),
]
FIRST_TITLE_PREFIXES = [
    pytest.param(
        "pipe_2de0e4517ed76082dcddf66f7b218057", 17, f"{NATIVE_TITLE}i", id="simplest"
    ),
    pytest.param(
        "pipe_c1cfa58f96243cea6ff50a12fc50c984",
        18,
        NATIVE_TITLE,
        id="filtered-multiple-sources",
    ),
    pytest.param(
        "pipe_QMrlL_FS3BGlpwryODY80A",
        7,
        "[Weight] More parents think their overweight",
        id="split",
        marks=SPLIT_PENDING,
    ),
    pytest.param(
        "pipe_06c4c44316efb0f5f16e4e7fa4589ba2",
        5,
        "American woman is being held hostage",
        id="tail",
    ),
    pytest.param(
        "pipe_e519dd393f943315f7e4128d19db2eac",
        63,
        "The 6 Best Enterprise Data Modeling Tools",
        id="urlbuilder",
    ),
]
KAZEEKI = [
    pytest.param("kazeeki1", 5, KAZEEKI1_EXAMPLE, KAZEEKI1_CONTENT, id="fetchdata"),
    pytest.param("kazeeki2", 1, KAZEEKI2_EXAMPLE, KAZEEKI2_CONTENT, id="itembuilder"),
]
WHOLE_STREAMS = [
    pytest.param(
        "pipe_b96287458de001ad62a637095df33ad5",
        ITEMBUILDER_ITEMS,
        None,
        id="itembuilder",
    ),
    pytest.param("pipe_UuvYtuMe3hGDsmRgPm7D0g", [CSV_ITEM], None, id="csv"),
    pytest.param("pipe_loop_subpipe", EMBEDDED, None, id="loop-subpipe-embed"),
    pytest.param("pipe_loop_assign", ASSIGNED, None, id="loop-count-all-assign"),
    pytest.param(
        "pipe_1LNyRuNS3BGdkTKaAsqenA",
        [{"symbol": "IBM"}],
        {"textinput1": "IBM"},
        id="input-override",
    ),
]


UNSUPPORTED_MODULES = [
    pytest.param(
        "pipe_b3d43c00f9e1145ff522fb71ea743e99", "locationbuilder", id="locationbuilder"
    ),
    pytest.param("pipe_93abb8500bd41d56a37e8885094c8d10", "termextractor", id="tagger"),
]


class TestStoredWorkflows:
    """Test a few sample workflows."""

    def _run_example(
        self, pipe_name: str, file_path: Path | None = None
    ) -> ParserMaterializedOutput:
        # prefer the workflow document; fall back to the hand-written module
        items: ParserMaterializedOutput = []

        if _document(pipe_name) is None:
            stream = dispatcher.require(pipe_name)(context=self.context)
            items = cast("ParserMaterializedOutput", list(listize(stream)))
        else:
            flow = workflow_resolver.load_workflow(pipe_name, directory=file_path)
            items = [*run_workflow(flow, context=self.context)]

        return items

    def _async_run_example(self, pipe_name: str) -> AsyncStream:
        pipe = dispatcher.require(pipe_name, True)
        assert is_subpipe(pipe)
        return pipe(context=self.context)

    def setup_method(self):
        """Creates the shared test ``Context``."""
        self.context = Context(test=True)

    @pytest.mark.parametrize(
        ("pipe_name", "count", "field", "expected"), FIRST_ITEM_FIELDS
    )
    def test_first_item_field(self, pipe_name, count, field, expected):
        """Runs a stored workflow and checks one field of its first item."""
        items = self._run_example(pipe_name)
        _check_results(items, count, 0)
        item = items[0]
        assert is_mapping(item)
        assert item.get(field) == expected

    @pytest.mark.parametrize(("pipe_name", "count", "prefix"), FIRST_TITLE_PREFIXES)
    def test_first_item_title_prefix(self, pipe_name, count, prefix):
        """Runs a stored workflow and checks how its first item's title begins."""
        items = self._run_example(pipe_name)
        _check_results(items, count, 0)
        item = items[0]
        assert is_mapping(item)
        assert str(item.get("title")).startswith(prefix)

    @pytest.mark.parametrize(("pipe_name", "expected", "inputs"), WHOLE_STREAMS)
    def test_whole_stream(self, pipe_name, expected, inputs):
        """Runs a stored workflow, optionally with inputs, and checks every item."""
        if inputs is not None:
            self.context = self.context.replace(inputs=inputs)

        assert self._run_example(pipe_name) == expected

    @pytest.mark.parametrize(("name", "count", "example", "content"), KAZEEKI)
    def test_kazeeki(self, name, count, example, content):
        """Loads a kazeeki simple test workflow and checks its first item."""
        items = self._run_example(f"pipe_{name}")
        _check_results(items, count, 0)
        item = items[0]
        assert is_mapping(item)
        _assert_kazeeki(item, example, content)

    @async_test
    @pytest.mark.parametrize(("name", "count", "example", "content"), KAZEEKI)
    async def test_async_kazeeki(self, name, count, example, content):
        """Loads an async kazeeki simple test workflow and checks its first item."""
        stream = self._async_run_example(f"pipe_async_{name}")
        items = [item async for item in stream]
        _check_results(items, count, 0)
        item = items[0]
        assert is_mapping(item)
        _assert_kazeeki(item, example, content)

    def test_fetchsitefeed(self):
        """Loads a workflow containing a fetchsitefeed module."""
        pipe_name = "pipe_551507461cbcb19a828165daad5fe007"
        items = self._run_example(pipe_name)
        _check_results(items, 1, 1)
        item = items[0]
        assert is_mapping(item)
        assert item.get("title")
        assert item.get("summary")

    def test_loops_1(self):
        """Loads a workflow containing a loop."""
        pipe_name = "pipe_125e9fe8bb5f84526d21bebfec3ad116"
        items = self._run_example(pipe_name)
        _check_results(items, 1, 0)

        item = items[0]
        assert is_mapping(item)
        assert item.get("description") == "public"

        info = item.get("info")
        assert is_mapping(info)
        assert info.get("login") == "defunkt"
        assert info.get("user_view_type") == "public"

    def test_kazeeki_full(self):
        """Loads the kazeeki simple test workflow."""
        pipe_name = "pipe_kazeeki_full"
        items = self._run_example(pipe_name)
        _check_results(items, 5, 0)

        example = {
            "author": {"name": "riko", "uri": "https://github.com/nerevu/riko"},
            "dc:creator": "riko",
            "id": 2241242391,
            "k:author": "Homepage for a germansocial organization",
            "k:budget_raw": "0 - $250",
            "k:budget_raw1": "0",
            "k:budget_raw1_code": "0",
            "k:budget_raw1_num": "0",
            "k:budget_raw1_sym": "0",
            "k:budget_raw2": "$250",
            "k:budget_raw2_code": "$250",
            "k:budget_raw2_num": "250",
            "k:budget_raw2_sym": "$",
            "k:budget": 125.0,
            "k:budget_converted": 125.0,
            "k:budget_converted_w_sym": "$125.00",
            "k:budget_full": "$125.00",
            "k:budget_sym": "$",
            "k:budget_w_sym": "$125.00",
            "k:client_location": "unknown",
            "k:content": (
                " With this specification sheet we want to give you a request for "
                "implementing a website for a german..."
            ),
            "k:cur_code": "USD",
            "k:due": "unknown",
            "k:job_type": "fixed",
            "k:job_type_code": "1",
            "k:marketplace": "guru.com",
            "k:posted": (
                "time.struct_time(tm_year=2015, tm_mon=1, tm_mday=6, tm_hour=17, "
                "tm_min=13, tm_sec=47, tm_wday=1, tm_yday=6, tm_isdst=0)"
            ),
            "k:rate": 1.0,
            "k:submissions": "unknown",
            "k:tags": [{"content": "IT"}, {"content": "Software"}, {"content": "Web"}],
            "k:work_location": " Worldwide",
            "link": (
                "http://www.guru.com/jobs/homepage-for-a-germansocial-organization/"
                "1099595"
            ),
            "links": [{}],
            "pubDate": (
                "time.struct_time(tm_year=2015, tm_mon=1, tm_mday=6, tm_hour=17, "
                "tm_min=13, tm_sec=47, tm_wday=1, tm_yday=6, tm_isdst=0)"
            ),
            "title": "Homepage for a germansocial organization",
            "updated": "Tue, 06 Jan 2015 17:13:47 GMT",
            "updated_parsed": (
                "time.struct_time(tm_year=2015, tm_mon=1, tm_mday=6, tm_hour=17, "
                "tm_min=13, tm_sec=47, tm_wday=1, tm_yday=6, tm_isdst=0)"
            ),
            "y:id": (
                "http://www.guru.com/jobs/homepage-for-a-germansocial-organization/"
                "1099595"
            ),
        }

        item = items[0]
        assert is_mapping(item)

        for k, v in example.items():
            assert item.get(k) == v, f"Expected {v} for key {k}, but got {item.get(k)}"

        summary = str(item.get("summary"))
        assert summary.startswith("<span><b>Description:</b> With this spe")
        assert summary.endswith("ancer Location:</b> Worldwide<br></span>")

    @pytest.mark.perf
    def test_feed(self):
        """Loads a simple test workflow."""
        pipe_name = "pipe_testpipe1"
        items = self._run_example(pipe_name)
        _check_results(items, 4, 0)

        for item in items:
            assert is_mapping(item)

            summary = str(item.get("summary"))
            assert "the" in summary

    @pytest.mark.perf
    def test_european_performance_cars(self):
        """Loads a workflow containing a sort."""
        pipe_name = "pipe_8NMkiTW32xGvMbDKruymrA"
        items = self._run_example(pipe_name)
        _check_results(items, 36, 0)
        first, last = items[0], items[-1]
        assert is_mapping(first)
        assert is_mapping(last)

        dates = _check_dates(first.get("pubDate"), last.get("pubDate"))
        assert dates[0] > dates[-1]

        cars = (
            "amg",
            "aston",
            "audi",
            "bmw",
            "ferrari",
            "lamborghini",
            "lotus",
            "mercedes",
            "pagani",
            "porsche",
            "tvr",
            "vw",
        )

        for item in items:
            assert is_mapping(item)

            summary = str(item.get("summary"))
            msg = f"Expected one of {cars} in summary, but got {summary}"
            assert any(car in summary.lower() for car in cars), msg

    def test_reverse_truncate(self):
        """Loads a workflow containing a reverse and truncate."""
        pipe_name = "pipe_58a53262da5a095fe7a0d6d905cc4db6"
        items = self._run_example(pipe_name)
        _check_results(items, 3, 0)
        prev_title = None

        for item in items:
            assert is_mapping(item)

            title = str(item.get("title"))
            assert not prev_title or title < prev_title
            prev_title = title

    def test_rssitembuilder(self):
        """Loads a workflow containing an rssitembuilder."""
        pipe_name = "pipe_1166de33b0ea6936d96808717355beaa"
        items = self._run_example(pipe_name)
        _check_results(items, 3, 0)

        expected = [
            {
                "media:thumbnail": {
                    "url": "http://example.com/a.jpg",
                    "height": "",
                    "width": "",
                },
                "link": "http://example.com/test.php?this=that",
                "description": "b",
                "y:title": "a",
            },
            {
                "newtitle": "NEWTITLE",
                "loop:itembuilder": {
                    "description": {"content": "DESCRIPTION"},
                    "title": "NEWTITLE",
                },
                "title": "TITLE1",
            },
            {
                "newtitle": "NEWTITLE",
                "loop:itembuilder": {
                    "description": {"content": "DESCRIPTION"},
                    "title": "NEWTITLE",
                },
                "title": "TITLE2",
            },
        ]

        for pos, item in enumerate(items):
            assert is_mapping(item)

            for k, v in expected[pos].items():
                assert item.get(k) == v, f"expected {v=} at {pos=}, {k=}. Got\n{item=}"

    def test_union_just_other(self):
        """
        Loads a workflow containing a union with the first input unconnected.

        Also tests for empty source string and reference to 'y:id.value'.
        """
        pipe_name = "pipe_6e30c269a69baf92cd420900b0645f88"
        items = self._run_example(pipe_name)
        _check_results(items, 24, 0)

        first, last = items[0], items[-1]
        assert is_mapping(first)
        assert is_mapping(last)

        dates = _check_dates(first.get("pubDate"), last.get("pubDate"))
        assert dates[0] > dates[-1]
        assert first.get("y:id") == "http://sz.de/1.2104394"

        for item in items:
            assert is_mapping(item)
            link, title = item.get("link"), item.get("title")
            msg = f"expected 210 in {link} or Poroschenko: in {title}"
            assert ("210" in str(link)) or ("Poroschenko:" in str(title)), msg

    def test_stringtokenizer(self):
        """Loads a workflow containing a stringtokenizer."""
        pipe_name = "pipe_975789b47f17690a21e89b10a702bcbd"
        items = self._run_example(pipe_name)
        _check_results(items, 2, 0)
        contains = [{"title": "#hashtags"}, {"title": "#with"}]

        for item in contains:
            assert item in items

    @pytest.mark.parametrize(
        "pipe_name",
        [
            pytest.param("pipe_9420a757a49ddf11d8b98349abb5bcf4", id="plain"),
            pytest.param("pipe_188eca77fd28c96c559f71f5729d91ec", id="within-loop"),
        ],
    )
    def test_fetchpage(self, pipe_name):
        """Loads a workflow containing a fetchpage module (plain and within a loop)."""
        items = self._run_example(pipe_name)
        _check_results(items, 8, 0)
        item = items[2]
        assert is_mapping(item)
        assert item.get("content") == "$3.00</td>"

    def test_loop_example(self):
        """Loads the loop example workflow."""
        pipe_name = "pipe_dAI_R_FS3BG6fTKsAsqenA"
        items = self._run_example(pipe_name)
        _check_results(items, 1, 0)
        expected = (
            "THIS TSUNAMI ADVISORY IS FOR ALASKA/ BRITISH COLUMBIA/ "
            "WASHINGTON/ OREGON\n     AND CALIFORNIA ONLY (Severe)"
        )

        item = items[0]
        assert is_mapping(item)
        assert item.get("title") == expected
        assert item.get("pubDate")

    def test_namespaceless_xml_input(self):
        """Loads a workflow containing deep xml source with no namespace."""
        pipe_name = "pipe_402e244d09a4146cd80421c6628eb6d9"
        items = self._run_example(pipe_name)
        _check_results(items, 5, 1)
        contains = [
            "Gower to Anglesey",
            "The Riddle of the Tides",
            "Wales: Severn Bore",
        ]

        sliced = islice(items, 3)

        for item in sliced:
            assert is_mapping(item)
            assert item.get("title") in contains

    def test_urlbuilder_loop(self):
        """Loads a workflow containing a URL builder in a loop (offline)."""
        pipe_name = "pipe_e65397e116d7754da0dd23425f1f0af1"
        items = self._run_example(pipe_name)
        _check_results(items, 2, 0)

        chart_url = (
            "https://example.invalid/chart?cht=qr&chs=200x200"
            "&chl=https%3A%2F%2Fexample.invalid%2Fitem%2F1"
        )
        first = items[0]
        assert is_mapping(first)
        assert first.get("link") == "https://example.invalid/item/1"

        content = first.get("media:content")
        assert is_mapping(content)
        assert content.get("url") == chart_url
        assert str(first.get("description")).startswith(
            f'<img src="{chart_url}" alt="QRcode" /><br/>'
        )

    @pytest.mark.perf
    def test_createrss(self):
        """Loads a workflow containing rssitembuilder."""
        pipe_name = "pipe_a08134746e30a6dd3a7cb3c0cf098692"

        items = self._run_example(pipe_name)
        _check_results(items, 94, 0)
        url = "i.cdn.turner.com/cnn/.e/img/3.0/global/header/intl/CNNi_Logo_new.png"

        item = items[0]
        assert is_mapping(item)
        assert item == {
            "pubDate": "",
            "author": "",
            "description": f'<img src="http://{url}">',
            "y:id": "",
            "link": "/",
            "media:content": {
                "height": "65",
                "type": "",
                "url": f"http://{url}",
                "width": "213",
            },
            "media:thumbnail": {"height": "", "url": "", "width": ""},
            "y:title": "CNN",
        }

    #######################
    # Unimplemented modules
    #######################
    @pytest.mark.parametrize(("pipe_name", "module"), UNSUPPORTED_MODULES)
    def test_an_unimplemented_module_is_reported_by_name(self, pipe_name, module):
        with pytest.raises(UnsupportedModuleError, match=rf"\b{module}\b"):
            self._run_example(pipe_name)
