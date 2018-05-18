# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
tests.test_examples
~~~~~~~~~~~~~~~~~~~

Provides example pipeline tests.
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

import nose.tools as nt

from importlib import import_module
from decimal import Decimal
from builtins import *  # noqa pylint: disable=unused-import


def setup_module():
    """site initialization"""
    global initialized
    initialized = True
    print('Basic Module Setup\n')


class TestExamples(object):
    def __init__(self):
        self.cls_initialized = False

    def _get_pipeline(self, pipe_name):
        module = import_module('examples.%s' % pipe_name)
        pipeline = module.pipe(test=True)
        return list(pipeline)

    def test_kazeeki(self):
        """Tests the kazeeki pipeline
        """
        pipe_name = 'kazeeki'
        pipeline = self._get_pipeline(pipe_name)
        example = {
            'description': (
                'We are looking for freelancers ( individuals and companies ) '
                'who offer their services related to Architecture Walkthrough '
                'and 3D animations. Please consider this job as a potential '
                'to several more and a long term relationship.   We are a '
                'Media'),
            'id': 'www.elance.com-66963214',
            'k:budget': Decimal('12.5'),
            'k:budget_full': '$12.50 / hr',
            'k:budget_w_sym': '$12.50',
            'k:categories': [
                {'content': 'animation'}, {'content': 'design & multimedia'}],
            'k:client_location': 'Cambodia',
            'k:cur_code': 'USD',
            'k:due': 'Thu, 05 Feb 2015 11:46:40 EST',
            'k:job_type': 'hourly',
            'k:num_jobs': '0',
            'k:per_awarded': '0%',
            'k:source': 'www.elance.com',
            'k:posted': 'Tue, 06 Jan 2015 11:46:40 EST',
            'k:submissions': '0',
            'k:tags': [
                {'content': '3d animation'},
                {'content': '3d modeling'},
                {'content': '3d rendering'},
                {'content': 'animation'},
                {'content': 'computer graphics'}],
            'k:tot_purchased': '$0',
            'link': (
                'https://www.elance.com/j/3d-architecture-walkthrough-3d-'
                'animation-artists/66963214/'),
            'title': (
                '3D Architecture Walkthrough &amp; 3D / Animation Artists')}

        expected = 180
        length = len(pipeline)
        msg = 'Pipeline %s has length %i, not %i'
        nt.assert_equal(length, expected, msg % (pipe_name, length, expected))
        nt.assert_equal(example, pipeline[-1])

    def test_gigs(self):
        """Tests the gigs pipeline
        """
        pipe_name = 'gigs'
        pipeline = self._get_pipeline(pipe_name)

        example = {
            'description': (
                '<b>Description:</b> Need a to port our existing iOS App to '
                'Android. Actually it is as good as writing a new Android '
                'app...<br><b>Category:</b> Web, Software & IT<br><b>Required '
                'skills:</b> android, sqlite<br><b>Fixed Price budget:</b> '
                '$250-$500<br><b>Project type:</b> Public<br><b>Freelancer '
                'Location:</b> India<br>'),
            'guid': 'http://www.guru.com/jobs/educational-android-app/1058980',
            'link': 'http://www.guru.com/jobs/educational-android-app/1058980',
            'pubDate': 'Tue, 05 Aug 2014 09:35:28 GMT',
            'title': 'Educational Android App',
            'y:id': {
                'permalink': 'false',
                'value': (
                    'http://www.guru.com/jobs/educational-android-app/'
                    '1058980')},
            'y:published': {
                'day': '5',
                'day_name': 'Tuesday',
                'day_of_week': '2',
                'day_ordinal_suffix': 'th',
                'hour': '9',
                'minute': '35',
                'month': '8',
                'month_name': 'August',
                'second': '28',
                'timezone': 'UTC',
                'utime': '1407231328',
                'year': '2014'},
            'y:repeatcount': '1',
            'y:title': 'Educational Android App'}

        length = len(pipeline)
        msg = 'Pipeline %s has length %i, not 1'
        nt.assert_equal(length, 49, msg % (pipe_name, length))
        nt.assert_equal(example, pipeline[-1])

    def test_simple1(self):
        """Tests the simple1 pipeline
        """
        pipe_name = 'simple1'
        pipeline = self._get_pipeline(pipe_name)
        length = len(pipeline)
        msg = 'Pipeline %s has length %i, not 1'
        nt.assert_equal(length, 1, msg % (pipe_name, length))
        nt.assert_equal({'url': 'farechart'}, pipeline[-1])

    def test_simple2(self):
        """Tests the simple2 pipeline
        """
        pipe_name = 'simple2'
        pipeline = self._get_pipeline(pipe_name)
        example = {
            'author': 'ABC', 'link': 'www.google.com', 'title': 'google'}

        length = len(pipeline)
        msg = 'Pipeline %s has length %i, not 1'
        nt.assert_equal(length, 1, msg % (pipe_name, length))
        nt.assert_equal(example, pipeline[-1])

    def test_split(self):
        """Tests the split pipeline
        """
        pipe_name = 'split'
        pipeline = self._get_pipeline(pipe_name)
        example = {'date': 'December 02, 2014', 'year': 2014}
        length = len(pipeline)
        msg = 'Pipeline %s has length %i, not 1'
        nt.assert_equal(length, 1, msg % (pipe_name, length))
        nt.assert_equal(example, pipeline[-1])

    def test_wired(self):
        """Tests the wired pipeline
        """
        pipe_name = 'wired'
        pipeline = self._get_pipeline(pipe_name)
        length = len(pipeline)
        msg = 'Pipeline %s has length %i, not 1'
        nt.assert_equal(length, 1, msg % (pipe_name, length))
        nt.assert_equal({'date': 'May 04, 1982'}, pipeline[-1])
