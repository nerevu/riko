"""Tests basic pipeline module usage

    Note: many of these tests simply make sure the module compiles and runs.
    We need more extensive tests with stable data feeds!
"""

from decimal import Decimal

from json import loads
from os import path as p, remove
from importlib import import_module
from itertools import islice
from riko.compile import parse_pipe_def, build_pipeline, stringify_pipe
from riko.types import Item, Items, PipelineDependencies, SyncPipeline
from riko.utils import extract_dependencies
from riko import Context, get_path

COMPARISONS = {Decimal('1'): ">", Decimal('-1'): "<", Decimal('0'): "=="}


class TestBasics:
    """Test a few sample pipelines"""

    def _get_pipeline(self, pipe_name) -> list[Item]:
        try:
            module = import_module(f"tests.pypipelines.{pipe_name}")
        except ImportError:
            parent = p.dirname(__file__)
            pipe_file_name = p.join(parent, "pipelines", f"{pipe_name}.json")

            with open(pipe_file_name) as f:
                pipe_def = loads(f.read())

            parsed_pipe_def = parse_pipe_def(pipe_def, pipe_name)
            stream = build_pipeline(parsed_pipe_def, pipe_def, context=self.context)
        else:
            pipeline: SyncPipeline = getattr(module, pipe_name)
            stream = pipeline(context=self.context)

        return list(stream)

    def _load(self, items: Items, pipe_name, value=0, check=1):
        _check = Decimal(check)
        length = len(items)
        compared = Decimal(length).compare(value)

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

        if compared != _check:
            actual, desired = COMPARISONS[compared], COMPARISONS[_check]
            msg = f"pipeline length {actual} {value}, but expected {desired} {value}."
            print(msg)

        print(f"Modules used in {pipe_name}: {pydeps}")
        assert compared == check

    def setup_method(self):
        """Compile common subpipe"""
        kwargs = {
            "test": True,
            "describe_input": False,
            "describe_dependencies": False,
        }

        self.context = Context(**kwargs)





    ##############
    # Online Tests
    ##############
    def test_feeddiscovery(self):
        """Loads a pipeline containing a feed auto-discovery module plus
        fetch-feed in a loop with emit all
        """
        pipe_name = "pipe_HrX5bjkv3BGEp9eSy6ky6g"
        items = self._get_pipeline(pipe_name)
        self._load(items, pipe_name)

    def test_fetchsitefeed(self):
        """Loads a pipeline containing a fetchsitefeed module"""
        pipe_name = "pipe_551507461cbcb19a828165daad5fe007"
        items = self._get_pipeline(pipe_name)
        self._load(items, pipe_name)

    def test_loops_1(self):
        """Loads a pipeline containing a loop"""
        pipe_name = "pipe_125e9fe8bb5f84526d21bebfec3ad116"
        items = self._get_pipeline(pipe_name)
        self._load(items, pipe_name, 1, 0)

        assert items[0]["info"]["login"] == "defunkt"
        assert items[0]["info"]["user_view_type"] == "public"
        assert items[0]["description"] == "public"

    def test_urlbuilder(self):
        """Loads the RTW URL Builder test pipeline and compiles and executes it
        to check the results
        """
        pipe_name = "pipe_e519dd393f943315f7e4128d19db2eac"
        items = self._get_pipeline(pipe_name)
        self._load(items, pipe_name)

    def test_input_override(self):
        """Loads a pipeline with input override"""
        self.context.inputs = {"textinput1": "IBM"}
        pipe_name = "pipe_1LNyRuNS3BGdkTKaAsqenA"
        items = self._get_pipeline(pipe_name)
        self._load(items, pipe_name)
        sliced = islice(items, 3)
        contains = self.context.inputs["textinput1"]
        # check if the ticker is in the title of any of the first 3 items
        assert contains in " ".join(item["title"] for item in sliced)

    ###############
    # Offline Tests
    ###############
    def test_kazeeki(self):
        """Loads the kazeeki simple test pipeline"""
        pipe_name = "pipe_kazeeki"
        items = self._get_pipeline(pipe_name)
        self._load(items, pipe_name)

        example = {
            "author": {"name": None, "uri": None},
            "dc:creator": None,
            "id": 474310371,
            "k:author": "Homepage for a germansocial organization",
            "k:budget": 125.0,
            "k:budget_converted": 125.0,
            "k:budget_converted_w_sym": "$125.00",
            "k:budget_full": "$125.00",
            "k:budget_raw": "0 - $250",
            "k:budget_raw1": "0",
            "k:budget_raw1_code": "",
            "k:budget_raw1_num": "0",
            "k:budget_raw1_sym": "",
            "k:budget_raw2": "$250",
            "k:budget_raw2_code": "",
            "k:budget_raw2_num": "250",
            "k:budget_raw2_sym": "$",
            "k:budget_sym": "$",
            "k:budget_w_sym": "$125.00",
            "k:client_location": "unknown",
            "k:content": " With this specification sheet we want to give you a request for implementing a website for a german...",
            "k:cur_code": "USD",
            "k:due": "unknown",
            "k:job_type": "fixed",
            "k:job_type_code": "1",
            "k:marketplace": "guru.com",
            "k:posted": "time.struct_time(tm_year=2015, tm_mon=1, tm_mday=6, tm_hour=17, tm_min=13, tm_sec=47, tm_wday=1, tm_yday=6, tm_isdst=0)",
            "k:rate": 1.0,
            "k:submissions": "unknown",
            "k:tags": [{"content": "IT"}, {"content": "Software"}, {"content": "Web"}],
            "k:work_location": " Worldwide",
            "link": "http://www.guru.com/jobs/homepage-for-a-germansocial-organization/1099595",
            "links": [{}],
            "loop:strregex": "fixed",
            "pubDate": "time.struct_time(tm_year=2015, tm_mon=1, tm_mday=6, tm_hour=17, tm_min=13, tm_sec=47, tm_wday=1, tm_yday=6, tm_isdst=0)",
            "summary": "<span><b>Description:</b> With this specification sheet we want to give you a request for implementing a website for a german...<br><b>Category:</b> Web, Software &amp; IT<br><b>Required skills:</b> html, php<br><b>Fixed Price budget:</b> Under $250<br><b>Job type:</b> Public<br><b>Freelancer Location:</b> Worldwide<br></span>",
            "title": "Homepage for a germansocial organization",
            "updated": "Tue, 06 Jan 2015 17:13:47 GMT",
            "updated_parsed": "time.struct_time(tm_year=2015, tm_mon=1, tm_mday=6, tm_hour=17, tm_min=13, tm_sec=47, tm_wday=1, tm_yday=6, tm_isdst=0)",
            "y:id": "http://www.guru.com/jobs/homepage-for-a-germansocial-organization/1099595",
        }

        assert example == items[0]

    def test_feed(self):
        """Loads a simple test pipeline and compiles and executes it to check
        the results

        TODO: have these tests iterate over a number of test pipelines
        """
        pipe_name = "pipe_testpipe1"
        items = self._get_pipeline(pipe_name)
        self._load(items, pipe_name)

        for i in items:
            assert "the" in i["description"]

    def test_european_performance_cars(self):
        """Loads a pipeline containing a sort"""
        pipe_name = "pipe_8NMkiTW32xGvMbDKruymrA"
        items = self._get_pipeline(pipe_name)
        self._load(items, pipe_name)

    # todo: need tests with single and mult-part key

    def test_reverse_truncate(self):
        """Loads a pipeline containing a reverse and truncate"""
        pipe_name = "pipe_58a53262da5a095fe7a0d6d905cc4db6"
        items = self._get_pipeline(pipe_name)
        self._load(items, pipe_name, 3, 0)
        prev_title = None

        for i in items:
            assert not prev_title or i["title"] < prev_title
            prev_title = i["title"]

    def test_tail(self):
        """Loads a pipeline containing a tail"""
        pipe_name = "pipe_06c4c44316efb0f5f16e4e7fa4589ba2"
        items = self._get_pipeline(pipe_name)
        self._load(items, pipe_name)

    def test_itembuilder(self):
        """Loads a pipeline containing an itembuilder"""
        pipe_name = "pipe_b96287458de001ad62a637095df33ad5"
        items = self._get_pipeline(pipe_name)
        self._load(items, pipe_name, 2, 0)

        contains = [
            {"attrpath": {"attr2": "VAL2"}, "ATTR1": "VAL1"},
            {
                "longpath": {"attrpath": {"attr3": "val3"}},
                "attrpath": {"attr2": "val2", "attr3": "extVal"},
                "attr1": "val1",
            },
        ]

        for item in contains:
            assert item in items

    def test_rssitembuilder(self):
        """Loads a pipeline containing an rssitembuilder"""
        pipe_name = "pipe_1166de33b0ea6936d96808717355beaa"
        items = self._get_pipeline(pipe_name)
        self._load(items, pipe_name, 3, 0)

        contains = [
            {
                "media:thumbnail": {"url": "http://example.com/a.jpg"},
                "link": "http://example.com/test.php?this=that",
                "description": "b",
                "y:title": "a",
                "title": "a",
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

        for item in contains:
            assert item in items

    def test_csv(self):
        """Loads a pipeline containing a csv source"""
        pipe_name = "pipe_UuvYtuMe3hGDsmRgPm7D0g"
        items = self._get_pipeline(pipe_name)
        self._load(items, pipe_name)

        description = (
            "Total allowances claimed, inc travel: "
            "151619<br>Total basic allowances claimed, ex travel: "
            "146282<br>Total Travel claimed: 5337<br>MP Mileage: "
            "3358<br>MP Rail Travel: 1473<br>MP Air Travel: 0<br>"
            "Cost of staying away from main home: 22541<br>London "
            "Supplement: 0<br>Office Running Costs: 19848<br>"
            "Staffing Costs: 88283"
        )

        contains = {
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
            assert contains == item

    def test_describe_input(self):
        """Loads a pipeline but just gets the input requirements"""
        self.context.describe_input = True
        pipe_name = "pipe_5fabfc509a8e44342941060c7c7d0340"
        items = self._get_pipeline(pipe_name)
        self._load(items, pipe_name)
        assert items == [
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

    def test_describe_dependencies(self):
        self.context.describe_dependencies = True
        pipe_name = "pipe_5fabfc509a8e44342941060c7c7d0340"
        items = self._get_pipeline(pipe_name)
        self._load(items, pipe_name)
        assert items == [
            "dateinput",
            "locationinput",
            "numberinput",
            "output",
            "privateinput",
            "rssitembuilder",
            "textinput",
            "urlinput",
        ]

    def test_describe_both(self):
        """Loads a pipeline but just gets the input requirements"""
        self.context.describe_input = True
        self.context.describe_dependencies = True
        pipe_name = "pipe_5fabfc509a8e44342941060c7c7d0340"
        items = self._get_pipeline(pipe_name)
        self._load(items, pipe_name)

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
            "dateinput",
            "locationinput",
            "numberinput",
            "privateinput",
            "rssitembuilder",
            "input",
            "urlinput",
        ]

        assert items == [{"inputs": inputs, "dependencies": dependencies}]

    def test_union_just_other(self):
        """Loads a pipeline containing a union with the first input unconnected
        Also tests for empty source string and reference to 'y:id.value'
        """
        pipe_name = "pipe_6e30c269a69baf92cd420900b0645f88"
        items = self._get_pipeline(pipe_name)
        self._load(items, pipe_name)

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
        self._load(items, pipe_name)

    def test_fetchpage_loop(self):
        """Loads a pipeline containing a fetchpage module within a loop"""
        pipe_name = "pipe_188eca77fd28c96c559f71f5729d91ec"
        items = self._get_pipeline(pipe_name)
        self._load(items, pipe_name)

    def test_split(self):
        """Loads an example pipeline containing a split module"""
        pipe_name = "pipe_QMrlL_FS3BGlpwryODY80A"
        items = self._get_pipeline(pipe_name)
        self._load(items, pipe_name)

    def test_simplemath_1(self):
        """Loads a pipeline containing simplemath"""
        pipe_name = "pipe_zKJifuNS3BGLRQK_GsevXg"  # empty feed
        items = self._get_pipeline(pipe_name)
        self._load(items, pipe_name, check=0)

    def test_twitter_caption_search(self):
        """Loads the Twitter Caption Search pipeline and compiles and
        executes it to check the results
        """
        pipe_name = "pipe_eb3e27f8f1841835fdfd279cd96ff9d8"
        items = self._get_pipeline(pipe_name)
        self._load(items, pipe_name)

    def test_loop_example(self):
        """Loads the loop example pipeline and compiles and executes it to
        check the results
        """
        pipe_name = "pipe_dAI_R_FS3BG6fTKsAsqenA"
        items = self._get_pipeline(pipe_name)
        self._load(items, pipe_name, value=1, check=0)
        contains = (
            "THIS TSUNAMI ADVISORY IS FOR ALASKA/ BRITISH COLUMBIA/ "
            "WASHINGTON/ OREGON\n            AND CALIFORNIA ONLY (Severe)"
        )

        # todo: check the data! e.g. pubdate etc.
        for item in items:
            assert contains == item["title"]

    def test_namespaceless_xml_input(self):
        """Loads a pipeline containing deep xml source with no namespace"""
        pipe_name = "pipe_402e244d09a4146cd80421c6628eb6d9"
        items = self._get_pipeline(pipe_name)
        self._load(items, pipe_name, value=5, check=1)
        contains = [
            "Gower to Anglesey",
            "The Riddle of the Tides",
            "Wales: Severn Bore",
        ]

        sliced = islice(items, 3)

        for item in sliced:
            assert item["title"] in contains

    # # need to compile
    # def test_yql(self):
    #     """Loads a pipeline containing a yql query
    #     """
    #     pipe_name = 'pipe_ea463d94cd7c63ea003d9b1d0589d9df'
    #     items = self._get_pipeline(pipe_name)
    #     self._load(items, pipe_name)
    #     [self.assertEqual(i['title'], i['a']['content']) for i in items]
    #
    # todo: test simplemath - divide by zero and check/implement yahoo handling
    # todo: test malformed pipeline syntax
    # todo: move these tests to the module doc blocks so each module is tested
    # individually
    # todo: test pipe compilation (compare output against expected .py file)
    #
    #
#######################
# Unimplemented modules
#######################
# # pipelocationbuilder module not yet implemented
# def test_submodule_loop(self):
#     """Loads a pipeline containing a sub-module in a loop and passes
#         input parameters. Also tests json fetch with nested list, assigns
#         part of loop result, and regexes multi-part reference.
#     """
#     pipe_name = 'pipe_b3d43c00f9e1145ff522fb71ea743e99'
#     items = self._get_pipeline(pipe_name)
#     self._load(items, pipe_name)
#     contains = u'Hywel Francis (University of Wales, Swansea (UWS))'
#     sliced = islice(items, 3)  # lots of data, so just check some of it
#     [self.assertEqual(item['title'], contains) for item in sliced]

# # TermExtractor module not yet implemented
# def test_simpletagger(self):
#     """Loads the RTW simple tagger pipeline and compiles and executes it
#          to check the results
#     """
#     pipe_name = 'pipe_93abb8500bd41d56a37e8885094c8d10'
#     items = self._get_pipeline(pipe_name)
#     self._load(items, pipe_name)

###############
# Failing Tests
###############
# # needs twitter api authentication
# # need to compile
# def test_twitter(self):
#     """Loads a pipeline containing a loop, complex regex etc. for twitter
#     """
#     pipe_name = 'pipe_21a90f8ebdba0265c136861a49cf3d93'
#     items = self._get_pipeline(pipe_name)
#     self._load(items, pipe_name)

# # need to fix xpath
# def test_xpathfetchpage_1(self):
#     """Loads a pipeline containing xpathfetchpage
#     """
#     pipe_name = 'pipe_a08134746e30a6dd3a7cb3c0cf098692'
#     items = self._get_pipeline(pipe_name)
#     self._load(items, pipe_name)
#     [self.assertIn(i, 'title') for i in pipe]

# # dead link, need to find a new data source
# def test_urlbuilder_loop(self):
#     """Loads a pipeline containing a URL builder in a loop
#     """
#     pipe_name = 'pipe_e65397e116d7754da0dd23425f1f0af1'
#     items = self._get_pipeline(pipe_name)
#     self._load(items, pipe_name)
