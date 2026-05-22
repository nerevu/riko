# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
tests.test_examples
~~~~~~~~~~~~~~~~~~~

Provides example pipeline tests.
"""
from importlib import import_module
from decimal import Decimal

import pytest


class TestExamples(object):
    def _get_pipeline(self, pipe_name):
        module = import_module("examples.%s" % pipe_name)
        pipeline = module.pipe(test=True)
        return list(pipeline)

    def test_gigs(self):
        """Tests the gigs pipeline"""
        pipe_name = "gigs"
        pipeline = self._get_pipeline(pipe_name)

        example = {
            "description": (
                "<b>Description:</b> Need a to port our existing iOS App to "
                "Android. Actually it is as good as writing a new Android "
                "app...<br><b>Category:</b> Web, Software & IT<br><b>Required "
                "skills:</b> android, sqlite<br><b>Fixed Price budget:</b> "
                "$250-$500<br><b>Project type:</b> Public<br><b>Freelancer "
                "Location:</b> India<br>"
            ),
            "guid": "http://www.guru.com/jobs/educational-android-app/1058980",
            "link": "http://www.guru.com/jobs/educational-android-app/1058980",
            "pubDate": "Tue, 05 Aug 2014 09:35:28 GMT",
            "title": "Educational Android App",
            "y:id": {
                "permalink": "false",
                "value": (
                    "http://www.guru.com/jobs/educational-android-app/" "1058980"
                ),
            },
            "y:published": {
                "day": "5",
                "day_name": "Tuesday",
                "day_of_week": "2",
                "day_ordinal_suffix": "th",
                "hour": "9",
                "minute": "35",
                "month": "8",
                "month_name": "August",
                "second": "28",
                "timezone": "UTC",
                "utime": "1407231328",
                "year": "2014",
            },
            "y:repeatcount": "1",
            "y:title": "Educational Android App",
        }

        length = len(pipeline)
        msg = "Pipeline %s has length %i, not 1"
        assert length == 49, msg % (pipe_name, length)
        assert example == pipeline[-1]

    def test_simple1(self):
        """Tests the simple1 pipeline"""
        pipe_name = "simple1"
        pipeline = self._get_pipeline(pipe_name)
        length = len(pipeline)
        msg = "Pipeline %s has length %i, not 1"
        assert length == 1, msg % (pipe_name, length)
        assert {"url": "farechart"} == pipeline[-1]

    def test_simple2(self):
        """Tests the simple2 pipeline"""
        pipe_name = "simple2"
        pipeline = self._get_pipeline(pipe_name)
        example = {"author": "ABC", "link": "www.google.com", "title": "google"}

        length = len(pipeline)
        msg = "Pipeline %s has length %i, not 1"
        assert length == 1, msg % (pipe_name, length)
        assert example == pipeline[-1]

    def test_split(self):
        """Tests the split pipeline"""
        pipe_name = "split"
        pipeline = self._get_pipeline(pipe_name)
        example = {"date": "December 02, 2014", "year": 2014}
        length = len(pipeline)
        msg = "Pipeline %s has length %i, not 1"
        assert length == 1, msg % (pipe_name, length)
        assert example == pipeline[-1]

    def test_wired(self):
        """Tests the wired pipeline"""
        pipe_name = "wired"
        pipeline = self._get_pipeline(pipe_name)
        length = len(pipeline)
        msg = "Pipeline %s has length %i, not 1"
        assert length == 1, msg % (pipe_name, length)
        assert {"date": "May 04, 1982"} == pipeline[-1]
