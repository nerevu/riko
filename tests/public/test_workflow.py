# vim: sw=4:ts=4:expandtab
"""Provides public tests for the ``Workflow`` graph and its documents."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from functools import partial
from math import inf, nan
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

import pytest

from riko.base._exceptions import InvalidPipelineError
from riko.definitions._nodes import (
    ActionNode,
    CacheNode,
    CallableNode,
    ModuleNode,
    PublishEdge,
    ReadNode,
    StreamEdge,
    SubscribeNode,
    WriteNode,
)
from riko.definitions._workflow_definition import (
    Workflow,
    migrate_v1_to_v2,
    normalize_workflow,
)
from riko.definitions._write import WriteMode
from riko.runtime._compile import compile_workflow
from riko.runtime._pipeline import Pipeline
from riko.types._enums import Backends, DocumentShape, Formats, IdentityMode
from riko.types._frozendict import FrozenDict, normalize_mapping
from riko.types._pipedef import Embed
from riko.types._workflow import Endpoint
from riko.types.modules import ItemBuilderConf, TruncateRawConf
from tests import TESTS_DIR, async_test
from tests._workflows import (
    DAG,
    DAG_DIR,
    EXCLAIMED,
    PARENT,
    PIPE_DEF,
    register_documents,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from riko.types._pipedef import DagModule, PipeDag

RAW_WORKFLOW = {"nodes": [{"name": "forever"}]}
DOCUMENT = json.loads(Workflow.parse(DAG).serialize())
EDGE_FAMILY_MISMATCHES = [
    pytest.param(PublishEdge, ModuleNode(id="b", name="sort"), id="publish-to-module"),
    pytest.param(
        StreamEdge, SubscribeNode(id="b", name="sub"), id="stream-to-subscribe"
    ),
]


def _fetch_workflow() -> Workflow:
    node = ModuleNode(id="fetch-1", name="fetch")
    return Workflow(
        nodes=[node], edges=(), outputs={"default": Endpoint(node.id, "out")}, inputs={}
    )


class TestWorkflow:
    def test_workflow_mappings_are_read_only(self):
        flow = _fetch_workflow()
        assert isinstance(flow.nodes, FrozenDict)
        with pytest.raises(TypeError):
            flow.outputs["extra"] = Endpoint("fetch-1", "out")  # type: ignore[index]

    @pytest.mark.parametrize(
        "build",
        [
            pytest.param(_fetch_workflow, id="constructed"),
            pytest.param(partial(normalize_workflow, RAW_WORKFLOW), id="normalized"),
        ],
    )
    def test_workflow_version_defaults_to_2(self, build):
        assert build().version == "2"

    def test_repr_counts_a_branching_graph(self):
        dag = {
            "modules": [
                {"id": "a", "name": "fetch"},
                {"id": "b", "name": "fetch"},
                {"id": "u", "name": "union"},
            ],
            "wires": [["a", "u"], ["b", "u", "in:1"]],
        }
        expected = "Workflow(nodes: 3, edges: 2; outputs: default)"
        assert repr(Workflow.parse(dag)) == expected

    def test_repr_shows_an_empty_workflow(self):
        assert repr(Workflow()) == "Workflow(empty)"

    def test_repr_counts_disconnected_nodes(self):
        flow = normalize_workflow({"nodes": [{"name": "fetch"}, {"name": "sort"}]})
        assert repr(flow) == "Workflow(nodes: 2, edges: 0)"

    def test_repr_survives_a_cycle(self):
        flow = normalize_workflow(
            {
                "nodes": [{"id": "a", "name": "fetch"}, {"id": "b", "name": "sort"}],
                "edges": [
                    {"source": {"node": "a"}, "target": {"node": "b"}},
                    {"source": {"node": "b"}, "target": {"node": "a"}},
                ],
            }
        )
        assert repr(flow) == "Workflow(nodes: 2, edges: 2)"

    def test_embeds_list_only_the_loop_nodes(self):
        embed = Embed(name="hash", conf={})
        nodes = [
            ModuleNode(id="loop-1", name="loop", embed=embed),
            ModuleNode(id="hash-1", name="hash"),
            WriteNode(id="write-1", name="write", backend=Backends.FILE),
        ]
        flow = Workflow(nodes=nodes)
        assert dict(flow.embeds) == {"loop-1": embed}

    def test_workflow_index_orders_and_indexes(self) -> None:
        a = ModuleNode(id="a", name="m")
        b = ModuleNode(id="b", name="m")
        c = ModuleNode(id="c", name="m")
        edge = StreamEdge(Endpoint("a", "out"), Endpoint("b", "in"))
        outputs = {"default": Endpoint("b", "out"), "extra": Endpoint("c", "out")}
        flow = Workflow(
            nodes=[a, b, c], outputs=outputs, inputs={}, edges=(edge,), resources=()
        )
        index = flow.index

        assert set(index.order) == {"a", "b", "c"}
        assert index.order.index("a") < index.order.index("b")
        assert set(index.roots) == {"a", "c"}
        assert set(index.leaves) == {"b", "c"}
        assert index.upstream["b"] == frozenset({"a"})
        assert index.downstream["a"] == frozenset({"b"})
        assert index.incoming["b"][0].source == "a"
        assert index.outgoing["a"][0].target == "b"
        assert set(index.outputs) == {"default", "extra"}
        assert index.required == {"default": ("a", "b"), "extra": ("c",)}

    def test_cycle_names_only_the_nodes_on_the_cycle(self):
        src = ModuleNode(id="src", name="fetch")
        a = ModuleNode(id="a", name="sort")
        b = ModuleNode(id="b", name="sort")
        after = ModuleNode(id="after", name="sort")
        edges = (
            StreamEdge(Endpoint("src", "out"), Endpoint("a", "in")),
            StreamEdge(Endpoint("a", "out"), Endpoint("b", "in")),
            StreamEdge(Endpoint("b", "out"), Endpoint("a", "in:1")),
            StreamEdge(Endpoint("b", "out"), Endpoint("after", "in")),
        )
        flow = Workflow(
            nodes=[src, a, b, after],
            edges=edges,
            outputs={"default": Endpoint("after", "out")},
            inputs={},
            resources=(),
            version="2",
        )
        assert flow.index.cyclic == ("a", "b")


NODE_FAMILIES = (
    (ModuleNode(id="fetch-1", name="fetch"), "module"),
    (ReadNode(id="read-1", name="read", backend=Backends.FILE), "read"),
    (WriteNode(id="write-1", name="write", backend=Backends.FILE), "write"),
    (CacheNode(id="cache-1", name="cache"), "cache"),
    (ActionNode(id="act-1", name="act", backend=Backends.HTTP), "action"),
    (SubscribeNode(id="sub-1", name="sub"), "subscribe"),
)


class TestNodeFamily:
    @pytest.mark.parametrize(("node", "family"), NODE_FAMILIES, ids=str)
    def test_node_family_discriminant(self, node, family):
        assert node.family == family

    def test_edge_family_discriminants(self):
        endpoint = Endpoint("fetch-1", "out")
        assert StreamEdge(endpoint, endpoint).family == "stream"
        assert PublishEdge(endpoint, endpoint).family == "publish"

    def test_write_node_defaults(self):
        node = WriteNode(id="write-1", name="write", backend=Backends.FILE)
        assert node.fmt is None
        assert node.mode is WriteMode.REPLACE
        assert node.keys == ()

    def test_node_is_frozen(self):
        node = ModuleNode(id="fetch-1", name="fetch")
        with pytest.raises(AttributeError):
            node.name = "other"  # type: ignore[misc]


@dataclass
class _Rule:
    field: str


_BLANK_IDENTIFIERS = [
    pytest.param(lambda: ModuleNode(id="", name="hash"), "ModuleNode 'id'", id="id"),
    pytest.param(
        lambda: ModuleNode(id=" ", name="hash"), "ModuleNode 'id'", id="blank"
    ),
    pytest.param(lambda: ModuleNode(id="a", name=""), "ModuleNode 'name'", id="name"),
    pytest.param(lambda: Endpoint("", "out"), "Endpoint 'node'", id="endpoint"),
    pytest.param(
        lambda: Workflow.parse({"nodes": [{"name": " "}], "outputs": {}}),
        "ModuleNode 'name'",
        id="document-name",
    ),
]


class TestNodes:
    def test_module_conf_accepts_floats_and_none(self):
        node = ModuleNode(id="a", name="sleep", conf={"wait": 1.5, "join_key": None})
        assert node.conf == {"wait": 1.5, "join_key": None}

    def test_module_conf_rejects_dataclass_values(self):
        conf = {"rule": _Rule("x")}

        with pytest.raises(InvalidPipelineError, match="not JSON-native"):
            ModuleNode(id="a", name="sort", conf=conf)  # pyright: ignore[reportArgumentType]

    def test_node_id_must_be_a_string(self):
        with pytest.raises(InvalidPipelineError, match="ModuleNode 'id'"):
            ModuleNode(id=1, name="hash")  # pyright: ignore[reportArgumentType]

    @pytest.mark.parametrize(("build", "match"), _BLANK_IDENTIFIERS)
    def test_blank_identifiers_are_rejected(self, build, match):
        with pytest.raises(InvalidPipelineError, match=f"{match} must not be blank"):
            build()

    @pytest.mark.parametrize(
        ("node", "kwargs", "match"),
        [
            (ActionNode, {"backend": "file", "params": 1}, "ActionNode 'params'"),
            (CacheNode, {"policy": 1}, "CacheNode 'policy'"),
            (SubscribeNode, {"policy": 1}, "SubscribeNode 'policy'"),
        ],
    )
    def test_json_fields_name_themselves(self, node: Any, kwargs: Any, match: str):
        with pytest.raises(InvalidPipelineError, match=f"{match} must be a mapping"):
            node(id="a", name="n", **kwargs)


_CALLABLE_NODE_ERRORS = [
    pytest.param({"resources": {"a-b": "db"}}, InvalidPipelineError, "identifiers"),
    pytest.param({"resources": "def"}, InvalidPipelineError, "identifiers"),
    pytest.param({"identity": "bogus"}, InvalidPipelineError, "'identity'"),
    pytest.param({"fn": "len"}, TypeError, "callable"),
]


class TestCallableNode:
    @pytest.mark.parametrize(("kwargs", "error", "match"), _CALLABLE_NODE_ERRORS)
    def test_construction_is_validated(self, kwargs: Any, error: Any, match: str):
        with pytest.raises(error, match=match):
            CallableNode(**{"id": "a", "name": "len", "fn": len, **kwargs})

    def test_identity_accepts_a_bare_string(self):
        node = CallableNode(id="a", name="len", fn=len, identity="preserve")
        assert node.identity is IdentityMode.PRESERVE

    def test_fn_is_compared_by_identity(self):
        node = CallableNode(id="a", name="len", fn=len, kwargs={"n": [1]})
        assert node == CallableNode(id="a", name="len", fn=len, kwargs={"n": [1]})
        assert node != CallableNode(id="a", name="len", fn=lambda value: value)


PARSE_REJECTIONS = [
    pytest.param({"pipeline": []}, None, "'nodes' or 'modules'", id="unknown-shape"),
    pytest.param(RAW_WORKFLOW, "v3", "Invalid shape", id="unknown-declared-shape"),
    pytest.param("{bad json", None, "malformed JSON", id="bad-json"),
    pytest.param(b"\xff", None, "malformed JSON", id="undecodable-bytes"),
    pytest.param({"nodes": []}, None, "no nodes", id="validates"),
]


DOCUMENTS = [
    pytest.param(
        DAG, DocumentShape.DAG, partial(Workflow.parse, shape="dag"), id="dag"
    ),
    pytest.param(PIPE_DEF, DocumentShape.V1, migrate_v1_to_v2, id="v1"),
    pytest.param(RAW_WORKFLOW, DocumentShape.V2, normalize_workflow, id="v2"),
    pytest.param(DOCUMENT, DocumentShape.V2, normalize_workflow, id="workflow"),
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

    @pytest.mark.parametrize(("document", "shape", "match"), PARSE_REJECTIONS)
    def test_parse_rejects(self, document, shape, match):
        with pytest.raises(InvalidPipelineError, match=match):
            Workflow.parse(document, shape=shape)


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
    @pytest.mark.parametrize(
        "wires",
        [pytest.param({}, id="omitted"), pytest.param({"wires": None}, id="null")],
    )
    def test_unwired_modules_chain_in_listing_order(self, wires):
        linear = Workflow.parse({"modules": MODULES, **wires})
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
        embed = Embed({"name": "fetch", "conf": {}})
        flow = Workflow.parse({"modules": [{"name": "loop", "embed": embed}]})
        module = _module_node(flow, "sw-1")
        assert module.embed is not None
        assert module.embed["name"] == "fetch"

    def test_expanded_dag_runs(self):
        flow = Workflow.parse(DAG)
        assert list(Pipeline(flow)) == [{"forever": True}] * 3

    def test_reordered_dag_runs_in_wired_order(self):
        flow = Workflow.parse(_dag("pipe_reordered"))
        assert list(Pipeline(flow)) == [{"forever": True}] * 2

    @pytest.mark.parametrize(
        ("document", "message"),
        [
            pytest.param({"modules": []}, "no nodes", id="empty-modules"),
            pytest.param({"modules": None}, "must be a list", id="null-modules"),
            pytest.param(
                {"modules": [{"type": "forever"}], "wires": 5},
                "must be a list",
                id="scalar-wires",
            ),
        ],
    )
    def test_parse_rejects_invalid_pipe_dags(self, document, message):
        with pytest.raises(InvalidPipelineError, match=message):
            Workflow.parse(document)

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
            pytest.param({"id": "x"}, "needs a 'name'", id="missing-name"),
            pytest.param(
                {"name": "forever", "family": "module"}, "family", id="node-family-key"
            ),
        ],
    )
    def test_pipe_dag_reports_unknown_module_keys(self, module, message):
        with pytest.raises(InvalidPipelineError, match=message):
            Workflow.parse({"modules": [module]})


NON_JSON_VALUES = [
    pytest.param(Decimal("1.50"), id="decimal"),
    pytest.param(date(2020, 6, 15), id="date"),
    pytest.param({"a", "b"}, id="set"),
    pytest.param(b"bytes", id="bytes"),
    pytest.param(nan, id="nan"),
    pytest.param(inf, id="inf"),
]

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
NORMALIZED_OUTPUTS = [
    pytest.param(_CHAINED, {"default": Endpoint("b", "out")}, id="single-leaf"),
    pytest.param({"nodes": _TWO_NODES}, {}, id="ambiguous-leaves"),
    pytest.param(_ROUTED, {"errors": Endpoint("a", "out:1")}, id="legacy-port-alias"),
    pytest.param(_EXPLICIT_EMPTY, {}, id="explicit-empty"),
]
_REPEATED = [{"name": "fetch"}, {"name": "filter"}, {"name": "filter"}]
_TAKEN_ID = [{"name": "fetch"}, {"id": "fetch-1", "name": "sort"}]
NODE_IDS = [
    pytest.param(_REPEATED, ["fetch-1", "filter-1", "filter-2"], id="occurrence-ids"),
    pytest.param([{"id": "keep", "name": "fetch"}], ["keep"], id="explicit-id-kept"),
    pytest.param({"a": {"id": "a", "name": "fetch"}}, ["a"], id="key-matches-id"),
    pytest.param(_TAKEN_ID, ["fetch-2", "fetch-1"], id="generated-skip-explicit"),
]


class TestNormalizeWorkflow:
    @pytest.mark.parametrize(("nodes", "expected"), NODE_IDS)
    def test_node_ids(self, nodes, expected):
        assert list(normalize_workflow({"nodes": nodes}).nodes) == expected

    def test_mapping_nodes_keep_explicit_ids(self):
        flow = normalize_workflow({"nodes": {"a": {"name": "fetch"}}})
        assert isinstance(flow.nodes["a"], ModuleNode)
        assert flow.nodes["a"].name == "fetch"

    def test_family_dispatch_and_enum_coercion(self):
        flow = normalize_workflow(
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
        flow = normalize_workflow(
            {"nodes": _TWO_NODES, "edges": [{"source": source, "target": target}]}
        )
        source_port, target_port = expected
        assert flow.edges == (
            StreamEdge(Endpoint("a", source_port), Endpoint("b", target_port)),
        )

    def test_publish_edge_detected_from_subscribe_target(self):
        flow = normalize_workflow(
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
        assert normalize_workflow(raw).outputs == expected

    @pytest.mark.parametrize(
        ("declaration", "schema"),
        [
            pytest.param("string", {"type": "string"}, id="type-name"),
            pytest.param(
                {"type": "integer", "default": 0},
                {"type": "integer", "default": 0},
                id="schema",
            ),
        ],
    )
    def test_input_declarations_become_schemas(self, declaration, schema):
        flow = normalize_workflow(
            {"nodes": [{"id": "a", "name": "fetch"}], "inputs": {"n": declaration}}
        )
        assert flow.inputs["n"] == schema

    def test_bare_string_resource_binds_to_itself(self):
        flow = normalize_workflow(
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
        flow = normalize_workflow(
            {"nodes": [{"id": "a", "name": "fetch"}], "resources": resources}
        )
        assert flow.resources == expected

    def test_explicit_stream_family_to_subscribe_is_preserved(self):
        flow = normalize_workflow(
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
        flow = normalize_workflow(
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

    def test_node_conf_is_isolated_from_caller_mutation(self):
        conf = {"limit": 5}
        flow = normalize_workflow(
            {"nodes": [{"id": "a", "name": "fetch", "conf": conf}]}
        )
        node = flow.nodes["a"]
        conf["limit"] = 99
        assert isinstance(node, ModuleNode)
        assert node.conf == {"limit": 5}

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
        first = normalize_workflow(raw)
        assert normalize_workflow(first) == first
        assert normalize_workflow(normalize_workflow(first)) == first

    def test_normalize_renormalizes_a_hand_built_workflow(self):
        a = ModuleNode(id="a", name="fetch")
        b = ModuleNode(id="b", name="filter")
        hand = Workflow(
            nodes=[a, b],
            edges=(StreamEdge(Endpoint("a", "_OUTPUT"), Endpoint("b", "_OTHER2")),),
            outputs={"default": Endpoint("b", "_OUTPUT")},
            inputs={},
        )
        normalized = normalize_workflow(hand)
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
        assert normalize_workflow(flow) == flow

    @pytest.mark.parametrize(
        "spelling",
        [
            pytest.param({"format": "csv"}, id="format-alias"),
            pytest.param({"fmt": "csv", "format": "csv"}, id="agreeing-fmt-format"),
        ],
    )
    def test_format_alias_maps_to_fmt(self, spelling):
        flow = normalize_workflow({"nodes": [{**_READ_NODE, **spelling}]})
        read = flow.nodes["r"]
        assert isinstance(read, ReadNode)
        assert read.fmt is Formats.CSV

    def test_raw_call_options_are_accepted(self):
        flow = normalize_workflow(
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
        flow = normalize_workflow(
            {
                "nodes": [
                    {"id": "a", "name": "f", "conf": {"nested": inner, "list": [1, 2]}}
                ]
            }
        )
        inner["k"] = 99
        node = flow.nodes["a"]
        assert isinstance(node, ModuleNode)
        assert node.conf is not None
        assert node.conf.get("nested") == {"k": 1}
        assert node.conf.get("list") == (1, 2)
        assert isinstance(node.conf.get("nested"), FrozenDict)

    def test_raw_embed_becomes_a_read_only_node_field(self):
        flow = normalize_workflow(
            {
                "nodes": [
                    {"name": "loop", "embed": {"name": "tokenizer", "conf": {"d": " "}}}
                ]
            }
        )
        node = flow.nodes["loop-1"]
        assert isinstance(node, ModuleNode)
        assert node.embed == {"name": "tokenizer", "conf": {"d": " "}}
        assert isinstance(node.embed, FrozenDict)
        assert node.conf == {}

    def test_embed_conf_defaults_to_empty_when_omitted(self):
        flow = normalize_workflow(
            {"nodes": [{"name": "loop", "embed": {"name": "tokenizer"}}]}
        )
        node = flow.nodes["loop-1"]
        assert isinstance(node, ModuleNode)
        assert node.embed == {"name": "tokenizer", "conf": {}}

    @pytest.mark.parametrize(
        ("node", "match"),
        [
            pytest.param(
                {"name": "fetch", "resources": 5}, "node 'resources'", id="resources"
            ),
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
            pytest.param(
                {"name": "fetch", "conf": []}, "ModuleNode 'conf'", id="falsey-conf"
            ),
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
            normalize_workflow({"nodes": [node]})

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
                "unknown Edge key",
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
            normalize_workflow(raw)

    def test_invalid_port_rejected(self):
        edge = {"source": {"node": "a"}, "target": {"node": "b", "port": "out:"}}

        with pytest.raises(InvalidPipelineError, match="invalid port: 'out:'"):
            normalize_workflow({"nodes": _TWO_NODES, "edges": [edge]})

    @pytest.mark.parametrize("declaration", [5, ["a"], None])
    def test_input_without_type_name_or_schema_raises(self, declaration):
        raw = {"nodes": [{"id": "a", "name": "fetch"}], "inputs": {"n": declaration}}

        with pytest.raises(InvalidPipelineError, match="type name or mapping"):
            normalize_workflow(raw)

    @pytest.mark.parametrize("value", NON_JSON_VALUES)
    @pytest.mark.parametrize("placement", sorted(_NODE_VALUE_PLACEMENTS))
    def test_non_json_native_node_value_rejected(self, placement, value):
        raw = {"nodes": [{"id": "n", **_NODE_VALUE_PLACEMENTS[placement](value)}]}

        with pytest.raises(InvalidPipelineError, match="JSON-native"):
            normalize_workflow(raw)

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
            normalize_workflow(raw)


_A = ModuleNode(id="a", name="fetch")


class TestRequireRunnableOnly:
    def test_a_module_only_workflow_passes(self):
        flow = Workflow(nodes=[_A], outputs={"default": Endpoint("a", "out")})

        assert flow.require_runnable_only("execution") is None

    def test_other_families_are_named_with_the_activity(self):
        write = WriteNode(id="w", name="write", backend="file", dest="out.csv")
        cache = CacheNode(id="c", name="cache")
        nodes = [_A, write, cache]
        flow = Workflow(nodes=nodes, outputs={"default": Endpoint("a", "out")})

        with pytest.raises(InvalidPipelineError, match="cache, write node execution"):
            flow.require_runnable_only("execution")

    def test_callable_nodes_pass(self):
        node = CallableNode(id="c", name="len", fn=len)
        flow = Workflow(nodes=[_A, node], outputs={"default": Endpoint("c", "out")})
        assert flow.require_runnable_only("execution") is None


_CALLABLE_FLOW = Workflow(
    nodes=[CallableNode(id="len-1", name="len", fn=len)],
    outputs={"default": Endpoint("len-1", "out")},
)


class TestCallableNodeDocuments:
    @pytest.mark.parametrize(
        "write",
        [
            pytest.param(Workflow.serialize, id="serialize"),
            pytest.param(normalize_workflow, id="normalize"),
            pytest.param(partial(compile_workflow, name="pipe_len"), id="compile"),
        ],
    )
    def test_a_callable_node_has_no_document_form(self, write):
        with pytest.raises(
            InvalidPipelineError, match=r"callable node\(s\) \['len-1'\]"
        ):
            write(_CALLABLE_FLOW)

    def test_a_document_cannot_declare_a_callable_node(self):
        raw = {"nodes": [{"name": "len", "family": "callable"}]}

        with pytest.raises(InvalidPipelineError, match="cannot hold a callable node"):
            Workflow.parse(raw)


_A_IN, _A_OUT = Endpoint("a", "in"), Endpoint("a", "out")
_B_IN, _B_OUT = Endpoint("b", "in"), Endpoint("b", "out")
_C_IN = Endpoint("c", "in")
_MERGE = {
    "nodes": [_A, ModuleNode(id="b", name="fetch"), ModuleNode(id="c", name="join")],
    "edges": [StreamEdge(_A_OUT, _C_IN), StreamEdge(_B_OUT, _C_IN)],
    "outputs": {"default": Endpoint("c", "out")},
}
_HAS_DB = ModuleNode(id="a", name="fetch", resources={"db": "prod"})
INVALID_WORKFLOWS = [
    pytest.param(
        {"nodes": [_A], "outputs": {"default": _A_OUT}, "version": "1"},
        "unsupported workflow version",
        id="unsupported-version",
    ),
    pytest.param({"nodes": []}, "no nodes", id="no-nodes"),
    pytest.param(_MERGE, "multiple stream edges", id="multiple-stream-edges"),
    pytest.param(
        {"nodes": [_HAS_DB], "outputs": {"default": _A_OUT}},
        "unresolved resource",
        id="unresolved-resource",
    ),
    pytest.param({"nodes": [_A]}, "exposes no workflow output", id="no-output"),
]
INVALID_EDGES = [
    pytest.param(
        [StreamEdge(_A_OUT, Endpoint("ghost", "in"))],
        _B_OUT,
        "missing node",
        id="missing-edge-node",
    ),
    pytest.param(
        [], Endpoint("ghost", "out"), "missing node", id="missing-output-node"
    ),
    pytest.param(
        [StreamEdge(_A_IN, _B_IN)],
        _B_OUT,
        r"'a', 'in'.*not an 'out' port",
        id="edge-source-on-input-port",
    ),
    pytest.param(
        [StreamEdge(_A_OUT, _B_OUT)],
        _B_OUT,
        r"'b', 'out'.*not an 'in' port",
        id="edge-target-on-output-port",
    ),
    pytest.param([], _A_IN, "not an 'out' port", id="output-on-input-port"),
    pytest.param(
        [], Endpoint("a", "sideways"), "invalid port direction", id="malformed-port"
    ),
    pytest.param(
        [StreamEdge(_A_OUT, Endpoint("b", "in:0"))], _B_OUT, "invalid port", id="in:0"
    ),
    pytest.param(
        [StreamEdge(Endpoint("a", "out:0"), _B_IN)], _B_OUT, "invalid port", id="out:0"
    ),
    pytest.param(
        [StreamEdge(_A_OUT, _B_IN), StreamEdge(_B_OUT, _A_IN)],
        _B_OUT,
        r"cycle.*\['a', 'b'\]",
        id="cycle",
    ),
    pytest.param(
        [StreamEdge(_A_OUT, _A_IN)], _A_OUT, r"cycle.*\['a'\]", id="self-loop"
    ),
]


_UNKNOWN_KEY_RULE = {"fieldd": "title", "op": "contains", "value": "1"}
INVALID_CONFS = [
    pytest.param("filter", {"rule": _UNKNOWN_KEY_RULE}, "fieldd", id="unknown-key"),
    pytest.param("sort", {"rule": 5}, "rule", id="wrong-type"),
    pytest.param(
        "simplemath", {"op": "nope", "other": {"value": 2}}, "op", id="bad-op"
    ),
    pytest.param("strconcat", {}, "part", id="missing-key"),
]


def _workflow(
    nodes, edges=(), outputs=None, inputs=None, resources=(), version="2"
) -> Workflow:
    return Workflow(
        nodes=nodes,
        edges=tuple(edges),
        outputs=normalize_mapping(outputs),
        inputs=normalize_mapping(inputs),
        resources=resources,
        version=version,
    )


def _counted_source(consumed):
    for index in range(3):
        consumed.append(index)
        yield {"title": str(index)}


_B = ModuleNode(id="b", name="sort")


class TestValidate:
    @pytest.mark.parametrize(
        ("nodes", "edges", "output", "resources"),
        [
            pytest.param([_A], [], "a", (), id="single-node"),
            pytest.param(
                [_A, ModuleNode(id="b", name="fetch"), ModuleNode(id="c", name="join")],
                [
                    StreamEdge(Endpoint("a", "out"), Endpoint("c", "in")),
                    StreamEdge(Endpoint("b", "out"), Endpoint("c", "in:1")),
                ],
                "c",
                (),
                id="distinct-fan-in-ports",
            ),
            pytest.param(
                [_A, SubscribeNode(id="s", name="sub")],
                [PublishEdge(Endpoint("a", "out"), Endpoint("s", "in"))],
                "a",
                (),
                id="publish-to-subscribe",
            ),
            pytest.param(
                [ModuleNode(id="a", name="fetch", resources={"db": "prod"})],
                [],
                "a",
                ("prod",),
                id="declared-resource",
            ),
        ],
    )
    def test_valid_graphs_pass(self, nodes, edges, output, resources):
        outputs = {"default": Endpoint(output, "out")}
        flow = _workflow(nodes, edges=edges, outputs=outputs, resources=resources)
        assert flow.validate() is None

    @pytest.mark.parametrize(("kwargs", "match"), INVALID_WORKFLOWS)
    def test_invalid_workflow_rejected(self, kwargs, match):
        with pytest.raises(InvalidPipelineError, match=match):
            _workflow(**kwargs).validate()

    @pytest.mark.parametrize(("edge", "target"), EDGE_FAMILY_MISMATCHES)
    def test_edge_family_disagreeing_with_its_target_rejected(self, edge, target):
        flow = _workflow(
            [_A, target],
            edges=[edge(Endpoint("a", "out"), Endpoint("b", "in"))],
            outputs={"default": Endpoint("a", "out")},
        )
        with pytest.raises(InvalidPipelineError, match="edge family disagrees"):
            flow.validate()

    @pytest.mark.parametrize(("edges", "output", "match"), INVALID_EDGES)
    def test_invalid_edges_rejected(self, edges, output, match):
        flow = _workflow([_A, _B], edges=edges, outputs={"default": output})
        with pytest.raises(InvalidPipelineError, match=match):
            flow.validate()

    @pytest.mark.xfail(
        strict=True,
        reason="module configuration is not validated against its contract yet",
    )
    @pytest.mark.parametrize(("name", "conf", "match"), INVALID_CONFS)
    def test_invalid_conf_rejected_before_the_source_is_read(self, name, conf, match):
        consumed = []
        pipeline = _counted_source(consumed) | Pipeline.from_module(name, conf=conf)

        with pytest.raises(InvalidPipelineError, match=match):
            list(pipeline)

        assert consumed == []


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


class TestMigrate:
    def test_terminal_output_becomes_default_output(self):
        flow = migrate_v1_to_v2(
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
            pytest.param(
                "_OUTPUT", "PARAM_5_value", ("out", "in:PARAM_5_value"), id="param"
            ),
        ],
    )
    def test_wire_ports_map_to_canonical_endpoints(
        self, source_port, target_port, expected
    ):
        flow = migrate_v1_to_v2(
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
        flow = migrate_v1_to_v2(
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
        flow = migrate_v1_to_v2(
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
        flow = migrate_v1_to_v2(
            {"modules": [{"id": "w", "type": "write", "conf": {"dest": "out.dat"}}]}
        )
        node = flow.nodes["w"]
        assert isinstance(node, WriteNode)
        assert node.backend is Backends.FILE
        assert node.fmt is None

    def test_module_call_options_become_node_options(self):
        flow = migrate_v1_to_v2(
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
        flow = migrate_v1_to_v2(
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
        flow = migrate_v1_to_v2(
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
        flow = migrate_v1_to_v2(
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
        flow = migrate_v1_to_v2(
            {"modules": [{"id": "f", "type": "fetch", "conf": conf}]}
        )
        node = flow.nodes["f"]
        assert isinstance(node, ModuleNode)
        assert node.conf == expected

    def test_orphan_module_is_retained_not_erased(self):
        flow = migrate_v1_to_v2(
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

    def test_omitted_output_node_defaults_to_lone_leaf(self):
        flow = migrate_v1_to_v2(
            {
                "modules": [
                    {"id": "a", "type": "fetch", "conf": {}},
                    {"id": "b", "type": "filter", "conf": {}},
                ],
                "wires": [_wire("_w1", "a", "b")],
            }
        )
        assert flow.outputs == {"default": Endpoint("b", "out")}

    def test_migration_warns(self, caplog):
        migrate_v1_to_v2({"modules": [{"id": "a", "type": "fetch", "conf": {}}]})
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
            pytest.param(
                {"id": "a", "conf": {}},
                r"missing PipeModule key\(s\): \['type'\]",
                id="missing-type",
            ),
        ],
    )
    def test_malformed_module_raises(self, module, match):
        with pytest.raises(InvalidPipelineError, match=match):
            migrate_v1_to_v2({"modules": [module]})

    def test_non_mapping_pipe_def_raises(self):
        with pytest.raises(InvalidPipelineError, match="pipe definition"):
            migrate_v1_to_v2(["not", "a", "mapping"])  # pyright: ignore[reportArgumentType]

    @pytest.mark.xfail(
        strict=True,
        reason="migrating a pipe definition's input modules into the workflow's "
        "input declarations is not yet implemented",
    )
    def test_input_module_becomes_a_declared_input(self):
        conf = {"name": "fmt", "prompt": "enter", "default": "%Y"}
        flow = migrate_v1_to_v2(
            {"modules": [{"id": "i", "type": "input", "conf": conf}]}
        )
        assert "fmt" in flow.inputs


RICH_RAW = {
    "version": "2",
    "inputs": {"since": "string"},
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
    b'ts":{"since":{"type":"string"}},"nodes":{"filter-1":{"conf":{"rule":{"field":"x"'
    b'}},"family":"module","id":"filter-1","name":"filter"},"read-1":{"backend":"http"'
    b',"family":"read","fmt":"json","id":"read-1","name":"read"},"sub-1":{"family":"su'
    b'bscribe","id":"sub-1","name":"listen","policy":{"buffer":0}},"write-1":{"backend'
    b'":"file","family":"write","fmt":"csv","id":"write-1","keys":["id"],"mode":"appen'
    b'd","name":"store","resources":{"db":"db"}}},"outputs":{"default":{"node":"write-'
    b'1","port":"out"}},"resources":["db"],"version":"2"}'
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
        "inputs": {"limit": {"type": "integer", "minimum": 1}},
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


class TestSerialize:
    def test_golden_bytes(self):
        flow = normalize_workflow(RICH_RAW)
        assert flow.serialize(indent=None) == RICH_GOLDEN

    def test_default_form_is_indented(self):
        flow = normalize_workflow(RICH_RAW)
        assert flow.serialize() == flow.serialize(indent=4)
        assert flow.serialize() != flow.serialize(indent=None)

    @pytest.mark.parametrize("raw", TOPOLOGIES.values(), ids=TOPOLOGIES.keys())
    def test_topologies_round_trip(self, raw):
        flow = normalize_workflow(raw)
        assert Workflow.parse(flow.serialize()) == flow

    @pytest.mark.parametrize("raw", TOPOLOGIES.values(), ids=TOPOLOGIES.keys())
    def test_serialization_is_idempotent(self, raw):
        flow = normalize_workflow(raw)
        once = flow.serialize()
        assert Workflow.parse(once).serialize() == once

    def test_indented_output_is_readable_and_sorted(self):
        flow = normalize_workflow(RICH_RAW)
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
        first = normalize_workflow(reordered).serialize()
        second = normalize_workflow(forward).serialize()
        assert first == second

    def test_migration_then_serialization_emits_no_pipe_def_structure(self):
        data = migrate_v1_to_v2(WRITE_PIPE_DEF).serialize(indent=None)
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
        flow = normalize_workflow(TOPOLOGIES["call-options"])
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
        flow = normalize_workflow(raw)
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
        flow = normalize_workflow(raw)
        document = json.loads(flow.serialize())
        node = document["nodes"]["loop-1"]

        assert node["embed"] == {
            "name": "tokenizer",
            "conf": {"delimiter": {"value": " "}},
        }
        assert "conf" not in node
        assert Workflow.parse(flow.serialize()) == flow


@pytest.fixture
def documents(tmp_path: Path) -> Path:
    register_documents(tmp_path)
    return tmp_path


def build_outer() -> Pipeline:
    conf = ItemBuilderConf({"attrs": [{"key": "title", "value": "hi"}]})
    source = Pipeline.from_module("itembuilder", conf=conf)
    return source.pipe(
        "loop",
        options={"count": "all", "emit": True},
        embed={"name": "pipe:exclaim", "conf": {}},
    )


@pytest.mark.usefixtures("documents")
class TestWorkflowDocumentResolution:
    def test_document_runs_as_pipeline(self):
        pipeline = Pipeline.from_module("pipe_exclaim")
        assert list(PARENT | pipeline) == EXCLAIMED

    def test_document_embeds_in_a_loop(self):
        assert list(build_outer()) == EXCLAIMED

    def test_module_wins_over_document(self):
        pipeline = Pipeline.from_module("pipe_shout")
        items = list(PARENT | pipeline)
        assert items == EXCLAIMED

    @async_test
    async def test_document_runs_as_async_pipeline(self):
        pipeline = Pipeline.from_module("pipe_exclaim")
        assert [item async for item in PARENT | pipeline] == EXCLAIMED
        assert [item async for item in build_outer()] == EXCLAIMED


def _loop_workflow() -> Workflow:
    """Parses the committed loop fixture whose embed carries a typed config."""
    data = (TESTS_DIR / "workflows" / "pipe_loop_assign.json").read_text()
    return Workflow.parse(data)


class TestCompileWorkflow:
    def test_loop_embed_is_rendered_as_a_node_field(self):
        """A loop node's embedded module is rebuilt from the typed ``Embed``."""
        source = compile_workflow(_loop_workflow(), "pipe_x")
        assert "embed=Embed(" in source
        assert "LoopConf" not in source

    def test_write_node_is_refused(self):
        """A workflow with a node family that has no generated form is refused."""
        node = WriteNode(id="write-1", name="write", backend="file", dest="out.csv")
        flow = Workflow(nodes=[node], outputs={"default": Endpoint(node.id, "out")})

        with pytest.raises(InvalidPipelineError, match="write node code generation"):
            compile_workflow(flow, "pipe_written")

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "a public import path for generated workflow modules is not yet implemented"
        ),
    )
    def test_generated_source_imports_no_private_module(self):
        """A generated workflow module imports only supported riko paths."""
        flow = Pipeline.from_module("itembuilder").workflow
        assert "from riko.runtime._" not in compile_workflow(flow, "pipe_public")
