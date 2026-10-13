# vim: sw=4:ts=4:expandtab
"""Provides internal tests for definition construction, write targets, and sessions."""

from __future__ import annotations

import copy
import pickle  # noqa: S403
import typing
from collections import ChainMap
from copy import deepcopy
from dataclasses import dataclass, make_dataclass
from dataclasses import field as dataclass_field
from pickle import dumps, loads  # noqa: S403
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    NotRequired,
    Required,
    TypedDict,
    get_args,
)

import pytest
from attrs import fields_dict

from riko.bado import as_async
from riko.base.exceptions import (
    InvalidPipelineError,
    PipelineStateError,
    UnsupportedTargetError,
)
from riko.definitions._composition import PipelineDefinition
from riko.definitions._context import Context
from riko.definitions._nodes import (
    ActionNode,
    CacheNode,
    ModuleNode,
    ReadNode,
    StreamEdge,
    SubscribeNode,
    WriteNode,
)
from riko.definitions._normalize import _NODE_BUILDERS, _normalize_port
from riko.definitions._resource_definition import Resource, ReusableResource
from riko.definitions._targets import (
    FileTarget,
    build_write,
    normalize_target,
    resolve_format,
    validate_target_mode,
)
from riko.definitions._workflow import Workflow
from riko.definitions._write import (
    WriteCapabilities,
    WriteMode,
    WriteOperation,
    WriteResult,
)
from riko.execution._execution import SyncExecution
from riko.execution._prepared import ExecutionPlan, PreparedNode, ResolvedModule
from riko.execution._resource_view import ResourceView
from riko.modules.hash import pipe as hash_pipe
from riko.modules.tail import async_pipe as async_tail
from riko.modules.tail import pipe as tail
from riko.runtime import _write_session
from riko.runtime._target_registry import register_target, reset_target_registry
from riko.runtime._write_session import (
    _SessionState,
    _SyncFileWriteSession,
    async_file_write_session,
    awrite_through,
    file_write_session,
    write_through,
)
from riko.types._collections import (
    FrozenDict,
    field_names,
    normalize_strs,
    require_binding,
    require_finite,
    require_from_attrs,
    require_from_typed_dict,
    require_str,
    require_strlike,
    typed_dict_keys,
)
from riko.types._compiler import Embed, PipeModule
from riko.types._enums import Backends, Executor, Formats, resolve_enum
from riko.types._guards import require_mapping, require_sequence
from riko.types._resource import FactoryKind
from riko.types._workflow import Edge as EdgeBase
from riko.types._workflow import Endpoint, NodeFamily, RawEdge, RawEndpoint, RawNode
from tests import async_test, skipif_issync

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence

    from riko.types._io import PathLike
    from riko.types._scalars import BasicValue
    from riko.types._streams import Feed, Items

ITEMS = [{"x": 0}, {"x": 1}, {"x": 2}]

_OUT = {"default": Endpoint("a", "out")}


def untyped_inputs(**values: Any) -> dict[str, Any]:
    """Builds inputs whose nested values fall outside the declared scalar type."""
    return values


def gen_client(*_args: object, **_kwargs: object):
    yield object()


class _Client:
    closed = False

    def close(self) -> None:
        self.closed = True


def _never() -> bool:
    """Reports a graceful close rather than a termination."""
    return False


def _always() -> bool:
    """Reports a termination rather than a graceful close."""
    return True


def _sink(items: Items, dest: PathLike, mode: str = "replace", **kwargs) -> WriteResult:
    """Delivers the whole stream to *dest* and commits it, as a terminal write does."""
    with file_write_session(build_write(dest, mode, **kwargs)) as session:
        session.write(items)
        result = session.finalize()

    return result


async def _asink(
    items: Feed, dest: PathLike, mode: str = "replace", **kwargs
) -> WriteResult:
    """Delivers the whole stream to *dest* and commits it, as a terminal write does."""
    async with async_file_write_session(build_write(dest, mode, **kwargs)) as session:
        await session.awrite(items)
        result = await session.afinalize()

    return result


@dataclass(frozen=True)
class _RecordStore:
    """A native keyed target exercising the match-keyed/idempotent branches."""

    backend: ClassVar[Backends] = Backends.AIRTABLE

    def capabilities(self, fmt=None) -> WriteCapabilities:
        return WriteCapabilities(
            modes=frozenset(WriteMode),
            match_keyed_modes=frozenset({WriteMode.MERGE, WriteMode.DELETE}),
            idempotent_modes=frozenset({WriteMode.APPEND}),
        )


class TestFrozenDict:
    @pytest.mark.parametrize(
        "source", [[("ids", [1])], ChainMap({"ids": [1]})], ids=["pairs", "chain-map"]
    )
    def test_values_are_frozen_from_any_source(self, source: Any):
        assert FrozenDict(source)["ids"] == (1,)


class TestContext:
    def test_nested_inputs_are_read_only(self):
        context = Context(inputs=untyped_inputs(tags=["a"], meta={"ids": [1]}))
        assert context.inputs is not None
        assert context.inputs["tags"] == ("a",)
        meta = context.inputs["meta"]
        assert isinstance(meta, FrozenDict)
        assert meta["ids"] == (1,)

    @pytest.mark.parametrize("inputs", ["abc", [("a", 1)]])
    def test_non_mapping_inputs_are_rejected(self, inputs: Any):
        with pytest.raises(TypeError, match="Context 'inputs' must be a mapping"):
            Context(inputs=inputs)

    def test_resources_must_be_reusable(self):
        with pytest.raises(
            TypeError, match="Context resource 'r' must be of type ReusableResource"
        ):
            Context(_resources={"r": _Client()})  # pyright: ignore[reportArgumentType]

    @pytest.mark.parametrize("resources", ["abc", None])
    def test_non_mapping_resources_are_rejected(self, resources: Any):
        with pytest.raises(TypeError, match="Context 'resources' must be a mapping"):
            Context(_resources=resources)

    @pytest.mark.parametrize(
        ("mode", "match"),
        [
            pytest.param(5, "Invalid ExecutionMode: 5", id="non-string"),
            pytest.param("bogus", "Invalid ExecutionMode: 'bogus'", id="unknown"),
        ],
    )
    def test_invalid_mode_is_rejected(self, mode: Any, match: str):
        with pytest.raises(ValueError, match=match):
            Context(mode=mode)

    def test_derived_inputs_are_read_only(self):
        derived = Context().replace(inputs=untyped_inputs(tags=["a"]))
        assert derived.inputs is not None
        assert derived.inputs["tags"] == ("a",)

    def test_nested_source_mutation_does_not_leak(self):
        tags = ["a"]
        context = Context(inputs=untyped_inputs(tags=tags))
        tags.append("b")
        assert context.inputs is not None
        assert context.inputs["tags"] == ("a",)

    @pytest.mark.parametrize("name", ["_mode", "_inputs", "_resources", "extra"])
    def test_private_fields_cannot_be_set(self, name: str):
        context = Context()

        with pytest.raises(AttributeError):
            setattr(context, name, None)

        with pytest.raises(AttributeError):
            delattr(context, name)

    def test_pickle_round_trip_keeps_frozen_inputs(self):
        resource = Resource.from_external(_Client())
        inputs = untyped_inputs(tags=["a"])
        context = Context(inputs=inputs).with_resource("client", resource)
        restored = loads(dumps(context))  # noqa: S301

        assert restored.inputs == context.inputs
        assert list(restored.resources) == ["client"]
        assert restored.inputs is not None
        assert restored.inputs["tags"] == ("a",)


_SYNC_FACTORY = FactoryKind.SYNC_CALLABLE_FACTORY


class TestResourceFreezing:
    def test_factory_arguments_are_read_only(self):
        resource = Resource.from_factory(
            gen_client, ["arg"], headers={"accept": ["json"]}
        )
        headers = resource.kwargs["headers"]

        assert resource.args == (("arg",),)
        assert isinstance(headers, FrozenDict)
        assert headers["accept"] == ("json",)

    def test_factory_receives_mutable_arguments(self):
        received: dict[str, Any] = {}
        client = _Client()

        def factory(*args: object, **kwargs: object):
            received.update(args=args, kwargs=kwargs)
            yield object()

        resource = Resource.from_factory(
            factory, ["arg"], client, headers={"accept": ["json"]}
        )

        with SyncExecution() as execution:
            execution.acquire(resource)

        tags, passed_client = received["args"]
        headers = received["kwargs"]["headers"]
        assert tags == ["arg"]
        assert passed_client is client
        assert isinstance(headers, dict)
        assert headers["accept"] == ["json"]

    @pytest.mark.parametrize(
        ("fields", "match"),
        [
            pytest.param(
                {"_external": True}, "must be reusable", id="external-one-shot"
            ),
            pytest.param({"_factory": len}, "factory and its kind", id="factory-only"),
            pytest.param(
                {"_kind": _SYNC_FACTORY}, "factory and its kind", id="kind-only"
            ),
            pytest.param(
                {"_external": True, "_factory": len, "_kind": _SYNC_FACTORY},
                "cannot carry a factory",
                id="external-factory",
            ),
        ],
    )
    def test_inconsistent_private_fields_are_rejected(
        self, fields: dict[str, Any], match: str
    ):
        with pytest.raises(TypeError, match=match):
            Resource(_Client(), cleanup=False, **fields)

    def test_opaque_argument_values_are_untouched(self):
        client = _Client()
        resource = Resource.from_factory(gen_client, client, session=client)

        assert resource.args[0] is client
        assert resource.kwargs["session"] is client

    @pytest.mark.parametrize("name", ["_value", "_kwargs", "_lazy", "extra"])
    def test_private_fields_cannot_be_set(self, name: str):
        resource = Resource.from_factory(gen_client)

        with pytest.raises(AttributeError):
            setattr(resource, name, None)

        with pytest.raises(AttributeError):
            delattr(resource, name)

    def test_pickle_and_copy_round_trip(self):
        resource = Resource.from_factory(gen_client, retries=[1, 2], lazy=True)

        pickled = loads(dumps(resource))  # noqa: S301

        for restored in (pickled, deepcopy(resource)):
            assert isinstance(restored, ReusableResource)
            assert restored.factory is gen_client
            assert restored.kind is resource.kind
            assert restored.lazy
            assert restored.kwargs["retries"] == (1, 2)


class TestResourceView:
    @pytest.mark.parametrize(
        "duplicate",
        [
            pytest.param(copy.copy, id="copy"),
            pytest.param(copy.deepcopy, id="deepcopy"),
            pytest.param(lambda view: pickle.loads(pickle.dumps(view)), id="pickle"),  # noqa: S301
        ],
    )
    def test_resource_view_can_be_copied(self, duplicate):
        assert dict(duplicate(ResourceView({"db": 1}))) == {"db": 1}


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


@dataclass
class _Rule:
    field: str


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


class TestWorkflowFields:
    def test_nodes_must_be_an_iterable_of_nodes(self):
        nodes: Any = {"a": ModuleNode(id="a", name="hash")}

        with pytest.raises(InvalidPipelineError, match="'nodes' must be a list"):
            Workflow(nodes=nodes, outputs=_OUT)

    def test_a_node_id_cannot_repeat(self):
        nodes = [ModuleNode(id="a", name="hash"), ModuleNode(id="a", name="count")]

        with pytest.raises(InvalidPipelineError, match="must not repeat a node id"):
            Workflow(nodes=nodes, outputs=_OUT)

    @pytest.mark.parametrize("field", ["nodes", "edges"])
    @pytest.mark.parametrize("value", ["ab", b"ab", {"a": 1}, 3])
    def test_node_and_edge_containers_must_be_lists(self, field: str, value: Any):
        kwargs = {"nodes": [ModuleNode(id="a", name="hash")], field: value}

        with pytest.raises(InvalidPipelineError, match=f"'{field}' must be a list"):
            Workflow(outputs=_OUT, **kwargs)

    def test_edges_must_be_edges(self):
        nodes = [ModuleNode(id="a", name="hash")]
        edges: Any = [("a", "b")]

        with pytest.raises(InvalidPipelineError, match="Workflow edge"):
            Workflow(nodes=nodes, outputs=_OUT, edges=edges)

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
        workflow = Workflow()
        mappings = (workflow.nodes, workflow.outputs, workflow.inputs)
        assert mappings == ({}, {}, {})
        assert (workflow.edges, workflow.resources) == ((), ())

    def test_pickle_and_copy_round_trip(self):
        node = ModuleNode(
            id="a",
            name="loop",
            conf=untyped_inputs(rules=[{"field": "x", "nested": {"ids": [1, 2]}}]),
            embed={"name": "tokenizer", "conf": {"delimiter": " "}},
            resources={"db": "primary_db"},
        )
        workflow = Workflow(nodes=[node], outputs={}, inputs={"q": {"type": "string"}})

        pickled = loads(dumps(workflow))  # noqa: S301

        for restored in (pickled, deepcopy(workflow)):
            assert restored == workflow
            restored_node = restored.nodes["a"]
            assert isinstance(restored_node, ModuleNode)
            rules = restored_node.conf["rules"]
            assert isinstance(rules, tuple)
            assert isinstance(rules[0], FrozenDict)
            assert rules == ({"field": "x", "nested": {"ids": (1, 2)}},)
            assert restored_node.resources == {"db": "primary_db"}
            assert isinstance(restored.inputs["q"], FrozenDict)

    @pytest.mark.xfail(
        strict=True,
        reason="owned by the pending workflow input declarations work: a strict "
        "Workflow accepts an input declaration that is not a JSON Schema mapping",
    )
    @pytest.mark.parametrize("declaration", [5, "string"])
    def test_non_schema_inputs_are_rejected(self, declaration: object):
        with pytest.raises(InvalidPipelineError, match="Workflow 'inputs'"):
            Workflow(nodes=[], outputs={}, inputs={"q": declaration})


class TestNormalizeInternals:
    @pytest.mark.parametrize(
        ("legacy", "direction", "canonical"),
        [
            ("_INPUT", "in", "in"),
            ("_OTHER", "in", "in:1"),
            ("_OTHER2", "in", "in:2"),
            ("_OTHER5", "in", "in:5"),
            ("_OUTPUT", "out", "out"),
            ("_OUTPUT1", "out", "out"),
            ("_OUTPUT2", "out", "out:1"),
            ("_OUTPUT4", "out", "out:3"),
            ("out:matched", "out", "out:matched"),
            ("in", "in", "in"),
            ("count", "in", "in:count"),
            ("matched", "out", "out:matched"),
        ],
    )
    def test_normalize_port_maps_open_ended_legacy_series(
        self, legacy, direction, canonical
    ):
        assert _normalize_port(legacy, direction) == canonical

    def test_every_node_family_has_a_builder(self):
        families = set(get_args(NodeFamily.__value__))
        assert set(_NODE_BUILDERS) == families
        assert {builder.family for builder in _NODE_BUILDERS.values()} == families


_NODES = (ModuleNode, ReadNode, WriteNode, ActionNode, CacheNode, SubscribeNode)
_NODE_ALIASES = frozenset({"family", "format"})
_EDGE_ALIASES = frozenset({"family"})


def _attrs_fields(*classes) -> set[str]:
    return {name for cls in classes for name in fields_dict(cls)}


def _required_keys(raw) -> set[str]:
    items = raw.__annotations__.items()
    return {key for key, hint in items if "Required[" in str(hint)}


class TestRawWorkflowFields:
    def test_raw_node_covers_every_node_field(self):
        attrs_keys = _attrs_fields(*_NODES)
        raw_keys = set(RawNode.__annotations__)
        assert not (attrs_keys - raw_keys), f"missing: {sorted(attrs_keys - raw_keys)}"
        assert not (raw_keys - attrs_keys - _NODE_ALIASES), (
            f"unknown: {sorted(raw_keys - attrs_keys - _NODE_ALIASES)}"
        )

    def test_raw_edge_covers_every_edge_field(self):
        attrs_keys = _attrs_fields(EdgeBase)
        raw_keys = set(RawEdge.__annotations__)
        assert not (attrs_keys - raw_keys), f"missing: {sorted(attrs_keys - raw_keys)}"
        assert not (raw_keys - attrs_keys - _EDGE_ALIASES), (
            f"unknown: {sorted(raw_keys - attrs_keys - _EDGE_ALIASES)}"
        )

    def test_raw_endpoint_covers_every_endpoint_field(self):
        attrs_keys = _attrs_fields(Endpoint)
        raw_keys = set(RawEndpoint.__annotations__)
        assert attrs_keys == raw_keys

    def test_raw_requiredness_matches_contract(self):
        assert _required_keys(RawNode) == {"name"}
        assert "id" in RawNode.__annotations__
        assert "id" not in _required_keys(RawNode)
        assert _required_keys(RawEndpoint) == {"node"}
        assert _required_keys(RawEdge) == {"source", "target"}


_HASH = ResolvedModule("hash", sync_pipe=hash_pipe)


class TestExecutionPlanFields:
    def test_workflow_must_be_a_workflow(self):
        with pytest.raises(InvalidPipelineError, match="ExecutionPlan 'workflow'"):
            ExecutionPlan(workflow={"nodes": []}, modules={})  # pyright: ignore[reportArgumentType]

    def test_execution_plan_modules_must_be_resolved_modules(self):
        workflow = Workflow(nodes=[], outputs={})

        with pytest.raises(InvalidPipelineError, match="ExecutionPlan module 'n'"):
            ExecutionPlan(workflow=workflow, modules={"n": 1})  # pyright: ignore[reportArgumentType]

    @pytest.mark.parametrize("modules", ["abc", None])
    def test_execution_plan_modules_must_be_a_mapping(self, modules: Any):
        workflow = Workflow(nodes=[], outputs={})

        with pytest.raises(InvalidPipelineError, match="ExecutionPlan 'modules'"):
            ExecutionPlan(workflow=workflow, modules=modules)

    @pytest.mark.parametrize(
        "modules", [{}, {"a": _HASH, "b": _HASH}], ids=["missing", "extra"]
    )
    def test_modules_must_match_the_workflow(self, modules: dict[str, ResolvedModule]):
        workflow = Workflow(nodes=[ModuleNode(id="a", name="hash")], outputs=_OUT)

        with pytest.raises(InvalidPipelineError, match="modules must match"):
            ExecutionPlan(workflow=workflow, modules=modules)

    @pytest.mark.parametrize(
        ("embed", "embeds"),
        [
            pytest.param({"name": "hash", "conf": {}}, {}, id="missing"),
            pytest.param(None, {"a": _HASH}, id="extra"),
        ],
    )
    def test_embeds_must_match_the_loop_embeds(
        self, embed: Any, embeds: dict[str, ResolvedModule]
    ):
        node = ModuleNode(id="a", name="loop", embed=embed)
        workflow = Workflow(nodes=[node], outputs=_OUT)

        with pytest.raises(InvalidPipelineError, match="embeds must match"):
            ExecutionPlan(workflow=workflow, modules={"a": _HASH}, embeds=embeds)

    def test_a_non_module_node_is_refused_when_built(self):
        node = WriteNode(id="a", name="write", backend="file", dest="out.csv")
        workflow = Workflow(nodes=[node], outputs=_OUT)

        with pytest.raises(InvalidPipelineError, match="not yet supported"):
            ExecutionPlan(workflow=workflow, modules={"a": _HASH})

    def test_nodes_pair_workflow_nodes_with_their_modules(self):
        node = ModuleNode(id="a", name="loop", embed={"name": "hash", "conf": {}})
        workflow = Workflow(nodes=[node], outputs=_OUT)
        plan = ExecutionPlan(
            workflow=workflow, modules={"a": _HASH}, embeds={"a": _HASH}
        )
        prepared = plan.nodes["a"]
        assert (prepared.node, prepared.module, prepared.embed) == (node, _HASH, _HASH)

    def test_prepared_module_must_be_resolved(self):
        with pytest.raises(InvalidPipelineError, match="PreparedNode 'module'"):
            PreparedNode(ModuleNode(id="a", name="hash"), "hash")  # pyright: ignore[reportArgumentType]


class TestPipelineDefinitionFields:
    @pytest.mark.parametrize(
        ("kwargs", "match"),
        [
            ({"context": "x"}, "'context' must be of type Context"),
            ({"settings": {}}, "'settings' must be of type ExecutionSettings"),
        ],
    )
    def test_run_settings_are_checked_when_built(self, kwargs: Any, match: str):
        with pytest.raises(TypeError, match=match):
            PipelineDefinition(**kwargs)

    def test_a_context_is_accepted(self):
        context = Context()
        assert PipelineDefinition(context=context).context is context


_INVALID: list[tuple[Callable[..., object], object]] = [
    (require_str, 1),
    (require_strlike, 1),
    (require_finite, float("nan")),
    (require_mapping, "abc"),
    (require_sequence, "abc"),
]


class TestRequireHelpers:
    @pytest.mark.parametrize(("require", "value"), _INVALID)
    def test_document_error_is_the_default(self, require, value):
        with pytest.raises(InvalidPipelineError, match="field"):
            require(value, "field")

    @pytest.mark.parametrize(("require", "value"), [*_INVALID, (require_binding, 1)])
    def test_caller_can_pick_the_error(self, require, value):
        with pytest.raises(ValueError, match="field"):
            require(value, "field", error=ValueError)

    def test_required_attrs_keys_respect_exclude(self):
        require = require_from_attrs(Endpoint, exclude={"port"})
        assert require({"node": "a"}) == {"node": "a"}

        with pytest.raises(
            InvalidPipelineError, match=r"missing Endpoint key\(s\): \['node'\]"
        ):
            require({"port": "out"})


class TestResolveEnum:
    @pytest.mark.parametrize("value", [None, "bogus"])
    def test_resolve_enum_defaults_to_the_document_error(self, value):
        with pytest.raises(InvalidPipelineError, match="WriteMode"):
            resolve_enum(WriteMode, value)

    def test_resolve_enum_lists_the_accepted_values(self):
        with pytest.raises(ValueError, match="'bogus'") as excinfo:
            resolve_enum(Executor, "bogus", error=ValueError)

        assert all(name in str(excinfo.value) for name in Executor)


class TestNormalizeStrs:
    def test_empty_key_rejected(self):
        with pytest.raises(InvalidPipelineError, match="non-empty"):
            normalize_strs(["id", ""])

    def test_duplicate_keys_rejected(self):
        with pytest.raises(InvalidPipelineError, match="duplicate"):
            normalize_strs(["id", "id"])

    @pytest.mark.parametrize("value", [[1, 2], ["a", 1], [None]])
    def test_non_string_keys_rejected(self, value):
        with pytest.raises(InvalidPipelineError, match="non-empty strings"):
            normalize_strs(value)

    def test_non_iterable_rejected(self):
        with pytest.raises(InvalidPipelineError, match="string or iterable"):
            normalize_strs(42)  # pyright: ignore[reportArgumentType]


def _runtime_record() -> type:
    # This module postpones annotations, so build a record whose ClassVar is an
    # evaluated annotation rather than a string.
    tag = ("tag", ClassVar[str], dataclass_field(default="point"))
    return make_dataclass(
        "_RuntimeRecord", [tag, ("x", int, dataclass_field(default=0))]
    )


class TestFieldNames:
    def test_field_names_includes_classvar_for_attrs_and_dataclass(self):
        assert "family" in field_names(EdgeBase)
        assert "family" in field_names(WriteNode)
        assert field_names(_runtime_record()) == frozenset({"tag", "x"})
        assert "family" not in field_names(Endpoint)


class Partial(TypedDict, total=False):
    kept: Required[BasicValue]
    loose: Sequence[BasicValue]


class Whole(TypedDict):
    plain: BasicValue
    dropped: NotRequired[BasicValue]
    qualified: typing.NotRequired[Sequence[BasicValue]]


class Inherited(Partial):
    added: BasicValue


class TestTypedDictKeys:
    def test_qualifiers_found_without_resolving_annotations(self):
        assert typed_dict_keys(Partial) == (frozenset({"kept"}), frozenset({"loose"}))
        assert typed_dict_keys(Whole) == (
            frozenset({"plain"}),
            frozenset({"dropped", "qualified"}),
        )

    def test_inherited_keys_keep_each_class_totality(self):
        assert typed_dict_keys(Inherited) == (
            frozenset({"kept", "added"}),
            frozenset({"loose"}),
        )

    def test_shipped_typed_dict_qualifiers_are_honored(self):
        assert typed_dict_keys(PipeModule)[0] == {"id", "type", "conf"}
        assert typed_dict_keys(Embed) == (
            frozenset({"conf", "name"}),
            frozenset({"id"}),
        )

    def test_required_qualifier_is_enforced(self):
        require = require_from_typed_dict(PipeModule)

        with pytest.raises(
            InvalidPipelineError, match=r"missing PipeModule key\(s\): \['conf'\]"
        ):
            require({"id": "a", "type": "fetch"})


class TestWriteMode:
    def test_mode_values(self):
        assert [m.value for m in WriteMode] == ["append", "merge", "replace", "delete"]


class TestFormats:
    def test_format_values(self):
        assert [f.value for f in Formats] == [
            "csv",
            "geojson",
            "json",
            "jsonl",
            "ofx",
            "qif",
        ]


class TestWriteOperation:
    @pytest.mark.parametrize(
        ("kwargs", "expected"),
        [
            pytest.param({}, (), id="omitted"),
            pytest.param({"keys": ("endpoint_id",)}, ("endpoint_id",), id="tuple"),
            pytest.param({"keys": ["id"]}, ("id",), id="list"),
            pytest.param({"keys": "id"}, ("id",), id="bare-key-not-split"),
        ],
    )
    def test_keys_normalize_to_a_tuple(self, kwargs: dict[str, Any], expected):
        assert WriteOperation(WriteMode.MERGE, **kwargs).keys == expected

    @pytest.mark.parametrize(
        "mode", [WriteMode.MERGE, "merge"], ids=["member", "string"]
    )
    def test_mode_normalizes_to_a_member(self, mode: WriteMode | str):
        assert WriteOperation(mode).mode is WriteMode.MERGE

    def test_equal_intents_hash_alike(self):
        listed = WriteOperation(WriteMode.MERGE, keys=["id"])
        bare = WriteOperation(WriteMode.MERGE, keys=("id",))

        assert listed == bare
        assert hash(listed) == hash(bare)

    def test_is_frozen(self):
        op = WriteOperation(WriteMode.REPLACE)

        with pytest.raises(AttributeError):
            op.mode = WriteMode.APPEND  # pyright: ignore[reportAttributeAccessIssue]


class TestWriteCapabilities:
    def test_appendable_derived_from_modes(self):
        appendable = WriteCapabilities(modes=frozenset({WriteMode.APPEND}))
        unappendable = WriteCapabilities(modes=frozenset({WriteMode.REPLACE}))

        assert appendable.appendable is True
        assert unappendable.appendable is False

    def test_serializes_derived_from_format(self):
        serializing = WriteCapabilities(modes=frozenset(), fmt=Formats.CSV)
        native = WriteCapabilities(modes=frozenset())

        assert serializing.serializes is True
        assert native.serializes is False

    def test_keyed_modes_is_union(self):
        caps = WriteCapabilities(
            modes=frozenset(WriteMode),
            match_keyed_modes=frozenset({WriteMode.MERGE}),
            idempotent_modes=frozenset({WriteMode.APPEND}),
        )

        assert caps.keyed_modes == frozenset({WriteMode.MERGE, WriteMode.APPEND})

    def test_keyed_modes_must_be_subset_of_modes(self):
        with pytest.raises(ValueError, match="not present in modes"):
            WriteCapabilities(
                modes=frozenset({WriteMode.REPLACE}),
                match_keyed_modes=frozenset({WriteMode.MERGE}),
            )

    def test_match_and_idempotent_must_not_overlap(self):
        with pytest.raises(ValueError, match="must not overlap"):
            WriteCapabilities(
                modes=frozenset({WriteMode.MERGE}),
                match_keyed_modes=frozenset({WriteMode.MERGE}),
                idempotent_modes=frozenset({WriteMode.MERGE}),
            )


class TestNormalizeTarget:
    def test_write_target_passes_through(self):
        target = FileTarget("out.json")
        assert normalize_target(target) is target

    def test_non_target_raises(self):
        with pytest.raises(TypeError, match="cannot resolve"):
            normalize_target(42)  # pyright: ignore[reportArgumentType]


class TestRegisterTarget:
    @pytest.mark.xfail(
        strict=True,
        reason="owned by the pending riko.ext extension-point layout work: "
        "register_target returns None, so using it as a class decorator binds the "
        "target's name to None instead of the registered class",
    )
    def test_register_target_returns_the_class_for_decorator_use(self) -> None:
        try:
            assert register_target(_RecordStore) is _RecordStore
        finally:
            reset_target_registry()


class TestResolveFormat:
    def test_explicit_format_wins(self):
        assert resolve_format("out.csv", "json") == "json"

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError, match="Invalid Formats"):
            resolve_format("out.txt", None)


class TestFileCapabilities:
    @pytest.mark.parametrize(
        ("dest", "appendable", "incremental"),
        [
            ("out.csv", True, True),
            ("out.jsonl", True, True),
            ("out.json", False, False),
            ("out.geojson", False, False),
        ],
    )
    def test_target_owns_format_behavior(self, dest, appendable, incremental):
        capabilities = FileTarget(dest).capabilities()

        assert capabilities.serializes is True
        assert capabilities.appendable is appendable
        assert (WriteMode.APPEND in capabilities.modes) is appendable
        assert capabilities.incremental is incremental
        assert WriteMode.REPLACE in capabilities.modes


class TestValidateTargetMode:
    def test_match_keyed_without_keys_rejected(self):
        capabilities = _RecordStore().capabilities()
        with pytest.raises(ValueError, match="requires 'keys'"):
            validate_target_mode(_RecordStore(), WriteMode.MERGE, capabilities)

    @pytest.mark.parametrize(
        ("mode", "keys"),
        [
            pytest.param(WriteMode.MERGE, ("id",), id="match-keyed"),
            pytest.param(WriteMode.APPEND, (), id="idempotent-unkeyed"),
            pytest.param(WriteMode.APPEND, ("id",), id="idempotent-keyed"),
        ],
    )
    def test_supported_key_combinations(self, mode, keys):
        capabilities = _RecordStore().capabilities()
        validate_target_mode(_RecordStore(), mode, capabilities, keys=keys)

    def test_unkeyed_mode_with_keys_rejected(self):
        capabilities = FileTarget("out.csv").capabilities()
        target = FileTarget("out.csv")

        with pytest.raises(ValueError, match="forbids 'keys'"):
            validate_target_mode(target, WriteMode.APPEND, capabilities, keys=("x",))


class TestBuildWrite:
    def test_path_defaults_to_extension_format_and_replace(self):
        prepared = build_write("out.csv")
        assert prepared.fmt is Formats.CSV
        assert prepared.operation.mode is WriteMode.REPLACE

    def test_record_store_binds_match_keys(self):
        prepared = build_write(_RecordStore(), "merge", keys="endpoint_id")

        assert prepared.operation.mode is WriteMode.MERGE
        assert prepared.operation.keys == ("endpoint_id",)

    def test_file_unsupported_mode(self):
        with pytest.raises(ValueError, match="does not support the 'merge'"):
            build_write(FileTarget("out.csv"), "merge")

    @pytest.mark.parametrize("dest", ["out.json", "out.geojson"])
    def test_file_append_rejected_for_framed_format(self, dest):
        with pytest.raises(ValueError, match="does not support the 'append'"):
            build_write(FileTarget(dest), "append")

    @pytest.mark.parametrize(
        ("kwargs", "error", "match"),
        [
            ({"mode": "bogus"}, ValueError, "Invalid WriteMode: 'bogus'"),
            ({"mode": "merge", "keys": 5}, TypeError, "keys must be a string"),
            ({"mode": "merge", "keys": ["a", "a"]}, ValueError, "duplicate keys"),
        ],
    )
    def test_build_write_raises_call_site_errors(self, kwargs, error, match):
        with pytest.raises(error, match=match):
            build_write("out.csv", **kwargs)


class TestConverterPath:
    """The native whole-stream path and the temporary singleton path."""

    def _spy(self, monkeypatch):
        calls = []
        original = _write_session.serialize_items

        def spy(items, fmt, **kwargs):
            materialized = list(items)
            calls.append(materialized)
            return original(materialized, fmt, **kwargs)

        monkeypatch.setattr(_write_session, "serialize_items", spy)
        return calls

    def test_sink_converts_whole_stream_once(self, monkeypatch, tmp_path):
        calls = self._spy(monkeypatch)
        _sink(ITEMS, tmp_path / "out.jsonl")

        assert len(calls) == 1
        assert calls[0] == ITEMS

    def test_passthrough_converts_per_item(self, monkeypatch, tmp_path):
        calls = self._spy(monkeypatch)
        prepared = build_write(tmp_path / "out.jsonl")
        yielded = list(write_through(ITEMS, prepared, terminating=_never))

        assert yielded == ITEMS
        assert len(calls) == len(ITEMS)


class TestCsv:
    def test_replace_writes_header_once(self, tmp_path):
        path = tmp_path / "out.csv"
        _sink(ITEMS, path)
        assert path.read_bytes() == b"x\r\n0\r\n1\r\n2\r\n"

    def test_append_existing_skips_header(self, tmp_path):
        path = tmp_path / "out.csv"
        _sink([{"x": 0}], path)
        _sink([{"x": 1}], path, "append")
        assert path.read_bytes() == b"x\r\n0\r\n1\r\n"

    def test_append_empty_emits_header(self, tmp_path):
        path = tmp_path / "out.csv"
        _sink([{"x": 0}], path, "append")
        assert path.read_bytes() == b"x\r\n0\r\n"

    def test_append_existing_without_newline_inserts_boundary(self, tmp_path):
        path = tmp_path / "out.csv"
        path.write_bytes(b"x\r\n0")
        _sink([{"x": 1}], path, "append")
        assert path.read_bytes() == b"x\r\n0\n1\r\n"

    def test_empty_append_does_not_mutate(self, tmp_path):
        path = tmp_path / "out.csv"
        path.write_bytes(b"x\r\n0\r\n")
        _sink([], path, "append")
        assert path.read_bytes() == b"x\r\n0\r\n"

    def test_passthrough_singleton_preserves_schema(self, tmp_path):
        path = tmp_path / "out.csv"
        rows = [{"a": 1, "b": 2}, {"b": 4, "a": 3}]
        list(write_through(rows, build_write(path), terminating=_never))
        assert path.read_bytes() == b"a,b\r\n1,2\r\n3,4\r\n"

    def test_passthrough_unexpected_field_raises(self, tmp_path):
        path = tmp_path / "out.csv"
        rows = [{"a": 1}, {"a": 2, "b": 3}]

        with pytest.raises(ValueError, match="not in the CSV header"):
            list(write_through(rows, build_write(path), terminating=_never))


class TestJsonl:
    def test_singleton_has_no_array(self, tmp_path):
        path = tmp_path / "out.jsonl"
        list(write_through(ITEMS, build_write(path), terminating=_never))
        assert path.read_bytes() == b'{"x": 0}\n{"x": 1}\n{"x": 2}\n'

    def test_append_newline_terminated_concatenates(self, tmp_path):
        path = tmp_path / "out.jsonl"
        path.write_bytes(b'{"x": 0}\n')
        _sink([{"x": 1}], path, "append")
        assert path.read_bytes() == b'{"x": 0}\n{"x": 1}\n'

    def test_append_unterminated_inserts_one_boundary(self, tmp_path):
        path = tmp_path / "out.jsonl"
        path.write_bytes(b'{"x": 0}')
        _sink([{"x": 1}], path, "append")
        assert path.read_bytes() == b'{"x": 0}\n{"x": 1}\n'

    def test_empty_append_does_not_mutate(self, tmp_path):
        path = tmp_path / "out.jsonl"
        path.write_bytes(b'{"x": 0}\n')
        _sink([], path, "append")
        assert path.read_bytes() == b'{"x": 0}\n'


class TestFramed:
    def test_passthrough_buffers_until_finalize(self, tmp_path):
        path = tmp_path / "out.json"
        stream = write_through(ITEMS, build_write(path), terminating=_never)
        first = next(stream)
        assert not path.exists()
        assert [first, *stream] == ITEMS
        assert path.read_bytes() == b'[{"x": 0}, {"x": 1}, {"x": 2}]'

    def test_sink_writes_one_document(self, tmp_path):
        path = tmp_path / "out.json"
        result = _sink(ITEMS, path)
        assert isinstance(result, WriteResult)
        assert result.written > 0
        assert path.read_bytes() == b'[{"x": 0}, {"x": 1}, {"x": 2}]'

    def test_abort_discards_staged_document(self, tmp_path):
        path = tmp_path / "out.json"
        prepared = build_write(path)

        with file_write_session(prepared) as session:
            session.write(ITEMS)
            session.abort()

        assert not path.exists()


class TestSessionLifecycle:
    def _session(self, tmp_path, name="out.json"):
        session = _SyncFileWriteSession(build_write(tmp_path / name))
        session.acquire()
        return session

    def test_open_to_finalized(self, tmp_path):
        session = self._session(tmp_path)
        session.write(ITEMS)
        session.finalize()
        assert session._state is _SessionState.FINALIZED
        session.teardown()

    def test_open_to_aborted(self, tmp_path):
        session = self._session(tmp_path)
        session.abort()
        assert session._state is _SessionState.ABORTED
        session.teardown()

    def test_write_after_finalize_rejected(self, tmp_path):
        session = self._session(tmp_path)
        session.write(ITEMS)
        session.finalize()

        with pytest.raises(
            PipelineStateError, match="the write session in state 'finalized'"
        ):
            session.write(ITEMS)

        session.teardown()

    def test_write_after_abort_rejected(self, tmp_path):
        session = self._session(tmp_path)
        session.abort()

        with pytest.raises(PipelineStateError, match="aborted"):
            session.write(ITEMS)

        session.teardown()

    def test_teardown_twice_is_safe(self, tmp_path):
        session = self._session(tmp_path)
        session.teardown()
        session.teardown()

    def test_teardown_never_commits(self, tmp_path):
        path = tmp_path / "out.json"
        session = _SyncFileWriteSession(build_write(path))
        session.acquire()
        session.write(ITEMS)
        session.teardown()
        assert not path.exists()

    def test_incremental_abort_keeps_written_bytes(self, tmp_path):
        path = tmp_path / "out.jsonl"
        session = _SyncFileWriteSession(build_write(path))
        session.acquire()
        session.write({"x": 1})
        session.abort()
        session.teardown()
        assert path.read_bytes() == b'{"x": 1}\n'

    def test_stream_then_item_rejected(self, tmp_path):
        session = self._session(tmp_path)
        session.write(ITEMS)

        with pytest.raises(PipelineStateError, match="cannot mix item and stream"):
            session.write({"x": 0})

        session.teardown()

    def test_item_then_stream_rejected(self, tmp_path):
        session = self._session(tmp_path)
        session.write({"x": 0})

        with pytest.raises(PipelineStateError, match="cannot mix item and stream"):
            session.write(ITEMS)

        session.teardown()

    def test_two_whole_streams_rejected(self, tmp_path):
        session = self._session(tmp_path)
        session.write(ITEMS)

        with pytest.raises(PipelineStateError, match="cannot attempt multiple stream"):
            session.write(ITEMS)

        session.teardown()


class TestWriteExecution:
    def test_writes_mid_chain(self, tmp_path):
        path = tmp_path / "out.json"
        stream = write_through(ITEMS, build_write(path), terminating=_never)
        assert list(tail(stream, conf={"count": 1})) == [{"x": 2}]
        assert path.read_bytes() == b'[{"x": 0}, {"x": 1}, {"x": 2}]'

    def test_replace_defers_truncation_until_consumed(self, tmp_path):
        path = tmp_path / "out.jsonl"
        path.write_bytes(b'{"old": 1}\n')
        prepared = build_write(path, "replace")
        stream = write_through(ITEMS, prepared, terminating=_never)
        assert path.read_bytes() == b'{"old": 1}\n'
        list(stream)
        assert path.read_bytes() == b'{"x": 0}\n{"x": 1}\n{"x": 2}\n'

    def test_graceful_close_finalizes_prefix(self, tmp_path):
        path = tmp_path / "out.json"
        stream = write_through(ITEMS, build_write(path), terminating=_never)
        next(stream)
        stream.close()
        assert path.read_bytes() == b'[{"x": 0}]'

    def test_terminate_aborts(self, tmp_path):
        path = tmp_path / "out.json"
        stream = write_through(ITEMS, build_write(path), terminating=_always)
        next(stream)
        stream.close()
        assert not path.exists()

    def test_exception_aborts(self, tmp_path):
        path = tmp_path / "out.json"
        stream = write_through(ITEMS, build_write(path), terminating=_never)
        next(stream)

        with pytest.raises(RuntimeError, match="boom"):
            stream.throw(RuntimeError("boom"))

        assert not path.exists()

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "a streaming replace write opens its destination for writing up front, "
            "so a failed run destroys the old content until writes publish atomically"
        ),
    )
    @pytest.mark.parametrize(
        ("name", "original"), [("out.csv", b"a\n1\n"), ("out.jsonl", b'{"a": 1}\n')]
    )
    def test_failed_replace_keeps_original_content(self, tmp_path, name, original):
        path = tmp_path / name
        path.write_bytes(original)

        def source() -> Iterator[dict[str, int]]:
            yield {"a": 2}
            raise ValueError("boom")

        stream = write_through(source(), build_write(path), terminating=_never)

        with pytest.raises(ValueError, match="boom"):
            list(stream)

        assert path.read_bytes() == original


@skipif_issync
class TestAsyncWriteExecution:
    @async_test
    async def test_passthrough_preserves_stream(self, tmp_path):
        prepared = build_write(tmp_path / "out.json")
        stream = awrite_through(as_async(ITEMS), prepared, terminating=_never)
        assert [item async for item in stream] == ITEMS

    @async_test
    async def test_writes_mid_chain(self, tmp_path):
        path = tmp_path / "out.json"
        stream = awrite_through(as_async(ITEMS), build_write(path), terminating=_never)
        tailed = async_tail(stream, conf={"count": 1})
        assert [item async for item in tailed] == [{"x": 2}]
        assert path.read_bytes() == b'[{"x": 0}, {"x": 1}, {"x": 2}]'

    @async_test
    async def test_csv_singleton_preserves_schema(self, tmp_path):
        path = tmp_path / "out.csv"
        rows = [{"a": 1, "b": 2}, {"b": 4, "a": 3}]
        stream = awrite_through(as_async(rows), build_write(path), terminating=_never)
        _ = [item async for item in stream]
        assert path.read_bytes() == b"a,b\r\n1,2\r\n3,4\r\n"

    @async_test
    async def test_graceful_close_finalizes_prefix(self, tmp_path):
        path = tmp_path / "out.json"
        stream = awrite_through(as_async(ITEMS), build_write(path), terminating=_never)
        await anext(stream)
        await stream.aclose()
        assert path.read_bytes() == b'[{"x": 0}]'

    @async_test
    async def test_terminate_aborts(self, tmp_path):
        path = tmp_path / "out.json"
        stream = awrite_through(as_async(ITEMS), build_write(path), terminating=_always)
        await anext(stream)
        await stream.aclose()
        assert not path.exists()

    @async_test
    async def test_exception_aborts(self, tmp_path):
        path = tmp_path / "out.json"
        stream = awrite_through(as_async(ITEMS), build_write(path), terminating=_never)
        await anext(stream)

        with pytest.raises(RuntimeError, match="boom"):
            await stream.athrow(RuntimeError("boom"))

        assert not path.exists()

    @async_test
    async def test_whole_stream_writes_one_document(self, tmp_path):
        path = tmp_path / "out.json"
        result = await _asink(ITEMS, path)
        assert result.written > 0
        assert path.read_bytes() == b'[{"x": 0}, {"x": 1}, {"x": 2}]'


class TestSink:
    def test_non_file_target_execution_unsupported(self):
        prepared = build_write(_RecordStore(), "replace")

        with (
            pytest.raises(UnsupportedTargetError, match="_RecordStore"),
            file_write_session(prepared),
        ):
            pass  # pragma: no cover
