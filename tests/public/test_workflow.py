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
from riko.definitions._workflow_definition import Workflow
from riko.definitions._write import WriteMode
from riko.runtime._compile import compile_workflow
from riko.runtime._pipeline import Pipeline
from riko.types._enums import Backends, IdentityMode
from riko.types._workflow import Endpoint, InputRef
from tests import FAN_IN_DAG, TESTS_DIR, TWO_NODES
from tests._execution import FETCH_NODE, HASH_NODE, M_NODE, OUTPUT_A, SORT_NODE
from tests._workflows import (
    CALLABLE_FLOW,
    CALLABLE_MATCH,
    EDGE_FAMILY_MISMATCHES,
    RAW_WORKFLOW,
    build_edge,
)

if TYPE_CHECKING:
    from riko.types._pipedef import Embed


_TWO_HASHES = [ModuleNode(id="b", name="hash"), ModuleNode(id="c", name="hash")]
_C_IN = Endpoint("c", "in")
_HAS_DB = ModuleNode(id="a", name="fetch", resources={"db": "prod"})
_UNKNOWN_KEY_RULE = {"fieldd": "title", "op": "contains", "value": "1"}
_INVALID = InvalidPipelineError
_URL_REF: dict[str, InputRef] = {"url": {"input": "u"}}
_ASKS_Q = ModuleNode(id="a", name="fetch", conf={"url": {"input": "q"}})
_A_IN, _A_OUT = Endpoint("a", "in"), Endpoint("a", "out")
_B_IN, _B_OUT = Endpoint("b", "in"), Endpoint("b", "out")

_MERGE_NODES = (
    FETCH_NODE,
    ModuleNode(id="b", name="fetch"),
    ModuleNode(id="c", name="join"),
)
_MERGE = {
    "nodes": _MERGE_NODES,
    "edges": [StreamEdge(_A_OUT, _C_IN), StreamEdge(_B_OUT, _C_IN)],
    "outputs": {"default": Endpoint("c", "out")},
}
_CONF_PENDING = "module configuration is not validated against its contract yet"
_HASH_FLOW: dict[str, Any] = {"nodes": [HASH_NODE], "outputs": OUTPUT_A}
_EMPTY_FLOW: dict[str, Any] = {"nodes": [], "outputs": {}}
_LIST_FIELDS = ("nodes", "edges")
_NON_LISTS = ("ab", b"ab", {"a": 1}, 3)
_BAD_SCHEMAS = "Workflow 'input_schemas'"
_UNBOUND_BINDINGS = {
    "bytes": b"db",
    "empty-name": "",
    "non-str-alias": {"db": 1},
    "none-alias": {"db": None},
    "non-str-key": {1: "db"},
    "empty-key": {"": "db"},
    "non-str-item": ["db", 1],
}
_UNBOUND_MSG = "must bind non-empty strings"
_TITLE_ROWS = [{"title": str(index)} for index in range(3)]
_WRITE_NODE = WriteNode(id="write-1", name="write", backend=Backends.FILE)

NODE_FAMILIES = (
    (ModuleNode(id="fetch-1", name="fetch"), "module"),
    (ReadNode(id="read-1", name="read", backend=Backends.FILE), "read"),
    (_WRITE_NODE, "write"),
    (CacheNode(id="cache-1", name="cache"), "cache"),
    (ActionNode(id="act-1", name="act", backend=Backends.HTTP), "action"),
    (SubscribeNode(id="sub-1", name="sub"), "subscribe"),
)


def _fetch_workflow() -> Workflow:
    return Workflow().with_nodes(ModuleNode(id="fetch-1", name="fetch"))


WORKFLOW_BUILDS = [
    pytest.param(_fetch_workflow, id="constructed"),
    pytest.param(partial(Workflow.from_raw, RAW_WORKFLOW), id="normalized"),
]

APPENDS = [
    pytest.param(lambda flow: flow.with_nodes(SORT_NODE), id="node"),
    pytest.param(
        lambda flow: flow.with_workflow(Workflow().with_nodes(SORT_NODE)), id="flow"
    ),
]


APPEND_REJECTIONS = [
    pytest.param(
        Workflow(nodes=[SORT_NODE]), "appended workflow has nodes", id="no-default"
    ),
    pytest.param(
        Workflow(nodes=_TWO_HASHES, outputs={"default": _B_OUT}),
        "exactly one node",
        id="two-open-inputs",
    ),
    pytest.param(
        Workflow(nodes=[SORT_NODE], outputs={"default": _B_OUT, "side": _B_OUT}),
        "workflow output",
        id="named-output-clash",
    ),
    pytest.param(
        Workflow(input_schemas={"limit": {"type": "string"}}),
        "give input",
        id="input-clash",
    ),
]


FIELD_TYPE_REJECTIONS = [
    *(
        pytest.param(
            _HASH_FLOW | {f: v}, f"'{f}' must be a list", id=f"{f}-{type(v).__name__}"
        )
        for f in _LIST_FIELDS
        for v in _NON_LISTS
    ),
    pytest.param(_HASH_FLOW | {"edges": [("a", "b")]}, "Workflow edge", id="edge"),
    pytest.param(
        {"nodes": [1], "outputs": {}},
        "Workflow node position 0 must be of type RikoNode",
        id="node",
    ),
    pytest.param(
        {"nodes": [], "outputs": {"o": 1}},
        "Workflow output 'o' must be of type Endpoint",
        id="output",
    ),
    pytest.param(_EMPTY_FLOW | {"outputs": "abc"}, "Workflow 'outputs'", id="outputs"),
    pytest.param(
        _EMPTY_FLOW | {"input_schemas": "abc"}, _BAD_SCHEMAS, id="input-schemas"
    ),
    pytest.param(
        _EMPTY_FLOW | {"input_schemas": {"q": 5}}, _BAD_SCHEMAS, id="schema-int"
    ),
    pytest.param(
        _EMPTY_FLOW | {"input_schemas": {"q": "string"}}, _BAD_SCHEMAS, id="schema-str"
    ),
]


class TestWorkflow:
    @pytest.mark.parametrize("build", WORKFLOW_BUILDS)
    def test_workflow_version_defaults_to_2(self, build):
        assert build().version == "2"

    def test_repr_counts_a_branching_graph(self):
        expected = "Workflow(nodes: 3, edges: 2; outputs: default)"
        assert repr(Workflow.parse(FAN_IN_DAG)) == expected

    def test_repr_shows_an_empty_workflow(self):
        assert repr(Workflow()) == "Workflow(empty)"

    def test_repr_counts_disconnected_nodes(self):
        flow = Workflow.from_raw({"nodes": [{"name": "fetch"}, {"name": "sort"}]})
        assert repr(flow) == "Workflow(nodes: 2, edges: 0)"

    def test_repr_survives_a_cycle(self):
        flow = Workflow.from_raw(
            {"nodes": TWO_NODES, "edges": [build_edge("a", "b"), build_edge("b", "a")]}
        )
        assert repr(flow) == "Workflow(nodes: 2, edges: 2)"

    def test_embeds_list_only_the_loop_nodes(self):
        embed: Embed = {"name": "hash", "conf": {}}
        nodes = [
            ModuleNode(id="loop-1", name="loop", embed=embed),
            ModuleNode(id="hash-1", name="hash"),
            _WRITE_NODE,
        ]
        flow = Workflow(nodes=nodes)
        assert dict(flow.embeds) == {"loop-1": embed}

    def test_workflow_index_orders_and_indexes(self) -> None:
        a = ModuleNode(id="a", name="m")
        c = ModuleNode(id="c", name="m")
        edge = StreamEdge(Endpoint("a", "out"), Endpoint("b", "in"))
        outputs = {"default": Endpoint("b", "out"), "extra": Endpoint("c", "out")}
        flow = Workflow(
            nodes=[a, M_NODE, c],
            outputs=outputs,
            input_schemas={},
            edges=(edge,),
            resources=(),
        )
        index = flow.index

        assert set(index.order) == {"a", "b", "c"}
        assert index.order.index("a") < index.order.index("b")
        assert set(index.roots) == {"a", "c"}
        assert set(index.leaves) == {"b", "c"}
        assert index.upstream["b"] == frozenset({"a"})
        assert index.downstream["a"] == frozenset({"b"})
        assert index.incoming["b"][0].source_id == "a"
        assert index.outgoing["a"][0].target_id == "b"
        assert set(index.outputs) == {"default", "extra"}
        assert index.required == {"default": ("a", "b"), "extra": ("c",)}
        assert index.edges == index.incoming["b"]

        with pytest.raises(TypeError):
            index.outputs["new"] = Endpoint("a", "out")  # type: ignore[index]

    def test_cycle_names_only_the_nodes_on_the_cycle(self):
        src = ModuleNode(id="src", name="fetch")
        a = ModuleNode(id="a", name="sort")
        after = ModuleNode(id="after", name="sort")
        edges = (
            StreamEdge(Endpoint("src", "out"), Endpoint("a", "in")),
            StreamEdge(Endpoint("a", "out"), Endpoint("b", "in")),
            StreamEdge(Endpoint("b", "out"), Endpoint("a", "in:1")),
            StreamEdge(Endpoint("b", "out"), Endpoint("after", "in")),
        )
        flow = Workflow(
            nodes=[src, a, SORT_NODE, after],
            edges=edges,
            outputs={"default": Endpoint("after", "out")},
            input_schemas={},
            resources=(),
            version="2",
        )
        assert flow.index.cyclic == ("a", "b")

    def test_appending_a_node_declares_its_resources(self):
        flow = Workflow(resources=("cache",))
        node = ModuleNode(id="a", name="hash", resources={"x": "db", "y": "cache"})
        assert flow.with_nodes(node).resources == ("cache", "db")

    def test_omitted_fields_are_empty(self):
        """Every omitted field defaults to its empty form."""
        flow = Workflow()
        mappings = (flow.nodes, flow.outputs, flow.input_schemas)
        assert mappings == ({}, {}, {})
        assert (flow.edges, flow.resources) == ((), ())

    def test_workflow_mappings_are_read_only(self):
        flow = _fetch_workflow()
        with pytest.raises(TypeError):
            flow.nodes["extra"] = flow.nodes["fetch-1"]  # type: ignore[index]
        with pytest.raises(TypeError):
            flow.outputs["extra"] = Endpoint("fetch-1", "out")  # type: ignore[index]

    @pytest.mark.parametrize("append", APPENDS)
    def test_appending_needs_a_default_output_to_follow(self, append):
        flow = Workflow(nodes=[FETCH_NODE])
        with pytest.raises(
            InvalidPipelineError, match="this workflow has nodes but no default output"
        ):
            append(flow)

    @pytest.mark.parametrize(
        "field", ["nodes", "outputs", "input_schemas", "edges", "resources"]
    )
    def test_none_is_not_an_omitted_field(self, field: str):
        """An explicit None is rejected rather than read as the empty default."""
        fields: dict[str, Any] = {field: None}

        with pytest.raises(InvalidPipelineError, match=f"Workflow '{field}'"):
            Workflow(**fields)

    @pytest.mark.parametrize(("other", "match"), APPEND_REJECTIONS)
    def test_appending_a_workflow_rejects(self, other, match):
        flow = Workflow(
            nodes=[FETCH_NODE],
            outputs={"default": Endpoint("a", "out"), "side": Endpoint("a", "out")},
            input_schemas={"limit": {"type": "integer"}},
        )
        with pytest.raises(InvalidPipelineError, match=match):
            flow.with_workflow(other)

    def test_a_node_id_cannot_repeat(self):
        nodes = [HASH_NODE, ModuleNode(id="a", name="count")]

        with pytest.raises(InvalidPipelineError, match="must not repeat a node id"):
            Workflow(nodes=nodes, outputs=OUTPUT_A)

    @pytest.mark.parametrize(("fields", "match"), FIELD_TYPE_REJECTIONS)
    def test_a_field_rejects_a_value_of_the_wrong_type(
        self, fields: dict[str, Any], match: str
    ):
        with pytest.raises(InvalidPipelineError, match=match):
            Workflow(**fields)

    def test_edge_endpoints_must_be_endpoints(self):
        with pytest.raises(InvalidPipelineError, match="StreamEdge 'source'"):
            StreamEdge(("a", "out"), Endpoint("b", "in"))  # pyright: ignore[reportArgumentType]

    @pytest.mark.parametrize(("node", "port"), [(1, "out"), ("a", None)])
    def test_endpoint_fields_must_be_strings(self, node: Any, port: Any):
        with pytest.raises(InvalidPipelineError, match="Endpoint '"):
            Endpoint(node, port)


class TestNodeFamily:
    @pytest.mark.parametrize(("node", "family"), NODE_FAMILIES, ids=str)
    def test_node_family_discriminant(self, node, family):
        assert node.family == family

    def test_edge_family_discriminants(self):
        endpoint = Endpoint("fetch-1", "out")
        assert StreamEdge(endpoint, endpoint).family == "stream"
        assert PublishEdge(endpoint, endpoint).family == "publish"

    def test_write_node_defaults(self):
        node = _WRITE_NODE
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

REFERENCED_INPUTS = [
    pytest.param(ModuleNode(id="a", name="fetch", conf=_URL_REF), {"u"}, id="conf"),
    pytest.param(
        ModuleNode(
            id="a",
            name="loop",
            conf={"assign_to": {"input": "q"}},
            embed={
                "name": "fetch",
                "conf": {"url": {"type": "url", "value": {"input": "u"}}},
            },
        ),
        {"q", "u"},
        id="loop-embed-conf",
    ),
    pytest.param(
        CallableNode(id="a", name="len", fn=len, kwargs={"n": {"input": "n"}}),
        {"n"},
        id="callable-kwargs",
    ),
]

JSON_FIELD_REJECTIONS = [
    pytest.param(
        ActionNode, {"backend": "file", "params": 1}, "ActionNode 'params'", id="params"
    ),
    pytest.param(CacheNode, {"policy": 1}, "CacheNode 'policy'", id="cache-policy"),
    pytest.param(
        SubscribeNode, {"policy": 1}, "SubscribeNode 'policy'", id="subscribe-policy"
    ),
]


class TestNodes:
    @pytest.mark.parametrize(("node", "expected"), REFERENCED_INPUTS)
    def test_referenced_inputs_collect_input_references(self, node, expected):
        assert Workflow(nodes=[node]).referenced_inputs == expected

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

    @pytest.mark.parametrize(("node", "kwargs", "match"), JSON_FIELD_REJECTIONS)
    def test_json_fields_name_themselves(self, node: Any, kwargs: Any, match: str):
        with pytest.raises(InvalidPipelineError, match=f"{match} must be a mapping"):
            node(id="a", name="n", **kwargs)


RESOURCE_FORMS = [
    pytest.param("db", {"db": "db"}, id="str"),
    pytest.param(["db", "cache"], {"db": "db", "cache": "cache"}, id="iterable"),
    pytest.param({"db": "primary_db"}, {"db": "primary_db"}, id="mapping"),
    pytest.param(None, {}, id="none"),
]
BINDING_REJECTIONS = [
    *(pytest.param(v, _UNBOUND_MSG, id=k) for k, v in _UNBOUND_BINDINGS.items()),
    pytest.param(5, "must be a str, mapping, or iterable", id="non-binding"),
]


class TestResourceBinding:
    @pytest.mark.parametrize(("resources", "expected"), RESOURCE_FORMS)
    def test_accepted_forms_normalize(self, resources: Any, expected: dict):
        assert (
            ModuleNode(id="a", name="hash", resources=resources).resources == expected
        )

    @pytest.mark.parametrize(("resources", "match"), BINDING_REJECTIONS)
    def test_invalid_bindings_are_rejected(self, resources: Any, match: str):
        with pytest.raises(InvalidPipelineError, match=f"node 'resources' {match}"):
            ModuleNode(id="a", name="hash", resources=resources)

    def test_an_alias_cannot_repeat(self):
        with pytest.raises(InvalidPipelineError, match="must not repeat an alias"):
            ModuleNode(id="a", name="hash", resources=["db", "db"])


_CALLABLE_NODE_ERRORS = [
    pytest.param({"resources": {"a-b": "db"}}, _INVALID, "identifiers", id="dashed"),
    pytest.param({"resources": "def"}, _INVALID, "identifiers", id="keyword"),
    pytest.param({"identity": "bogus"}, _INVALID, "'identity'", id="identity"),
    pytest.param({"fn": "len"}, TypeError, "callable", id="uncallable"),
    pytest.param({"kwargs": {"resources": 1}}, _INVALID, "reserved", id="resources-kw"),
    pytest.param({"kwargs": {"version": 1}}, _INVALID, "reserved", id="version-kw"),
    pytest.param({"kwargs": {"identity": 1}}, _INVALID, "reserved", id="identity-kw"),
    pytest.param(
        {"fn": lambda _, **kwargs: kwargs, "kwargs": {"_": 1}},
        _INVALID,
        "reserved",
        id="item-parameter-kw",
    ),
]


class TestCallableNode:
    def test_identity_accepts_a_bare_string(self):
        node = CallableNode(id="a", name="len", fn=len, identity="preserve")
        assert node.identity is IdentityMode.PRESERVE

    def test_fn_is_compared_by_identity(self):
        node = CallableNode(id="a", name="len", fn=len, kwargs={"n": [1]})
        assert node == CallableNode(id="a", name="len", fn=len, kwargs={"n": [1]})
        assert node != CallableNode(id="a", name="len", fn=lambda value: value)

    @pytest.mark.parametrize(("kwargs", "error", "match"), _CALLABLE_NODE_ERRORS)
    def test_construction_is_validated(self, kwargs: Any, error: Any, match: str):
        with pytest.raises(error, match=match):
            CallableNode(**{"id": "a", "name": "len", "fn": len, **kwargs})


class TestRequireRunnableOnly:
    def test_callable_nodes_pass(self):
        node = CallableNode(id="c", name="len", fn=len)
        flow = Workflow(nodes=[FETCH_NODE, node])
        assert flow.require_runnable_only("execution") is None

    def test_other_families_are_named_with_the_activity(self):
        write = WriteNode(id="w", name="write", backend="file", dest="out.csv")
        cache = CacheNode(id="c", name="cache")
        nodes = [FETCH_NODE, write, cache]
        flow = Workflow(nodes=nodes)

        with pytest.raises(InvalidPipelineError, match="cache, write node execution"):
            flow.require_runnable_only("execution")


VALID_GRAPHS = [
    pytest.param([FETCH_NODE], [], "a", (), id="single-node"),
    pytest.param(
        _MERGE_NODES,
        [
            StreamEdge(Endpoint("a", "out"), Endpoint("c", "in")),
            StreamEdge(Endpoint("b", "out"), Endpoint("c", "in:1")),
        ],
        "c",
        (),
        id="distinct-fan-in-ports",
    ),
    pytest.param(
        [FETCH_NODE, SubscribeNode(id="s", name="sub")],
        [PublishEdge(Endpoint("a", "out"), Endpoint("s", "in"))],
        "a",
        (),
        id="publish-to-subscribe",
    ),
    pytest.param([_HAS_DB], [], "a", ("prod",), id="declared-resource"),
]
INVALID_WORKFLOWS = [
    pytest.param(
        {"nodes": [FETCH_NODE], "outputs": {"default": _A_OUT}, "version": "1"},
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
    pytest.param({"nodes": [FETCH_NODE]}, "exposes no workflow output", id="no-output"),
    pytest.param(
        {"nodes": [_ASKS_Q], "outputs": {"default": _A_OUT}},
        r"unresolved input reference\(s\): \['q'\]",
        id="unresolved-input",
    ),
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
        [
            StreamEdge(_A_OUT, Endpoint("b", "in:1")),
            StreamEdge(_A_OUT, Endpoint("b", "in:01")),
        ],
        _B_OUT,
        r"multiple stream edges.*\('b', 'in:1'\)",
        id="in:1-and-in:01",
    ),
    pytest.param(
        [StreamEdge(_A_OUT, _B_IN), StreamEdge(_B_OUT, _A_IN)],
        _B_OUT,
        r"cycle.*\['a', 'b'\]",
        id="cycle",
    ),
    pytest.param([StreamEdge(_A_OUT, _A_IN)], _A_OUT, r"cycle.*'a'", id="self-loop"),
]


def _conf_pending(raises: type[BaseException]) -> pytest.MarkDecorator:
    return pytest.mark.xfail(strict=True, raises=raises, reason=_CONF_PENDING)


INVALID_CONFS = [
    pytest.param(
        "filter",
        {"rule": _UNKNOWN_KEY_RULE},
        "fieldd",
        id="unknown-key",
        marks=_conf_pending(pytest.fail.Exception),
    ),
    pytest.param(
        "sort",
        {"rule": 5},
        "rule",
        id="wrong-type",
        marks=_conf_pending(AttributeError),
    ),
    pytest.param(
        "simplemath",
        {"op": "nope", "other": {"value": 2}},
        "op",
        id="op",
        marks=_conf_pending(TypeError),
    ),
    pytest.param(
        "strconcat", {}, "part", id="missing-key", marks=_conf_pending(TypeError)
    ),
    pytest.param(
        "filter",
        {"rule": {"field": "x", "op": "after", "value": "foo"}},
        "value",
        id="unparseable-date",
        marks=_conf_pending(pytest.fail.Exception),
    ),
]


def _workflow(
    nodes, edges=(), outputs=None, input_schemas=None, resources=(), version="2"
) -> Workflow:
    return Workflow(
        nodes=nodes,
        edges=tuple(edges),
        outputs=outputs or {},
        input_schemas=input_schemas or {},
        resources=resources,
        version=version,
    )


class TestValidate:
    @pytest.mark.parametrize(("nodes", "edges", "output", "resources"), VALID_GRAPHS)
    def test_valid_graphs_pass(self, nodes, edges, output, resources):
        outputs = {"default": Endpoint(output, "out")}
        flow = _workflow(nodes, edges=edges, outputs=outputs, resources=resources)
        assert flow.validate() is None

    @pytest.mark.parametrize(("name", "conf", "match"), INVALID_CONFS)
    def test_invalid_conf_rejected_before_the_source_is_read(self, name, conf, match):
        seed = iter(_TITLE_ROWS)
        pipeline = seed | Pipeline.from_module(name, conf=conf)

        with pytest.raises(InvalidPipelineError, match=match):
            list(pipeline)

        assert list(seed) == _TITLE_ROWS

    def test_validate_runs_its_checks_once_per_workflow(self, monkeypatch):
        calls = []
        validate_input_schemas = Workflow.validate_input_schemas

        def counted(flow):
            calls.append(flow)
            validate_input_schemas(flow)

        monkeypatch.setattr(Workflow, "validate_input_schemas", counted)
        outputs = {"default": Endpoint("a", "out")}
        flow = _workflow(
            [FETCH_NODE], outputs=outputs, input_schemas={"q": {"type": "string"}}
        )
        flow.validate()
        flow.validate()

        assert flow.is_valid
        assert calls == [flow]

    def test_validate_raises_on_every_call_to_an_invalid_workflow(self):
        flow = _workflow([FETCH_NODE], input_schemas={"q": {"type": "strng"}})

        for _ in range(2):
            assert not flow.is_valid

            with pytest.raises(InvalidPipelineError, match="invalid schema"):
                flow.validate()

    @pytest.mark.parametrize(("kwargs", "match"), INVALID_WORKFLOWS)
    def test_invalid_workflow_rejected(self, kwargs, match):
        with pytest.raises(InvalidPipelineError, match=match):
            _workflow(**kwargs).validate()

    @pytest.mark.parametrize(("edge", "target"), EDGE_FAMILY_MISMATCHES)
    def test_edge_family_disagreeing_with_its_target_rejected(self, edge, target):
        flow = _workflow(
            [FETCH_NODE, target],
            edges=[edge(Endpoint("a", "out"), Endpoint("b", "in"))],
            outputs={"default": Endpoint("a", "out")},
        )
        with pytest.raises(InvalidPipelineError, match="edge family disagrees"):
            flow.validate()

    @pytest.mark.parametrize(("edges", "output", "match"), INVALID_EDGES)
    def test_invalid_edges_rejected(self, edges, output, match):
        flow = _workflow(
            [FETCH_NODE, SORT_NODE], edges=edges, outputs={"default": output}
        )
        with pytest.raises(InvalidPipelineError, match=match):
            flow.validate()


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

    def test_a_callable_node_has_no_document_form(self):
        with pytest.raises(InvalidPipelineError, match=CALLABLE_MATCH):
            compile_workflow(CALLABLE_FLOW, "pipe_len")

    @pytest.mark.xfail(
        strict=True,
        raises=AssertionError,
        reason=(
            "a public import path for generated workflow modules is not yet implemented"
        ),
    )
    def test_generated_source_imports_no_private_module(self):
        """A generated workflow module imports only supported riko paths."""
        flow = Pipeline.from_module("itembuilder").workflow
        assert "from riko.runtime._" not in compile_workflow(flow, "pipe_public")
