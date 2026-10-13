# vim: sw=4:ts=4:expandtab
"""Provides public tests for the ``Workflow`` graph and its documents."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from functools import partial
from types import MappingProxyType
from typing import TYPE_CHECKING

import pytest

from riko.bado.itertools import as_async
from riko.base.exceptions import InvalidPipelineError, UnsupportedWorkflowError
from riko.definitions._context import Context
from riko.definitions._nodes import (
    ActionNode,
    CacheNode,
    ModuleNode,
    PublishEdge,
    ReadNode,
    StreamEdge,
    SubscribeNode,
    WriteNode,
)
from riko.definitions._workflow import Workflow, migrate_v1_to_v2, normalize_workflow
from riko.definitions._write import WriteMode
from riko.runtime._pipeline import Pipeline
from riko.runtime._resolver import dispatcher
from riko.runtime._workflows import register_workflow_store
from riko.types._collections import FrozenDict
from riko.types._compiler import Embed
from riko.types._enums import Backends, DocumentShape, ExecutionMode, Formats
from riko.types._workflow import Endpoint, ParsedPort, parse_port
from riko.types.modules import ItemBuilderConf, StrconcatRawConf, TruncateRawConf
from tests import TESTS_DIR, async_test
from tests._workflows import DAG, PIPE_DEF

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from riko.types._compiler import DagModule, PipeDag

DAG_DIR = TESTS_DIR / "dags"
RAW_WORKFLOW = {"nodes": [{"name": "forever"}]}
DOCUMENT = json.loads(Workflow.parse(DAG).serialize())
DOCUMENTS = [
    pytest.param(
        DAG, DocumentShape.DAG, partial(Workflow.parse, shape="dag"), id="dag"
    ),
    pytest.param(PIPE_DEF, DocumentShape.V1, migrate_v1_to_v2, id="v1"),
    pytest.param(RAW_WORKFLOW, DocumentShape.V2, normalize_workflow, id="v2"),
    pytest.param(DOCUMENT, DocumentShape.V2, normalize_workflow, id="workflow"),
]
EDGE_FAMILY_MISMATCHES = [
    pytest.param(PublishEdge, ModuleNode(id="b", name="sort"), id="publish-to-module"),
    pytest.param(
        StreamEdge, SubscribeNode(id="b", name="sub"), id="stream-to-subscribe"
    ),
]


def _fetch_workflow():
    node = ModuleNode(id="fetch-1", name="fetch")
    return Workflow(
        nodes=[node], edges=(), outputs={"default": Endpoint(node.id, "out")}, inputs={}
    )


class TestWorkflow:
    def test_workflow_mappings_are_read_only(self):
        workflow = _fetch_workflow()
        assert isinstance(workflow.nodes, FrozenDict)
        with pytest.raises(TypeError):
            workflow.outputs["extra"] = Endpoint("fetch-1", "out")  # type: ignore[index]

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


class TestParsePort:
    @pytest.mark.parametrize(
        ("port", "expected"),
        [
            ("in", ParsedPort("in", None, None)),
            ("out", ParsedPort("out", None, None)),
            ("in:1", ParsedPort("in", 1, None)),
            ("out:2", ParsedPort("out", 2, None)),
            ("out:matched", ParsedPort("out", None, "matched")),
            ("in:count", ParsedPort("in", None, "count")),
        ],
    )
    def test_parse_port_grammar(self, port, expected):
        assert parse_port(port) == expected

    @pytest.mark.parametrize(
        ("port", "expected"),
        [
            pytest.param("in", (True, False), id="default"),
            pytest.param("in:1", (False, True), id="positional"),
            pytest.param("in:count", (False, False), id="named"),
        ],
    )
    def test_parse_port_kind_predicates(self, port, expected):
        parsed = parse_port(port)

        assert (parsed.is_default, parsed.is_positional) == expected

    @pytest.mark.parametrize("port", ["sideways", "up:1", ""])
    def test_parse_port_rejects_bad_direction(self, port):
        with pytest.raises(ValueError, match="invalid port direction"):
            parse_port(port)

    @pytest.mark.parametrize(
        "port", ["out:-1", "out:", "out:a b", "in:", "in:-1", "in:a b"]
    )
    def test_parse_port_rejects_bad_qualifier(self, port):
        with pytest.raises(ValueError, match="invalid port"):
            parse_port(port)

    @pytest.mark.parametrize("port", ["in:0", "out:0"])
    def test_parse_port_rejects_zero_position(self, port):
        with pytest.raises(ValueError, match="invalid port"):
            parse_port(port)


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

    def test_parse_rejects_an_unknown_shape(self):
        with pytest.raises(InvalidPipelineError, match="'nodes' or 'modules'"):
            Workflow.parse({"pipeline": []})

    def test_parse_rejects_an_unknown_declared_shape(self):
        with pytest.raises(InvalidPipelineError, match="Invalid shape"):
            Workflow.parse(RAW_WORKFLOW, shape="v3")

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

    @pytest.mark.parametrize(
        "document",
        [
            pytest.param("{bad json", id="bad-json"),
            pytest.param(b"\xff", id="undecodable-bytes"),
            pytest.param("[]", id="not-a-mapping"),
        ],
    )
    def test_parse_rejects_malformed_text(self, document):
        with pytest.raises(InvalidPipelineError):
            Workflow.parse(document)

    def test_parse_validates(self):
        with pytest.raises(InvalidPipelineError, match="no nodes"):
            Workflow.parse({"nodes": []})


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


def _edges(workflow: Workflow) -> list[tuple[str, str]]:
    """Projects a workflow's edges onto their source and target node ids."""
    return [(edge.source.node, edge.target.node) for edge in workflow.edges]


def _module_node(workflow: Workflow, node_id: str) -> ModuleNode:
    """Narrows one of a workflow's nodes to a module node."""
    node = workflow.nodes[node_id]
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
        workflow = Workflow.parse(_dag("pipe_reordered"))
        assert _edges(workflow) == [("gen", "trunc")]
        assert workflow.outputs["default"] == Endpoint("trunc", "out")

    def test_third_wire_entry_sets_the_target_port(self):
        workflow = Workflow.parse({"modules": FAN_IN_MODULES, "wires": FAN_IN_WIRES})
        ports = [(edge.source.port, edge.target.port) for edge in workflow.edges]
        assert ports == [("out", "in"), ("out", "in:1")]
        assert workflow.outputs["default"] == Endpoint("u", "out")

    def test_conf_survives_verbatim(self):
        workflow = Workflow.parse({"modules": MODULES})
        assert dict(_module_node(workflow, "sw-2").conf) == {
            "count": {"type": "int", "value": "3"}
        }

    def test_options_pass_through(self):
        modules: list[DagModule] = [
            {"id": "t", "type": "tokenizer", "options": {"emit": True}}
        ]
        workflow = Workflow.parse({"modules": modules})
        assert dict(_module_node(workflow, "t").options) == {"emit": True}

    def test_pipe_dag_accepts_the_older_type_spelling_of_name(self):
        named = Workflow.parse({"modules": [{"name": "forever"}]})
        typed = Workflow.parse({"modules": [{"type": "forever"}]})
        agreeing = Workflow.parse({"modules": [{"name": "forever", "type": "forever"}]})
        assert named == typed == agreeing
        assert _module_node(typed, "sw-1").name == "forever"

    def test_pipe_dag_offers_known_node_fields_to_the_node(self):
        embed = Embed({"name": "fetch", "conf": {}})
        workflow = Workflow.parse({"modules": [{"name": "loop", "embed": embed}]})
        module = _module_node(workflow, "sw-1")
        assert module.embed is not None
        assert module.embed["name"] == "fetch"

    def test_expanded_dag_runs(self):
        workflow = Workflow.parse(_dag("pipe_forever"))
        assert list(Pipeline(workflow)) == [{"forever": True}] * 3

    def test_reordered_dag_runs_in_wired_order(self):
        workflow = Workflow.parse(_dag("pipe_reordered"))
        assert list(Pipeline(workflow)) == [{"forever": True}] * 2

    def test_empty_modules_raise_invalid_pipeline(self):
        with pytest.raises(InvalidPipelineError, match="no nodes"):
            Workflow.parse({"modules": []})

    @pytest.mark.parametrize(
        ("document", "message"),
        [
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


_NODE_VALUE_PLACEMENTS = {
    "options": lambda value: {"name": "tag", "options": {"assign": value}},
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


class TestNormalizeWorkflow:
    def test_list_nodes_generate_occurrence_ids(self):
        workflow = normalize_workflow(
            {"nodes": [{"name": "fetch"}, {"name": "filter"}, {"name": "filter"}]}
        )
        assert list(workflow.nodes) == ["fetch-1", "filter-1", "filter-2"]

    def test_mapping_nodes_keep_explicit_ids(self):
        workflow = normalize_workflow({"nodes": {"a": {"name": "fetch"}}})
        assert isinstance(workflow.nodes["a"], ModuleNode)
        assert workflow.nodes["a"].name == "fetch"

    def test_explicit_id_in_list_is_preserved(self):
        workflow = normalize_workflow({"nodes": [{"id": "keep", "name": "fetch"}]})
        assert list(workflow.nodes) == ["keep"]

    def test_family_dispatch_and_enum_coercion(self):
        workflow = normalize_workflow(
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
        read = workflow.nodes["read-1"]
        write = workflow.nodes["write-1"]
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
        workflow = normalize_workflow(
            {"nodes": _TWO_NODES, "edges": [{"source": source, "target": target}]}
        )
        source_port, target_port = expected
        assert workflow.edges == (
            StreamEdge(Endpoint("a", source_port), Endpoint("b", target_port)),
        )

    def test_publish_edge_detected_from_subscribe_target(self):
        workflow = normalize_workflow(
            {
                "nodes": [
                    {"id": "a", "name": "fetch"},
                    {"id": "s", "name": "sub", "family": "subscribe"},
                ],
                "edges": [{"source": {"node": "a"}, "target": {"node": "s"}}],
            }
        )
        assert isinstance(workflow.nodes["s"], SubscribeNode)
        assert isinstance(workflow.edges[0], PublishEdge)

    def test_omitted_outputs_materialize_single_leaf(self):
        workflow = normalize_workflow(
            {
                "nodes": _TWO_NODES,
                "edges": [{"source": {"node": "a"}, "target": {"node": "b"}}],
            }
        )
        assert workflow.outputs == {"default": Endpoint("b", "out")}

    def test_omitted_outputs_empty_when_ambiguous(self):
        workflow = normalize_workflow(
            {"nodes": [{"id": "a", "name": "fetch"}, {"id": "b", "name": "other"}]}
        )
        assert workflow.outputs == {}

    def test_explicit_outputs_alias_ports(self):
        workflow = normalize_workflow(
            {
                "nodes": [{"id": "a", "name": "route"}],
                "outputs": {"errors": {"node": "a", "port": "_OUTPUT2"}},
            }
        )
        assert workflow.outputs == {"errors": Endpoint("a", "out:1")}

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
        workflow = normalize_workflow(
            {"nodes": [{"id": "a", "name": "fetch"}], "inputs": {"n": declaration}}
        )
        assert workflow.inputs["n"] == schema

    def test_bare_string_resource_binds_to_itself(self):
        workflow = normalize_workflow(
            {"nodes": [{"id": "a", "name": "fetch", "resources": "db"}]}
        )
        assert workflow.nodes["a"].resources == {"db": "db"}

    @pytest.mark.parametrize(
        ("resources", "expected"),
        [
            pytest.param(["db", "cache"], ("db", "cache"), id="list"),
            pytest.param("db", ("db",), id="bare-string"),
        ],
    )
    def test_top_level_resources_normalize_to_tuple(self, resources, expected):
        workflow = normalize_workflow(
            {"nodes": [{"id": "a", "name": "fetch"}], "resources": resources}
        )
        assert workflow.resources == expected

    def test_explicit_stream_family_to_subscribe_is_preserved(self):
        workflow = normalize_workflow(
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
        assert isinstance(workflow.edges[0], StreamEdge)

    def test_explicit_empty_outputs_not_materialized(self):
        workflow = normalize_workflow(
            {"nodes": [{"id": "a", "name": "fetch"}], "outputs": {}}
        )
        assert workflow.outputs == {}

    def test_write_dest_is_preserved(self):
        workflow = normalize_workflow(
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
        write = workflow.nodes["w-1"]
        assert isinstance(write, WriteNode)
        assert write.dest == "out.json"

    def test_node_conf_is_isolated_from_caller_mutation(self):
        conf = {"limit": 5}
        workflow = normalize_workflow(
            {"nodes": [{"id": "a", "name": "fetch", "conf": conf}]}
        )
        node = workflow.nodes["a"]
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

    def test_mapping_key_matching_inner_id_allowed(self):
        workflow = normalize_workflow({"nodes": {"a": {"id": "a", "name": "fetch"}}})
        assert list(workflow.nodes) == ["a"]

    @pytest.mark.parametrize(
        "spelling",
        [
            pytest.param({"format": "csv"}, id="format-alias"),
            pytest.param({"fmt": "csv", "format": "csv"}, id="agreeing-fmt-format"),
        ],
    )
    def test_format_alias_maps_to_fmt(self, spelling):
        workflow = normalize_workflow({"nodes": [{**_READ_NODE, **spelling}]})
        read = workflow.nodes["r"]
        assert isinstance(read, ReadNode)
        assert read.fmt is Formats.CSV

    def test_raw_call_options_are_accepted(self):
        workflow = normalize_workflow(
            {
                "nodes": [
                    {
                        "name": "tokenizer",
                        "options": {"field": "title", "count": "first"},
                    }
                ]
            }
        )
        node = workflow.nodes["tokenizer-1"]
        assert isinstance(node, ModuleNode)
        assert node.options == {"field": "title", "count": "first"}
        assert node.conf == {}

    def test_nested_conf_is_deeply_frozen_and_isolated(self):
        inner = {"k": 1}
        workflow = normalize_workflow(
            {
                "nodes": [
                    {"id": "a", "name": "f", "conf": {"nested": inner, "list": [1, 2]}}
                ]
            }
        )
        inner["k"] = 99
        node = workflow.nodes["a"]
        assert isinstance(node, ModuleNode)
        assert node.conf is not None
        assert node.conf.get("nested") == {"k": 1}
        assert node.conf.get("list") == (1, 2)
        assert isinstance(node.conf.get("nested"), FrozenDict)

    def test_raw_embed_becomes_a_read_only_node_field(self):
        workflow = normalize_workflow(
            {
                "nodes": [
                    {"name": "loop", "embed": {"name": "tokenizer", "conf": {"d": " "}}}
                ]
            }
        )
        node = workflow.nodes["loop-1"]
        assert isinstance(node, ModuleNode)
        assert node.embed == {"name": "tokenizer", "conf": {"d": " "}}
        assert isinstance(node.embed, FrozenDict)
        assert node.conf == {}

    def test_embed_conf_defaults_to_empty_when_omitted(self):
        workflow = normalize_workflow(
            {"nodes": [{"name": "loop", "embed": {"name": "tokenizer"}}]}
        )
        node = workflow.nodes["loop-1"]
        assert isinstance(node, ModuleNode)
        assert node.embed == {"name": "tokenizer", "conf": {}}

    def test_generated_ids_skip_explicit_ids(self):
        nodes = [{"name": "fetch"}, {"id": "fetch-1", "name": "sort"}]
        workflow = normalize_workflow({"nodes": nodes})
        assert list(workflow.nodes) == ["fetch-2", "fetch-1"]

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

    @pytest.mark.parametrize(
        "port", ["out:", "bogus:x", "", "out:-1", "in:-1", "out:a b"]
    )
    def test_invalid_port_rejected(self, port):
        edge = {"source": {"node": "a"}, "target": {"node": "b", "port": port}}

        with pytest.raises(InvalidPipelineError, match="port"):
            normalize_workflow({"nodes": _TWO_NODES, "edges": [edge]})

    @pytest.mark.parametrize("declaration", [5, ["a"], None])
    def test_input_without_type_name_or_schema_raises(self, declaration):
        raw = {"nodes": [{"id": "a", "name": "fetch"}], "inputs": {"n": declaration}}

        with pytest.raises(InvalidPipelineError, match="type name or mapping"):
            normalize_workflow(raw)

    @pytest.mark.parametrize(
        "value",
        [
            Decimal("1.50"),
            date(2020, 6, 15),
            {"a", "b"},
            b"bytes",
            float("nan"),
            float("inf"),
        ],
    )
    def test_non_json_native_conf_value_rejected(self, value):
        raw = {"nodes": [{"id": "n", "name": "tag", "conf": {"x": value}}]}

        with pytest.raises(InvalidPipelineError):
            normalize_workflow(raw)

    @pytest.mark.parametrize(
        "value", [Decimal("1.50"), {"a", "b"}, b"bytes", float("nan")]
    )
    @pytest.mark.parametrize("placement", sorted(_NODE_VALUE_PLACEMENTS))
    def test_non_json_native_node_value_rejected(self, placement, value):
        raw = {"nodes": [{"id": "n", **_NODE_VALUE_PLACEMENTS[placement](value)}]}

        with pytest.raises(InvalidPipelineError, match="JSON-native"):
            normalize_workflow(raw)

    def test_non_string_policy_key_rejected(self):
        raw = {
            "nodes": [
                {"id": "n", "family": "cache", "name": "cache", "policy": {1: True}}
            ]
        }

        with pytest.raises(
            InvalidPipelineError, match="mapping key must be of type str"
        ):
            normalize_workflow(raw)


def _workflow(nodes, edges=(), outputs=None, inputs=None, resources=(), version="2"):
    return Workflow(
        nodes=nodes,
        edges=tuple(edges),
        outputs={} if outputs is None else outputs,
        inputs={} if inputs is None else inputs,
        resources=resources,
        version=version,
    )


def _counted_source(consumed):
    for index in range(3):
        consumed.append(index)
        yield {"title": str(index)}


_A = ModuleNode(id="a", name="fetch")
_B = ModuleNode(id="b", name="sort")


class TestRequireModuleOnly:
    def test_a_module_only_workflow_passes(self):
        workflow = Workflow(nodes=[_A], outputs={"default": Endpoint("a", "out")})

        assert workflow.require_module_only("execution") is None

    def test_other_families_are_named_with_the_activity(self):
        write = WriteNode(id="w", name="write", backend="file", dest="out.csv")
        cache = CacheNode(id="c", name="cache")
        nodes = [_A, write, cache]
        workflow = Workflow(nodes=nodes, outputs={"default": Endpoint("a", "out")})

        with pytest.raises(InvalidPipelineError, match="cache, write node execution"):
            workflow.require_module_only("execution")


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
        workflow = _workflow(nodes, edges=edges, outputs=outputs, resources=resources)
        assert workflow.validate() is None

    def test_unsupported_version_rejected(self):
        workflow = _workflow(
            [_A], outputs={"default": Endpoint("a", "out")}, version="1"
        )
        with pytest.raises(InvalidPipelineError, match="unsupported workflow version"):
            workflow.validate()

    def test_empty_node_set_rejected(self):
        with pytest.raises(InvalidPipelineError, match="no nodes"):
            _workflow([]).validate()

    def test_multiple_stream_edges_into_one_port_rejected(self):
        b = ModuleNode(id="b", name="fetch")
        c = ModuleNode(id="c", name="join")
        edges = [
            StreamEdge(Endpoint("a", "out"), Endpoint("c", "in")),
            StreamEdge(Endpoint("b", "out"), Endpoint("c", "in")),
        ]
        workflow = _workflow(
            [_A, b, c], edges=edges, outputs={"default": Endpoint("c", "out")}
        )
        with pytest.raises(InvalidPipelineError, match="multiple stream edges"):
            workflow.validate()

    @pytest.mark.parametrize(("edge", "target"), EDGE_FAMILY_MISMATCHES)
    def test_edge_family_disagreeing_with_its_target_rejected(self, edge, target):
        workflow = _workflow(
            [_A, target],
            edges=[edge(Endpoint("a", "out"), Endpoint("b", "in"))],
            outputs={"default": Endpoint("a", "out")},
        )
        with pytest.raises(InvalidPipelineError, match="edge family disagrees"):
            workflow.validate()

    def test_unresolved_resource_reference_rejected(self):
        node = ModuleNode(id="a", name="fetch", resources={"db": "prod"})
        workflow = _workflow([node], outputs={"default": Endpoint("a", "out")})
        with pytest.raises(InvalidPipelineError, match="unresolved resource"):
            workflow.validate()

    def test_non_empty_graph_without_output_rejected(self):
        with pytest.raises(InvalidPipelineError, match="exposes no workflow output"):
            _workflow([_A]).validate()

    @pytest.mark.parametrize(
        ("edges", "output", "match"),
        [
            pytest.param(
                [StreamEdge(Endpoint("a", "out"), Endpoint("ghost", "in"))],
                Endpoint("b", "out"),
                "missing node",
                id="missing-edge-node",
            ),
            pytest.param(
                [], Endpoint("ghost", "out"), "missing node", id="missing-output-node"
            ),
            pytest.param(
                [StreamEdge(Endpoint("a", "in"), Endpoint("b", "in"))],
                Endpoint("b", "out"),
                r"'a', 'in'.*not an 'out' port",
                id="edge-source-on-input-port",
            ),
            pytest.param(
                [StreamEdge(Endpoint("a", "out"), Endpoint("b", "out"))],
                Endpoint("b", "out"),
                r"'b', 'out'.*not an 'in' port",
                id="edge-target-on-output-port",
            ),
            pytest.param(
                [], Endpoint("a", "in"), "not an 'out' port", id="output-on-input-port"
            ),
            pytest.param(
                [],
                Endpoint("a", "sideways"),
                "invalid port direction",
                id="malformed-port",
            ),
            pytest.param(
                [StreamEdge(Endpoint("a", "out"), Endpoint("b", "in:0"))],
                Endpoint("b", "out"),
                "invalid port",
                id="in:0",
            ),
            pytest.param(
                [StreamEdge(Endpoint("a", "out:0"), Endpoint("b", "in"))],
                Endpoint("b", "out"),
                "invalid port",
                id="out:0",
            ),
        ],
    )
    def test_unusable_endpoint_rejected(self, edges, output, match):
        workflow = _workflow([_A, _B], edges=edges, outputs={"default": output})
        with pytest.raises(InvalidPipelineError, match=match):
            workflow.validate()

    def test_cycle_rejected(self):
        a = ModuleNode(id="a", name="sort")
        edges = [
            StreamEdge(Endpoint("a", "out"), Endpoint("b", "in")),
            StreamEdge(Endpoint("b", "out"), Endpoint("a", "in")),
        ]
        workflow = _workflow(
            [a, _B], edges=edges, outputs={"default": Endpoint("b", "out")}
        )
        with pytest.raises(InvalidPipelineError, match=r"cycle.*\['a', 'b'\]"):
            workflow.validate()

    def test_self_loop_rejected(self):
        node = ModuleNode(id="a", name="sort")
        edges = [StreamEdge(Endpoint("a", "out"), Endpoint("a", "in"))]
        workflow = _workflow(
            [node], edges=edges, outputs={"default": Endpoint("a", "out")}
        )
        with pytest.raises(InvalidPipelineError, match=r"cycle.*\['a'\]"):
            workflow.validate()

    @pytest.mark.xfail(
        strict=True,
        reason="module configuration is not validated against its contract yet: "
        "an unknown key is silently ignored",
    )
    def test_unknown_conf_key_rejected_before_the_source_is_read(self):
        consumed = []
        rule = {"fieldd": "title", "op": "contains", "value": "1"}
        pipeline = _counted_source(consumed) | Pipeline.from_module(
            "filter",
            conf={"rule": rule},  # pyright: ignore[reportArgumentType]
        )

        with pytest.raises(InvalidPipelineError, match="fieldd"):
            list(pipeline)

        assert consumed == []

    @pytest.mark.xfail(
        strict=True,
        reason="module configuration is not validated against its contract yet: "
        "a wrongly typed value fails later with AttributeError",
    )
    def test_wrongly_typed_conf_value_rejected_before_the_source_is_read(self):
        consumed = []
        pipeline = _counted_source(consumed) | Pipeline.from_module(
            "sort",
            conf={"rule": 5},  # pyright: ignore[reportArgumentType]
        )

        with pytest.raises(InvalidPipelineError, match="rule"):
            list(pipeline)

        assert consumed == []


def _wire(wid, src_mod, tgt_mod, src_port="_OUTPUT", tgt_port="_INPUT"):
    return {
        "id": wid,
        "src": {"id": src_port, "moduleid": src_mod},
        "tgt": {"id": tgt_port, "moduleid": tgt_mod},
    }


class TestMigrate:
    def test_terminal_output_becomes_default_output(self):
        workflow = migrate_v1_to_v2(
            {
                "modules": [
                    {"id": "sw-1", "type": "fetch", "conf": {}},
                    {"id": "_OUTPUT", "type": "output", "conf": {}},
                ],
                "wires": [_wire("_w1", "sw-1", "_OUTPUT")],
            }
        )
        assert list(workflow.nodes) == ["sw-1"]
        assert workflow.outputs["default"] == Endpoint("sw-1", "out")
        assert workflow.edges == ()
        assert workflow.version == "2"

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
        workflow = migrate_v1_to_v2(
            {
                "modules": [
                    {"id": "a", "type": "fetch", "conf": {}},
                    {"id": "b", "type": "urlbuilder", "conf": {}},
                ],
                "wires": [_wire("_w1", "a", "b", source_port, target_port)],
            }
        )
        source, target = expected
        assert workflow.edges[0].source == Endpoint("a", source)
        assert workflow.edges[0].target == Endpoint("b", target)

    def test_write_module_preserves_destination_mode_and_keys(self):
        workflow = migrate_v1_to_v2(
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
        node = workflow.nodes["w"]
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
        workflow = migrate_v1_to_v2(
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
        node = workflow.nodes["w"]
        assert isinstance(node, WriteNode)
        assert node.mode is mode

    def test_write_module_without_format_defaults_to_none(self):
        workflow = migrate_v1_to_v2(
            {"modules": [{"id": "w", "type": "write", "conf": {"dest": "out.dat"}}]}
        )
        node = workflow.nodes["w"]
        assert isinstance(node, WriteNode)
        assert node.backend is Backends.FILE
        assert node.fmt is None

    def test_module_call_options_become_node_options(self):
        workflow = migrate_v1_to_v2(
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
        node = workflow.nodes["c"]
        assert isinstance(node, ModuleNode)
        assert node.conf == {"x": 1}
        assert node.options == {
            "emit": True,
            "assign": "total",
            "field": "title",
            "count": "first",
        }

    def test_call_option_does_not_collide_with_a_same_named_conf_key(self):
        workflow = migrate_v1_to_v2(
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
        node = workflow.nodes["t"]
        assert isinstance(node, ModuleNode)
        assert node.conf == {"count": {"value": 3}}
        assert node.options == {"count": "first"}

    def test_loop_embed_and_its_configuration_become_the_node_embed(self):
        workflow = migrate_v1_to_v2(
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
        node = workflow.nodes["sw-2"]
        assert isinstance(node, ModuleNode)
        assert node.conf == {}
        assert node.embed == {
            "name": "tokenizer",
            "conf": {"delimiter": {"value": ","}},
        }
        assert node.options == {
            "count": "first",
            "assign": "words",
            "emit": True,
            "field": "title",
        }

    def test_loop_embedded_subpipe_keeps_its_prefixed_name(self):
        workflow = migrate_v1_to_v2(
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
        node = workflow.nodes["sw-2"]
        assert isinstance(node, ModuleNode)
        assert node.conf == {}
        assert node.embed == {"name": "pipe:shout", "conf": {}}

    def test_uppercase_conf_keys_are_lowered(self):
        workflow = migrate_v1_to_v2(
            {"modules": [{"id": "f", "type": "fetch", "conf": {"URL": {"value": "x"}}}]}
        )
        node = workflow.nodes["f"]
        assert isinstance(node, ModuleNode)
        assert node.conf == {"url": {"value": "x"}}

    def test_orphan_module_is_retained_not_erased(self):
        workflow = migrate_v1_to_v2(
            {
                "modules": [
                    {"id": "a", "type": "fetch", "conf": {}},
                    {"id": "orphan", "type": "count", "conf": {}},
                    {"id": "_OUTPUT", "type": "output", "conf": {}},
                ],
                "wires": [_wire("_w1", "a", "_OUTPUT")],
            }
        )
        assert "orphan" in workflow.nodes

    def test_omitted_output_node_defaults_to_lone_leaf(self):
        workflow = migrate_v1_to_v2(
            {
                "modules": [
                    {"id": "a", "type": "fetch", "conf": {}},
                    {"id": "b", "type": "filter", "conf": {}},
                ],
                "wires": [_wire("_w1", "a", "b")],
            }
        )
        assert workflow.outputs == {"default": Endpoint("b", "out")}

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
        workflow = normalize_workflow(RICH_RAW)
        assert workflow.serialize(indent=None) == RICH_GOLDEN

    def test_default_form_is_indented(self):
        workflow = normalize_workflow(RICH_RAW)
        assert workflow.serialize() == workflow.serialize(indent=4)
        assert workflow.serialize() != workflow.serialize(indent=None)

    @pytest.mark.parametrize("raw", TOPOLOGIES.values(), ids=TOPOLOGIES.keys())
    def test_topologies_round_trip(self, raw):
        workflow = normalize_workflow(raw)
        assert Workflow.parse(workflow.serialize()) == workflow

    @pytest.mark.parametrize("raw", TOPOLOGIES.values(), ids=TOPOLOGIES.keys())
    def test_serialization_is_idempotent(self, raw):
        workflow = normalize_workflow(raw)
        once = workflow.serialize()
        assert Workflow.parse(once).serialize() == once

    def test_indented_output_is_readable_and_sorted(self):
        workflow = normalize_workflow(RICH_RAW)
        document = workflow.serialize(indent=2).decode("utf-8")
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
        workflow = normalize_workflow(TOPOLOGIES["call-options"])
        data = workflow.serialize(indent=None)
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
        workflow = normalize_workflow(raw)
        assert Workflow.parse(workflow.serialize()) == workflow

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
        workflow = normalize_workflow(raw)
        document = json.loads(workflow.serialize())
        node = document["nodes"]["loop-1"]

        assert node["embed"] == {
            "name": "tokenizer",
            "conf": {"delimiter": {"value": " "}},
        }
        assert "conf" not in node
        assert Workflow.parse(workflow.serialize()) == workflow


PARENT = [{"title": "hi"}]
EXCLAIMED = [{"title": "hi", "strconcat": "hi!"}]


def write_document(directory: Path, name: str, suffix: str) -> None:
    conf = StrconcatRawConf(
        {
            "part": [
                {"subkey": "title", "type": "text"},
                {"type": "text", "value": suffix},
            ]
        }
    )
    pipeline = Pipeline.from_module("strconcat", conf=conf)
    path = directory / f"{name}.json"
    path.write_bytes(pipeline.workflow.serialize())


@pytest.fixture
def documents(tmp_path: Path) -> Path:
    write_document(tmp_path, "pipe_exclaim", "!")
    write_document(tmp_path, "pipe_shout", "?")
    register_workflow_store(directory=tmp_path, replace=True)
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

    def test_document_exposes_both_interfaces(self):
        interfaces = dispatcher.require_interfaces("pipe_exclaim")
        assert interfaces == frozenset({"pipe", "async_pipe"})

    def test_document_embeds_in_a_loop(self):
        assert list(build_outer()) == EXCLAIMED

    def test_document_describes_dependencies(self):
        context = Context(ExecutionMode.DESCRIBE_DEPENDENCIES)
        pipe = dispatcher.require("pipe_exclaim")
        assert pipe(context=context) == ["strconcat"]

    def test_module_wins_over_document(self):
        pipeline = Pipeline.from_module("pipe_shout")
        items = list(PARENT | pipeline)
        assert items == EXCLAIMED

    def test_missing_name_still_raises(self):
        with pytest.raises(UnsupportedWorkflowError):
            dispatcher.require("pipe_missing")

    @async_test
    async def test_document_runs_async(self):
        pipe = dispatcher.require("pipe_exclaim", is_async=True)
        items = [item async for item in pipe(as_async(PARENT))]
        assert items == EXCLAIMED

    @async_test
    async def test_document_runs_as_async_pipeline(self):
        pipeline = Pipeline.from_module("pipe_exclaim")
        assert [item async for item in PARENT | pipeline] == EXCLAIMED
        assert [item async for item in build_outer()] == EXCLAIMED
