# vim: sw=4:ts=4:expandtab
"""Provides public tests for the ``Workflow`` graph and its documents."""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
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
from riko.definitions._workflow_definition import Workflow, normalize_workflow
from riko.definitions._write import WriteMode
from riko.runtime._compile import compile_workflow
from riko.runtime._pipeline import Pipeline
from riko.types._enums import Backends, IdentityMode
from riko.types._workflow import Endpoint
from riko.types.modules import ItemBuilderConf
from tests import TESTS_DIR, async_test
from tests._execution import OUTPUT_A
from tests._workflows import (
    EDGE_FAMILY_MISMATCHES,
    EXCLAIMED,
    PARENT,
    RAW_WORKFLOW,
    register_documents,
)

if TYPE_CHECKING:
    from pathlib import Path

    from riko.types._pipedef import Embed


_TWO_HASHES = [ModuleNode(id="b", name="hash"), ModuleNode(id="c", name="hash")]
_A = ModuleNode(id="a", name="fetch")
_C_IN = Endpoint("c", "in")
_HAS_DB = ModuleNode(id="a", name="fetch", resources={"db": "prod"})
_UNKNOWN_KEY_RULE = {"fieldd": "title", "op": "contains", "value": "1"}
_B = ModuleNode(id="b", name="sort")
_INVALID = InvalidPipelineError
_A_IN, _A_OUT = Endpoint("a", "in"), Endpoint("a", "out")
_B_IN, _B_OUT = Endpoint("b", "in"), Endpoint("b", "out")

_MERGE = {
    "nodes": [_A, ModuleNode(id="b", name="fetch"), ModuleNode(id="c", name="join")],
    "edges": [StreamEdge(_A_OUT, _C_IN), StreamEdge(_B_OUT, _C_IN)],
    "outputs": {"default": Endpoint("c", "out")},
}

NODE_FAMILIES = (
    (ModuleNode(id="fetch-1", name="fetch"), "module"),
    (ReadNode(id="read-1", name="read", backend=Backends.FILE), "read"),
    (WriteNode(id="write-1", name="write", backend=Backends.FILE), "write"),
    (CacheNode(id="cache-1", name="cache"), "cache"),
    (ActionNode(id="act-1", name="act", backend=Backends.HTTP), "action"),
    (SubscribeNode(id="sub-1", name="sub"), "subscribe"),
)


def _fetch_workflow() -> Workflow:
    node = ModuleNode(id="fetch-1", name="fetch")
    return Workflow(
        nodes=[node], edges=(), outputs={"default": Endpoint(node.id, "out")}, inputs={}
    )


APPENDS = [
    pytest.param(lambda flow: flow.with_node(_B), id="node"),
    pytest.param(lambda flow: flow.with_workflow(Workflow().with_node(_B)), id="flow"),
]


APPEND_REJECTIONS = [
    pytest.param(Workflow(nodes=[_B]), "appended workflow has nodes", id="no-default"),
    pytest.param(
        Workflow(nodes=_TWO_HASHES, outputs={"default": _B_OUT}),
        "exactly one node",
        id="two-open-inputs",
    ),
    pytest.param(
        Workflow(nodes=[_B], outputs={"default": _B_OUT, "side": _B_OUT}),
        "workflow output",
        id="named-output-clash",
    ),
    pytest.param(
        Workflow(inputs={"limit": {"type": "string"}}),
        "declare input",
        id="input-clash",
    ),
]


class TestWorkflow:
    def test_workflow_mappings_are_read_only(self):
        flow = _fetch_workflow()
        with pytest.raises(TypeError):
            flow.nodes["extra"] = flow.nodes["fetch-1"]  # type: ignore[index]
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
        embed: Embed = {"name": "hash", "conf": {}}
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
        assert index.edges == index.incoming["b"]

        with pytest.raises(TypeError):
            index.outputs["new"] = Endpoint("a", "out")  # type: ignore[index]

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

    def test_appending_a_node_declares_its_resources(self):
        flow = Workflow(resources=("cache",))
        node = ModuleNode(id="a", name="hash", resources={"x": "db", "y": "cache"})
        assert flow.with_node(node).resources == ("cache", "db")

    @pytest.mark.parametrize("append", APPENDS)
    def test_appending_needs_a_default_output_to_follow(self, append):
        flow = Workflow(nodes=[ModuleNode(id="a", name="fetch")])
        with pytest.raises(
            InvalidPipelineError, match="this workflow has nodes but no default output"
        ):
            append(flow)

    @pytest.mark.parametrize(
        "field", ["nodes", "outputs", "inputs", "edges", "resources"]
    )
    def test_none_is_not_an_omitted_field(self, field: str):
        """An explicit None is rejected rather than read as the empty default."""
        fields: dict[str, Any] = {field: None}

        with pytest.raises(InvalidPipelineError, match=f"Workflow '{field}'"):
            Workflow(**fields)

    def test_omitted_fields_are_empty(self):
        """Every omitted field defaults to its empty form."""
        flow = Workflow()
        mappings = (flow.nodes, flow.outputs, flow.inputs)
        assert mappings == ({}, {}, {})
        assert (flow.edges, flow.resources) == ((), ())

    @pytest.mark.parametrize(("other", "match"), APPEND_REJECTIONS)
    def test_appending_a_workflow_rejects(self, other, match):
        flow = Workflow(
            nodes=[ModuleNode(id="a", name="fetch")],
            outputs={"default": Endpoint("a", "out"), "side": Endpoint("a", "out")},
            inputs={"limit": {"type": "integer"}},
        )
        with pytest.raises(InvalidPipelineError, match=match):
            flow.with_workflow(other)

    def test_nodes_must_be_an_iterable_of_nodes(self):
        nodes: Any = {"a": ModuleNode(id="a", name="hash")}

        with pytest.raises(InvalidPipelineError, match="'nodes' must be a list"):
            Workflow(nodes=nodes, outputs=OUTPUT_A)

    def test_a_node_id_cannot_repeat(self):
        nodes = [ModuleNode(id="a", name="hash"), ModuleNode(id="a", name="count")]

        with pytest.raises(InvalidPipelineError, match="must not repeat a node id"):
            Workflow(nodes=nodes, outputs=OUTPUT_A)

    @pytest.mark.parametrize("field", ["nodes", "edges"])
    @pytest.mark.parametrize("value", ["ab", b"ab", {"a": 1}, 3])
    def test_node_and_edge_containers_must_be_lists(self, field: str, value: Any):
        kwargs = {"nodes": [ModuleNode(id="a", name="hash")], field: value}

        with pytest.raises(InvalidPipelineError, match=f"'{field}' must be a list"):
            Workflow(outputs=OUTPUT_A, **kwargs)

    def test_edges_must_be_edges(self):
        nodes = [ModuleNode(id="a", name="hash")]
        edges: Any = [("a", "b")]

        with pytest.raises(InvalidPipelineError, match="Workflow edge"):
            Workflow(nodes=nodes, outputs=OUTPUT_A, edges=edges)

    def test_edge_endpoints_must_be_endpoints(self):
        with pytest.raises(InvalidPipelineError, match="StreamEdge 'source'"):
            StreamEdge(("a", "out"), Endpoint("b", "in"))  # pyright: ignore[reportArgumentType]

    @pytest.mark.parametrize(("node", "port"), [(1, "out"), ("a", None)])
    def test_endpoint_fields_must_be_strings(self, node: Any, port: Any):
        with pytest.raises(InvalidPipelineError, match="Endpoint '"):
            Endpoint(node, port)

    @pytest.mark.parametrize(
        ("fields", "match"),
        [
            pytest.param(
                {"nodes": [1], "outputs": {}},
                "Workflow node position 0 must be of type Node",
                id="nodes",
            ),
            pytest.param(
                {"nodes": [], "outputs": {"o": 1}},
                "Workflow output 'o' must be of type Endpoint",
                id="outputs",
            ),
        ],
    )
    def test_mapping_values_must_have_the_field_type(
        self, fields: dict[str, Any], match: str
    ):
        with pytest.raises(InvalidPipelineError, match=match):
            Workflow(**fields)

    @pytest.mark.parametrize("field", ["outputs", "inputs"])
    def test_non_mapping_fields_are_rejected(self, field: str):
        fields: dict[str, Any] = {"nodes": [], "outputs": {}, field: "abc"}

        with pytest.raises(InvalidPipelineError, match=f"Workflow '{field}'"):
            Workflow(**fields)

    @pytest.mark.xfail(
        strict=True,
        reason="owned by the pending workflow input declarations work: a strict "
        "Workflow accepts an input declaration that is not a JSON Schema mapping",
    )
    @pytest.mark.parametrize("declaration", [5, "string"])
    def test_non_schema_inputs_are_rejected(self, declaration: object):
        with pytest.raises(InvalidPipelineError, match="Workflow 'inputs'"):
            Workflow(nodes=[], outputs={}, inputs={"q": declaration})


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
    pytest.param(lambda: ModuleNode(id=" ", name="hash"), "'id'", id="blank"),
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
    pytest.param({"resources": {"a-b": "db"}}, _INVALID, "identifiers", id="dashed"),
    pytest.param({"resources": "def"}, _INVALID, "identifiers", id="keyword"),
    pytest.param({"identity": "bogus"}, _INVALID, "'identity'", id="identity"),
    pytest.param({"fn": "len"}, TypeError, "callable", id="uncallable"),
]


class TestResourceBinding:
    @pytest.mark.parametrize(
        ("resources", "match"),
        [
            *(
                pytest.param(value, "must bind non-empty strings", id=repr(value))
                for value in (
                    b"db",
                    "",
                    {"db": 1},
                    {"db": None},
                    {1: "db"},
                    {"": "db"},
                    ["db", 1],
                )
            ),
            pytest.param(5, "must be a str, mapping, or iterable", id="non-binding"),
        ],
    )
    def test_invalid_bindings_are_rejected(self, resources: Any, match: str):
        with pytest.raises(InvalidPipelineError, match=f"node 'resources' {match}"):
            ModuleNode(id="a", name="hash", resources=resources)

    def test_an_alias_cannot_repeat(self):
        with pytest.raises(InvalidPipelineError, match="must not repeat an alias"):
            ModuleNode(id="a", name="hash", resources=["db", "db"])

    @pytest.mark.parametrize(
        ("resources", "expected"),
        [
            ("db", {"db": "db"}),
            (["db", "cache"], {"db": "db", "cache": "cache"}),
            ({"db": "primary_db"}, {"db": "primary_db"}),
            (None, {}),
        ],
    )
    def test_accepted_forms_normalize(self, resources: Any, expected: dict):
        assert (
            ModuleNode(id="a", name="hash", resources=resources).resources == expected
        )


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


class TestRequireRunnableOnly:
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
    pytest.param([], Endpoint("ghost", "out"), "missing node", id="missing-output"),
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
    pytest.param([], Endpoint("a", "sideways"), "port direction", id="malformed-port"),
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
    pytest.param([StreamEdge(_A_OUT, _A_IN)], _A_OUT, r"cycle.*'a'", id="self-loop"),
]


INVALID_CONFS = [
    pytest.param("filter", {"rule": _UNKNOWN_KEY_RULE}, "fieldd", id="unknown-key"),
    pytest.param("sort", {"rule": 5}, "rule", id="wrong-type"),
    pytest.param("simplemath", {"op": "nope", "other": {"value": 2}}, "op", id="op"),
    pytest.param("strconcat", {}, "part", id="missing-key"),
]


def _workflow(
    nodes, edges=(), outputs=None, inputs=None, resources=(), version="2"
) -> Workflow:
    return Workflow(
        nodes=nodes,
        edges=tuple(edges),
        outputs=outputs or {},
        inputs=inputs or {},
        resources=resources,
        version=version,
    )


def _counted_source(consumed):
    for index in range(3):
        consumed.append(index)
        yield {"title": str(index)}


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
class TestWorkflowDocument:
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
