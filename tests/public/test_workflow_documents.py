# vim: sw=4:ts=4:expandtab
"""Provides public tests for reading, migrating, and writing workflow documents."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from functools import partial
from math import inf, nan
from types import MappingProxyType
from typing import TYPE_CHECKING

import pytest

from riko.base._exceptions import InvalidPipelineError
from riko.definitions._context import Context
from riko.definitions._nodes import (
    ModuleNode,
    PublishEdge,
    ReadNode,
    StreamEdge,
    SubscribeNode,
    WriteNode,
)
from riko.definitions._workflow_definition import Workflow
from riko.definitions._write import WriteMode
from riko.runtime._pipeline import Pipeline
from riko.types._enums import Backends, DocumentShape, Formats
from riko.types._workflow import Endpoint
from riko.types.modules import TruncateRawConf
from tests._workflows import (
    CALLABLE_FLOW,
    CALLABLE_MATCH,
    DAG,
    DAG_DIR,
    DOCUMENT,
    EDGE_FAMILY_MISMATCHES,
    PIPE_DEF,
    RAW_WORKFLOW,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from riko.types._pipedef import DagModule, Embed, PipeDag


_NODE_VALUE_PLACEMENTS = {
    "conf": lambda value: {"name": "tag", "conf": {"x": value}},
    "embed": lambda value: {
        "name": "loop",
        "embed": {"name": "tag", "conf": {"x": value}},
    },
    "policy": lambda value: {
        "family": "cache",
        "name": "cache",
        "policy": {"x": value},
    },
    "params": lambda value: {
        "family": "action",
        "name": "notify",
        "backend": "file",
        "params": {"x": value},
    },
}

_READ_NODE = {"id": "r", "name": "read", "family": "read", "backend": "file"}
_TWO_NODES = [{"id": "a", "name": "fetch"}, {"id": "b", "name": "filter"}]
_CHAIN = {"source": {"node": "a"}, "target": {"node": "b"}}
_CHAINED = {"nodes": _TWO_NODES, "edges": [_CHAIN]}
_ERRORS = {"errors": {"node": "a", "port": "_OUTPUT2"}}
_ROUTED = {"nodes": [{"id": "a", "name": "route"}], "outputs": _ERRORS}
_EXPLICIT_EMPTY = {"nodes": [{"id": "a", "name": "fetch"}], "outputs": {}}
_REPEATED = [{"name": "fetch"}, {"name": "filter"}, {"name": "filter"}]
_TAKEN_ID = [{"name": "fetch"}, {"id": "fetch-1", "name": "sort"}]
_NULL_STRING = {"type": ("string", "null"), "default": None}
_ENUM = {"type": "integer", "default": 1, "enum": (1, 2)}


MODULES: list[DagModule] = [
    {"id": "sw-1", "name": "forever"},
    {
        "id": "sw-2",
        "name": "truncate",
        "conf": TruncateRawConf({"count": {"type": "int", "value": "3"}}),
    },
]

FAN_IN_MODULES: list[DagModule] = [
    {"id": "a", "name": "fetch"},
    {"id": "b", "name": "fetch"},
    {"id": "u", "name": "union"},
]

FAN_IN_WIRES: Sequence[Sequence[str]] = [["a", "u"], ["b", "u", "in:1"]]

RICH_RAW = {
    "version": "2",
    "input_schemas": {"since": "string"},
    "resources": ["db"],
    "nodes": [
        {
            "id": "read-1",
            "name": "read",
            "family": "read",
            "backend": "http",
            "fmt": "json",
        },
        {"id": "filter-1", "name": "filter", "conf": {"rule": {"field": "x"}}},
        {
            "id": "sub-1",
            "name": "listen",
            "family": "subscribe",
            "policy": {"buffer": 0},
        },
        {
            "id": "write-1",
            "name": "store",
            "family": "write",
            "backend": "file",
            "fmt": "csv",
            "mode": "append",
            "keys": ["id"],
            "resources": {"db": "db"},
        },
    ],
    "edges": [
        {"source": {"node": "read-1"}, "target": {"node": "filter-1"}},
        {
            "source": {"node": "filter-1"},
            "target": {"node": "sub-1"},
            "family": "publish",
        },
        {"source": {"node": "filter-1"}, "target": {"node": "write-1"}},
    ],
    "outputs": {"default": {"node": "write-1", "port": "out"}},
}

RICH_GOLDEN = (
    b'{"edges":[{"family":"stream","source":{"node":"read-1","port":"out"},"target":{"'
    b'node":"filter-1","port":"in"}},{"family":"publish","source":{"node":"filter-1","'
    b'port":"out"},"target":{"node":"sub-1","port":"in"}},{"family":"stream","source":'
    b'{"node":"filter-1","port":"out"},"target":{"node":"write-1","port":"in"}}],"inpu'
    b't_schemas":{"since":{"type":"string"}},"nodes":{"filter-1":{"conf":{"rule":{"fie'
    b'ld":"x"}},"family":"module","id":"filter-1","name":"filter"},"read-1":{"backend"'
    b':"http","family":"read","fmt":"json","id":"read-1","name":"read"},"sub-1":{"fami'
    b'ly":"subscribe","id":"sub-1","name":"listen","policy":{"buffer":0}},"write-1":{"'
    b'backend":"file","family":"write","fmt":"csv","id":"write-1","keys":["id"],"mode"'
    b':"append","name":"store","resources":{"db":"db"}}},"outputs":{"default":{"node":'
    b'"write-1","port":"out"}},"resources":["db"],"version":"2"}'
)

TOPOLOGIES = {
    "single-module": {"nodes": [{"name": "fetch"}]},
    "module-chain": {
        "nodes": [{"name": "fetch"}, {"name": "filter"}],
        "edges": [{"source": {"node": "fetch-1"}, "target": {"node": "filter-1"}}],
    },
    "read-write": {
        "nodes": [
            {
                "id": "r",
                "name": "read",
                "family": "read",
                "backend": "s3",
                "fmt": "jsonl",
            },
            {
                "id": "w",
                "name": "store",
                "family": "write",
                "backend": "file",
                "dest": "out.jsonl",
                "keys": ["k"],
            },
        ],
        "edges": [{"source": {"node": "r"}, "target": {"node": "w"}}],
        "outputs": {"default": {"node": "w", "port": "out"}},
    },
    "cache": {
        "nodes": [{"id": "c", "name": "cache", "family": "cache", "policy": {"ttl": 5}}]
    },
    "action": {
        "nodes": [
            {
                "id": "a",
                "name": "notify",
                "family": "action",
                "backend": "intune",
                "params": {"scope": "all"},
            }
        ]
    },
    "publish-subscribe": {
        "nodes": [
            {"id": "p", "name": "produce"},
            {"id": "s", "name": "listen", "family": "subscribe"},
        ],
        "edges": [
            {"source": {"node": "p"}, "target": {"node": "s"}, "family": "publish"}
        ],
        "outputs": {"default": {"node": "p", "port": "out"}},
    },
    "typed-inputs": {
        "nodes": [{"name": "fetch"}],
        "input_schemas": {"limit": {"type": "integer", "minimum": 1}},
    },
    "call-options": {
        "nodes": [
            {
                "id": "n",
                "name": "tokenizer",
                "conf": {"delimiter": {"value": ","}},
                "options": {"emit": True, "count": "first"},
            }
        ]
    },
    "positional-ports": {
        "nodes": [{"id": "a", "name": "union"}, {"id": "b", "name": "fetch"}],
        "edges": [{"source": {"node": "b"}, "target": {"node": "a", "port": "in:1"}}],
        "outputs": {"default": {"node": "a", "port": "out"}},
    },
}

WRITE_PIPE_DEF = {
    "modules": [
        {"id": "sw-1", "type": "fetch", "conf": {}},
        {"id": "sw-2", "type": "write", "conf": {"fmt": "json"}},
        {"id": "_OUTPUT", "type": "output", "conf": {}},
    ],
    "wires": [
        {
            "id": "_w1",
            "src": {"id": "_OUTPUT", "moduleid": "sw-1"},
            "tgt": {"id": "_INPUT", "moduleid": "sw-2"},
        },
        {
            "id": "_w2",
            "src": {"id": "_OUTPUT", "moduleid": "sw-2"},
            "tgt": {"id": "_INPUT", "moduleid": "_OUTPUT"},
        },
    ],
}


PARSE_REJECTIONS = [
    pytest.param({"pipeline": []}, None, "'nodes' or 'modules'", id="unknown-shape"),
    pytest.param(RAW_WORKFLOW, "v3", "Invalid shape", id="unknown-declared-shape"),
    pytest.param("{bad json", None, "malformed JSON", id="bad-json"),
    pytest.param(b"\xff", None, "malformed JSON", id="undecodable-bytes"),
    pytest.param(
        '{"nodes": [{"name": "fetch"}], "nodes": [{"name": "count"}]}',
        None,
        "duplicate key 'nodes'",
        id="duplicate-top-level-key",
    ),
    pytest.param(
        '{"nodes": [{"name": "fetch", "conf": {"url": "a", "url": "b"}}]}',
        None,
        "duplicate key 'url'",
        id="duplicate-nested-key",
    ),
    pytest.param({"nodes": []}, None, "no nodes", id="validates"),
]


DOCUMENTS = [
    pytest.param(
        DAG, DocumentShape.DAG, partial(Workflow.parse, shape="dag"), id="dag"
    ),
    pytest.param(PIPE_DEF, DocumentShape.V1, Workflow.parse, id="v1"),
    pytest.param(RAW_WORKFLOW, DocumentShape.V2, Workflow.from_raw, id="v2"),
    pytest.param(DOCUMENT, DocumentShape.V2, Workflow.from_raw, id="workflow"),
]


class TestWorkflowParse:
    @pytest.mark.parametrize(
        "declare",
        [
            pytest.param(lambda shape: None, id="detected"),
            pytest.param(lambda shape: shape, id="enum"),
            pytest.param(lambda shape: shape.value, id="value"),
        ],
    )
    @pytest.mark.parametrize(("document", "shape", "loader"), DOCUMENTS)
    def test_parse_reads_each_document_shape(self, document, shape, loader, declare):
        """Each readable shape, detected or declared, is read as its loader would."""
        assert Workflow.parse(document, shape=declare(shape)) == loader(document)

    def test_parse_reads_a_workflow_only_as_v2(self):
        flow = Workflow.parse(DAG)
        assert Workflow.parse(flow, shape=DocumentShape.V2) == flow

        with pytest.raises(InvalidPipelineError, match="only be read as shape 'v2'"):
            Workflow.parse(flow, shape=DocumentShape.DAG)

        with pytest.raises(InvalidPipelineError, match="Invalid shape"):
            Workflow.parse(flow, shape="v3")

    @pytest.mark.parametrize(("document", "shape", "loader"), DOCUMENTS)
    def test_parse_is_idempotent(self, document, shape, loader):
        flow = Workflow.parse(document)
        assert Workflow.parse(flow) == flow

    def test_parse_reads_pipe_dag_text(self):
        assert Workflow.parse(json.dumps(DAG)) == Workflow.parse(DAG)

    @pytest.mark.parametrize(
        ("document", "shape"),
        [
            pytest.param(DAG, DocumentShape.V2, id="dag-as-v2"),
            pytest.param(DAG, DocumentShape.V1, id="dag-as-v1"),
            pytest.param(PIPE_DEF, DocumentShape.DAG, id="v1-as-dag"),
            pytest.param(PIPE_DEF, DocumentShape.V2, id="v1-as-v2"),
            pytest.param(RAW_WORKFLOW, DocumentShape.DAG, id="v2-as-dag"),
            pytest.param(RAW_WORKFLOW, DocumentShape.V1, id="v2-as-v1"),
        ],
    )
    def test_parse_rejects_a_document_read_as_another_shape(self, document, shape):
        """A document read as a shape it is not written in is rejected, not guessed."""
        with pytest.raises(InvalidPipelineError):
            Workflow.parse(document, shape=shape)

    @pytest.mark.parametrize(("document", "shape", "match"), PARSE_REJECTIONS)
    def test_parse_rejects(self, document, shape, match):
        with pytest.raises(InvalidPipelineError, match=match):
            Workflow.parse(document, shape=shape)

    def test_a_document_cannot_declare_a_callable_node(self):
        raw = {"nodes": [{"name": "len", "family": "callable"}]}

        with pytest.raises(InvalidPipelineError, match="cannot hold a callable node"):
            Workflow.parse(raw)


def _dag(name: str) -> PipeDag:
    """Loads a committed fixture holding a serialized ``PipeDag``."""
    return json.loads((DAG_DIR / f"{name}.json").read_text())


def _edges(flow: Workflow) -> list[tuple[str, str]]:
    """Projects a workflow's edges onto their source and target node ids."""
    return [(edge.source.node, edge.target.node) for edge in flow.edges]


def _module_node(flow: Workflow, node_id: str) -> ModuleNode:
    """Narrows one of a workflow's nodes to a module node."""
    node = flow.nodes[node_id]
    assert isinstance(node, ModuleNode)
    return node


class TestPipeDag:
    def test_null_wires_chain_in_listing_order(self):
        linear = Workflow.parse({"modules": MODULES, "wires": None})
        wired = Workflow.parse({"modules": MODULES, "wires": [["sw-1", "sw-2"]]})
        assert linear == wired
        assert _edges(linear) == [("sw-1", "sw-2")]

    def test_wires_override_listing_order(self):
        flow = Workflow.parse(_dag("pipe_reordered"))
        assert _edges(flow) == [("gen", "trunc")]
        assert flow.outputs["default"] == Endpoint("trunc", "out")

    def test_third_wire_entry_sets_the_target_port(self):
        flow = Workflow.parse({"modules": FAN_IN_MODULES, "wires": FAN_IN_WIRES})
        ports = [(edge.source.port, edge.target.port) for edge in flow.edges]
        assert ports == [("out", "in"), ("out", "in:1")]
        assert flow.outputs["default"] == Endpoint("u", "out")

    def test_conf_survives_verbatim(self):
        flow = Workflow.parse({"modules": MODULES})
        assert dict(_module_node(flow, "sw-2").conf) == {
            "count": {"type": "int", "value": "3"}
        }

    def test_options_pass_through(self):
        modules: list[DagModule] = [
            {"id": "t", "type": "tokenizer", "options": {"emit": True}}
        ]
        flow = Workflow.parse({"modules": modules})
        assert _module_node(flow, "t").options.kwargs == {"emit": True}

    def test_pipe_dag_accepts_the_older_type_spelling_of_name(self):
        named = Workflow.parse({"modules": [{"name": "forever"}]})
        typed = Workflow.parse({"modules": [{"type": "forever"}]})
        agreeing = Workflow.parse({"modules": [{"name": "forever", "type": "forever"}]})
        assert named == typed == agreeing
        assert _module_node(typed, "sw-1").name == "forever"

    def test_pipe_dag_offers_known_node_fields_to_the_node(self):
        embed: Embed = {"name": "fetch", "conf": {}}
        flow = Workflow.parse({"modules": [{"name": "loop", "embed": embed}]})
        module = _module_node(flow, "sw-1")
        assert module.embed is not None
        assert module.embed["name"] == "fetch"

    def test_reordered_dag_runs_in_wired_order(self):
        flow = Workflow.parse(_dag("pipe_reordered"))
        assert list(Pipeline(flow)) == [{"forever": True}] * 2

    @pytest.mark.parametrize(
        ("document", "message"),
        [
            pytest.param({"modules": []}, "no nodes", id="empty-modules"),
            pytest.param({"modules": None}, "must be a list", id="null-modules"),
            pytest.param({"modules": [1]}, "module must be a mapping", id="int-module"),
            pytest.param(
                {"modules": [{"type": "forever"}], "wires": 5},
                "must be a list",
                id="scalar-wires",
            ),
        ],
    )
    def test_parse_rejects_invalid_pipe_dags(self, document, message, caplog):
        with pytest.raises(InvalidPipelineError, match=message):
            Workflow.parse(document)

        assert not any("pipe definition" in r.message for r in caplog.records)

    @pytest.mark.parametrize("wire", [["a"], ["a", "u", "in:1", "extra"]])
    def test_bad_wire_length_raises_invalid_pipeline(self, wire: list[str]):
        with pytest.raises(InvalidPipelineError, match="wire"):
            Workflow.parse({"modules": FAN_IN_MODULES, "wires": [wire]})

    @pytest.mark.parametrize(
        ("module", "message"),
        [
            pytest.param({"name": "forever", "bogus": 1}, "bogus", id="unknown-key"),
            pytest.param(
                {"type": "forever", "name": "sort"},
                "conflicting",
                id="name-type-conflict",
            ),
            pytest.param(
                {"id": "x", "options": 0}, "needs a 'name'", id="missing-name"
            ),
            pytest.param(
                {"name": "forever", "family": "module"}, "family", id="node-family-key"
            ),
        ],
    )
    def test_pipe_dag_reports_unknown_module_keys(self, module, message):
        with pytest.raises(InvalidPipelineError, match=message):
            Workflow.parse({"modules": [module]})


NON_JSON_NODE_VALUES = [
    pytest.param("conf", Decimal("1.50"), id="conf-decimal"),
    pytest.param("conf", date(2020, 6, 15), id="conf-date"),
    pytest.param("conf", {"a", "b"}, id="conf-set"),
    pytest.param("conf", b"bytes", id="conf-bytes"),
    pytest.param("conf", nan, id="conf-nan"),
    pytest.param("conf", inf, id="conf-inf"),
    pytest.param("embed", date(2020, 6, 15), id="embed-date"),
    pytest.param("policy", {"a", "b"}, id="policy-set"),
    pytest.param("params", nan, id="params-nan"),
]


NORMALIZED_OUTPUTS = [
    pytest.param(_CHAINED, {"default": Endpoint("b", "out")}, id="single-leaf"),
    pytest.param({"nodes": _TWO_NODES}, {}, id="ambiguous-leaves"),
    pytest.param(_ROUTED, {"errors": Endpoint("a", "out:1")}, id="legacy-port-alias"),
    pytest.param(_EXPLICIT_EMPTY, {}, id="explicit-empty"),
]

INPUT_SCHEMAS = [
    pytest.param("string", {"type": "string"}, id="type-name"),
    pytest.param(
        {"type": "integer", "default": 0},
        {"type": "integer", "default": 0},
        id="schema",
    ),
    pytest.param({"type": "string", "default": None}, _NULL_STRING, id="null-default"),
    pytest.param(
        {"type": ["string", "null"], "default": None}, _NULL_STRING, id="nullable"
    ),
    pytest.param({"default": None}, {"default": None}, id="untyped-null-default"),
    pytest.param({"type": ["string"], "default": None}, _NULL_STRING, id="type-list"),
    pytest.param(_ENUM, _ENUM, id="enum"),
]
BAD_INPUT_SCHEMAS = [
    pytest.param(5, "type name or mapping", id="number"),
    pytest.param(["a"], "type name or mapping", id="list"),
    pytest.param(None, "type name or mapping", id="null"),
    pytest.param("strng", "invalid schema: data.type must be", id="unknown-type"),
    pytest.param({"type": []}, "invalid schema", id="empty-type-list"),
    pytest.param({"minimum": "x"}, "invalid schema", id="malformed-keyword"),
]


NODE_IDS = [
    pytest.param(_REPEATED, ["fetch-1", "filter-1", "filter-2"], id="occurrence-ids"),
    pytest.param([{"id": "keep", "name": "fetch"}], ["keep"], id="explicit-id-kept"),
    pytest.param({"a": {"id": "a", "name": "fetch"}}, ["a"], id="key-matches-id"),
    pytest.param(_TAKEN_ID, ["fetch-2", "fetch-1"], id="generated-skip-explicit"),
]


class TestNormalizeWorkflow:
    @pytest.mark.parametrize(("nodes", "expected"), NODE_IDS)
    def test_node_ids(self, nodes, expected):
        assert list(Workflow.from_raw({"nodes": nodes}).nodes) == expected

    def test_mapping_nodes_keep_explicit_ids(self):
        flow = Workflow.from_raw({"nodes": {"a": {"name": "fetch"}}})
        assert isinstance(flow.nodes["a"], ModuleNode)
        assert flow.nodes["a"].name == "fetch"

    def test_family_dispatch_and_enum_coercion(self):
        flow = Workflow.from_raw(
            {
                "nodes": [
                    {"name": "read", "family": "read", "backend": "file", "fmt": "csv"},
                    {
                        "name": "write",
                        "family": "write",
                        "backend": "s3",
                        "fmt": "jsonl",
                        "mode": "append",
                        "keys": "id",
                    },
                ]
            }
        )
        read = flow.nodes["read-1"]
        write = flow.nodes["write-1"]
        assert isinstance(read, ReadNode)
        assert read.backend is Backends.FILE
        assert read.fmt is Formats.CSV
        assert isinstance(write, WriteNode)
        assert write.backend is Backends.S3
        assert write.fmt is Formats.JSONL
        assert write.mode is WriteMode.APPEND
        assert write.keys == ("id",)

    @pytest.mark.parametrize(
        ("source", "target", "expected"),
        [
            pytest.param(
                {"node": "a", "port": "_OUTPUT"},
                {"node": "b", "port": "_OTHER"},
                ("out", "in:1"),
                id="legacy",
            ),
            pytest.param({"node": "a"}, {"node": "b"}, ("out", "in"), id="omitted"),
            pytest.param(
                {"node": "a", "port": None},
                {"node": "b", "port": None},
                ("out", "in"),
                id="null",
            ),
            pytest.param(
                {"node": "a"},
                {"node": "b", "port": "in:count"},
                ("out", "in:count"),
                id="named-preserved",
            ),
        ],
    )
    def test_edge_ports_normalize_to_canonical_endpoints(
        self, source, target, expected
    ):
        flow = Workflow.from_raw(
            {"nodes": _TWO_NODES, "edges": [{"source": source, "target": target}]}
        )
        source_port, target_port = expected
        assert flow.edges == (
            StreamEdge(Endpoint("a", source_port), Endpoint("b", target_port)),
        )

    def test_publish_edge_detected_from_subscribe_target(self):
        flow = Workflow.from_raw(
            {
                "nodes": [
                    {"id": "a", "name": "fetch"},
                    {"id": "s", "name": "sub", "family": "subscribe"},
                ],
                "edges": [{"source": {"node": "a"}, "target": {"node": "s"}}],
            }
        )
        assert isinstance(flow.nodes["s"], SubscribeNode)
        assert isinstance(flow.edges[0], PublishEdge)

    @pytest.mark.parametrize(("raw", "expected"), NORMALIZED_OUTPUTS)
    def test_outputs_normalize(self, raw, expected):
        assert Workflow.from_raw(raw).outputs == expected

    @pytest.mark.parametrize(("raw_schema", "schema"), INPUT_SCHEMAS)
    def test_input_schemas_normalize(self, raw_schema, schema):
        def normalize(value: object):
            raw = {
                "nodes": [{"id": "a", "name": "fetch"}],
                "input_schemas": {"n": value},
            }
            return Workflow.parse(raw).input_schemas["n"]

        normalized = normalize(raw_schema)
        assert (normalized, normalize(normalized)) == (schema, schema)

    def test_bare_string_resource_binds_to_itself(self):
        flow = Workflow.from_raw(
            {"nodes": [{"id": "a", "name": "fetch", "resources": "db"}]}
        )
        assert flow.nodes["a"].resources == {"db": "db"}

    @pytest.mark.parametrize(
        ("resources", "expected"),
        [
            pytest.param(["db", "cache"], ("db", "cache"), id="list"),
            pytest.param("db", ("db",), id="bare-string"),
        ],
    )
    def test_top_level_resources_normalize_to_tuple(self, resources, expected):
        flow = Workflow.from_raw(
            {"nodes": [{"id": "a", "name": "fetch"}], "resources": resources}
        )
        assert flow.resources == expected

    def test_explicit_stream_family_to_subscribe_is_preserved(self):
        flow = Workflow.from_raw(
            {
                "nodes": [
                    {"id": "a", "name": "fetch"},
                    {"id": "s", "name": "sub", "family": "subscribe"},
                ],
                "edges": [
                    {
                        "source": {"node": "a"},
                        "target": {"node": "s"},
                        "family": "stream",
                    }
                ],
            }
        )
        assert isinstance(flow.edges[0], StreamEdge)

    def test_write_dest_is_preserved(self):
        flow = Workflow.from_raw(
            {
                "nodes": [
                    {
                        "name": "w",
                        "family": "write",
                        "backend": "file",
                        "dest": "out.json",
                    }
                ]
            }
        )
        write = flow.nodes["w-1"]
        assert isinstance(write, WriteNode)
        assert write.dest == "out.json"

    @pytest.mark.parametrize(
        "raw",
        [
            pytest.param(
                {
                    "nodes": [
                        {"name": "fetch"},
                        {"name": "write", "family": "write", "backend": "file"},
                    ],
                    "edges": [
                        {"source": {"node": "fetch-1"}, "target": {"node": "write-1"}}
                    ],
                },
                id="write-chain",
            ),
            pytest.param(
                {
                    "nodes": [
                        {
                            "name": "loop",
                            "embed": {"name": "tokenizer", "conf": {"d": " "}},
                        }
                    ]
                },
                id="embed",
            ),
        ],
    )
    def test_normalizing_a_workflow_is_a_fixed_point(self, raw):
        first = Workflow.from_raw(raw)
        assert Workflow.from_raw(first) == first
        assert Workflow.from_raw(Workflow.from_raw(first)) == first

    def test_normalize_renormalizes_a_hand_built_workflow(self):
        a = ModuleNode(id="a", name="fetch")
        b = ModuleNode(id="b", name="filter")
        hand = Workflow(
            nodes=[a, b],
            edges=(StreamEdge(Endpoint("a", "_OUTPUT"), Endpoint("b", "_OTHER2")),),
            outputs={"default": Endpoint("b", "_OUTPUT")},
            input_schemas={},
        )
        normalized = Workflow.from_raw(hand)
        assert normalized.edges[0].source.port == "out"
        assert normalized.edges[0].target.port == "in:2"
        assert normalized.outputs["default"].port == "out"

    @pytest.mark.parametrize(("edge", "target"), EDGE_FAMILY_MISMATCHES)
    def test_renormalizing_keeps_an_edge_family(self, edge, target):
        """A mismatched edge family is kept, not inferred from its target."""
        flow = Workflow(
            nodes=[ModuleNode(id="a", name="fetch"), target],
            edges=[edge(Endpoint("a", "out"), Endpoint("b", "in"))],
            outputs={"default": Endpoint("a", "out")},
        )
        assert Workflow.from_raw(flow) == flow

    @pytest.mark.parametrize(
        "spelling",
        [
            pytest.param({"format": "csv"}, id="format-alias"),
            pytest.param({"fmt": "csv", "format": "csv"}, id="agreeing-fmt-format"),
        ],
    )
    def test_format_alias_maps_to_fmt(self, spelling):
        flow = Workflow.from_raw({"nodes": [{**_READ_NODE, **spelling}]})
        read = flow.nodes["r"]
        assert isinstance(read, ReadNode)
        assert read.fmt is Formats.CSV

    def test_raw_call_options_are_accepted(self):
        flow = Workflow.from_raw(
            {
                "nodes": [
                    {
                        "name": "tokenizer",
                        "options": {"field": "title", "count": "first"},
                    }
                ]
            }
        )
        node = flow.nodes["tokenizer-1"]
        assert isinstance(node, ModuleNode)
        assert node.options.kwargs == {"field": "title", "count": "first"}
        assert node.conf == {}

    def test_nested_conf_is_deeply_frozen_and_isolated(self):
        inner = {"k": 1}
        conf = {"nested": inner, "list": [1, 2]}
        flow = Workflow.from_raw({"nodes": [{"id": "a", "name": "f", "conf": conf}]})
        inner["k"] = 99
        conf["list"] = [3]
        node = flow.nodes["a"]
        assert isinstance(node, ModuleNode)
        assert node.conf is not None
        assert node.conf.get("nested") == {"k": 1}
        assert node.conf.get("list") == (1, 2)
        with pytest.raises(TypeError):
            node.conf["nested"]["k"] = 2  # type: ignore[index]

    def test_raw_embed_becomes_a_read_only_node_field(self):
        flow = Workflow.from_raw(
            {
                "nodes": [
                    {"name": "loop", "embed": {"name": "tokenizer", "conf": {"d": " "}}}
                ]
            }
        )
        node = flow.nodes["loop-1"]
        assert isinstance(node, ModuleNode)
        assert node.embed == {"name": "tokenizer", "conf": {"d": " "}}
        with pytest.raises(TypeError):
            node.embed["name"] = "hash"  # type: ignore[index]
        assert node.conf == {}

    def test_embed_conf_defaults_to_empty_when_omitted(self):
        flow = Workflow.from_raw(
            {"nodes": [{"name": "loop", "embed": {"name": "tokenizer"}}]}
        )
        node = flow.nodes["loop-1"]
        assert isinstance(node, ModuleNode)
        assert node.embed == {"name": "tokenizer", "conf": {}}

    @pytest.mark.parametrize(
        ("node", "match"),
        [
            pytest.param({"name": "fetch", "resources": 5}, "'resources'", id="res"),
            pytest.param(
                {"name": "w", "family": "write", "backend": "file", "keys": 5},
                "WriteNode 'keys' must be a string",
                id="keys-type",
            ),
            pytest.param(
                {"name": "w", "family": "write", "backend": "file", "keys": ["a", "a"]},
                "duplicate WriteNode 'keys'",
                id="keys-duplicate",
            ),
            pytest.param(
                {"name": "w", "family": "write"},
                r"missing WriteNode key\(s\): \['backend'\]",
                id="missing-backend",
            ),
            pytest.param(
                {"name": "r", "family": "read", "backend": "ftp"},
                "Invalid Backends",
                id="unknown-backend",
            ),
            pytest.param(
                {"name": "x", "family": "sink"},
                "unknown node family",
                id="unknown-family",
            ),
            pytest.param({"family": "module"}, "node 'name'", id="missing-name"),
            pytest.param(
                {"name": "w", "family": "write", "backend": "file", "mode": "apend"},
                "Invalid WriteMode",
                id="invalid-write-mode",
            ),
            pytest.param(
                {"name": "r", "family": "read", "backend": "file", "fmt": "xml"},
                "Invalid Formats",
                id="invalid-format",
            ),
            pytest.param(
                {"name": "fetch", "bogus": 1},
                "unknown ModuleNode key",
                id="unknown-field",
            ),
            pytest.param({"name": "fetch", "conf": []}, "Node 'conf'", id="falsy-conf"),
            pytest.param(
                {**_READ_NODE, "fmt": "csv", "format": "jsonl"},
                "conflicting node 'fmt'/'format'",
                id="conflicting-fmt-format",
            ),
            pytest.param(
                {"name": "tokenizer", "options": {"bogus": 1}},
                "unknown ModuleNode 'options' key",
                id="unknown-call-option",
            ),
            pytest.param(
                {"name": "loop", "embed": {"name": "tokenizer", "bogus": 1}},
                "unknown ModuleNode 'embed' key",
                id="unknown-embed-key",
            ),
            pytest.param(
                {"name": "loop", "embed": {"conf": {}}},
                "missing ModuleNode 'embed' key",
                id="embed-without-name",
            ),
            pytest.param(
                {"id": "a", "type": "fetch", "conf": {"url": "x"}},
                "a module goes in 'name'",
                id="type-key",
            ),
            pytest.param(
                {"id": "n", "family": "cache", "name": "cache", "policy": {1: True}},
                "mapping key must be of type str",
                id="non-string-policy-key",
            ),
        ],
    )
    def test_malformed_node_values_raise_invalid_pipeline(self, node, match):
        with pytest.raises(InvalidPipelineError, match=match):
            Workflow.from_raw({"nodes": [node]})

    @pytest.mark.parametrize(
        ("raw", "match"),
        [
            pytest.param(
                {"nodes": [{"name": "fetch"}], "bogus": 1},
                "unknown Workflow key",
                id="unknown-top-level-field",
            ),
            pytest.param(
                {
                    "nodes": [
                        {"id": "a", "name": "fetch"},
                        {"id": "a", "name": "filter"},
                    ]
                },
                "duplicate node id",
                id="duplicate-ids",
            ),
            pytest.param(
                {"nodes": {"a": {"id": "b", "name": "fetch"}}},
                "conflicts",
                id="mapping-key-conflicts-inner-id",
            ),
            pytest.param(
                {
                    "nodes": _TWO_NODES,
                    "edges": [
                        {"source": {"node": "a"}, "target": {"node": "b"}, "bogus": 1}
                    ],
                },
                "unknown PortEdge key",
                id="unknown-edge-field",
            ),
            pytest.param(
                {
                    "nodes": _TWO_NODES,
                    "edges": [
                        {
                            "source": {"node": "a"},
                            "target": {"node": "b"},
                            "family": "broadcast",
                        }
                    ],
                },
                "unknown edge family",
                id="unknown-edge-family",
            ),
            pytest.param(
                {
                    "nodes": _TWO_NODES,
                    "edges": [
                        {
                            "source": {"node": "a"},
                            "target": {"node": "b"},
                            "type": "stream",
                        }
                    ],
                },
                "type",
                id="edge-type-key",
            ),
            pytest.param(
                {
                    "nodes": _TWO_NODES,
                    "edges": [
                        {
                            "source": {"node": "a"},
                            "target": {"node": "b", "porrt": "in"},
                        }
                    ],
                },
                "unknown Endpoint key",
                id="unknown-endpoint-field",
            ),
            *(
                pytest.param(
                    {
                        "nodes": _TWO_NODES,
                        "edges": [{alias: {"node": "a"}, "target": {"node": "b"}}],
                    },
                    "'source'/'target'",
                    id=f"edge-alias-{alias}",
                )
                for alias in ("src", "tgt", "from", "to")
            ),
        ],
    )
    def test_malformed_graphs_raise_invalid_pipeline(self, raw, match):
        with pytest.raises(InvalidPipelineError, match=match):
            Workflow.from_raw(raw)

    def test_invalid_port_rejected(self):
        edge = {"source": {"node": "a"}, "target": {"node": "b", "port": "out:"}}

        with pytest.raises(InvalidPipelineError, match="invalid port: 'out:'"):
            Workflow.from_raw({"nodes": _TWO_NODES, "edges": [edge]})

    @pytest.mark.parametrize(("raw_schema", "match"), BAD_INPUT_SCHEMAS)
    def test_input_without_type_name_or_schema_raises(self, raw_schema, match):
        raw = {
            "nodes": [{"id": "a", "name": "fetch"}],
            "input_schemas": {"n": raw_schema},
        }

        with pytest.raises(InvalidPipelineError, match=match):
            Workflow.parse(raw)

    @pytest.mark.parametrize(("placement", "value"), NON_JSON_NODE_VALUES)
    def test_non_json_native_node_value_rejected(self, placement, value):
        raw = {"nodes": [{"id": "n", **_NODE_VALUE_PLACEMENTS[placement](value)}]}

        with pytest.raises(InvalidPipelineError, match="JSON-native"):
            Workflow.from_raw(raw)

    @pytest.mark.parametrize(
        "options",
        [
            {"assign": b"bytes"},
            {"field": float("nan")},
            {"emit": "yes"},
            {"count": "x"},
            {"count": ["first"]},
        ],
    )
    def test_mistyped_option_rejected(self, options):
        raw = {"nodes": [{"id": "n", "name": "tag", "options": options}]}

        with pytest.raises(InvalidPipelineError, match="CallOptions"):
            Workflow.from_raw(raw)

    def test_a_callable_node_has_no_document_form(self):
        with pytest.raises(InvalidPipelineError, match=CALLABLE_MATCH):
            Workflow.from_raw(CALLABLE_FLOW)


def _wire(wid, src_mod, tgt_mod, src_port="_OUTPUT", tgt_port="_INPUT"):
    return {
        "id": wid,
        "src": {"id": src_port, "moduleid": src_mod},
        "tgt": {"id": tgt_port, "moduleid": tgt_mod},
    }


UPPERCASE_CONFS = [
    pytest.param({"URL": {"value": "x"}}, {"url": {"value": "x"}}, id="mapping"),
    pytest.param({"URL": [{"VALUE": "x"}]}, {"url": ({"value": "x"},)}, id="list"),
]


_FETCH = {"id": "a", "type": "fetch", "conf": {}}
_INPUT = {"id": "i", "type": "input", "conf": {"name": "q", "default": "x"}}
_OUT = {"id": "_OUTPUT", "type": "output", "conf": {}}
_WIRE = _wire("_w1", "a", "_OUTPUT")

MALFORMED_DOCUMENTS = [
    pytest.param(
        {"modules": [_FETCH, _OUT], "wires": [_WIRE], "bogus": 1},
        "unknown pipe definition key",
        id="pipe-def-unknown-key",
    ),
    pytest.param(
        {"modules": [_FETCH, _OUT], "wires": [{**_WIRE, "bogus": 1}]},
        "unknown wire key",
        id="wire-unknown-key",
    ),
    pytest.param(
        {
            "modules": [_FETCH, _OUT],
            "wires": [{**_WIRE, "src": {"id": "_OUTPUT", "moduleid": "a", "x": 1}}],
        },
        "unknown wire endpoint key",
        id="wire-endpoint-unknown-key",
    ),
    pytest.param(
        {"modules": [_FETCH, {**_OUT, "conf": {"x": 1}}], "wires": [_WIRE]},
        "output node takes no 'conf'",
        id="output-module-conf",
    ),
    pytest.param(
        {"modules": [_FETCH, {**_OUT, "bogus": 1}], "wires": [_WIRE]},
        "unknown `PipeDef` output node key",
        id="output-module-unknown-key",
    ),
    pytest.param(
        {"modules": [{"name": "forever"}], "bogus": 1},
        "unknown dag key",
        id="dag-unknown-key",
    ),
    pytest.param(
        {"modules": [_INPUT, {**_INPUT, "id": "j", "conf": {"name": "q"}}, _OUT]},
        "gives input 'q' two different schemas",
        id="input-schema-clash",
    ),
    pytest.param(
        {"modules": [{**_INPUT, "conf": {"type": {"x": 1}}}, _OUT]},
        "input 'type' must be a string or a ConfArg",
        id="input-type-mapping",
    ),
]

_TYPED = {"type": "text", "value": "int"}
_INT = {"type": "integer"}
_STR = {"type": "string"}

MIGRATED_INPUTS = [
    pytest.param(
        {"name": "q", "default": {"type": "int", "value": "5"}},
        "q",
        {**_STR, "default": "5"},
        {},
        id="default-type-ignored",
    ),
    pytest.param(
        {"name": "q", "prompt": {"type": "text", "value": "Term:"}},
        "q",
        {**_STR, "description": "Term:"},
        {},
        id="prompt",
    ),
    pytest.param(
        {"input_key": {"type": "text", "value": "k"}},
        "k",
        _STR,
        {},
        id="input-key-name",
    ),
    pytest.param(
        {"type": _TYPED}, "content", _INT, {"type": _TYPED}, id="content-name"
    ),
    pytest.param({"type": "int"}, "content", _INT, {"type": _TYPED}, id="bare-type"),
]
V1_TYPED_DEFAULTS = [
    pytest.param("int", "5", {**_INT, "default": 5}, id="int"),
    pytest.param("int", "x", {**_STR, "default": "x"}, id="unparseable-int"),
    pytest.param("float", "1.5", {"type": "number", "default": 1.5}, id="float"),
    pytest.param("decimal", "2", {"type": "number", "default": 2.0}, id="decimal"),
    pytest.param("bool", "Yes", {"type": "boolean", "default": True}, id="bool"),
    pytest.param("bool", "maybe", {**_STR, "default": "maybe"}, id="unparseable-bool"),
    pytest.param("url", "file://a.xml", {**_STR, "default": "file://a.xml"}, id="url"),
    pytest.param("date", "10/14/2010", {**_STR, "default": "10/14/2010"}, id="date"),
    pytest.param("text", "", {**_STR, "default": ""}, id="text"),
]


class TestMigrate:
    def test_terminal_output_becomes_default_output(self):
        flow = Workflow.parse(
            {
                "modules": [
                    {"id": "sw-1", "type": "fetch", "conf": {}},
                    {"id": "_OUTPUT", "type": "output", "conf": {}},
                ],
                "wires": [_wire("_w1", "sw-1", "_OUTPUT")],
            }
        )
        assert list(flow.nodes) == ["sw-1"]
        assert flow.outputs["default"] == Endpoint("sw-1", "out")
        assert flow.edges == ()
        assert flow.version == "2"

    @pytest.mark.parametrize(
        ("source_port", "target_port", "expected"),
        [
            pytest.param("_OUTPUT", "_OTHER1", ("out", "in:1"), id="legacy"),
            pytest.param(None, None, ("out", "in"), id="null"),
            pytest.param("_OUTPUT", "count", ("out", "in:count"), id="named"),
            pytest.param("_OUTPUT", "1_URL", ("out", "in:_1_URL"), id="sanitized"),
            pytest.param("_OUTPUT", "PARAM_5_x", ("out", "in:PARAM_5_x"), id="param"),
        ],
    )
    def test_wire_ports_map_to_canonical_endpoints(
        self, source_port, target_port, expected
    ):
        flow = Workflow.parse(
            {
                "modules": [
                    {"id": "a", "type": "fetch", "conf": {}},
                    {"id": "b", "type": "urlbuilder", "conf": {}},
                ],
                "wires": [_wire("_w1", "a", "b", source_port, target_port)],
            }
        )
        source, target = expected
        assert flow.edges[0].source == Endpoint("a", source)
        assert flow.edges[0].target == Endpoint("b", target)

    def test_write_module_preserves_destination_mode_and_keys(self):
        flow = Workflow.parse(
            {
                "modules": [
                    {
                        "id": "w",
                        "type": "write",
                        "conf": {
                            "dest": "out.jsonl",
                            "fmt": "jsonl",
                            "mode": "append",
                            "keys": "id",
                        },
                    }
                ]
            }
        )
        node = flow.nodes["w"]
        assert isinstance(node, WriteNode)
        assert node.dest == "out.jsonl"
        assert node.fmt is Formats.JSONL
        assert node.mode is WriteMode.APPEND
        assert node.keys == ("id",)

    @pytest.mark.parametrize(
        ("pipe_def_mode", "mode"),
        [
            ("wb+", WriteMode.REPLACE),
            ("w", WriteMode.REPLACE),
            ("ab", WriteMode.APPEND),
            ("a+", WriteMode.APPEND),
        ],
    )
    def test_pipe_def_file_open_mode_translates(self, pipe_def_mode, mode):
        flow = Workflow.parse(
            {
                "modules": [
                    {
                        "id": "w",
                        "type": "write",
                        "conf": {"dest": "o.json", "mode": pipe_def_mode},
                    }
                ]
            }
        )
        node = flow.nodes["w"]
        assert isinstance(node, WriteNode)
        assert node.mode is mode

    def test_write_module_without_format_defaults_to_none(self):
        flow = Workflow.parse(
            {"modules": [{"id": "w", "type": "write", "conf": {"dest": "out.dat"}}]}
        )
        node = flow.nodes["w"]
        assert isinstance(node, WriteNode)
        assert node.backend is Backends.FILE
        assert node.fmt is None

    def test_module_call_options_become_node_options(self):
        flow = Workflow.parse(
            {
                "modules": [
                    {
                        "id": "c",
                        "type": "count",
                        "conf": {"x": 1},
                        "emit": True,
                        "assign": "total",
                        "field": "title",
                        "count": "first",
                    }
                ]
            }
        )
        node = flow.nodes["c"]
        assert isinstance(node, ModuleNode)
        assert node.conf == {"x": 1}
        assert node.options.kwargs == {
            "emit": True,
            "assign": "total",
            "field": "title",
            "count": "first",
        }

    def test_call_option_does_not_collide_with_a_same_named_conf_key(self):
        flow = Workflow.parse(
            {
                "modules": [
                    {
                        "id": "t",
                        "type": "truncate",
                        "conf": {"count": {"value": 3}},
                        "count": "first",
                    }
                ]
            }
        )
        node = flow.nodes["t"]
        assert isinstance(node, ModuleNode)
        assert node.conf == {"count": {"value": 3}}
        assert node.options.kwargs == {"count": "first"}

    def test_loop_embed_and_its_configuration_become_the_node_embed(self):
        flow = Workflow.parse(
            {
                "modules": [
                    {
                        "id": "sw-2",
                        "type": "loop",
                        "embed": {"id": "sw-3", "type": "tokenizer"},
                        "conf": {"delimiter": {"value": ","}},
                        "count": "first",
                        "assign": "words",
                        "emit": True,
                        "field": "title",
                    }
                ]
            }
        )
        node = flow.nodes["sw-2"]
        assert isinstance(node, ModuleNode)
        assert node.conf == {}
        assert node.embed == {
            "name": "tokenizer",
            "conf": {"delimiter": {"value": ","}},
        }
        assert node.options.kwargs == {
            "count": "first",
            "assign": "words",
            "emit": True,
            "field": "title",
        }

    def test_loop_embedded_subpipe_keeps_its_prefixed_name(self):
        flow = Workflow.parse(
            {
                "modules": [
                    {
                        "id": "sw-2",
                        "type": "loop",
                        "embed": {"id": "sw-3", "type": "pipe:shout"},
                        "conf": {},
                    }
                ]
            }
        )
        node = flow.nodes["sw-2"]
        assert isinstance(node, ModuleNode)
        assert node.conf == {}
        assert node.embed == {"name": "pipe:shout", "conf": {}}

    @pytest.mark.parametrize(("conf", "expected"), UPPERCASE_CONFS)
    def test_uppercase_conf_keys_are_lowered(self, conf, expected):
        flow = Workflow.parse({"modules": [{"id": "f", "type": "fetch", "conf": conf}]})
        node = flow.nodes["f"]
        assert isinstance(node, ModuleNode)
        assert node.conf == expected

    def test_orphan_module_is_retained_not_erased(self):
        flow = Workflow.parse(
            {
                "modules": [
                    {"id": "a", "type": "fetch", "conf": {}},
                    {"id": "orphan", "type": "count", "conf": {}},
                    {"id": "_OUTPUT", "type": "output", "conf": {}},
                ],
                "wires": [_wire("_w1", "a", "_OUTPUT")],
            }
        )
        assert "orphan" in flow.nodes

    def test_migration_warns(self, caplog):
        Workflow.parse({"modules": [{"id": "a", "type": "fetch", "conf": {}}]})
        assert any("pipe definition" in record.message for record in caplog.records)

    @pytest.mark.parametrize(
        ("module", "match"),
        [
            pytest.param(
                {"id": "w", "type": "write", "conf": {"dest": "o", "mode": "rb"}},
                "write mode",
                id="unmappable-write-mode",
            ),
            pytest.param(
                {"id": "w", "type": "write", "conf": {"dest": "o"}, "emit": True},
                "write option",
                id="write-wrapper-option",
            ),
            pytest.param(
                {"id": "w", "type": "write", "conf": {"dest": "o", "bogus": 1}},
                "WriteConf key",
                id="write-unknown-conf-key",
            ),
            pytest.param(
                {"id": "c", "type": "count", "conf": {"x": 1}, "bogus": 1},
                "unknown PipeModule key",
                id="unknown-module-key",
            ),
            pytest.param({"id": "a", "conf": {}}, "needs a 'name'", id="missing-type"),
            pytest.param(
                {"id": "f", "type": "fetch", "conf": {"URL": "x", "url": "y"}},
                "differ only in case",
                id="case-colliding-conf-keys",
            ),
            pytest.param(
                {"id": "f", "type": "fetch", "conf": {"url": {"VALUE": 1, "value": 2}}},
                "differ only in case",
                id="nested-case-colliding-conf-keys",
            ),
        ],
    )
    def test_malformed_module_raises(self, module, match):
        with pytest.raises(InvalidPipelineError, match=match):
            Workflow.parse({"modules": [module]})

    @pytest.mark.parametrize(("document", "match"), MALFORMED_DOCUMENTS)
    def test_unknown_document_key_raises(self, document, match):
        with pytest.raises(InvalidPipelineError, match=match):
            Workflow.parse(document)

    def test_non_mapping_pipe_def_raises(self):
        with pytest.raises(InvalidPipelineError, match="document"):
            Workflow.parse(["not", "a", "mapping"])  # pyright: ignore[reportArgumentType]

    def test_missing_modules_raises(self):
        with pytest.raises(InvalidPipelineError, match=r"the document needs"):
            Workflow.parse({"wires": []})

    def test_input_module_becomes_a_workflow_input(self):
        conf = {"name": "fmt", "prompt": "enter", "default": "%Y"}
        flow = Workflow.parse({"modules": [{"id": "i", "type": "input", "conf": conf}]})
        assert "fmt" in flow.input_schemas

    @pytest.mark.parametrize(("conf", "name", "schema", "kept"), MIGRATED_INPUTS)
    def test_input_module_conf_migrates(self, conf, name, schema, kept):
        flow = Workflow.parse({"modules": [{"id": "i", "type": "input", "conf": conf}]})
        node = flow.nodes["i"]
        assert isinstance(node, ModuleNode)
        assert flow.input_schemas == {name: schema}
        assert node.conf == {"input_key": {"type": "text", "value": name}, **kept}

    @pytest.mark.parametrize(("v1_type", "default", "schema"), V1_TYPED_DEFAULTS)
    def test_input_module_type_sets_its_schema(self, v1_type, default, schema):
        conf = {"name": "q", "type": v1_type, "default": default}
        flow = Workflow.parse({"modules": [{"id": "i", "type": "input", "conf": conf}]})
        node = flow.nodes["i"]
        assert isinstance(node, ModuleNode)
        assert flow.input_schemas == {"q": schema}
        assert node.conf["type"] == {"type": "text", "value": v1_type}

    def test_migrated_url_input_accepts_a_schemeless_host(self):
        conf = {"name": "u", "type": "url"}
        flow = Workflow.parse({"modules": [{"id": "i", "type": "input", "conf": conf}]})
        pipeline = Pipeline(flow).with_context(Context(inputs={"u": "example.com"}))
        assert list(pipeline) == ["http://example.com"]


class TestSerialize:
    def test_golden_bytes(self):
        flow = Workflow.from_raw(RICH_RAW)
        assert flow.serialize(indent=None) == RICH_GOLDEN

    def test_default_form_is_indented(self):
        flow = Workflow.from_raw(RICH_RAW)
        assert flow.serialize() == flow.serialize(indent=4)
        assert flow.serialize() != flow.serialize(indent=None)

    @pytest.mark.parametrize("raw", TOPOLOGIES.values(), ids=TOPOLOGIES.keys())
    def test_topologies_round_trip(self, raw):
        flow = Workflow.from_raw(raw)
        assert Workflow.parse(flow.serialize()) == flow

    def test_indented_output_is_readable_and_sorted(self):
        flow = Workflow.from_raw(RICH_RAW)
        document = flow.serialize(indent=2).decode("utf-8")
        top_level = [
            line[2:] for line in document.splitlines() if line.startswith('  "')
        ]
        keys = [line.split('"')[1] for line in top_level]

        assert document.endswith("\n")
        assert keys == sorted(keys)
        assert '\n  "version": "2"\n' in document

    def test_serialization_is_order_independent(self):
        reordered = {
            "nodes": [{"name": "filter"}, {"name": "fetch"}],
            "edges": [{"source": {"node": "fetch-1"}, "target": {"node": "filter-1"}}],
            "outputs": {"default": {"node": "filter-1", "port": "out"}},
        }
        forward = {
            "nodes": [{"name": "fetch"}, {"name": "filter"}],
            "edges": [{"source": {"node": "fetch-1"}, "target": {"node": "filter-1"}}],
            "outputs": {"default": {"node": "filter-1", "port": "out"}},
        }
        first = Workflow.from_raw(reordered).serialize()
        second = Workflow.from_raw(forward).serialize()
        assert first == second

    def test_migration_then_serialization_emits_no_pipe_def_structure(self):
        data = Workflow.parse(WRITE_PIPE_DEF).serialize(indent=None)
        text = data.decode("utf-8")
        assert b'"version":"2"' in data

        for token in (
            "_OUTPUT",
            "_INPUT",
            "wires",
            '"src"',
            '"tgt"',
            '"type":"output"',
        ):
            assert token not in text

    def test_call_options_are_serialized_apart_from_conf(self):
        flow = Workflow.from_raw(TOPOLOGIES["call-options"])
        data = flow.serialize(indent=None)
        assert b'"options":{"count":"first","emit":true}' in data
        assert b'"conf":{"delimiter":{"value":","}}' in data

    def test_json_native_conf_round_trips_by_equality(self):
        raw = {
            "nodes": [
                {
                    "id": "n",
                    "name": "tag",
                    "conf": {
                        "rate": 1.5,
                        "count": 3,
                        "flag": True,
                        "empty": None,
                        "tags": ["b", "a", "c"],
                        "nested": MappingProxyType({"k": 2, "items": [1, 2]}),
                    },
                }
            ]
        }
        flow = Workflow.from_raw(raw)
        assert Workflow.parse(flow.serialize()) == flow

    def test_loop_embed_serializes_as_a_node_field(self):
        raw = {
            "nodes": [
                {
                    "id": "loop-1",
                    "name": "loop",
                    "embed": {
                        "name": "tokenizer",
                        "conf": {"delimiter": {"value": " "}},
                    },
                }
            ]
        }
        flow = Workflow.from_raw(raw)
        document = json.loads(flow.serialize())
        node = document["nodes"]["loop-1"]

        assert node["embed"] == {
            "name": "tokenizer",
            "conf": {"delimiter": {"value": " "}},
        }
        assert "conf" not in node
        assert Workflow.parse(flow.serialize()) == flow

    def test_a_callable_node_has_no_document_form(self):
        with pytest.raises(InvalidPipelineError, match=CALLABLE_MATCH):
            Workflow.serialize(CALLABLE_FLOW)
