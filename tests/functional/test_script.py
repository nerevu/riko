# vim: sw=4:ts=4:expandtab

"""Tests riko runpipe CLI functionality."""

import builtins
import json
import subprocess
import sys
from difflib import unified_diff
from io import StringIO
from os.path import isfile

import pytest

from riko.runtime._migrate import build_workflow
from riko.runtime._serialize import serialize_workflow
from tests import TESTS_DIR, skipif_issync

_BASEDIR = TESTS_DIR.parent
DAG_PATH = TESTS_DIR / "dags" / "pipe_forever.json"
DEMO_SCRIPT = "run-pipe"
BENCHMARK_SCRIPT = "benchmark"
DEMO_TEXT = "Deadline to clear up health law eligibility near\n682\n"
TIMEZONE_TEXT = "{'date': '5/4/1982', 'dateformat': 'May 04, 1982 UTC'}\n"
ITEM_ATTRS = {"key": "title", "value": "riko"}
BENCHMARK_LABELS = [
    "baseline_sync",
    "baseline_threads",
    "baseline_procs",
    "sync_pipeline",
    "sync_pipe",
    "sync_workflow",
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


def test_usage_sync():
    """The usage example still runs through the CLI entry point."""
    output = run_command(DEMO_SCRIPT, "usage")
    assert "'hash': 197222720" in output


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


def run_module(module: str, *args: str, **kwargs) -> subprocess.CompletedProcess:
    """Run a riko command module in a subprocess and return the finished process."""
    return subprocess.run(
        [sys.executable, "-m", f"riko.cli.{module}", *args],
        cwd=_BASEDIR,
        capture_output=True,
        text=True,
        check=False,
        **kwargs,
    )


def test_convert_dag_pipes_to_compile_stdin():
    convert = run_module("convert_dag", str(DAG_PATH))
    compiled = run_module("compile", "-", input=convert.stdout)

    assert '"version": "2"' in convert.stdout
    assert '"nodes"' in convert.stdout
    assert "def pipe(" in compiled.stdout
    assert "TruncateRawConf" in compiled.stdout


def test_convert_dag_and_compile(tmp_path):
    workflow_file = tmp_path / "pipe_forever.json"
    convert = run_module("convert_dag", str(DAG_PATH), "-o", str(workflow_file))
    compiled = run_module("compile", str(workflow_file))
    converted = workflow_file.read_text(encoding="utf-8")

    assert not convert.stdout
    assert '"version": "2"' in converted
    assert '"nodes"' in converted
    assert "def pipe(" in compiled.stdout
    assert "TruncateRawConf" in compiled.stdout


def test_convert_dag_compact_is_canonical():
    """The compact form is the same byte-stable document the serializer emits."""
    dag = json.loads(DAG_PATH.read_text(encoding="utf-8"))
    expected = serialize_workflow(build_workflow(dag), indent=None).decode("utf-8")
    convert = run_module("convert_dag", str(DAG_PATH), "-c")
    assert convert.stdout == expected


def test_convert_dag_format_override_rejects_wrong_shape():
    convert = run_module("convert_dag", str(DAG_PATH), "--format", "v2")
    assert convert.returncode
    assert convert.stderr


def test_convert_dag_empty_dag_exits_nonzero(tmp_path):
    empty = tmp_path / "empty.json"
    empty.write_text('{"modules": []}', encoding="utf-8")
    convert = run_module("convert_dag", str(empty))
    assert convert.returncode == 1
    assert "no nodes" in convert.stderr


def test_compile_rejects_legacy_document():
    compiled = run_module("compile", str(DAG_PATH))
    assert compiled.returncode == 1
    assert "convert-dag" in compiled.stderr


def test_run_pipe_workflow_document(tmp_path):
    workflow_file = tmp_path / "flow.json"
    run_module("convert_dag", str(DAG_PATH), "-o", str(workflow_file))
    ran = run_module("runpipe", "-p", str(workflow_file))
    assert ran.returncode == 0
    assert ran.stdout == "{'forever': True}\n" * 3


def test_run_pipe_missing_workflow_document(tmp_path):
    ran = run_module("runpipe", "-p", str(tmp_path / "missing.json"))
    assert ran.returncode == 1
    assert "not found" in ran.stderr


@skipif_issync
def test_run_pipe_workflow_document_async(tmp_path):
    """
    The async run of a workflow document produces the same items as the sync one.

    Its source is finite because the async operators still gather their whole
    input before producing anything.
    """
    dag_file = tmp_path / "item.dag.json"
    workflow_file = tmp_path / "item.json"
    dag = {
        "modules": [
            {"type": "itembuilder", "conf": {"attrs": ITEM_ATTRS}},
            {"type": "truncate", "conf": {"count": {"type": "int", "value": "1"}}},
        ]
    }
    dag_file.write_text(json.dumps(dag), encoding="utf-8")
    run_module("convert_dag", str(dag_file), "-o", str(workflow_file))
    ran = run_module("runpipe", "-a", "-p", str(workflow_file))

    assert ran.returncode == 0
    assert ran.stdout == "{'title': 'riko'}\n"


def test_run_pipe_example_document():
    """An example id with no script of its own runs the document of that name."""
    output = run_command(DEMO_SCRIPT, "pipe_timezone")
    assert output == TIMEZONE_TEXT
