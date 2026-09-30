# vim: sw=4:ts=4:expandtab
"""
Regression tests for the code-generation path (``stringify_pipe``).

These tie the two compilation paths together: for the same pipe definition the
generated Python module (path a) must, when executed, produce the exact same
stream as the in-process executor ``build_pipeline`` (path b). Any divergence —
or a codegen regression — fails here.
"""

from __future__ import annotations

from keyword import iskeyword
from typing import TYPE_CHECKING

import pytest

from riko.base._strutils import pythonise
from riko.base.exceptions import UnsupportedModuleError
from riko.execution.context import Context
from riko.runtime._compile import (
    build_pipeline,
    compile_pipe_def,
    get_wire,
    parse_pipe_def,
    resolve_module,
    stringify_pipe,
)
from riko.types._compiler import GraphIndex, LoopModule, PipeDef, PipeId, PipeModule
from riko.types.modules import ItemBuilderRawConf, Param, TruncateRawConf
from tests import async_test

if TYPE_CHECKING:
    from riko.types._streams import Item


def _itembuilder_src(title: str, module_id: str = "sw-1") -> PipeModule:
    """Builds a single-item itembuilder source module carrying ``title``."""
    return PipeModule(
        {
            "id": module_id,
            "type": "itembuilder",
            "conf": ItemBuilderRawConf(
                {
                    "attrs": Param(
                        {
                            "key": {"type": "text", "value": "title"},
                            "value": {"type": "text", "value": title},
                        }
                    )
                }
            ),
        }
    )


def _forever_def(count: str) -> PipeDef:
    """Builds an endless source truncated to ``count`` items."""
    return PipeDef(
        {
            "modules": [
                PipeModule({"id": "sw-1", "type": "forever", "conf": {}}),
                PipeModule(
                    {
                        "id": "sw-2",
                        "type": "truncate",
                        "conf": TruncateRawConf(
                            {"count": {"type": "int", "value": count}}
                        ),
                    }
                ),
                PipeModule({"id": "_OUTPUT", "type": "output", "conf": {}}),
            ],
            "wires": [
                get_wire("sw-1", "sw-2", "_w1"),
                get_wire("sw-2", "_OUTPUT", "_w2"),
            ],
        }
    )


FOREVER = _forever_def("2")

ITEMBUILDER = PipeDef(
    {
        "modules": [
            _itembuilder_src("hello"),
            PipeModule({"id": "_OUTPUT", "type": "output", "conf": {}}),
        ],
        "wires": [get_wire("sw-1", "_OUTPUT", "_w1")],
    }
)

ITEMBUILDER_SRC = _itembuilder_src("a b c")

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
                PipeModule({"id": "_OUTPUT", "type": "output", "conf": {}}),
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


def _run_generated(source, pipe_name) -> list[Item]:
    namespace: dict = {}
    exec(compile(source, f"<{pipe_name}>", "exec"), namespace)
    return list(namespace["pipe"](context=Context()))


def _run_executor(parsed) -> list[Item]:
    return list(build_pipeline(parsed, context=Context()))


def _compile_and_run(pipe_def, pipe_name) -> list[Item]:
    return _run_executor(parse_pipe_def(pipe_def, pipe_name))


def _compact_loop_def(
    loop_module: PipeModule, source: PipeModule = ITEMBUILDER_SRC
) -> PipeDef:
    modules = [
        source,
        loop_module,
        PipeModule({"id": "_OUTPUT", "type": "output", "conf": {}}),
    ]
    wires = [get_wire("sw-1", "sw-2", "_w1"), get_wire("sw-2", "_OUTPUT", "_w2")]
    return PipeDef({"modules": modules, "wires": wires})


LOOP_SUBPIPE = _compact_loop_def(
    LoopModule(
        {
            "id": "sw-2",
            "type": "loop",
            "conf": {},
            "embed": {"id": "sw-3", "type": PipeId("pipe:shout")},
            "count": "all",
            "emit": True,
        }
    ),
    _itembuilder_src("hello"),
)

LOOP_ASSIGN = _compact_loop_def(
    LoopModule(
        {
            "id": "sw-2",
            "type": "loop",
            "conf": {"delimiter": {"type": "text", "value": " "}},
            "embed": {"id": "sw-3", "type": "tokenizer"},
            "count": "all",
            "assign": "tokens",
            "emit": False,
            "field": "title",
        }
    )
)


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


@pytest.mark.parametrize("case", list(MALFORMED))
def test_malformed_pipeline_syntax(case):
    pipe_def, expected = MALFORMED[case]

    with pytest.raises(expected):
        _compile_and_run(pipe_def, f"pipe_{case}")


def test_compile_wraps_parse_and_stringify():
    name = "pipe_gen_itembuilder"
    expected = stringify_pipe(parse_pipe_def(ITEMBUILDER, name))

    assert compile_pipe_def(ITEMBUILDER, name) == expected


def test_unresolved_subpipeline_raises():
    with pytest.raises(UnsupportedModuleError):
        resolve_module("pipe_missing")


def test_parse_pipe_def_replaces_wires_with_graph_index():
    parsed = parse_pipe_def(FOREVER, "pipe_gen_forever")
    graph = parsed["graph"]

    assert "wires" not in parsed
    assert isinstance(graph, GraphIndex)
    assert graph.order == ("sw_1", "sw_2", "_OUTPUT")
    assert graph.roots == ("sw_1",)
    assert graph.leaves == ("_OUTPUT",)
    assert graph.dependencies["sw_2"] == frozenset({"sw_1"})
    assert graph.dependents["sw_1"] == frozenset({"sw_2"})


def test_graph_index_indexes_wire_ports():
    graph = parse_pipe_def(FOREVER, "pipe_gen_forever")["graph"]
    (edge,) = graph.incoming["sw_2"]

    assert (edge.source, edge.source_port) == ("sw_1", "_OUTPUT")
    assert (edge.target, edge.target_port) == ("sw_2", "_INPUT")
    assert graph.outgoing["sw_1"] == graph.incoming["sw_2"]
    assert graph.outputs["default"].node == "sw_2"


def test_graph_index_orders_embed_before_its_loop():
    # sw-9 is embedded in the loop sw-2; the embed relationship keeps the embed
    # ahead of its loop even though no wire connects them and its id sorts later.
    loop = LoopModule(
        {
            "id": "sw-2",
            "type": "loop",
            "conf": {"delimiter": {"type": "text", "value": " "}},
            "embed": {"id": "sw-9", "type": "tokenizer"},
            "count": "all",
            "emit": True,
            "field": "title",
        }
    )
    order = parse_pipe_def(_compact_loop_def(loop), "x")["graph"].order

    assert order.index("sw_9") < order.index("sw_2")


@async_test
async def test_async_codegen_matches_sync():
    """
    Ensure async compilation matches sync pipeline output.

    The async path emits a runnable AnyIO pipeline.
    """
    name = "pipe_gen_itembuilder"
    async_src = compile_pipe_def(ITEMBUILDER, name, is_async=True)
    async_ns: dict = {}
    exec(async_src, async_ns)
    async_result = [item async for item in async_ns["async_pipe"]()]

    sync_src = compile_pipe_def(ITEMBUILDER, name, is_async=False)
    sync_ns: dict = {}
    exec(sync_src, sync_ns)
    sync_result = list(sync_ns["pipe"]())
    assert async_result == sync_result


class TestCompactLoopConsumption:
    """
    Compile the compact loop representation directly.

    The top-level ``embed`` references the submodule, ``conf`` holds its config, and
    ``count``, ``emit``, ``assign``, and ``field`` remain at the top level. No
    legacy ``conf.embed.value`` nesting is required.
    """

    def test_compact_processor_loop_emit(self):
        loop = LoopModule(
            {
                "id": "sw-2",
                "type": "loop",
                "conf": {"delimiter": {"type": "text", "value": " "}},
                "embed": {"id": "sw-3", "type": "tokenizer"},
                "count": "all",
                "emit": True,
                "field": "title",
            }
        )
        assert _compile_and_run(_compact_loop_def(loop), "pipe_compact") == [
            {"content": "a"},
            {"content": "b"},
            {"content": "c"},
        ]

    def test_compact_processor_loop_assign_per_parent(self):
        loop = LoopModule(
            {
                "id": "sw-2",
                "type": "loop",
                "conf": {"delimiter": {"type": "text", "value": " "}},
                "embed": {"id": "sw-3", "type": "tokenizer"},
                "count": "all",
                "emit": False,
                "assign": "toks",
                "field": "title",
            }
        )
        assert _compile_and_run(_compact_loop_def(loop), "pipe_compact") == [
            {"title": "a b c", "toks": {"content": "a"}},
            {"title": "a b c", "toks": {"content": "b"}},
            {"title": "a b c", "toks": {"content": "c"}},
        ]


class TestNecessaryLoopFixtures:
    """
    Keep non-collapsible loops in compact-loop form.

    These two cases remain compact loops.
    """

    def test_subpipe_loop_via_top_level_embed(self):
        # A `pipe:` sub-pipeline embed (the top-level EmbedRef confarg) can't be
        # inlined, so it stays a loop and runs once per parent.
        assert _compile_and_run(LOOP_SUBPIPE, "pipe_loop_subpipe") == [
            {"title": "hello", "strconcat": "hello!"}
        ]

    def test_subpipe_loop_codegen_imports_embed(self):
        # codegen must import the sub-pipeline used as a loop embed
        source = stringify_pipe(parse_pipe_def(LOOP_SUBPIPE, "pipe_loop_subpipe"))
        assert "import pipe as pipe_shout" in source
        assert "embed=pipe_shout" in source

    def test_count_all_assign_yields_per_parent_copies(self):
        # count=all + assign keeps one preserved-parent copy per child result — a
        # direct node would list-wrap into a single item, so this stays a loop.
        assert _compile_and_run(LOOP_ASSIGN, "pipe_loop_assign") == [
            {"title": "a b c", "tokens": {"content": "a"}},
            {"title": "a b c", "tokens": {"content": "b"}},
            {"title": "a b c", "tokens": {"content": "c"}},
        ]


@pytest.mark.xfail(
    reason="pythonise does not sanitize ids into valid identifiers yet", strict=True
)
def test_pythonise_yields_valid_identifiers():
    """
    Every generated id must be a legal, non-keyword Python identifier.

    ``pythonise`` only replaces four characters and ASCII-``replace``-encodes, so
    ``"class"``/``"foo bar"``/``"foo.bar"``/``"café"`` survive into generated source
    as invalid identifiers (``"1st"`` already becomes ``"_1st"``).
    ``ext/codegen.py::enum_member_name`` already sanitizes properly.
    """
    results = [pythonise(raw) for raw in ("class", "foo bar", "foo.bar", "1st", "café")]
    assert all(r.isidentifier() and not iskeyword(r) for r in results)
