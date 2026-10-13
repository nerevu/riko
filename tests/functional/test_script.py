# vim: sw=4:ts=4:expandtab
"""Provides functional tests for the riko command-line scripts and optional extras."""

import builtins
import importlib.util
import json
import subprocess
import sys
from difflib import unified_diff
from io import StringIO
from os.path import isfile

import pytest

from riko.definitions._workflow import Workflow
from riko.parsing.documents import IJSON_IS_NATIVE, IS_FASTFEEDPARSER, IS_LXML
from riko.runtime.collections import list_formats
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
    "sync_module",
    "sync_pipeline",
    "sync_workflow",
]
DEMO_PARAMS = [
    pytest.param("demo", DEMO_TEXT, id="demo"),
    pytest.param("simple1", "'farechart'\n", id="simple1"),
    pytest.param("pipe_timezone", TIMEZONE_TEXT, id="example-document"),
]
DEMO_OPTS = [
    pytest.param([], id="sync"),
    pytest.param(["-a"], marks=skipif_issync, id="async"),
]


def run_command(script: str, argument: str, *opts: str) -> str:
    """
    Run *script* with *opts* and *argument*, return stdout as a string.

    Mirrors what scripttest's ``TestFileEnvironment.run`` did:
    - stderr is captured but not checked (``expect_stderr=True`` behavior)
    - the working directory is the repository root (``_BASEDIR``)
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

    result.check_returncode()
    return result.stdout


def assert_output_matches(output: str, *expects, command: str = "") -> None:
    """
    Assert that *output* matches each of *expects* line-by-line.

    Each expected value can be:
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


def run_module(module: str, *args: str, **kwargs) -> subprocess.CompletedProcess:
    """Run a riko command module in a subprocess and return the finished process."""
    options = {"cwd": _BASEDIR, "capture_output": True, "text": True} | kwargs
    return subprocess.run(
        [sys.executable, "-m", f"riko.cli.{module}", *args], check=False, **options
    )


def _installed(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


class TestRunPipe:
    @pytest.mark.parametrize("opts", DEMO_OPTS)
    @pytest.mark.parametrize(("argument", "expected"), DEMO_PARAMS)
    def test_demo(self, argument, expected, opts):
        command = " ".join([DEMO_SCRIPT, *opts, argument])
        output = run_command(DEMO_SCRIPT, argument, *opts)
        assert_output_matches(output, expected, command=command)

    def test_usage_sync(self):
        """The usage example still runs through the CLI entry point."""
        output = run_command(DEMO_SCRIPT, "usage")
        assert "'hash': 197222720" in output

    def test_run_pipe_workflow_document(self, tmp_path):
        workflow_file = tmp_path / "flow.json"
        run_module("build_workflow", str(DAG_PATH), "-o", str(workflow_file))
        ran = run_module("runpipe", "-p", str(workflow_file))
        assert ran.returncode == 0
        assert ran.stdout == "{'forever': True}\n" * 3

    @skipif_issync
    def test_run_pipe_workflow_document_async(self, tmp_path):
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
        run_module("build_workflow", str(dag_file), "-o", str(workflow_file))
        ran = run_module("runpipe", "-a", "-p", str(workflow_file))

        assert ran.returncode == 0
        assert ran.stdout == "{'title': 'riko'}\n"

    @pytest.mark.parametrize(("argument", "expected"), DEMO_PARAMS)
    def test_run_pipe_example_id_outside_the_checkout(
        self, tmp_path, argument, expected
    ):
        """An example id resolves through the ``examples`` directory from any cwd."""
        ran = run_module("runpipe", argument, cwd=tmp_path)
        assert ran.returncode == 0, ran.stderr
        assert ran.stdout == expected

    @pytest.mark.parametrize(
        ("outside", "message"),
        [
            pytest.param(True, "not found in examples", id="outside-checkout"),
            pytest.param(False, "not found in examples!", id="checkout-listed-once"),
        ],
    )
    def test_run_pipe_unknown_example_id_names_the_searched_directories(
        self, tmp_path, outside, message
    ):
        options = {"cwd": tmp_path} if outside else {}
        ran = run_module("runpipe", "pipe_missing", **options)
        assert ran.returncode == 1
        assert f"Example pipe_missing {message}" in ran.stderr

    def test_run_pipe_missing_workflow_document(self, tmp_path):
        ran = run_module("runpipe", "-p", str(tmp_path / "missing.json"))
        assert ran.returncode == 1
        assert "not found" in ran.stderr


class TestBuildWorkflow:
    @pytest.mark.parametrize("to_file", [False, True], ids=["stdout", "file"])
    def test_build_workflow_output_compiles(self, tmp_path, to_file):
        workflow_file = tmp_path / "pipe_forever.json"
        output = ["-o", str(workflow_file)] if to_file else []
        convert = run_module("build_workflow", str(DAG_PATH), *output)

        if to_file:
            converted = workflow_file.read_text(encoding="utf-8")
            compiled = run_module("compile", str(workflow_file))
            assert not convert.stdout
        else:
            converted = convert.stdout
            compiled = run_module("compile", "-", input=converted)

        assert '"version": "2"' in converted
        assert '"nodes"' in converted
        assert "pipe = build_workflow_pipes(" in compiled.stdout
        assert "TruncateRawConf" in compiled.stdout

    def test_build_workflow_compact_matches_the_serializer(self):
        """The compact form is the same byte-stable document the serializer emits."""
        dag = json.loads(DAG_PATH.read_text(encoding="utf-8"))
        expected = Workflow.parse(dag).serialize(indent=None).decode("utf-8")
        convert = run_module("build_workflow", str(DAG_PATH), "-c")
        assert convert.stdout == expected

    def test_build_workflow_format_override_rejects_wrong_shape(self):
        convert = run_module("build_workflow", str(DAG_PATH), "--format", "v2")
        assert convert.returncode == 1
        assert "unknown Workflow key(s)" in convert.stderr
        assert "Traceback" not in convert.stderr

    @pytest.mark.parametrize(
        ("content", "message"),
        [
            pytest.param('{"modules": []}', "no nodes", id="empty-dag"),
            pytest.param('{"modules": null}', "must be a list", id="null-modules"),
        ],
    )
    def test_build_workflow_invalid_dag_exits_nonzero(self, tmp_path, content, message):
        invalid = tmp_path / "invalid.json"
        invalid.write_text(content, encoding="utf-8")
        convert = run_module("build_workflow", str(invalid))
        assert convert.returncode == 1
        assert message in convert.stderr
        assert "Traceback" not in convert.stderr

    @pytest.mark.parametrize("module", ["build_workflow", "compile"])
    @pytest.mark.parametrize(
        ("content", "message"),
        [
            pytest.param("{bad json", "Unable to parse input", id="malformed-json"),
            pytest.param(None, "Unable to read input file", id="missing-file"),
        ],
    )
    def test_unreadable_input_exits_nonzero_without_a_traceback(
        self, tmp_path, content, message, module
    ):
        path = tmp_path / "input.json"

        if content is not None:
            path.write_text(content, encoding="utf-8")

        result = run_module(module, str(path))
        assert result.returncode == 1
        assert message in result.stderr
        assert "Traceback" not in result.stderr


class TestCompile:
    def test_compile_rejects_a_serialized_pipe_dag(self):
        compiled = run_module("compile", str(DAG_PATH))
        assert compiled.returncode == 1
        assert "build-workflow" in compiled.stderr


class TestBenchmark:
    def test_benchmark(self):
        output = run_command(BENCHMARK_SCRIPT, "")
        lines = [line.strip() for line in output.splitlines()]
        missing = [
            label
            for label in BENCHMARK_LABELS
            if not any(line.startswith(f"{label} -") for line in lines)
        ]
        msg = f"benchmark output missing labels {missing}:\n{output}"
        assert not missing, msg


class TestOptionalExtras:
    """
    Pin each optional extra's contract with and without it installed.

    These run unmarked in every environment, so the base environment verifies the
    degraded behavior rather than skipping the extra-only tests.
    """

    def test_capability_flags_track_installed_libs(self):
        """The parser capability flags reflect whether each perf lib is importable."""
        assert IS_LXML is _installed("lxml")
        assert IS_FASTFEEDPARSER is _installed("fastfeedparser")

        if not _installed("ijson"):
            assert IJSON_IS_NATIVE is False

    def test_finance_targets_track_csv2ofx(self):
        """``ofx``/``qif`` formats appear only when the finance extra is present."""
        finance_targets = {"ofx", "qif"}
        targets = set(list_formats())

        if _installed("csv2ofx"):
            assert finance_targets <= targets
        else:
            assert not (finance_targets & targets)
