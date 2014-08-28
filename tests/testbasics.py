"""Unit tests using basic pipeline modules

   Note: many of these tests simply make sure the module compiles and runs
         - we need more extensive tests with stable data feeds!
"""

import unittest

from os import path as p, remove
from itertools import islice
from pipe2py.compile import parse_pipe_def, build_pipeline, stringify_pipe
from pipe2py.util import extract_modules
from pipe2py import Context

try:
    from json import loads
except (ImportError, AttributeError):
    from simplejson import loads


class TestBasics(unittest.TestCase):
    """Test a few sample pipelines

        Note: asserting post-conditions for these is almost impossible because
            many use live sources.

            See createtest.py for an attempt at creating a stable test-suite.
    """
    def _get_pipe_def(self, pipe_name):

        pipe_file_name = p.join(
            p.dirname(__file__), 'pipelines', '%s.json' % pipe_name)

        with open(pipe_file_name) as f:
            return loads(f.read())

    def _load(self, pipe_def, pipe_name, value=0, check=1):
        pipe = parse_pipe_def(pipe_def, pipe_name)
        pipeline = list(build_pipeline(self.context, pipe))
        length = len(pipeline)
        switch = {1: '>', -1: '<', 0: '=='}

        # compare pipeline length to baseline value
        # 1: length > value
        # -1: length < value
        # 0: length == value
        compared = cmp(length, value)

        print 'pipeline length %s %i, but expected %s %i.' % (
            switch.get(compared), value, switch.get(check), value)

        print 'Modules used in pipe %s: %s' % (
            pipe_name, extract_modules(pipe_def=pipe_def))

        # assert that pipeline length is as expected
        self.assertEqual(compared, check)

        return pipeline

    def setUp(self):
        """Compile common subpipe"""
        self.context = Context(test=True)
        pipe_name = 'pipe_2de0e4517ed76082dcddf66f7b218057'
        pipe_def = self._get_pipe_def(pipe_name)
        pipe = parse_pipe_def(pipe_def, pipe_name)

        with open("%s.py" % pipe_name, "w") as f:
            f.write(stringify_pipe(self.context, pipe))

    def tearDown(self):
        remove('pipe_2de0e4517ed76082dcddf66f7b218057.py')

    def test_feed(self):
        """Loads a simple test pipeline and compiles and executes it to check
            the results

            TODO: have these tests iterate over a number of test pipelines
        """
        pipe_name = 'testpipe1'
        pipe_def = self._get_pipe_def(pipe_name)
        pipeline = self._load(pipe_def, pipe_name)
        [self.assertIn('the', i.get('description')) for i in pipeline]

    def test_simplest(self):
        """Loads the RTW simple test pipeline and compiles and executes it to
            check the results
        """
        pipe_name = 'pipe_2de0e4517ed76082dcddf66f7b218057'
        pipe_def = self._get_pipe_def(pipe_name)
        self._load(pipe_def, pipe_name)

    def test_filtered_multiple_sources(self):
        """Loads the filter multiple sources pipeline and compiles and executes
            it to check the results
           Note: uses a subpipe pipe_2de0e4517ed76082dcddf66f7b218057
            (assumes its been compiled to a .py file - see test setUp)
        """
        pipe_name = 'pipe_c1cfa58f96243cea6ff50a12fc50c984'
        pipe_def = self._get_pipe_def(pipe_name)
        self._load(pipe_def, pipe_name)

    def test_urlbuilder(self):
        """Loads the RTW URL Builder test pipeline and compiles and executes it
            to check the results
        """
        pipe_name = 'pipe_e519dd393f943315f7e4128d19db2eac'
        pipe_def = self._get_pipe_def(pipe_name)
        self._load(pipe_def, pipe_name)

    def test_european_performance_cars(self):
        """Loads a pipeline containing a sort
        """
        pipe_name = 'pipe_8NMkiTW32xGvMbDKruymrA'
        pipe_def = self._get_pipe_def(pipe_name)
        self._load(pipe_def, pipe_name)

    # todo: need tests with single and mult-part key

    def test_reverse_truncate(self):
        """Loads a pipeline containing a reverse and truncate
        """
        pipe_name = 'pipe_58a53262da5a095fe7a0d6d905cc4db6'
        pipe_def = self._get_pipe_def(pipe_name)
        pipeline = self._load(pipe_def, pipe_name, 3, 0)
        prev_title = None

        for i in pipeline:
            self.assertTrue(not prev_title or i['title'] < prev_title)
            prev_title = i['title']

    def test_tail(self):
        """Loads a pipeline containing a tail
        """
        pipe_name = 'pipe_06c4c44316efb0f5f16e4e7fa4589ba2'
        pipe_def = self._get_pipe_def(pipe_name)
        self._load(pipe_def, pipe_name)

    def test_itembuilder(self):
        """Loads a pipeline containing an itembuilder
        """
        pipe_name = 'pipe_b96287458de001ad62a637095df33ad5'
        pipe_def = self._get_pipe_def(pipe_name)
        pipeline = self._load(pipe_def, pipe_name, 2, 0)
        contains = [
            {u'attrpath': {u'attr2': u'VAL2'}, u'ATTR1': u'VAL1'},
            {
                u'longpath': {u'attrpath': {u'attr3': u'val3'}},
                u'attrpath': {u'attr2': u'val2', u'attr3': u'extVal'},
                u'attr1': u'val1'
            }
        ]
        # print list(pipeline)
        # self.assertIn(contains[1], pipeline)
        [self.assertIn(item, pipeline) for item in contains]

    def test_rssitembuilder(self):
        """Loads a pipeline containing an rssitembuilder
        """
        pipe_name = 'pipe_1166de33b0ea6936d96808717355beaa'
        pipe_def = self._get_pipe_def(pipe_name)
        pipeline = self._load(pipe_def, pipe_name, 3, 0)
        contains = [
            {
                'media:thumbnail': {'url': u'http://example.com/a.jpg'},
                u'link': u'http://example.com/test.php?this=that',
                u'description': u'b', u'y:title': u'a', u'title': u'a'
            },
            {
                u'newtitle': u'NEWTITLE',
                u'loop:itembuilder': [
                    {
                        u'description': {u'content': u'DESCRIPTION'},
                        u'title': u'NEWTITLE',
                    }
                ],
                u'title': u'TITLE1',
            },
            {
                u'newtitle': u'NEWTITLE',
                u'loop:itembuilder': [
                    {
                        u'description': {u'content': u'DESCRIPTION'},
                        u'title': u'NEWTITLE',
                    }
                ],
                u'title': u'TITLE2',
            }
        ]

        [self.assertIn(item, pipeline) for item in contains]

    def test_csv(self):
        """Loads a pipeline containing a csv source
        """
        pipe_name = 'pipe_UuvYtuMe3hGDsmRgPm7D0g'
        pipe_def = self._get_pipe_def(pipe_name)
        pipeline = self._load(pipe_def, pipe_name)

        description = (
            u'Total allowances claimed, inc travel: '
            '151619<br>Total basic allowances claimed, ex travel: '
            '146282<br>Total Travel claimed: 5337<br>MP Mileage: '
            '3358<br>MP Rail Travel: 1473<br>MP Air Travel: 0<br>'
            'Cost of staying away from main home: 22541<br>London '
            'Supplement: 0<br>Office Running Costs: 19848<br>'
            'Staffing Costs: 88283'
        )

        contains = {
                u'FamilyNumOfJourneys': u'0',
                u'Member': u'Lancaster',
                u'MPOtherEuropean': u'0',
                u'FamilyTotal': u'0',
                u'OfficeRunningCosts': u'19848',
                u'MPOtherRail': u'233',
                u'CostofStayingAwayFromMainHome': u'22541',
                u'StationeryAssocdPostageCosts': u'3471',
                u'CommsAllowance': u'9767',
                u'Mileage': u'3358',
                u'MPMisc': u'20',
                u'title': u'Mr Mark Lancaster',
                u'description': description,
                u'TotalAllowancesClaimedIncTravel': u'151619',
                u'SpouseTotal': u'31',
                u'EmployeeTotal': u'222',
                u'MPRail': u'1473',
                u'LondonSupplement': u'0',
                u'StaffingCosts': u'88283',
                u'EmployeeNumOfJourneys': u'21',
                u'CentrallyPurchasedStationery': u'1149',
                u'TotalBasicAllowancesExcTravel': u'146282',
                u'CentralITProvision': u'1223',
                u'StaffCoverAndOtherCosts': u'0',
                u'firstName': u'Mr Mark',
                u'MPOtherAir': u'0',
                u'MPOtherMileage': u'0',
                u'TotalTravelClaimed': u'5337',
                u'MPAir': u'0',
                u'SpouseNumOfJourneys': u'1'
            }

        [self.assertEqual(contains, item) for item in pipeline]

    def test_describe_input(self):
        """Loads a pipeline but just gets the input requirements
        """
        self.context.describe_input = True
        pipe_name = 'pipe_5fabfc509a8e44342941060c7c7d0340'
        pipe_def = self._get_pipe_def(pipe_name)
        inputs = self._load(pipe_def, pipe_name)

        self.assertTrue(
            inputs, [
                (
                    u'', u'dateinput1', u'dateinput1', u'datetime',
                    u'10/14/2010'
                ),
                (
                    u'', u'locationinput1', u'locationinput1', u'location',
                    u'isle of wight, uk'
                ),
                (u'', u'numberinput1', u'numberinput1', u'number', u'12121'),
                (u'', u'privateinput1', u'privateinput1', u'text', u''),
                (
                    u'', u'textinput1', u'textinput1', u'text',
                    u'This is default text - is there debug text too?'
                ),
                (
                    u'', u'urlinput1', u'urlinput1', u'url',
                    u'http://example.com'
                )
            ]
        )

    def test_union_just_other(self):
        """Loads a pipeline containing a union with the first input unconnected
            Also tests for empty source string and reference to 'y:id.value'
        """
        pipe_name = 'pipe_6e30c269a69baf92cd420900b0645f88'
        pipe_def = self._get_pipe_def(pipe_name)
        self._load(pipe_def, pipe_name)

    # def test_submodule_loop(self):
    #     """Loads a pipeline containing a sub-module in a loop and passes
    #         input parameters. Also tests json fetch with nested list, assigns
    #         part of loop result, and regexes multi-part reference.

    #        Note: too slow
    #     """
    #     # todo: use small, fixed data set to restrict duration
    #     # Compile submodule to disk
    #     self.context = Context(test=True)
    #     pipe_name = 'pipe_bd0834cfe6cdacb0bea5569505d330b8'
    #     pipe_def = self._get_pipe_def(pipe_name)
    #     pipe = parse_pipe_def(pipe_def, pipe_name)

    #     try:
    #         with open("%s.py" % pipe_name, "w") as f:
    #             f.write(stringify_pipe(self.context, pipe))

    #         pipe_name = 'pipe_b3d43c00f9e1145ff522fb71ea743e99'
    #         pipe_def = self._get_pipe_def(pipe_name)
    #         pipeline = self._load(pipe_def, pipe_name)

    #         contains = u'Hywel Francis (University of Wales, Swansea (UWS))'
    #         # lots of data, so just check some of it
    #         sliced = islice(pipeline, 3)
    #         [self.assertEqual(item['title'], contains) for item in sliced]
    #     finally:
    #         remove("%s.py" % pipe_name)

    def test_loops_1(self):
        """Loads a pipeline containing a loop
        """
        pipe_name = 'pipe_125e9fe8bb5f84526d21bebfec3ad116'
        pipe_def = self._get_pipe_def(pipe_name)
        pipeline = self._load(pipe_def, pipe_name, 1, 0)
        base = 'http://ajax.googleapis.com/ajax/services/language/detect'
        contains = {
            u'description': None, u'language': None,
            u'language-url': base + '?q=Guten+Tag&v=1.0',
            u'title': u'Guten Tag'
        }

        [self.assertEqual(item, contains) for item in pipeline]

    def test_feeddiscovery(self):
        """Loads a pipeline containing a feed auto-discovery module plus
            fetch-feed in a loop with emit all
        """
        pipe_name = 'pipe_HrX5bjkv3BGEp9eSy6ky6g'
        pipe_def = self._get_pipe_def(pipe_name)
        self._load(pipe_def, pipe_name)

    def test_stringtokeniser(self):
        """Loads a pipeline containing a stringtokeniser
        """
        pipe_name = 'pipe_975789b47f17690a21e89b10a702bcbd'
        pipe_def = self._get_pipe_def(pipe_name)
        pipeline = self._load(pipe_def, pipe_name, 2, 0)
        contains = [{u'title': u'#hashtags'}, {u'title': u'#with'}]
        # print list(pipeline)
        [self.assertIn(item, pipeline) for item in contains]

    def test_fetchsitefeed(self):
        """Loads a pipeline containing a fetchsitefeed module
        """
        pipe_name = 'pipe_551507461cbcb19a828165daad5fe007'
        pipe_def = self._get_pipe_def(pipe_name)
        self._load(pipe_def, pipe_name)

    def test_fetchpage(self):
        """Loads a pipeline containing a fetchpage module
        """
        pipe_name = 'pipe_9420a757a49ddf11d8b98349abb5bcf4'
        pipe_def = self._get_pipe_def(pipe_name)
        self._load(pipe_def, pipe_name)

    def test_fetchpage_loop(self):
        """Loads a pipeline containing a fetchpage module within a loop
        """
        pipe_name = 'pipe_188eca77fd28c96c559f71f5729d91ec'
        pipe_def = self._get_pipe_def(pipe_name)
        self._load(pipe_def, pipe_name)

    def test_split(self):
        """Loads an example pipeline containing a split module
        """
        pipe_name = 'pipe_QMrlL_FS3BGlpwryODY80A'
        pipe_def = self._get_pipe_def(pipe_name)
        self._load(pipe_def, pipe_name)

    def test_simplemath_1(self):
        """Loads a pipeline containing simplemath
        """
        pipe_name = 'pipe_zKJifuNS3BGLRQK_GsevXg'  # empty feed
        pipe_def = self._get_pipe_def(pipe_name)
        self._load(pipe_def, pipe_name, check=0)

    # todo: test simplemath - divide by zero and check/implement yahoo handling
    # todo: test malformed pipeline syntax
    # todo: test pipe compilation (compare output against expected .py file)

##############
# Failing Tests
##############
    # # failing
    # def test_twitter(self):
    #     """Loads a pipeline containing a loop, complex regex etc. for twitter
    #     """
    #     pipe_file = 'pipe_ac45e9eb9b0174a4e53f23c4c9903c3f.json'
    #     pipe_def = self._get_pipe_def(pipe_file)
    #     pipe = parse_and_build_pipe(self.context, pipe_def)
    #     # todo: check the data!
    #     self.assertTrue(len(list(pipe)) > 0)

    # # failing
    # def test_xpathfetchpage_1(self):
    #     """Loads a pipeline containing xpathfetchpage
    #     """
    #     pipe_file = 'pipe_a08134746e30a6dd3a7cb3c0cf098692.json'
    #     pipe_def = self._get_pipe_def(pipe_file)
    #     pipe = parse_and_build_pipe(self.context, pipe_def)

    #     try:
    #         self.assertTrue(len(list(pipe)) > 0)
    #         [self.assertTrue('title' in i) for i in pipe]
    #     except ImportError:
    #         pass  #ignore in case lxml not installed

    # # failing
    # def test_yql(self):
    #     """Loads a pipeline containing a yql query
    #     """
    #     pipe_name = 'pipe_80fb3dfc08abfa7e27befe9306fc3ded'
    #     pipe_def = self._get_pipe_def(pipe_name)
    #     pipeline = self._load(pipe_def, pipe_name)
    #     [self.assertEqual(i['title'], i['a']['content']) for i in pipeline]

##############
# Broken Tests
##############
    # # Note: this test will be skipped for now
    # # - it requires a TermExtractor module which isn't top of the list
    # def test_simpletagger(self):
    #     """Loads the RTW simple tagger pipeline and compiles and executes it
    #          to check the results
    #         Note: uses a subpipe pipe_2de0e4517ed76082dcddf66f7b218057
    #         (assumes its been compiled to a .py file - see test setUp)
    #     """
    #     pipe_file = 'pipe_93abb8500bd41d56a37e8885094c8d10.json'
    #     pipe_def = self._get_pipe_def(pipe_file)
    #     pipe = parse_and_build_pipe(self.context, pipe_def)

    #     # todo: check the data!
    #     count = 0
    #     for i in pipe:
    #         count += 1

    #     self.assertTrue(count > 0)

    # # removed: dead link
    # def test_urlbuilder_loop(self):
    #     """Loads a pipeline containing a URL builder in a loop
    #     """
    #     pipe_file = 'pipe_e65397e116d7754da0dd23425f1f0af1.json'
    #     pipe_def = self._get_pipe_def(pipe_file)
    #     pipe = parse_and_build_pipe(self.context, pipe_def)
    #     # todo: check the data!
    #     self.assertTrue(len(list(pipe)) > 0)

    # # removed: dead link
    # def test_complex_datebuilding(self):
    #     """Loads a pipeline containing a datebuilder with complex inputs
    #     """
    #     pipe_file = 'pipe_bd9c0c9793ccaec7582b19f45e24f2e6.json'
    #     pipe_def = self._get_pipe_def(pipe_file)
    #     pipe = parse_and_build_pipe(self.context, pipe_def)
    #     # todo: check the data!
    #     self.assertTrue(len(list(pipe)) > 0)

    # # removed: dead link
    # def test_twitter_caption_search(self):
    #     """Loads the Twitter Caption Search pipeline and compiles and
    #         executes it to check the results
    #     """
    #     pipe_file = 'pipe_eb3e27f8f1841835fdfd279cd96ff9d8.json'
    #     pipe_def = self._get_pipe_def(pipe_file)
    #     pipe = parse_and_build_pipe(self.context, pipe_def)

    #     # todo: check the data!
    #     count = 0
    #     for i in pipe:
    #         count += 1

    #     self.assertTrue(count > 0)

    # # removed: 'dc:creator' missing
    # def test_unique(self):
    #     """Loads a pipeline containing a unique
    #     """
    #     pipe_file = 'pipe_1I75yiUv3BGhgVWjjUnRlg.json'
    #     pipe_def = self._get_pipe_def(pipe_file)
    #     pipe = parse_and_build_pipe(self.context, pipe_def)

    #     # todo: check the data! e.g. pubdate etc.
    #     creators = set()
    #     for i in pipe:
    #         if i.get('dc:creator') in creators:
    #             self.fail()
    #         creators.add(i.get('dc:creator'))

    # # removed: dead link
    # def test_loop_example(self):
    #     """Loads the loop example pipeline and compiles and executes it to
    #         check the results
    #     """
    #     pipe_file = 'pipe_dAI_R_FS3BG6fTKsAsqenA.json'
    #     pipe_def = self._get_pipe_def(pipe_file)
    #     pipe = parse_and_build_pipe(self.context, pipe_def)

    #     # todo: check the data! e.g. pubdate etc.
    #     count = 0
    #     for i in pipe:
    #         count += 1

    #     self.assertTrue(count == 1)
    #     self.assertEqual(
    #         i['title'],
    #         'THIS TSUNAMI ADVISORY IS FOR ALASKA/ BRITISH COLUMBIA/ '
    #         "WASHINGTON/OREGON\nAND CALIFORNIA ONLY\n(Severe)"
    #     )

    # # removed: data too unstable: get a local copy
    # def test_namespaceless_xml_input(self):
    #     """Loads a pipeline containing deep xml source with no namespace
    #     """
    #     pipe_file = 'pipe_402e244d09a4146cd80421c6628eb6d9.json'
    #     pipe_def = self._get_pipe_def(pipe_file)
    #     pipe = parse_and_build_pipe(self.context, pipe_def)

    #     count = 0
    #     match = 0
    #     for i in pipe:
    #         count += 1
    #         t = i['title']
    #         if t == 'Lands End to Porthcawl':
    #             match += 1
    #         if t == 'Brittany':
    #             match += 1
    #         if t == 'Ravenscar to Hull':
    #             match += 1
    #         if t == 'East Coast - Smugglers, Alum and Scarborough Bay':
    #             match += 1
    #         if t == "Swanage to Land's End":
    #             match += 1
    #         if t == 'Heart of the British Isles - A Grand Tour':
    #             match += 1

    #     self.assertTrue(count == 5)
    #     self.assertTrue(match == 5)

if __name__ == '__main__':
    unittest.main()
