# vim: sw=4:ts=4:expandtab
"""Provides functional tests for the command-line scripts, examples, and extras."""

import builtins
import importlib.util
import json
import subprocess
import sys
from decimal import Decimal
from difflib import unified_diff
from importlib import import_module
from io import StringIO
from os.path import isfile

import pytest

from riko.base._paths import ROOT_DIR
from riko.definitions._context import Context
from riko.definitions._workflow import Workflow
from riko.execution._prepared import ExecutionPlan
from riko.execution._sync_execution import SyncExecution
from riko.parsing.documents import IJSON_IS_NATIVE, IS_FASTFEEDPARSER, IS_LXML
from riko.runtime._resolver import dispatcher
from riko.runtime.collections import list_formats
from tests import TESTS_DIR, async_test, skipif_issync

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
RAISING_SCRIPT = (
    "from riko import UnsupportedModuleError\n\n"
    "def pipe(test=False):\n    raise UnsupportedModuleError('x')\n"
)
RAISED_MESSAGE = "Unsupported riko module: x\n"
TYPO_DAG = json.dumps({"modules": [{"type": "trunkate"}]})
TYPO_MESSAGE = "Unsupported riko module: trunkate (did you mean 'truncate'?)\n"
RIKO_ERRORS = [
    pytest.param("pipe.py", RAISING_SCRIPT, RAISED_MESSAGE, id="pipe-script"),
    pytest.param("pipe.dag.json", TYPO_DAG, TYPO_MESSAGE, id="workflow-document"),
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
        assert ran.stderr == message

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


class TestExamplePipelines:
    """Each ``examples`` pipeline runs end to end and yields its expected items."""

    def _run_example(self, pipe_name):
        module = import_module(f"examples.{pipe_name}")
        items = module.pipe(test=True)
        return items

    @pytest.mark.timeout(150)
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
                marks=pytest.mark.xfail(
                    strict=True, reason="Pipeline.split() is not available yet"
                ),
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
            pytest.param(
                "split",
                marks=pytest.mark.xfail(
                    strict=True, reason="Pipeline.split() is not available yet"
                ),
            ),
            "demo",
            "wired",
            pytest.param(
                "kazeeki",
                marks=[
                    pytest.mark.timeout(150),
                    pytest.mark.xfail(
                        strict=True,
                        reason=(
                            "gating a node on a per-item predicate is not available "
                            "yet, so the ungated budget math yields NaN values that "
                            "never compare equal"
                        ),
                    ),
                ],
            ),
        ],
    )
    async def test_async_matches_sync(self, pipe_name):
        """Each example's async_pipe yields the same items as its sync pipe."""
        module = import_module(f"examples.{pipe_name}")
        sync_result = list(module.pipe(test=True))
        async_stream = module.async_pipe(test=True)
        async_result = [item async for item in async_stream]
        assert async_result == sync_result

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
        document = ROOT_DIR / "examples" / "workflows" / f"{pipe_name}.json"
        flow = Workflow.parse(document.read_text())
        items = []

        with SyncExecution(context=Context(test=True)) as execution:
            items = list(execution.run(ExecutionPlan.from_workflow(flow, dispatcher)))

        assert items == expected

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
        module = import_module("examples.pyworkflows.pipe_timezone")
        item = next(iter(module.pipe(test=True)))
        assert "EST" in item["dateformat"]
