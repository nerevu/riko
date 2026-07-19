"""
Tests basic pipeline module usage

Note: many of these tests simply make sure the module compiles and runs.
We need more extensive tests with stable data feeds!
"""

from collections.abc import Sequence
from decimal import Decimal
from importlib import import_module
from itertools import islice
from json import loads
from os import path as p
from typing import cast

import pytest

from riko import Context, get_path, listize
from riko.compile import build_pipeline, parse_pipe_def
from riko.types.general import ParserOutput, PipelineDependencies, SyncPipeParser
from riko.types.values import StreamState
from riko.utils import extract_dependencies, truncate_content

COMPARISONS = {Decimal(1): ">", Decimal(-1): "<", Decimal(0): "=="}


class TestBasics:
    """Test a few sample pipelines"""

    def _get_pipeline(
        self, pipe_name: str
    ) -> list[ParserOutput | dict[str, StreamState]]:
        try:
            module = import_module(f"tests.pypipelines.{pipe_name}")
        except ImportError as e:
            print(f"Couldn't import module for {pipe_name}: {e}. Building from json...")
            parent = p.dirname(__file__)
            pipe_file_name = p.join(parent, "pipelines", f"{pipe_name}.json")

            with open(pipe_file_name) as f:
                pipe_def = loads(f.read())

            parsed_pipe_def = parse_pipe_def(pipe_def, pipe_name)
            stream = build_pipeline(parsed_pipe_def, pipe_def, context=self.context)
        else:
            pipeline: SyncPipeParser = getattr(module, pipe_name)
            stream = pipeline(context=self.context)

        return list(listize(stream))

    def _load(
        self,
        items: Sequence[ParserOutput | dict[str, StreamState]],
        pipe_name,
        value=0,
        check=1,
    ):
        _check = Decimal(check)
        compared = Decimal(len(items)).compare(Decimal(value))

        try:
            module = import_module(f"tests.pypipelines.{pipe_name}")
        except ImportError:
            parent = p.dirname(__file__)
            pipe_file_name = p.join(parent, "pipelines", f"{pipe_name}.json")

            with open(pipe_file_name) as f:
                pipe_def = loads(f.read())

            pydeps = extract_dependencies(pipe_def)
        else:
            pipeline: PipelineDependencies = getattr(module, pipe_name)
            pydeps = extract_dependencies(pipeline=pipeline)

        assert pydeps, f"Expected to find dependencies for {pipe_name}, but got none."
        actual, desired = COMPARISONS[compared], COMPARISONS[_check]
        msg = f"pipeline length {actual} {value}, but expected {desired} {value}. Got "

        try:
            first = items[0]
        except IndexError:
            msg += f"{type(items)=}"
        else:
            msg += f"{len(items)} items. First item is {truncate_content(first)}"

        assert compared == _check, msg

    def setup_method(self):
        """Compile common subpipe"""
        kwargs = {"test": True, "describe_input": False, "describe_dependencies": False}

        self.context = Context(**kwargs)
        # pipe_name = "pipe_2de0e4517ed76082dcddf66f7b218057"
        # parent = p.dirname(__file__)
        # pipe_file_name = p.join(parent, f"pipelines", f"{pipe_name}.json")

        # with open(pipe_file_name) as f:
        #     pipe_def = loads(f.read())

        # parsed_pipe_def = parse_pipe_def(pipe_def, pipe_name)
        # pipe_file_name = p.join(parent, "pypipelines", f"{pipe_name}.py")

        # with open(pipe_file_name, "w") as f:
        #     f.write(stringify_pipe(parsed_pipe_def, pipe_def, context=self.context))
        #     self.context.describe_input = False
        #     self.context.describe_dependencies = False

    # def teardown_method(self):
    #     pipe_name = "pipe_2de0e4517ed76082dcddf66f7b218057"
    #     parent = p.dirname(__file__)
    #     pipe_file_name = p.join(parent, "pypipelines", f"{pipe_name}.py")
    #     remove(pipe_file_name)

    ##############
    # Online Tests
    ##############
    def test_feeddiscovery(self):
        """
        Loads a pipeline containing a feed auto-discovery module plus
        fetch-feed in a loop with emit all
        """
        pipe_name = "pipe_HrX5bjkv3BGEp9eSy6ky6g"
        items = self._get_pipeline(pipe_name)
        self._load(items, pipe_name, 25, 0)
        item = cast(dict, items[0])
        assert item["link"].startswith("https://edition.cnn.com/webview/politics")

    def test_fetchsitefeed(self):
        """Loads a pipeline containing a fetchsitefeed module"""
        pipe_name = "pipe_551507461cbcb19a828165daad5fe007"
        items = self._get_pipeline(pipe_name)
        self._load(items, pipe_name, 1, 1)
        item = cast(dict, items[0])
        assert item["title"]
        assert item["summary"]

    def test_loops_1(self):
        """Loads a pipeline containing a loop"""
        pipe_name = "pipe_125e9fe8bb5f84526d21bebfec3ad116"
        items = self._get_pipeline(pipe_name)
        self._load(items, pipe_name, 1, 0)

        item = cast(dict, items[0])
        assert item["info"]["login"] == "defunkt"
        assert item["info"]["user_view_type"] == "public"
        assert item["description"] == "public"

    def test_urlbuilder(self):
        """
        Loads the RTW URL Builder test pipeline and compiles and executes it
        to check the results
        """
        pipe_name = "pipe_e519dd393f943315f7e4128d19db2eac"
        items = self._get_pipeline(pipe_name)
        self._load(items, pipe_name, 63, 0)
        item = cast(dict, items[0])
        assert "The 6 Best Enterprise Data Modeling Tools" in item["title"]

    def test_input_override(self):
        """Overrides an offline input->itembuilder pipeline via Context.inputs"""
        self.context.inputs = {"textinput1": "IBM"}
        pipe_name = "input_override"
        items = self._get_pipeline(pipe_name)
        self._load(items, pipe_name, 1, 0)
        assert items == [{"symbol": "IBM"}]

    ###############
    # Offline Tests
    ###############
    def test_kazeeki1(self):
        """Loads the kazeeki simple test pipeline."""
        pipe_name = "pipe_kazeeki1"
        items = self._get_pipeline(pipe_name)
        self._load(items, pipe_name, 5, 0)

        example = {
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

        item = cast(dict, items[0])

        for k, v in example.items():
            assert item.get(k) == v, f"Expected {v} for key {k}, but got {item.get(k)}"

        assert item["k:content"].startswith(" With this specification sheet we")
        assert item["k:content"].endswith("for implementing a website for a german...")

    def test_kazeeki2(self):
        """Loads the kazeeki simple test pipeline."""
        pipe_name = "pipe_kazeeki2"
        items = self._get_pipeline(pipe_name)
        self._load(items, pipe_name, 1, 0)

        example = {
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

        item = cast(dict, items[0])

        for k, v in example.items():
            assert item.get(k) == v, f"Expected {v} for key {k}, but got {item.get(k)}"

        assert item["k:content"].startswith("<p>Hello, I need to fix an application")
        assert item["k:content"].endswith("are welcome to this project.<br><br><b>")

    def test_kazeeki_full(self):
        """Loads the kazeeki simple test pipeline."""
        pipe_name = "pipe_kazeeki_full"
        items = self._get_pipeline(pipe_name)
        self._load(items, pipe_name, 5, 0)

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

        item = cast(dict, items[0])

        for k, v in example.items():
            assert item.get(k) == v, f"Expected {v} for key {k}, but got {item.get(k)}"

        assert item["summary"].startswith("<span><b>Description:</b> With this spe")
        assert item["summary"].endswith("ancer Location:</b> Worldwide<br></span>")

    def test_simplest(self):
        """
        Loads the RTW simple test pipeline and compiles and executes it to
        check the results
        """
        pipe_name = "pipe_2de0e4517ed76082dcddf66f7b218057"
        items = self._get_pipeline(pipe_name)
        self._load(items, pipe_name, 17, 0)
        item = cast(dict, items[0])
        assert item["title"].startswith("Running “Native” Data Wrangling Applicati")

    def test_feed(self):
        """
        Loads a simple test pipeline and compiles and executes it to check
        the results

        TODO: have these tests iterate over a number of test pipelines
        """
        pipe_name = "pipe_testpipe1"
        items = self._get_pipeline(pipe_name)
        self._load(items, pipe_name, 4, 0)

        for i in items:
            item = cast(dict, i)
            assert "the" in item["summary"]

    # Not compiled
    @pytest.mark.skip
    def test_filtered_multiple_sources(self):
        """
        Loads the filter multiple sources pipeline and compiles and executes
         it to check the results
        Note: uses a subpipe pipe_2de0e4517ed76082dcddf66f7b218057
         (assumes its been compiled to a .py file - see test setUp)
        """
        pipe_name = "pipe_c1cfa58f96243cea6ff50a12fc50c984"
        items = self._get_pipeline(pipe_name)
        self._load(items, pipe_name, 63, 0)
        assert items[0] == "test"

    def test_european_performance_cars(self):
        """Loads a pipeline containing a sort"""
        pipe_name = "pipe_8NMkiTW32xGvMbDKruymrA"
        items = self._get_pipeline(pipe_name)
        self._load(items, pipe_name, 26, 0)
        first, last = cast(dict, items[0]), cast(dict, items[-1])
        assert first["pubDate"] > last["pubDate"]

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

        for i in items:
            item = cast(dict, i)
            msg = f"Expected one of {cars} in summary, but got {item['summary']}"
            assert any(car in item["summary"].lower() for car in cars), msg

    # todo: need tests with single and mult-part key
    def test_reverse_truncate(self):
        """Loads a pipeline containing a reverse and truncate"""
        pipe_name = "pipe_58a53262da5a095fe7a0d6d905cc4db6"
        items = self._get_pipeline(pipe_name)
        self._load(items, pipe_name, 3, 0)
        prev_title = None

        for i in items:
            item = cast(dict, i)
            assert not prev_title or item["title"] < prev_title
            prev_title = item["title"]

    def test_tail(self):
        """Loads a pipeline containing a tail"""
        pipe_name = "pipe_06c4c44316efb0f5f16e4e7fa4589ba2"
        items = self._get_pipeline(pipe_name)
        self._load(items, pipe_name, 5, 0)
        item = cast(dict, items[0])
        assert "American woman is being held hostage" in item["title"]

    def test_itembuilder(self):
        """Loads a pipeline containing an itembuilder"""
        pipe_name = "pipe_b96287458de001ad62a637095df33ad5"
        items = self._get_pipeline(pipe_name)
        self._load(items, pipe_name, 2, 0)

        expected = [
            {
                "attr1": "val1",
                "attrpath": {"attr2": "val2", "attr3": "extVal"},
                "longpath": {"attrpath": {"attr3": "val3"}},
            },
            {"attrpath": {"attr2": "VAL2"}, "ATTR1": "VAL1"},
        ]

        for pos, item in enumerate(items):
            assert item == expected[pos]

    # FIXME: need a test with a real feed and more stable data
    @pytest.mark.skip
    def test_rssitembuilder(self):
        """Loads a pipeline containing an rssitembuilder"""
        pipe_name = "pipe_1166de33b0ea6936d96808717355beaa"
        items = self._get_pipeline(pipe_name)
        self._load(items, pipe_name, 3, 0)

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
                "loop:itembuilder": [
                    {
                        "description": {"content": "DESCRIPTION"},
                        "title": "NEWTITLE",
                    }
                ],
                "title": "TITLE1",
            },
            {
                "newtitle": "NEWTITLE",
                "loop:itembuilder": [
                    {
                        "description": {"content": "DESCRIPTION"},
                        "title": "NEWTITLE",
                    }
                ],
                "title": "TITLE2",
            },
        ]

        for pos, i in enumerate(items):
            item = cast(dict, i)
            for k, v in expected[pos].items():
                assert item.get(k) == v, f"expected {v=} at {pos=}, {k=}. Got\n{item=}"

    def test_csv(self):
        """Loads a pipeline containing a csv source"""
        pipe_name = "pipe_UuvYtuMe3hGDsmRgPm7D0g"
        items = self._get_pipeline(pipe_name)
        self._load(items, pipe_name, 1, 0)

        description = (
            "Total allowances claimed, inc travel: "
            "151619<br>Total basic allowances claimed, ex travel: "
            "146282<br>Total Travel claimed: 5337<br>MP Mileage: "
            "3358<br>MP Rail Travel: 1473<br>MP Air Travel: 0<br>"
            "Cost of staying away from main home: 22541<br>London "
            "Supplement: 0<br>Office Running Costs: 19848<br>"
            "Staffing Costs: 88283"
        )

        expected = {
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
            "description": description,
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

        for item in items:
            assert item == expected

    def test_describe_input(self):
        """Loads a pipeline but just gets the input requirements"""
        self.context.describe_input = True
        pipe_name = "pipe_5fabfc509a8e44342941060c7c7d0340"
        items = self._get_pipeline(pipe_name)
        self._load(items, pipe_name, 6, 0)

        expected = [
            ("", "dateinput1", "dateinput1", "datetime", "10/14/2010"),
            (
                "",
                "locationinput1",
                "locationinput1",
                "location",
                "isle of wight, uk",
            ),
            ("", "numberinput1", "numberinput1", "number", "12121"),
            ("", "privateinput1", "privateinput1", "text", ""),
            (
                "",
                "textinput1",
                "textinput1",
                "text",
                "This is default text - is there debug text too?",
            ),
            ("", "urlinput1", "urlinput1", "url", get_path("example.html")),
        ]

        for pos, item in enumerate(items):
            assert item == expected[pos]

    def test_describe_dependencies(self):
        self.context.describe_dependencies = True
        pipe_name = "pipe_5fabfc509a8e44342941060c7c7d0340"
        items = self._get_pipeline(pipe_name)
        self._load(items, pipe_name, 3, 0)
        assert items == [
            "input",
            "output",
            "rssitembuilder",
        ]

    def test_describe_both(self):
        """Loads a pipeline but just gets the input requirements"""
        self.context.describe_input = True
        self.context.describe_dependencies = True
        pipe_name = "pipe_5fabfc509a8e44342941060c7c7d0340"
        items = self._get_pipeline(pipe_name)
        self._load(items, pipe_name, 1, 0)

        inputs = [
            ("", "dateinput1", "dateinput1", "datetime", "10/14/2010"),
            ("", "locationinput1", "locationinput1", "location", "isle of wight, uk"),
            ("", "numberinput1", "numberinput1", "number", "12121"),
            ("", "privateinput1", "privateinput1", "text", ""),
            (
                "",
                "textinput1",
                "textinput1",
                "text",
                "This is default text - is there debug text too?",
            ),
            ("", "urlinput1", "urlinput1", "url", get_path("example.html")),
        ]

        dependencies = [
            "input",
            "output",
            "rssitembuilder",
        ]

        item = cast(dict, items[0])
        assert item["inputs"] == inputs
        assert item["dependencies"] == dependencies

    def test_union_just_other(self):
        """
        Loads a pipeline containing a union with the first input unconnected
        Also tests for empty source string and reference to 'y:id.value'
        """
        pipe_name = "pipe_6e30c269a69baf92cd420900b0645f88"
        items = self._get_pipeline(pipe_name)
        self._load(items, pipe_name, 24, 0)

        first, last = cast(dict, items[0]), cast(dict, items[-1])
        assert first["pubDate"] > last["pubDate"]
        assert first["y:id"] == "http://sz.de/1.2104394"

        for i in items:
            item = cast(dict, i)
            msg = "expected 210 in {link} or Poroschenko: in {title}".format(**item)
            assert ("210" in item["link"]) or ("Poroschenko:" in item["title"]), msg

    def test_stringtokeniser(self):
        """Loads a pipeline containing a stringtokeniser"""
        pipe_name = "pipe_975789b47f17690a21e89b10a702bcbd"
        items = self._get_pipeline(pipe_name)
        self._load(items, pipe_name, 2, 0)
        contains = [{"title": "#hashtags"}, {"title": "#with"}]

        for item in contains:
            assert item in items

    def test_fetchpage(self):
        """Loads a pipeline containing a fetchpage module"""
        pipe_name = "pipe_9420a757a49ddf11d8b98349abb5bcf4"
        items = self._get_pipeline(pipe_name)
        self._load(items, pipe_name, 8, 0)
        item = cast(dict, items[2])
        assert item["content"] == "$3.00</td>"

    def test_fetchpage_loop(self):
        """Loads a pipeline containing a fetchpage module within a loop"""
        pipe_name = "pipe_188eca77fd28c96c559f71f5729d91ec"
        items = self._get_pipeline(pipe_name)
        self._load(items, pipe_name, 8, 0)
        item = cast(dict, items[2])
        assert item["content"] == "$3.00</td>"

    def test_split(self):
        """Loads an example pipeline containing a split module"""
        pipe_name = "pipe_QMrlL_FS3BGlpwryODY80A"
        items = self._get_pipeline(pipe_name)
        self._load(items, pipe_name, 7, 0)
        item = cast(dict, items[0])
        assert (
            item["title"] == "[Drugs] Ebola: Questions, answers about an unproven drug"
        )

    def test_simplemath_1(self):
        """Loads a pipeline containing simplemath"""
        pipe_name = "pipe_zKJifuNS3BGLRQK_GsevXg"
        items = self._get_pipeline(pipe_name)
        self._load(items, pipe_name, 4, 0)
        item = cast(dict, items[0])
        assert item["title"] == "Open researcher open course"

    def test_twitter_caption_search(self):
        """
        Loads the Twitter Caption Search pipeline and compiles and
        executes it to check the results
        """
        pipe_name = "pipe_eb3e27f8f1841835fdfd279cd96ff9d8"
        items = self._get_pipeline(pipe_name)
        self._load(items, pipe_name, 3, 0)
        item = cast(dict, items[0])
        assert item["ctime"] == "&time=00:01:41&time="

    def test_loop_example(self):
        """
        Loads the loop example pipeline and compiles and executes it to
        check the results
        """
        pipe_name = "pipe_dAI_R_FS3BG6fTKsAsqenA"
        items = self._get_pipeline(pipe_name)
        self._load(items, pipe_name, 1, 0)
        expected = (
            "THIS TSUNAMI ADVISORY IS FOR ALASKA/ BRITISH COLUMBIA/ "
            "WASHINGTON/ OREGON\n     AND CALIFORNIA ONLY (Severe)"
        )

        item = cast(dict, items[0])
        assert item["title"] == expected
        assert item["pubDate"]

    def test_namespaceless_xml_input(self):
        """Loads a pipeline containing deep xml source with no namespace"""
        pipe_name = "pipe_402e244d09a4146cd80421c6628eb6d9"
        items = self._get_pipeline(pipe_name)
        self._load(items, pipe_name, 5, 1)
        contains = [
            "Gower to Anglesey",
            "The Riddle of the Tides",
            "Wales: Severn Bore",
        ]

        sliced = islice(items, 3)

        for i in sliced:
            item = cast(dict, i)
            assert item["title"] in contains

    # FIXME
    @pytest.mark.skip
    def test_xpathfetchpage_1(self):
        """
        Loads a pipeline containing xpathfetchpage
        """
        pipe_name = "pipe_a08134746e30a6dd3a7cb3c0cf098692"
        items = self._get_pipeline(pipe_name)
        self._load(items, pipe_name, 63, 0)

        for i in items:
            item = cast(dict, i)
            assert "title" in item

    # FIXME
    @pytest.mark.skip
    def test_urlbuilder_loop(self):
        """
        Loads a pipeline containing a URL builder in a loop
        """
        pipe_name = "pipe_e65397e116d7754da0dd23425f1f0af1"
        items = self._get_pipeline(pipe_name)
        self._load(items, pipe_name, 63, 0)
        assert items[0] == "test"

    # todo: test simplemath - divide by zero and check/implement yahoo handling
    # todo: test malformed pipeline syntax
    # todo: move these tests to the module doc blocks so each module is tested
    # individually
    # todo: test pipe compilation (compare output against expected .py file)

    #######################
    # Unimplemented modules
    #######################
    @pytest.mark.skip
    def test_yql(self):
        """
        Loads a pipeline containing a yql query
        """
        pipe_name = "pipe_ea463d94cd7c63ea003d9b1d0589d9df"
        items = self._get_pipeline(pipe_name)
        self._load(items, pipe_name, 63, 0)

        for i in items:
            item = cast(dict, i)
            assert item["title"]
            assert item["a"]["content"]

    # pipelocationbuilder module not yet implemented
    @pytest.mark.skip
    def test_submodule_loop(self):
        """
        Loads a pipeline containing a sub-module in a loop and passes
        input parameters. Also tests json fetch with nested list, assigns
        part of loop result, and regexes multi-part reference.
        """
        pipe_name = "pipe_b3d43c00f9e1145ff522fb71ea743e99"
        items = self._get_pipeline(pipe_name)
        self._load(items, pipe_name, 63, 0)
        contains = "Hywel Francis (University of Wales, Swansea (UWS))"

        for i in islice(items, 3):  # lots of data, so just check some of it
            item = cast(dict, i)
            assert item["title"] == contains

    # TermExtractor module not yet implemented
    @pytest.mark.skip
    def test_simpletagger(self):
        """
        Loads the RTW simple tagger pipeline and compiles and executes it
        to check the results
        """
        pipe_name = "pipe_93abb8500bd41d56a37e8885094c8d10"
        items = self._get_pipeline(pipe_name)
        self._load(items, pipe_name, 63, 0)
        assert items[0] == "test"

    ###############
    # Failing Tests
    ###############
    # needs twitter api authentication
    # need to compile
    @pytest.mark.skip
    def test_twitter(self):
        """
        Loads a pipeline containing a loop, complex regex etc. for twitter
        """
        pipe_name = "pipe_21a90f8ebdba0265c136861a49cf3d93"
        items = self._get_pipeline(pipe_name)
        self._load(items, pipe_name, 63, 0)
        assert items[0] == "test"
