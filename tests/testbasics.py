"""Unit tests using basic pipeline modules

    Note: many of these tests simply make sure the module compiles and runs.
    We need more extensive tests with stable data feeds!
"""

import unittest

from os import path as p, remove
from importlib import import_module
from itertools import islice
from pipe2py.compile import parse_pipe_def, build_pipeline, stringify_pipe
from pipe2py.util import extract_dependencies
from pipe2py import Context

try:
    from json import loads
except (ImportError, AttributeError):
    from simplejson import loads


class TestBasics(unittest.TestCase):
    """Test a few sample pipelines
    """
    def _get_pipeline(self, pipe_name):
        try:
            module = import_module('tests.pypipelines.%s' % pipe_name)
        except ImportError:
            parent = p.dirname(__file__)
            pipe_file_name = p.join(parent, 'pipelines', '%s.json' % pipe_name)

            with open(pipe_file_name) as f:
                pipe_def = loads(f.read())

            pipe = parse_pipe_def(pipe_def, pipe_name)
            pipeline = build_pipeline(self.context, pipe, pipe_def)
        else:
            pipe_generator = getattr(module, pipe_name)
            pipeline = pipe_generator(self.context)

        return list(pipeline)

    def _load(self, pipeline, pipe_name, value=0, check=1):
        length = len(pipeline)
        switch = {1: '>', -1: '<', 0: '=='}

        # compare pipeline length to baseline value and obtain the following
        # result
        # 1 if length > value
        # -1 if length < value
        # 0 if length == value
        compared = cmp(length, value)

        try:
            module = import_module('tests.pypipelines.%s' % pipe_name)
        except ImportError:
            parent = p.dirname(__file__)
            pipe_file_name = p.join(parent, 'pipelines', '%s.json' % pipe_name)

            with open(pipe_file_name) as f:
                pjson = f.read()

            pydeps = extract_dependencies(loads(pjson))
        else:
            pipe_generator = getattr(module, pipe_name)
            pydeps = extract_dependencies(pipe_generator=pipe_generator)

        print 'pipeline length %s %i, but expected %s %i.' % (
            switch.get(compared), value, switch.get(check), value)

        print 'Modules used in %s: %s' % (pipe_name, pydeps)

        # assert that pipeline length is as expected
        return self.assertEqual(compared, check)

    def setUp(self):
        """Compile common subpipe"""
        kwargs = {
            'test': True,
            'describe_input': True,
            'describe_dependencies': True,
        }

        self.context = Context(**kwargs)
        pipe_name = 'pipe_2de0e4517ed76082dcddf66f7b218057'
        parent = p.dirname(__file__)
        pipe_file_name = p.join(parent, 'pipelines', '%s.json' % pipe_name)

        with open(pipe_file_name) as f:
            pipe_def = loads(f.read())

        pipe = parse_pipe_def(pipe_def, pipe_name)
        parent = p.dirname(p.dirname(__file__))
        pipe_file_name = p.join(
            parent, 'pipe2py', 'pypipelines', '%s.py' % pipe_name)

        with open(pipe_file_name, 'w') as f:
            f.write(stringify_pipe(self.context, pipe, pipe_def))
            self.context.describe_input = False
            self.context.describe_dependencies = False

    def tearDown(self):
        pipe_name = 'pipe_2de0e4517ed76082dcddf66f7b218057'
        parent = p.dirname(p.dirname(__file__))
        pipe_file_name = p.join(
            parent, 'pipe2py', 'pypipelines', '%s.py' % pipe_name)

        remove(pipe_file_name)

##############
# Online Tests
##############
    def test_feeddiscovery(self):
        """Loads a pipeline containing a feed auto-discovery module plus
            fetch-feed in a loop with emit all
        """
        pipe_name = 'pipe_HrX5bjkv3BGEp9eSy6ky6g'
        pipeline = self._get_pipeline(pipe_name)
        self._load(pipeline, pipe_name)

    def test_fetchsitefeed(self):
        """Loads a pipeline containing a fetchsitefeed module
        """
        pipe_name = 'pipe_551507461cbcb19a828165daad5fe007'
        pipeline = self._get_pipeline(pipe_name)
        self._load(pipeline, pipe_name)

    def test_loops_1(self):
        """Loads a pipeline containing a loop
        """
        pipe_name = 'pipe_125e9fe8bb5f84526d21bebfec3ad116'
        pipeline = self._get_pipeline(pipe_name)
        self._load(pipeline, pipe_name, 1, 0)
        base = 'http://ajax.googleapis.com/ajax/services/language/detect'
        contains = {
            u'description': None, u'language': None,
            u'language-url': base + '?q=Guten+Tag&v=1.0',
            u'title': u'Guten Tag'
        }

        [self.assertEqual(item, contains) for item in pipeline]

    def test_urlbuilder(self):
        """Loads the RTW URL Builder test pipeline and compiles and executes it
            to check the results
        """
        pipe_name = 'pipe_e519dd393f943315f7e4128d19db2eac'
        pipeline = self._get_pipeline(pipe_name)
        self._load(pipeline, pipe_name)

###############
# Offline Tests
###############
    def test_simplest(self):
        """Loads the RTW simple test pipeline and compiles and executes it to
            check the results
        """
        pipe_name = 'pipe_2de0e4517ed76082dcddf66f7b218057'
        pipeline = self._get_pipeline(pipe_name)
        self._load(pipeline, pipe_name)

    def test_feed(self):
        """Loads a simple test pipeline and compiles and executes it to check
            the results

            TODO: have these tests iterate over a number of test pipelines
        """
        pipe_name = 'pipe_testpipe1'
        pipeline = self._get_pipeline(pipe_name)
        self._load(pipeline, pipe_name)
        [self.assertIn('the', i.get('description')) for i in pipeline]

    def test_filtered_multiple_sources(self):
        """Loads the filter multiple sources pipeline and compiles and executes
            it to check the results
           Note: uses a subpipe pipe_2de0e4517ed76082dcddf66f7b218057
            (assumes its been compiled to a .py file - see test setUp)
        """
        pipe_name = 'pipe_c1cfa58f96243cea6ff50a12fc50c984'
        pipeline = self._get_pipeline(pipe_name)
        self._load(pipeline, pipe_name)

    def test_european_performance_cars(self):
        """Loads a pipeline containing a sort
        """
        pipe_name = 'pipe_8NMkiTW32xGvMbDKruymrA'
        pipeline = self._get_pipeline(pipe_name)
        self._load(pipeline, pipe_name)

    # todo: need tests with single and mult-part key

    def test_reverse_truncate(self):
        """Loads a pipeline containing a reverse and truncate
        """
        pipe_name = 'pipe_58a53262da5a095fe7a0d6d905cc4db6'
        pipeline = self._get_pipeline(pipe_name)
        self._load(pipeline, pipe_name, 3, 0)
        prev_title = None

        for i in pipeline:
            self.assertTrue(not prev_title or i['title'] < prev_title)
            prev_title = i['title']

    def test_tail(self):
        """Loads a pipeline containing a tail
        """
        pipe_name = 'pipe_06c4c44316efb0f5f16e4e7fa4589ba2'
        pipeline = self._get_pipeline(pipe_name)
        self._load(pipeline, pipe_name)

    def test_itembuilder(self):
        """Loads a pipeline containing an itembuilder
        """
        pipe_name = 'pipe_b96287458de001ad62a637095df33ad5'
        pipeline = self._get_pipeline(pipe_name)
        self._load(pipeline, pipe_name, 2, 0)

        contains = [
            {u'attrpath': {u'attr2': u'VAL2'}, u'ATTR1': u'VAL1'},
            {
                u'longpath': {u'attrpath': {u'attr3': u'val3'}},
                u'attrpath': {u'attr2': u'val2', u'attr3': u'extVal'},
                u'attr1': u'val1'
            }
        ]

        [self.assertIn(item, pipeline) for item in contains]

    def test_rssitembuilder(self):
        """Loads a pipeline containing an rssitembuilder
        """
        pipe_name = 'pipe_1166de33b0ea6936d96808717355beaa'
        pipeline = self._get_pipeline(pipe_name)
        self._load(pipeline, pipe_name, 3, 0)

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
        pipeline = self._get_pipeline(pipe_name)
        self._load(pipeline, pipe_name)

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
        pipeline = self._get_pipeline(pipe_name)
        self._load(pipeline, pipe_name)
        self.assertEqual(
            pipeline, [
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
                    u'file://data/example.html'
                )
            ]
        )

    def test_describe_dependencies(self):
        """Loads a pipeline but just gets the input requirements
        """
        self.context.describe_dependencies = True
        pipe_name = 'pipe_5fabfc509a8e44342941060c7c7d0340'
        pipeline = self._get_pipeline(pipe_name)
        self._load(pipeline, pipe_name)
        self.assertEqual(
            pipeline, [
                'pipedateinput',
                'pipelocationinput',
                'pipenumberinput',
                'pipeoutput',
                'pipeprivateinput',
                'piperssitembuilder',
                'pipetextinput',
                'pipeurlinput'
            ]
        )

    def test_describe_both(self):
        """Loads a pipeline but just gets the input requirements
        """
        self.context.describe_input = True
        self.context.describe_dependencies = True
        pipe_name = 'pipe_5fabfc509a8e44342941060c7c7d0340'
        pipeline = self._get_pipeline(pipe_name)
        self._load(pipeline, pipe_name)

        inputs = [
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
                u'file://data/example.html'
            )
        ]

        dependencies = [
            'pipedateinput',
            'pipelocationinput',
            'pipenumberinput',
            'pipeoutput',
            'pipeprivateinput',
            'piperssitembuilder',
            'pipetextinput',
            'pipeurlinput'
        ]

        self.assertEqual(
            pipeline, [{u'inputs': inputs, 'dependencies': dependencies}])

    def test_input_override(self):
        """Loads a pipeline with input override
        """
        self.context.inputs = {'textinput1': 'IBM'}
        pipe_name = 'pipe_1LNyRuNS3BGdkTKaAsqenA'
        pipeline = self._get_pipeline(pipe_name)
        self._load(pipeline, pipe_name)
        sliced = islice(pipeline, 3)
        contains = self.context.inputs['textinput1']
        # check if the ticker is in the title of any of the first 3 items
        self.assertIn(contains, ' '.join(item['title'] for item in sliced))

    def test_union_just_other(self):
        """Loads a pipeline containing a union with the first input unconnected
            Also tests for empty source string and reference to 'y:id.value'
        """
        pipe_name = 'pipe_6e30c269a69baf92cd420900b0645f88'
        pipeline = self._get_pipeline(pipe_name)
        self._load(pipeline, pipe_name)

    def test_stringtokeniser(self):
        """Loads a pipeline containing a stringtokeniser
        """
        pipe_name = 'pipe_975789b47f17690a21e89b10a702bcbd'
        pipeline = self._get_pipeline(pipe_name)
        self._load(pipeline, pipe_name, 2, 0)
        contains = [{u'title': u'#hashtags'}, {u'title': u'#with'}]
        [self.assertIn(item, pipeline) for item in contains]

    def test_fetchpage(self):
        """Loads a pipeline containing a fetchpage module
        """
        pipe_name = 'pipe_9420a757a49ddf11d8b98349abb5bcf4'
        pipeline = self._get_pipeline(pipe_name)
        self._load(pipeline, pipe_name)

    def test_fetchpage_loop(self):
        """Loads a pipeline containing a fetchpage module within a loop
        """
        pipe_name = 'pipe_188eca77fd28c96c559f71f5729d91ec'
        pipeline = self._get_pipeline(pipe_name)
        self._load(pipeline, pipe_name)

    def test_split(self):
        """Loads an example pipeline containing a split module
        """
        pipe_name = 'pipe_QMrlL_FS3BGlpwryODY80A'
        pipeline = self._get_pipeline(pipe_name)
        self._load(pipeline, pipe_name)

    def test_simplemath_1(self):
        """Loads a pipeline containing simplemath
        """
        pipe_name = 'pipe_zKJifuNS3BGLRQK_GsevXg'  # empty feed
        pipeline = self._get_pipeline(pipe_name)
        self._load(pipeline, pipe_name, check=0)

    def test_twitter_caption_search(self):
        """Loads the Twitter Caption Search pipeline and compiles and
            executes it to check the results
        """
        pipe_name = 'pipe_eb3e27f8f1841835fdfd279cd96ff9d8'
        pipeline = self._get_pipeline(pipe_name)
        self._load(pipeline, pipe_name)

    def test_loop_example(self):
        """Loads the loop example pipeline and compiles and executes it to
            check the results
        """
        pipe_name = 'pipe_dAI_R_FS3BG6fTKsAsqenA'
        pipeline = self._get_pipeline(pipe_name)
        self._load(pipeline, pipe_name, value=1, check=0)
        contains = (
            'THIS TSUNAMI ADVISORY IS FOR ALASKA/ BRITISH COLUMBIA/ '
            'WASHINGTON/ OREGON\n            AND CALIFORNIA ONLY (Severe)'
        )

        # todo: check the data! e.g. pubdate etc.
        [self.assertEqual(contains, item['title']) for item in pipeline]

    def test_namespaceless_xml_input(self):
        """Loads a pipeline containing deep xml source with no namespace
        """
        pipe_name = 'pipe_402e244d09a4146cd80421c6628eb6d9'
        pipeline = self._get_pipeline(pipe_name)
        self._load(pipeline, pipe_name, value=5, check=1)
        contains = [
            'Gower to Anglesey',
            'The Riddle of the Tides',
            'Wales: Severn Bore',
        ]

        sliced = islice(pipeline, 3)
        [self.assertIn(item['title'], contains) for item in sliced]

    # # need to compile
    # def test_yql(self):
    #     """Loads a pipeline containing a yql query
    #     """
    #     pipe_name = 'pipe_ea463d94cd7c63ea003d9b1d0589d9df'
    #     pipeline = self._get_pipeline(pipe_name)
    #     self._load(pipeline, pipe_name)
    #     [self.assertEqual(i['title'], i['a']['content']) for i in pipeline]

    # todo: test simplemath - divide by zero and check/implement yahoo handling
    # todo: test malformed pipeline syntax
    # todo: move these tests to the module doc blocks so each module is tested
    # individually
    # todo: test pipe compilation (compare output against expected .py file)

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
    #     pipeline = self._get_pipeline(pipe_name)
    #     self._load(pipeline, pipe_name)
    #     contains = u'Hywel Francis (University of Wales, Swansea (UWS))'
    #     sliced = islice(pipeline, 3)  # lots of data, so just check some of it
    #     [self.assertEqual(item['title'], contains) for item in sliced]

    # # TermExtractor module not yet implemented
    # def test_simpletagger(self):
    #     """Loads the RTW simple tagger pipeline and compiles and executes it
    #          to check the results
    #     """
    #     pipe_name = 'pipe_93abb8500bd41d56a37e8885094c8d10'
    #     pipeline = self._get_pipeline(pipe_name)
    #     self._load(pipeline, pipe_name)

###############
# Failing Tests
###############
    # # needs twitter api authentication
    # # need to compile
    # def test_twitter(self):
    #     """Loads a pipeline containing a loop, complex regex etc. for twitter
    #     """
    #     pipe_name = 'pipe_21a90f8ebdba0265c136861a49cf3d93'
    #     pipeline = self._get_pipeline(pipe_name)
    #     self._load(pipeline, pipe_name)

    # # need to fix xpath
    # def test_xpathfetchpage_1(self):
    #     """Loads a pipeline containing xpathfetchpage
    #     """
    #     pipe_name = 'pipe_a08134746e30a6dd3a7cb3c0cf098692'
    #     pipeline = self._get_pipeline(pipe_name)
    #     self._load(pipeline, pipe_name)
    #     [self.assertIn(i, 'title') for i in pipe]

    # # dead link, need to find a new data source
    # def test_urlbuilder_loop(self):
    #     """Loads a pipeline containing a URL builder in a loop
    #     """
    #     pipe_name = 'pipe_e65397e116d7754da0dd23425f1f0af1'
    #     pipeline = self._get_pipeline(pipe_name)
    #     self._load(pipeline, pipe_name)


if __name__ == '__main__':
    unittest.main()
