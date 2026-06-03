# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab

"""
tests.test_script
~~~~~~~~~~~~~~~~~

Tests riko runpipe CLI functionality.
"""

import sys
import subprocess

import pytest

from difflib import unified_diff, SequenceMatcher
from os import path as p
from io import StringIO, open

try:
    from riko.bado import _issync
except ImportError:
    _issync = True

PARENT_DIR = p.abspath(p.dirname(p.dirname(__file__)))
DEMO_SCRIPT = "runpipe"
BENCHMARK_SCRIPT = "benchmark"
DEMO_TEXT = "Deadline to clear up health law eligibility near 682\n"
BENCHMARK_TEXTS = [
    "baseline_sync - 1 repetitions/loop, best of 1 loops",
    "baseline_threads - 1 repetitions/loop, best of 1 loops",
    "baseline_procs - 1 repetitions/loop, best of 1 loops",
    "sync_pipeline - 1 repetitions/loop, best of 1 loops",
    "sync_pipe - 1 repetitions/loop, best of 1 loops",
    "sync_collection - 1 repetitions/loop, best of 1 loops",
    "par_sync_collection - 1 repetitions/loop, best of 1 loops"
]


def run_command(script: str, argument: str, *opts: str) -> str:
    """Run *script* with *opts* and *arguments*, return stdout as a string.

    Mirrors what scripttest's ``TestFileEnvironment.run`` did:
    - stderr is captured but not checked (``expect_stderr=True`` behavior)
    - the working directory is ``PARENT_DIR``
    - a non-zero exit code raises ``subprocess.CalledProcessError``
    """
    cmd = [script] + list(opts)

    if argument:
        cmd.append(argument)

    result = subprocess.run(
        cmd,
        cwd=PARENT_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    if result.stderr:
        print(result.stderr, file=sys.stderr)

    # Raise if process fails so the test is marked ERROR, not FAIL.
    result.check_returncode()
    return result.stdout


def assert_output_matches(output: str, *expects, command: str = "", partial=False) -> None:
    """Assert that *output* matches *expected*.

    *expected* can be:
    - ``bool``   – truth-value of the output must match
    - file path  – output must match the file's contents line-by-line
    - ``str``    – output must match the string line-by-line
    """
    fd = StringIO(output)
    r_outlines = fd.readlines()
    b_outlines = [str(bool(fd.read()))]

    for expected in expects:
        if isinstance(expected, bool):
            outlines = b_outlines
            checklines = [str(expected)]
        elif p.isfile(expected):
            outlines = r_outlines

            with open(expected, encoding="utf-8") as f:
                checklines = f.readlines()
        else:
            outlines = r_outlines
            checklines = StringIO(expected).readlines()

        if partial:
            checkwords = " ".join(checklines).split(" ")
            outwords = " ".join(outlines).split(" ")
            s = SequenceMatcher(None, checkwords, outwords)
            blocks = s.get_matching_blocks()
            diffs = f"{checklines} not found in {outlines}"
            msg = f"Output for {command} doesn't match expected.\n{diffs}"
            assert blocks[0].size == 7, msg
        else:
            args = ("expected", "got")
            diffs = "".join(unified_diff(checklines, outlines, *args))
            msg = f"Output for {command} doesn't match expected.\n{diffs}"
            assert not diffs, msg


def gen_params():
    yield from [
        ("demo", DEMO_TEXT),
        ("simple1", "'farechart'\n"),
    ]


@pytest.mark.skip
@pytest.mark.parametrize("value", gen_params())
def test_demo_sync(value):
    argument, expected = value
    command = f"{DEMO_SCRIPT} {argument}"
    output = run_command(DEMO_SCRIPT, argument)
    assert_output_matches(output, expected, command=command)


@pytest.mark.skip
@pytest.mark.skipif(_issync, reason="async support not available")
@pytest.mark.parametrize("value", gen_params())
def test_demo_async(value):
    argument, expected = value
    opts = ["-a"]

    joined_opts = " ".join(opts)
    command = f"{DEMO_SCRIPT} {joined_opts} {argument}"

    output = run_command(DEMO_SCRIPT, argument, *opts)
    assert_output_matches(output, expected, command=command)


def test_benchmark():
    output = run_command(BENCHMARK_SCRIPT, "")
    kwargs = {"command": BENCHMARK_SCRIPT, "partial": True}
    assert_output_matches(output, *BENCHMARK_TEXTS, **kwargs)
