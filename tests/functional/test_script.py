# vim: sw=4:ts=4:expandtab
"""Provides functional tests for the command-line scripts, examples, and extras."""

import builtins
import json
import subprocess
import sys
from collections.abc import Mapping
from decimal import Decimal
from difflib import unified_diff
from importlib import import_module
from io import StringIO
from os.path import isfile

import pytest

from riko.base._paths import ROOT_DIR
from riko.definitions._workflow_definition import Workflow
from tests import SCRIPT_TIMEOUT, TESTS_DIR, async_test, run_python, skipif_issync
from tests._workflows import (
    DAG,
    DAG_PATH,
    EXAMPLES_DIR,
    SPLIT_METHOD_PENDING,
    run_document,
)

ENTRY_POINTS = {"runpipe": "run-pipe", "benchmark": "benchmark"}
DEMO_TEXT = "Deadline to clear up health law eligibility near\n682\n"
ITEM_ATTRS = {"key": "title", "value": "riko"}
TIMEZONE_TEXT = "{'date': '5/4/1982', 'dateformat': 'May 04, 1982 UTC'}\n"

RAISING_SCRIPT = (
    "from riko import UnsupportedModuleError\n\n"
    "def pipe(test=False):\n    raise UnsupportedModuleError('x')\n"
)

TYPO_DAG = json.dumps({"modules": [{"type": "trunkate"}]})

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
DEMO_RUNS = [
    pytest.param([], True, False, id="entry-point-sync"),
    pytest.param(["-a"], True, False, marks=skipif_issync, id="entry-point-async"),
    pytest.param([], False, True, id="module-outside-checkout"),
]
RIKO_ERRORS = [
    pytest.param("pipe.py", RAISING_SCRIPT, "module: x", id="pipe-script"),
    pytest.param("pipe.dag.json", TYPO_DAG, "module: trunkate", id="workflow-document"),
]


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


def run_module(
    module: str, *args: str, entry_point: bool = False, **kwargs
) -> subprocess.CompletedProcess:
    """
    Runs a riko command in a subprocess and returns the finished process.

    It runs ``python -m riko.cli.<module>``, or the installed console script when
    ``entry_point`` is set, from the repository root unless ``cwd`` says otherwise.
    """
    command = [ENTRY_POINTS[module]] if entry_point else [sys.executable, "-m"]
    target = [] if entry_point else [f"riko.cli.{module}"]
    options = {"cwd": ROOT_DIR, "capture_output": True, "text": True}
    options |= {"timeout": SCRIPT_TIMEOUT} | kwargs
    return subprocess.run([*command, *target, *args], check=False, **options)


class TestRunPipe:
    @pytest.mark.parametrize(("opts", "entry_point", "outside"), DEMO_RUNS)
    @pytest.mark.parametrize(("argument", "expected"), DEMO_PARAMS)
    def test_demo(self, tmp_path, argument, expected, opts, entry_point, outside):
        """An example id runs from the checkout or, by module, from any cwd."""
        cwd = tmp_path if outside else ROOT_DIR
        ran = run_module("runpipe", *opts, argument, entry_point=entry_point, cwd=cwd)
        assert ran.returncode == 0, ran.stderr
        assert_output_matches(ran.stdout, expected, command=" ".join(ran.args))

    def test_usage_sync(self):
        """The usage example still runs through the CLI entry point."""
        ran = run_module("runpipe", "usage", entry_point=True)
        assert ran.returncode == 0, ran.stderr
        assert "'hash': 197222720" in ran.stdout

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

    @pytest.mark.parametrize(("filename", "content", "message"), RIKO_ERRORS)
    def test_run_pipe_reports_a_riko_error_without_a_traceback(
        self, tmp_path, filename, content, message
    ):
        path = tmp_path / filename
        path.write_text(content, encoding="utf-8")

        if path.suffix == ".json":
            target = tmp_path / "pipe.json"
            run_module("build_workflow", str(path), "-o", str(target))
        else:
            target = path

        ran = run_module("runpipe", "-p", str(target))
        assert ran.returncode == 1
        assert message in ran.stderr
        assert "Traceback" not in ran.stderr

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
        expected = Workflow.parse(DAG).serialize(indent=None).decode("utf-8")
        convert = run_module("build_workflow", str(DAG_PATH), "-c")
        assert convert.stdout == expected

    def test_build_workflow_format_override_rejects_wrong_shape(self):
        convert = run_module("build_workflow", str(DAG_PATH), "--format", "v2")
        assert convert.returncode == 1
        assert "unknown Workflow key(s)" in convert.stderr
        assert "Traceback" not in convert.stderr

    @pytest.mark.parametrize(
        "content",
        [
            pytest.param('{"modules": []}', id="empty-dag"),
            pytest.param('{"modules": null}', id="null-modules"),
        ],
    )
    def test_build_workflow_invalid_dag_exits_nonzero(self, tmp_path, content):
        invalid = tmp_path / "invalid.json"
        invalid.write_text(content, encoding="utf-8")
        convert = run_module("build_workflow", str(invalid))
        assert convert.returncode == 1
        assert "Invalid pipeline" in convert.stderr
        assert "Traceback" not in convert.stderr

    @pytest.mark.parametrize("module", ["build_workflow", "compile"])
    @pytest.mark.parametrize(
        "content",
        [
            pytest.param("{bad json", id="malformed-json"),
            pytest.param(None, id="missing-file"),
        ],
    )
    def test_unreadable_input_exits_nonzero_without_a_traceback(
        self, tmp_path, content, module
    ):
        path = tmp_path / "input.json"

        if content is not None:
            path.write_text(content, encoding="utf-8")

        result = run_module(module, str(path))
        assert result.returncode == 1
        assert "Unable to" in result.stderr
        assert "Traceback" not in result.stderr


class TestCompile:
    def test_compile_writes_to_a_file_and_reports_it(self, tmp_path):
        dest = tmp_path / "pipe_testpipe1.py"
        flow_path = TESTS_DIR / "workflows" / "pipe_testpipe1.json"
        compiled = run_module("compile", str(flow_path), "-o", str(dest), "-v")
        assert compiled.returncode == 0
        assert compiled.stdout == ""
        assert f"wrote {len(dest.read_text())} bytes to {dest}" in compiled.stderr

    def test_compile_rejects_a_serialized_pipe_dag(self):
        compiled = run_module("compile", str(DAG_PATH))
        assert compiled.returncode == 1
        assert "build-workflow" in compiled.stderr
        assert "Traceback" not in compiled.stderr


class TestBenchmark:
    def test_benchmark(self):
        ran = run_module("benchmark", entry_point=True, timeout=20)
        assert ran.returncode == 0, ran.stderr
        output = ran.stdout
        lines = [line.strip() for line in output.splitlines()]
        missing = [
            label
            for label in BENCHMARK_LABELS
            if not any(line.startswith(f"{label} -") for line in lines)
        ]
        msg = f"benchmark output missing labels {missing}:\n{output}"
        assert not missing, msg


def _without_nan(value: object) -> object:
    """Replaces each NaN with a marker so equal outputs compare equal."""
    if isinstance(value, Mapping):
        result = {key: _without_nan(item) for key, item in value.items()}
    elif isinstance(value, list):
        result = [_without_nan(item) for item in value]
    elif isinstance(value, (Decimal, float)) and value != value:  # noqa: PLR0124
        result = "NaN"
    else:
        result = value

    return result


class TestExamplePipelines:
    """Each ``examples`` pipeline runs end to end and yields its expected items."""

    def _run_example(self, pipe_name):
        module = import_module(f"examples.{pipe_name}")
        items = module.pipe(test=True)
        return items

    @pytest.mark.timeout(5)
    def test_kazeeki(self):
        """Tests the kazeeki pipeline."""
        pipe_name = "kazeeki"
        items = self._run_example(pipe_name)
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
            "k:budget_w_sym": "$12.50",
            "k:budget_full": "$12.50 / hr",
            "k:categories": [
                {"content": "animation"},
                {"content": "design & multimedia"},
            ],
            "k:client_location": "Cambodia",
            "k:cur_code": "USD",
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
        length = len(items)
        msg = f"Pipeline {pipe_name} has {length=}, but {expected=}"
        assert length == expected, msg
        last = items[-1]

        for k, v in example.items():
            got = last[k]
            msg = f"Pipeline {pipe_name} {got=} for {k=}, but expected={v}"
            assert got == v, msg

    def test_gigs(self):
        """Tests the gigs pipeline."""
        pipe_name = "gigs"
        items = self._run_example(pipe_name)

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

        length = len(items)
        assert length == 49, f"Pipeline {pipe_name} has length {length}, not 49"
        assert example == items[-1]

    @pytest.mark.parametrize(
        ("pipe_name", "expected"),
        [
            ("simple1", {"url": "farechart"}),
            ("simple2", {"author": "ABC", "link": "www.google.com", "title": "google"}),
            pytest.param(
                "split",
                {"date": "December 02, 2014", "year": 2014},
                marks=SPLIT_METHOD_PENDING,
            ),
            ("wired", {"date": "May 04, 1982"}),
        ],
    )
    def test_simple_pipeline(self, pipe_name, expected):
        """Each single-item example pipeline yields exactly its expected item."""
        items = self._run_example(pipe_name)
        length = len(items)
        assert length == 1, f"Pipeline {pipe_name} has length {length}, not 1"
        assert items[-1] == expected

    @async_test
    @pytest.mark.parametrize(
        "pipe_name",
        [
            "simple1",
            "simple2",
            "gigs",
            pytest.param("split", marks=SPLIT_METHOD_PENDING),
            "demo",
            "wired",
            "kazeeki",
        ],
    )
    async def test_async_matches_sync(self, pipe_name):
        """Each example's async_pipe yields the same items as its sync pipe."""
        module = import_module(f"examples.{pipe_name}")
        sync_result = list(module.pipe(test=True))
        async_stream = module.async_pipe(test=True)
        async_result = [item async for item in async_stream]
        assert _without_nan(async_result) == _without_nan(sync_result)

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
    def test_example_document_runs(self, pipe_name, expected):
        """Runs each example workflow document and checks the stream it produces."""
        assert (
            run_document(EXAMPLES_DIR / "workflows" / f"{pipe_name}.json") == expected
        )

    @pytest.mark.parametrize(
        ("script", "expected"),
        [
            ("register_alias", "[{'count': 3}]"),
            ("register_module", "[{'content': 'HI'}]"),
        ],
    )
    def test_register_example(self, script, expected):
        """Tests the runtime-registration example scripts run and register."""
        proc = run_python(f"examples/{script}.py", check=False)
        assert proc.returncode == 0, f"{script} failed: {proc.stderr}"
        assert expected in proc.stdout, f"{script} output: {proc.stdout!r}"

    @pytest.mark.xfail(
        reason="dateformat timezone setting is not yet implemented.", strict=True
    )
    def test_unsupported_timezone(self):
        """The timezone example asks for EST but dateformat ignores it (UTC)."""
        module = import_module("examples.pyworkflows.pipe_timezone")
        item = next(iter(module.pipe(test=True)))
        assert "EST" in item["dateformat"]
