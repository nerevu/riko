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

def setup_module():
    """site initialization"""
    global initialized
    initialized = True
    print('Basic Module Setup\n')


class TestExamples:
    def __init__(self):
        self.cls_initialized = False

    def _get_pipeline(self, pipe_name):
        module = import_module('examples.%s' % pipe_name)
        pipe_generator = getattr(module, pipe_name)
        pipeline = getattr(module, pipe_name)(test=True)
        return list(pipeline)

    def test_kazeeki(self):
        """Tests the kazeeki pipeline
        """
        pipe_name = 'pipe_kazeeki'
        pipeline = self._get_pipeline(pipe_name)

        example = {
            u'author': {u'name': None, u'uri': None},
            u'id': 2761769956L,
            u'k:author': u'unknown',
            u'k:budget': Decimal('0'),
            u'k:budget_converted': Decimal('0.000000'),
            u'k:budget_converted_w_sym': u'$0.00',
            u'k:budget_full': u'$0.00',
            u'k:budget_w_sym': u'$0.00',
            u'k:client_location': u'Cambodia',
            u'k:content': u'We are looking for freelancers ( individuals and companies ) who offer their services related to Architecture Walkthrough and 3D animations. Please consider this job as a potential to several more and a long term relationship.   We are a Media...',
            u'k:cur_code': u'USD',
            u'k:due': u' Thu, 05 Feb 2015 11:46:40 EST',
            u'k:job_type': u'2',
            u'k:marketplace': u'elance.com',
            u'k:parsed_type': u'fixed',
            u'k:posted': u'Tue, 06 Jan 2015 11:46:40 EST',
            u'k:rate': Decimal('1.000000'),
            u'k:submissions': u'0',
            u'k:tags': [
                {u'content': u'animation'},
                {u'content': u'design'},
                {u'content': u'multimedia'}],
            u'k:work_location': u'unknown',
            u'link': u'https://www.elance.com/j/3d-architecture-walkthrough-3d-animation-artists/66963214/',
            u'links': [{}],
            u'title': u'3D Architecture Walkthrough &amp; 3D / Animation Artists '}

        length = len(pipeline)
        msg = 'Pipeline %s has length %i, not 1'
        nt.assert_equal(length, 180, msg % (pipe_name, length))
        nt.assert_equal(example, pipeline[-1])

    def test_gigs(self):
        """Tests the gigs pipeline
        """
        pipe_name = 'pipe_gigs'
        pipeline = self._get_pipeline(pipe_name)

        example = {
            u'description': u'<b>Description:</b> Need a to port our existing iOS App to Android. Actually it is as good as writing a new Android app...<br><b>Category:</b> Web, Software & IT<br><b>Required skills:</b> android, sqlite<br><b>Fixed Price budget:</b> $250-$500<br><b>Project type:</b> Public<br><b>Freelancer Location:</b> India<br>',
            u'guid': u'http://www.guru.com/jobs/educational-android-app/1058980',
            u'link': u'http://www.guru.com/jobs/educational-android-app/1058980',
            u'pubDate': u'Tue, 05 Aug 2014 09:35:28 GMT',
            u'title': u'Educational Android App',
            u'y:id': {
                u'permalink': u'false',
                u'value': u'http://www.guru.com/jobs/educational-android-app/1058980'},
            u'y:published': {
                u'day': u'5',
                u'day_name': u'Tuesday',
                u'day_of_week': u'2',
                u'day_ordinal_suffix': u'th',
                u'hour': u'9',
                u'minute': u'35',
                u'month': u'8',
                u'month_name': u'August',
                u'second': u'28',
                u'timezone': u'UTC',
                u'utime': u'1407231328',
                u'year': u'2014'},
            u'y:repeatcount': u'1',
            u'y:title': u'Educational Android App'}

        length = len(pipeline)
        msg = 'Pipeline %s has length %i, not 1'
        nt.assert_equal(length, 49, msg % (pipe_name, length))
        nt.assert_equal(example, pipeline[-1])

    def test_simple1(self):
        """Tests the simple1 pipeline
        """
        pipe_name = 'pipe_simple1'
        pipeline = self._get_pipeline(pipe_name)
        length = len(pipeline)
        msg = 'Pipeline %s has length %i, not 1'
        nt.assert_equal(length, 1, msg % (pipe_name, length))
        nt.assert_equal({u'url': u'farechart'}, pipeline[-1])

    def test_simple2(self):
        """Tests the simple2 pipeline
        """
        pipe_name = 'pipe_simple2'
        pipeline = self._get_pipeline(pipe_name)
        example = {u'author': u'ABC', u'link': u'www.google.com', u'title': u'google'}
        length = len(pipeline)
        msg = 'Pipeline %s has length %i, not 1'
        nt.assert_equal(length, 1, msg % (pipe_name, length))
        nt.assert_equal(example, pipeline[-1])

    def test_split(self):
        """Tests the split pipeline
        """
        pipe_name = 'pipe_split'
        pipeline = self._get_pipeline(pipe_name)
        example = {u'date': 'December 02, 2014', u'year': 2014}
        length = len(pipeline)
        msg = 'Pipeline %s has length %i, not 1'
        nt.assert_equal(length, 1, msg % (pipe_name, length))
        nt.assert_equal(example, pipeline[-1])

    def test_wired(self):
        """Tests the wired pipeline
        """
        pipe_name = 'pipe_wired'
        pipeline = self._get_pipeline(pipe_name)
        length = len(pipeline)
        msg = 'Pipeline %s has length %i, not 1'
        nt.assert_equal(length, 1, msg % (pipe_name, length))
        nt.assert_equal({u'date': 'May 04, 1982'}, pipeline[-1])
