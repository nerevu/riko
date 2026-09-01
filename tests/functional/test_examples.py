# vim: sw=4:ts=4:expandtab
"""
Provides example pipeline tests.
"""

import subprocess
import sys
from decimal import Decimal
from importlib import import_module

import pytest

from riko.paths import ROOT_DIR


class TestExamples:
    def _get_pipeline(self, pipe_name):
        module = import_module(f"examples.{pipe_name}")
        pipeline = module.pipe(test=True)
        return pipeline

    @pytest.mark.timeout(150)
    def test_kazeeki(self):
        """Tests the kazeeki pipeline."""
        pipe_name = "kazeeki"
        pipeline = self._get_pipeline(pipe_name)
        example = {
            "description": (
                "We are looking for freelancers ( individuals and companies ) "
                "who offer their services related to Architecture Walkthrough "
                "and 3D animations. Please consider this job as a potential "
                "to several more and a long term relationship.   We are a "
                "Media"
            ),
            "id": "www.elance.com-66963214",
            "k:budget": Decimal("12.5"),
            # "k:budget_w_sym": "$12.50",
            # "k:budget_full": "$12.50 / hr",
            "k:categories": [
                {"content": "animation"},
                {"content": "design & multimedia"},
            ],
            "k:client_location": "Cambodia",
            # "k:cur_code": "USD",
            "k:due": "Thu, 05 Feb 2015 11:46:40 EST",
            "k:job_type": "hourly",
            "k:num_jobs": "0",
            "k:per_awarded": "0%",
            "k:source": "www.elance.com",
            "k:posted": "Tue, 06 Jan 2015 11:46:40 EST",
            "k:submissions": "0",
            "k:tags": [
                {"content": "3d animation"},
                {"content": "3d modeling"},
                {"content": "3d rendering"},
                {"content": "animation"},
                {"content": "computer graphics"},
            ],
            "k:tot_purchased": "$0",
            "link": (
                "https://www.elance.com/j/3d-architecture-walkthrough-3d-"
                "animation-artists/66963214/"
            ),
            "title": "3D Architecture Walkthrough &amp; 3D / Animation Artists",
        }

        expected = 180
        length = len(pipeline)
        msg = f"Pipeline {pipe_name} has {length=}, but {expected=}"
        assert length == expected, msg
        last = pipeline[-1]
        # print(last)

        for k, v in example.items():
            got = last[k]
            msg = f"Pipeline {pipe_name} {got=} for {k=}, but expected={v}"
            assert got == v, msg

    def test_gigs(self):
        """Tests the gigs pipeline."""
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
                "value": ("http://www.guru.com/jobs/educational-android-app/1058980"),
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
        assert length == 49, f"Pipeline {pipe_name} has length {length}, not 49"
        assert example == pipeline[-1]

    @pytest.mark.parametrize(
        ("pipe_name", "expected"),
        [
            ("simple1", {"url": "farechart"}),
            ("simple2", {"author": "ABC", "link": "www.google.com", "title": "google"}),
            ("split", {"date": "December 02, 2014", "year": 2014}),
            ("wired", {"date": "May 04, 1982"}),
        ],
    )
    def test_simple_pipeline(self, pipe_name, expected):
        """Each single-item example pipeline yields exactly its expected record."""
        pipeline = self._get_pipeline(pipe_name)
        length = len(pipeline)
        assert length == 1, f"Pipeline {pipe_name} has length {length}, not 1"
        assert pipeline[-1] == expected

    @pytest.mark.parametrize(
        ("pipeid", "expected"),
        [
            ("usage", "'hash': 197222720"),
            ("demo", "Deadline to clear up health law eligibility near"),
        ],
    )
    def test_run_pipe(self, pipeid, expected):
        """Tests the run-pipe CLI against the example pipelines."""
        cmd = [sys.executable, "-m", "riko.cli.runpipe", pipeid]
        proc = subprocess.run(
            cmd, cwd=ROOT_DIR, capture_output=True, text=True, check=False
        )
        assert proc.returncode == 0, f"run-pipe {pipeid} failed: {proc.stderr}"
        assert expected in proc.stdout, f"run-pipe {pipeid} output: {proc.stdout!r}"

    @pytest.mark.parametrize(
        ("pipe_name", "expected"),
        [
            (
                "pipe_679e2c544332e978b15b6b163767975f",
                [{"link": "www.google.com", "title": "google", "author": "USD"}],
            ),
            ("pipe_a3d1afa31f0a24cc51dcbe79f1590343", [{"url": "farechart"}]),
            (
                "pipe_1a0ea1b39a8f261d0339a12fb5f0f03e",
                [{"date": "December 02, 2014", "year": "1201"}],
            ),
            ("pipe_4f26297843f4952fad920af5990ddc50", [{"date": "December 03, 2014"}]),
        ],
    )
    def test_compiled_pipe(self, pipe_name, expected):
        """Tests the JSON-compiled example pipes produce the expected stream."""
        module = import_module(f"examples.pypipelines.{pipe_name}")
        assert list(module.pipe(test=True)) == expected

    @pytest.mark.parametrize(
        ("script", "expected"),
        [
            ("register_alias", "[{'count': 3}]"),
            ("register_module", "[{'content': 'HI'}]"),
        ],
    )
    def test_register_example(self, script, expected):
        """Tests the runtime-registration example scripts run and register."""
        cmd = [sys.executable, f"examples/{script}.py"]
        proc = subprocess.run(
            cmd, cwd=ROOT_DIR, capture_output=True, text=True, check=False
        )
        assert proc.returncode == 0, f"{script} failed: {proc.stderr}"
        assert expected in proc.stdout, f"{script} output: {proc.stdout!r}"

    @pytest.mark.xfail(
        reason="dateformat timezone setting is not yet implemented.", strict=True
    )
    def test_unsupported_timezone(self):
        """The timezone example asks for EST but dateformat ignores it (UTC)."""
        module = import_module("examples.pypipelines.pipe_timezone")
        item = next(iter(module.pipe(test=True)))
        assert "EST" in item["dateformat"]
