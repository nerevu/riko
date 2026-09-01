# vim: sw=4:ts=4:expandtab

"""
Tests riko runpipe CLI functionality.
"""

import builtins
import subprocess
import sys
from difflib import unified_diff
from io import StringIO
from os.path import isfile

import pytest

from tests import TESTS_DIR, skipif_issync

_BASEDIR = TESTS_DIR.parent
DEMO_SCRIPT = "run-pipe"
BENCHMARK_SCRIPT = "benchmark"
DEMO_TEXT = "Deadline to clear up health law eligibility near\n682\n"
BENCHMARK_LABELS = [
    "baseline_sync",
    "baseline_threads",
    "baseline_procs",
    "sync_pipeline",
    "sync_pipe",
    "sync_collection",
    "par_sync_collection",
]
DEMO_PARAMS = [("demo", DEMO_TEXT), ("simple1", "'farechart'\n")]


def run_command(script: str, argument: str, *opts: str) -> str:
    """
    Run *script* with *opts* and *arguments*, return stdout as a string.

    Mirrors what scripttest's ``TestFileEnvironment.run`` did:
    - stderr is captured but not checked (``expect_stderr=True`` behavior)
    - the working directory is ``PARENT_DIR``
    - a non-zero exit code raises ``subprocess.CalledProcessError``
    """
    cmd = [script, *opts]

    if argument:
        cmd.append(argument)

    result = subprocess.run(
        cmd, cwd=_BASEDIR, capture_output=True, text=True, check=False
    )

    if result.stderr:
        print(result.stderr, file=sys.stderr)

    # Raise if process fails so the test is marked ERROR, not FAIL.
    result.check_returncode()
    return result.stdout


def assert_output_matches(output: str, *expects, command: str = "") -> None:
    """
    Assert that *output* matches *expected* line-by-line.

    *expected* can be:
    - file path  – output must match the file's contents line-by-line
    - ``str``    – output must match the string line-by-line
    """
    outlines = StringIO(output).readlines()

    for expected in expects:
        if isfile(expected):
            with builtins.open(expected, encoding="utf-8") as f:
                checklines = f.readlines()
        else:
            checklines = StringIO(expected).readlines()

        diffs = "".join(unified_diff(checklines, outlines, "expected", "got"))
        msg = f"Output for {command} doesn't match expected.\n{diffs}"
        assert not diffs, msg


@pytest.mark.parametrize("value", DEMO_PARAMS)
def test_demo_sync(value):
    argument, expected = value
    command = f"{DEMO_SCRIPT} {argument}"
    output = run_command(DEMO_SCRIPT, argument)
    assert_output_matches(output, expected, command=command)


@skipif_issync
@pytest.mark.parametrize("value", DEMO_PARAMS)
def test_demo_async(value):
    argument, expected = value
    opts = ["-a"]

    joined_opts = " ".join(opts)
    command = f"{DEMO_SCRIPT} {joined_opts} {argument}"

    output = run_command(DEMO_SCRIPT, argument, *opts)
    assert_output_matches(output, expected, command=command)


def test_benchmark():
    output = run_command(BENCHMARK_SCRIPT, "")
    lines = [line.strip() for line in output.splitlines()]
    missing = [
        label
        for label in BENCHMARK_LABELS
        if not any(line.startswith(f"{label} -") for line in lines)
    ]
    msg = f"benchmark output missing labels {missing}:\n{output}"
    assert not missing, msg


def test_convert_dag_and_compile(tmp_path):
    dag = TESTS_DIR / "dags" / "pipe_forever.json"
    pipe_file = tmp_path / "pipe_forever.json"

    convert = subprocess.run(
        [sys.executable, "-m", "riko.cli.convert_dag", dag, "-o", str(pipe_file)],
        cwd=_BASEDIR,
        capture_output=True,
        text=True,
        check=True,
    )

    compiled = subprocess.run(
        [sys.executable, "-m", "riko.cli.compile", str(pipe_file)],
        cwd=_BASEDIR,
        capture_output=True,
        text=True,
        check=True,
    )

    assert not convert.stdout
    assert '"moduleid": "_OUTPUT"' in pipe_file.read_text(encoding="utf-8")
    assert "def pipe(" in compiled.stdout
    assert "truncate" in compiled.stdout
