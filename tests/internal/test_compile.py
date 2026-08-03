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
from riko.bado import issync
from riko.compile import (
    build_pipeline,
    convert_dag,
    get_wire,
    legacy_loop_to_canonical,
    normalize_raw_module,
    parse_pipe_def,
    resolve_module,
    stringify_pipe,
)
from riko.compile import compile as compile_pipe
from riko.exceptions import UnsupportedModuleError, UnsupportedPipelineError
from riko.types.compile import DagModule, PipeDag, PipeDef, PipeModule
from riko.types.modules import (
    Embed,
    EmbeddedModule,
    FetchDataRawConf,
    ItemBuilderRawConf,
    LoopRawConf,
    Param,
    PipeId,
    RegexRawConf,
    RegexRawRule,
    SubModuleRawConf,
    TokenizerRawConf,
    TruncateRawConf,
)
from riko.utils import listize

PARENT = Path(__file__).parent.parent
PIPELINE_DIR = PARENT / "pipelines"
PYPIPELINE_DIR = PARENT / "pypipelines"
DAG_DIR = PARENT / "dags"

FOREVER = PipeDef(
    {
        "modules": [
            PipeModule({"id": "sw-1", "type": "forever", "conf": {}}),
            PipeModule(
                {
                    "id": "sw-2",
                    "type": "truncate",
                    "conf": TruncateRawConf({"count": {"type": "float", "value": "2"}}),
                }
            ),
            PipeModule({"id": "_OUTPUT", "type": "output", "conf": {}}),
        ],
        "wires": [get_wire("sw-1", "sw-2", "_w1"), get_wire("sw-2", "_OUTPUT", "_w2")],
    }
)

ITEMBUILDER = PipeDef(
    {
        "modules": [
            PipeModule(
                {
                    "id": "sw-1",
                    "type": "itembuilder",
                    "conf": ItemBuilderRawConf(
                        {
                            "attrs": Param(
                                {
                                    "key": {"type": "text", "value": "title"},
                                    "value": {"type": "text", "value": "hello"},
                                }
                            )
                        }
                    ),
                }
            ),
            PipeModule({"id": "_OUTPUT", "type": "output", "conf": {}}),
        ],
        "wires": [get_wire("sw-1", "_OUTPUT", "_w1")],
    }
)

# A canonical direct-processor node with a first-class top-level `count`.
DIRECT_COUNT = PipeDef(
    {
        "modules": [
            PipeModule(
                {
                    "id": "sw-1",
                    "type": "itembuilder",
                    "conf": {
                        "attrs": {
                            "key": {"type": "text", "value": "content"},
                            "value": {"type": "text", "value": "a b c"},
                        }
                    },
                }
            ),
            PipeModule(
                {
                    "id": "sw-2",
                    "type": "tokenizer",
                    "field": "content",
                    "count": "first",
                    "conf": {"delimiter": {"type": "text", "value": " "}},
                }
            ),
            PipeModule({"id": "_OUTPUT", "type": "output", "conf": {}}),
        ],
        "wires": [get_wire("sw-1", "sw-2", "_w1"), get_wire("sw-2", "_OUTPUT", "_w2")],
    }
)

MALFORMED = {
    "unknown_module": (
        {
            "modules": [
                {"id": "sw-1", "type": "nonexistent", "conf": {}},
                {"id": "_OUTPUT", "type": "output", "conf": {}},
            ],
            "wires": [get_wire("sw-1", "_OUTPUT", "_w1")],
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

PIPES = {
    "pipe_gen_forever": FOREVER,
    "pipe_gen_itembuilder": ITEMBUILDER,
    "pipe_gen_direct_count": DIRECT_COUNT,
}


class TestNormalizeRawModule:
    def test_ordinary_module_is_identity(self):
        module = PipeModule(
            {
                "id": "sw-1",
                "type": "tokenizer",
                "conf": {"delimiter": {"type": "text", "value": " "}},
            }
        )
        assert normalize_raw_module(module) == module

    def test_legacy_processor_loop_emit_true_becomes_direct_processor(self):
        legacy = PipeModule(
            {
                "id": "sw-598",
                "type": "loop",
                "field": "title",
                "conf": LoopRawConf(
                    {
                        "embed": Embed(
                            {
                                "type": "module",
                                "value": EmbeddedModule(
                                    {
                                        "id": "sw-601",
                                        "type": "regex",
                                        "conf": RegexRawConf(
                                            {
                                                "rule": RegexRawRule(
                                                    {
                                                        "field": {
                                                            "type": "text",
                                                            "value": "content",
                                                        },
                                                        "match": {
                                                            "type": "text",
                                                            "value": r"(\\w+)\\s(\\w+)",
                                                        },
                                                        "replace": {
                                                            "type": "text",
                                                            "value": "$2wide",
                                                        },
                                                    }
                                                )
                                            }
                                        ),
                                        "emit": {"type": "bool", "value": True},
                                    }
                                ),
                            }
                        ),
                    }
                ),
            }
        )
        assert normalize_raw_module(legacy) == {
            "id": "sw-598",
            "type": "regex",
            "conf": {
                "rule": {
                    "field": {
                        "type": "text",
                        "value": "content",
                    },
                    "match": {
                        "type": "text",
                        "value": r"(\\w+)\\s(\\w+)",
                    },
                    "replace": {
                        "type": "text",
                        "value": "$2wide",
                    },
                }
            },
            "field": "title",
            "emit": True,
        }

    def test_legacy_processor_loop_count_first_becomes_direct_processor(self):
        legacy = PipeModule(
            {
                "id": "sw-142",
                "type": "loop",
                "conf": LoopRawConf(
                    {
                        "count": {"type": "text", "value": "first"},
                        "embed": Embed(
                            {
                                "type": "module",
                                "value": EmbeddedModule(
                                    {
                                        "id": "sw-150",
                                        "type": "fetchdata",
                                        "conf": FetchDataRawConf(
                                            {"url": {"subkey": "link", "type": "url"}}
                                        ),
                                        "emit": {"type": "bool", "value": False},
                                        "assign": {"type": "text", "value": "info"},
                                    }
                                ),
                            }
                        ),
                    }
                ),
            }
        )
        assert normalize_raw_module(legacy) == {
            "id": "sw-142",
            "type": "fetchdata",
            "conf": {"url": {"subkey": "link", "type": "url"}},
            "assign": "info",
            "emit": False,
            "count": "first",
        }

    def test_legacy_processor_loop_count_all_assign_stays_loop(self):
        legacy = PipeModule(
            {
                "id": "sw-500",
                "type": "loop",
                "field": "title",
                "conf": LoopRawConf(
                    {
                        "count": {"type": "text", "value": "all"},
                        "embed": Embed(
                            {
                                "type": "module",
                                "value": EmbeddedModule(
                                    {
                                        "id": "sw-508",
                                        "type": "tokenizer",
                                        "conf": TokenizerRawConf(),
                                        "emit": {"type": "bool", "value": False},
                                        "assign": {"type": "text", "value": "terms"},
                                    }
                                ),
                            }
                        ),
                    }
                ),
            }
        )
        # emit=False + count=all + assign diverges from a direct processor
        # (list-wrap vs one copy per result), so it stays a loop embedding it.
        assert legacy_loop_to_canonical(legacy) == {
            "id": "sw-500",
            "type": "loop",
            "embed": {"id": "sw-508", "type": "tokenizer"},
            "conf": {},
            "field": "title",
            "assign": "terms",
            "emit": False,
            "count": "all",
        }
        # normalize_raw_module defers this compact-loop case (leaves it legacy).
        assert normalize_raw_module(legacy) == legacy

    def test_legacy_pipeline_loop_becomes_compact_loop(self):
        subkey = "result.winning-mp.aristotle-id"
        pipe_id = PipeId("pipe:bd0834cfe6cdacb0bea5569505d330b8")
        legacy = PipeModule(
            {
                "id": "sw-595",
                "type": "loop",
                "conf": LoopRawConf(
                    {
                        "count": {"type": "text", "value": "first"},
                        "embed": Embed(
                            {
                                "type": "module",
                                "value": EmbeddedModule(
                                    {
                                        "id": "sw-603",
                                        "type": pipe_id,
                                        "emit": {"type": "bool", "value": False},
                                        "assign": {
                                            "type": "text",
                                            "value": "mpdetails",
                                        },
                                        "conf": SubModuleRawConf(
                                            {"gid": {"subkey": subkey, "type": "text"}}
                                        ),
                                    }
                                ),
                            }
                        ),
                    }
                ),
            }
        )
        # The full transform lifts it to a compact loop...
        assert legacy_loop_to_canonical(legacy) == {
            "id": "sw-595",
            "type": "loop",
            "embed": {
                "id": "sw-603",
                "type": "pipe:bd0834cfe6cdacb0bea5569505d330b8",
            },
            "conf": {"gid": {"subkey": subkey, "type": "text"}},
            "assign": "mpdetails",
            "emit": False,
            "count": "first",
        }

        # ...but normalize_raw_module defers compact loops (leaves them legacy)
        # until the compiler reads the top-level embed ref.
        assert normalize_raw_module(legacy) == legacy

    def test_loop_level_options_win_over_embed_level(self):
        legacy = PipeModule(
            {
                "id": "sw-1",
                "type": "loop",
                "field": "outer",
                "conf": LoopRawConf(
                    {
                        "embed": Embed(
                            {
                                "type": "module",
                                "value": EmbeddedModule(
                                    {
                                        "id": "sw-2",
                                        "type": "tokenizer",
                                        "conf": TokenizerRawConf(),
                                        "field": {"type": "text", "value": "inner"},
                                    }
                                ),
                            }
                        )
                    }
                ),
            }
        )
        assert normalize_raw_module(legacy).get("field") == "outer"


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


def test_codegen_renders_top_level_count():
    parsed = parse_pipe_def(DIRECT_COUNT, "pipe_gen_direct_count")
    assert 'count="first"' in stringify_pipe(parsed)


def test_direct_count_node_applies_count():
    # count="first" reduces the tokenizer's three tokens to one, per parent item
    assert _compile_and_run(DIRECT_COUNT, "pipe_gen_direct_count") == [{"content": "a"}]


def _codegen_pairs():
    pipe_files = sorted(PIPELINE_DIR.glob("pipe_*.json"))
    exists = lambda pfile: (PYPIPELINE_DIR / f"{pfile.stem}.py").exists()
    return list(filter(exists, pipe_files))


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
        resolve_module("pipe_missing", "pipe_missing")

    with pytest.raises(UnsupportedPipelineError):
        resolve_module("pipe_missing", "pipe_missing", compile_missing=True)


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
                "conf": {"count": {"type": "float", "value": "3"}},
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
                        "conf": {"count": {"type": "float", "value": "3"}},
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


@pytest.mark.anyio
@pytest.mark.skipif(issync, reason="async support not installed")
def test_async_codegen_matches_sync():
    """
    ``compile(is_async=True)`` emits a runnable anyio pipeline whose output
    matches the sync compilation.
    """
    import anyio  # noqa: PLC0415

    pipe_def = loads((PIPELINE_DIR / "pipe_gigs.json").read_text())

    async_src = compile_pipe(pipe_def, "pipe_gigs", is_async=True)
    async_ns: dict = {}
    exec(async_src, async_ns)
    async_result = list(anyio.run(async_ns["pipe_gigs"]))

    sync_src = compile_pipe(pipe_def, "pipe_gigs", is_async=False)
    sync_ns: dict = {}
    exec(sync_src, sync_ns)
    sync_result = list(sync_ns["pipe_gigs"]())

    assert async_result
    assert async_result == sync_result
