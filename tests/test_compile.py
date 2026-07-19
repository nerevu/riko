# vim: sw=4:ts=4:expandtab
"""
Regression tests for the code-generation path (``stringify_pipe``).

These tie the two compilation paths together: for the same pipe definition the
generated Python module (path a) must, when executed, produce the exact same
stream as the in-process executor ``build_pipeline`` (path b). Any divergence —
or a codegen regression — fails here.
"""

from difflib import unified_diff
from json import loads
from pathlib import Path

import pytest

from riko import Context
from riko.compile import (
    _resolve_module,
    _wire,
    build_pipeline,
    convert_dag,
    parse_pipe_def,
    stringify_pipe,
)
from riko.compile import compile as compile_pipe
from riko.exceptions import UnsupportedModuleError, UnsupportedPipelineError
from riko.types.compile import DagModule, PipeDag, PipeDef, PipeModule
from riko.utils import listize

PARENT = Path(__file__).parent
PIPELINE_DIR = PARENT / "pipelines"
PYPIPELINE_DIR = PARENT / "pypipelines"
DAG_DIR = PARENT / "dags"
HAND_MAINTAINED = {"pipe_QMrlL_FS3BGlpwryODY80A", "pipe_zKJifuNS3BGLRQK_GsevXg"}

FOREVER = PipeDef(
    {
        "modules": [
            PipeModule({"id": "sw-1", "type": "forever", "conf": {}}),
            PipeModule(
                {
                    "id": "sw-2",
                    "type": "truncate",
                    "conf": {"count": {"type": "number", "value": "2"}},
                }
            ),
            PipeModule({"id": "_OUTPUT", "type": "output", "conf": {}}),
        ],
        "wires": [_wire("sw-1", "sw-2", "_w1"), _wire("sw-2", "_OUTPUT", "_w2")],
    }
)

ITEMBUILDER = PipeDef(
    {
        "modules": [
            PipeModule(
                {
                    "id": "sw-1",
                    "type": "itembuilder",
                    "conf": {
                        "attrs": {
                            "key": {"type": "text", "value": "title"},
                            "value": {"type": "text", "value": "hello"},
                        }
                    },
                }
            ),
            PipeModule({"id": "_OUTPUT", "type": "output", "conf": {}}),
        ],
        "wires": [_wire("sw-1", "_OUTPUT", "_w1")],
    }
)

MALFORMED = {
    "unknown_module": (
        {
            "modules": [
                {"id": "sw-1", "type": "nonexistent", "conf": {}},
                {"id": "_OUTPUT", "type": "output", "conf": {}},
            ],
            "wires": [_wire("sw-1", "_OUTPUT", "_w1")],
        },
        UnsupportedModuleError,
    ),
    "missing_modules": ({"wires": []}, KeyError),
    "empty": ({"modules": [], "wires": []}, IndexError),
    "module_without_type": (
        {"modules": [{"id": "sw-1", "conf": {}}], "wires": []},
        KeyError,
    ),
}

PIPES = {"pipe_gen_forever": FOREVER, "pipe_gen_itembuilder": ITEMBUILDER}


def _run_generated(source, pipe_name):
    namespace: dict = {}
    exec(compile(source, f"<{pipe_name}>", "exec"), namespace)
    return list(listize(namespace[pipe_name](context=Context())))


def _run_executor(parsed):
    return list(listize(build_pipeline(parsed, context=Context())))


def _compile_and_run(pipe_def, pipe_name):
    parsed = parse_pipe_def(pipe_def, pipe_name)
    return list(listize(build_pipeline(parsed, context=Context())))


@pytest.mark.parametrize("pipe_name", list(PIPES))
def test_codegen_matches_executor(pipe_name):
    pipe_def = PIPES[pipe_name]
    parsed = parse_pipe_def(pipe_def, pipe_name)
    source = stringify_pipe(parsed)
    assert _run_generated(source, pipe_name) == _run_executor(parsed)


def _codegen_pairs():
    pipe_files = sorted(PIPELINE_DIR.glob("pipe_*.json"))
    exists = lambda pfile: (PYPIPELINE_DIR / f"{pfile.stem}.py").exists()
    filterer = lambda pfile: exists(pfile) and pfile.stem not in HAND_MAINTAINED
    return list(filter(filterer, pipe_files))


@pytest.mark.parametrize("pipe_name", _codegen_pairs())
def test_codegen_matches_expected_file(pipe_name):
    pipe_def = loads((PIPELINE_DIR / f"{pipe_name.stem}.json").read_text())
    expected = (PYPIPELINE_DIR / f"{pipe_name.stem}.py").read_text()
    source = stringify_pipe(parse_pipe_def(pipe_def, pipe_name.stem))
    args = (expected.splitlines(keepends=True), source.splitlines(keepends=True))
    diff = "".join(unified_diff(*args, "expected", "got"))
    assert not diff, f"Generated source for {pipe_name.stem} diverged:\n{diff}"


@pytest.mark.parametrize("case", list(MALFORMED))
def test_malformed_pipeline_syntax(case):
    pipe_def, expected = MALFORMED[case]

    with pytest.raises(expected):
        _compile_and_run(pipe_def, f"pipe_{case}")


def test_compile_wraps_parse_and_stringify():
    pipe_def = loads((PIPELINE_DIR / "pipe_gigs.json").read_text())
    expected = stringify_pipe(parse_pipe_def(pipe_def, "pipe_gigs"))

    assert compile_pipe(pipe_def, "pipe_gigs") == expected


def test_unresolved_subpipeline_raises():
    with pytest.raises(UnsupportedPipelineError):
        _resolve_module("pipe_missing", "pipe_missing")

    with pytest.raises(UnsupportedPipelineError):
        _resolve_module("pipe_missing", "pipe_missing", compile_missing=True)


def test_convert_dag_appends_output():
    dag = loads((DAG_DIR / "pipe_forever.json").read_text())
    pipe_def = convert_dag(dag)
    module_ids = [module["id"] for module in pipe_def["modules"]]
    output_wire = pipe_def["wires"][-1]

    assert module_ids == ["sw-1", "sw-2", "_OUTPUT"]
    assert output_wire["src"]["moduleid"] == "sw-2"
    assert output_wire["tgt"]["moduleid"] == "_OUTPUT"


def test_convert_dag_matches_full_pipeline():
    dag = loads((DAG_DIR / "pipe_forever.json").read_text())
    full = loads((PIPELINE_DIR / "pipe_forever.json").read_text())
    converted = _compile_and_run(convert_dag(dag), "pipe_forever")
    expected = _compile_and_run(full, "pipe_forever")
    assert converted == expected


def test_convert_dag_linear_default_matches_explicit_wires():
    modules = [
        DagModule({"id": "sw-1", "type": "forever", "conf": {}}),
        DagModule(
            {
                "id": "sw-2",
                "type": "truncate",
                "conf": {"count": {"type": "number", "value": "3"}},
            }
        ),
    ]
    linear = convert_dag({"modules": modules})
    wired = convert_dag({"modules": modules, "wires": [("sw-1", "sw-2")]})
    assert linear == wired


def test_convert_dag_wires_override_listing_order():
    dag = loads((DAG_DIR / "pipe_reordered.json").read_text())
    wires = convert_dag(dag)["wires"]
    edges = [(wire["src"]["moduleid"], wire["tgt"]["moduleid"]) for wire in wires]

    assert edges == [("gen", "trunc"), ("trunc", "_OUTPUT")]
    assert len(_compile_and_run(convert_dag(dag), "pipe_reordered")) == 2


def test_convert_dag_generates_ids_when_omitted():
    dag = PipeDag(
        {
            "modules": [
                DagModule({"type": "forever", "conf": {}}),
                DagModule(
                    {
                        "type": "truncate",
                        "conf": {"count": {"type": "number", "value": "3"}},
                    }
                ),
            ]
        }
    )
    pipe_def = convert_dag(dag)
    module_ids = [module["id"] for module in pipe_def["modules"]]
    edges = [
        (wire["src"]["moduleid"], wire["tgt"]["moduleid"]) for wire in pipe_def["wires"]
    ]

    assert module_ids == ["sw-1", "sw-2", "_OUTPUT"]
    assert edges == [("sw-1", "sw-2"), ("sw-2", "_OUTPUT")]
