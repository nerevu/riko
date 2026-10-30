# vim: sw=4:ts=4:expandtab
"""Provides internal tests for definition construction, write targets, and sessions."""

from __future__ import annotations

import json
from collections import ChainMap
from copy import deepcopy
from functools import partial
from pickle import dumps, loads  # noqa: S403
from typing import TYPE_CHECKING, Any, get_args, get_type_hints

import pytest
from attrs import fields_dict

from riko.base._require_guards import typed_dict_keys
from riko.definitions._context import Context
from riko.definitions._nodes import (
    ActionNode,
    CacheNode,
    ModuleNode,
    ReadNode,
    SubscribeNode,
    WriteNode,
)
from riko.definitions._normalize import _NODE_BUILDERS, _build_nodes, _normalize_port
from riko.definitions._pipeline_definition import PipelineDefinition
from riko.definitions._resource_definition import (
    OneShotResource,
    Resource,
    ReusableResource,
)
from riko.definitions._serialize import WorkflowEncoder
from riko.definitions._settings import ExecutionSettings
from riko.definitions._targets import (
    FileTarget,
    build_write,
    normalize_target,
    resolve_format,
    validate_target_mode,
)
from riko.definitions._workflow_definition import Workflow
from riko.definitions._write import WriteCapabilities, WriteMode, WriteOperation
from riko.types._enums import Formats
from riko.types._frozendict import FrozenDict
from riko.types._io import is_closeable
from riko.types._options import CallOptions, RawCallOptions
from riko.types._resource import (
    AsyncLifecyclePlan,
    LifecycleFactory,
    ResourceStrategy,
    SyncLifecyclePlan,
    ValueFactory,
    ValueFactoryPlan,
    build_factory_plan,
    build_lifecycle_plan,
)
from riko.types._workflow import (
    DocumentNodeFamily,
    Endpoint,
    ParsedPort,
    RawEdge,
    RawEndpoint,
    RawNode,
    parse_port,
)
from riko.types._workflow import Edge as EdgeBase
from tests._resources import (
    CREDENTIAL,
    SCALAR,
    VALUE_FACTORIES,
    Connection,
    async_callable_factory,
    async_cm_factory,
    async_gen_factory,
    check_credential_and_lazy,
    check_metadata,
    close_async_connection,
    close_connection,
    sync_callable_factory,
    sync_cm_factory,
    sync_gen_factory,
    wrapped_async_cm_factory,
    wrapped_async_gen_factory,
    wrapped_sync_cm_factory,
    wrapped_sync_gen_factory,
)
from tests._targets import RecordStore

if TYPE_CHECKING:
    from collections.abc import Callable


_RESOLVED = "Expected a resolved resource value"
_NODES = (ModuleNode, ReadNode, WriteNode, ActionNode, CacheNode, SubscribeNode)
_NODE_ALIASES = frozenset({"family", "format"})
_EDGE_ALIASES = frozenset({"family"})


def untyped_inputs(**values: Any) -> dict[str, Any]:
    """Builds inputs whose nested values fall outside the declared scalar type."""
    return values


def gen_client(*_args: object, **_kwargs: object):
    yield object()


class _Client:
    closed = False

    def close(self) -> None:
        self.closed = True


class TestFrozenDict:
    @pytest.mark.parametrize(
        "source", [[("ids", [1])], ChainMap({"ids": [1]})], ids=["pairs", "chain-map"]
    )
    def test_values_are_frozen_from_any_source(self, source: Any):
        assert FrozenDict(source)["ids"] == (1,)

    def test_equal_frozen_dicts_hash_alike(self):
        assert hash(FrozenDict({"a": [1]})) == hash(FrozenDict({"a": (1,)}))

    def test_an_unhashable_value_makes_it_unhashable(self):
        with pytest.raises(TypeError, match="unhashable type: 'bytearray'"):
            hash(FrozenDict({"a": bytearray()}))

    @pytest.mark.parametrize(
        ("merged", "expected"),
        [
            pytest.param(
                FrozenDict({"a": 1}) | {"a": 2, "b": [3]}, {"a": 2, "b": (3,)}, id="or"
            ),
            pytest.param(
                {"a": 2, "b": 3} | FrozenDict({"a": 1}), {"a": 1, "b": 3}, id="ror"
            ),
        ],
    )
    def test_merging_returns_a_frozen_dict(self, merged: Any, expected: dict):
        assert isinstance(merged, FrozenDict)
        assert merged == expected


def _sync_generator():
    yield SCALAR


async def _async_generator():
    yield SCALAR


GENERATOR_FUNCS = [
    pytest.param(_sync_generator, id="sync"),
    pytest.param(_async_generator, id="async"),
]


RESOURCE_SHAPES = [
    pytest.param(
        lambda: Resource.from_external(Connection()),
        ResourceStrategy.EXTERNAL,
        False,
        True,
        id="external",
    ),
    pytest.param(
        lambda: Resource(Connection()), ResourceStrategy.OWNED, False, True, id="owned"
    ),
    pytest.param(
        lambda: Resource.from_factory(sync_callable_factory, cleanup=close_connection),
        ResourceStrategy.VALUE_FACTORY,
        False,
        False,
        id="sync-value-factory",
    ),
    pytest.param(
        lambda: Resource.from_factory(
            async_callable_factory, cleanup=close_async_connection
        ),
        ResourceStrategy.VALUE_FACTORY,
        True,
        False,
        id="async-value-factory",
    ),
    pytest.param(
        lambda: Resource.from_lifecycle(sync_gen_factory),
        ResourceStrategy.LIFECYCLE,
        False,
        False,
        id="sync-lifecycle",
    ),
    pytest.param(
        lambda: Resource.from_lifecycle(async_gen_factory),
        ResourceStrategy.LIFECYCLE,
        True,
        False,
        id="async-lifecycle",
    ),
]


MARKER_CONSTRUCTION_CASES = [
    pytest.param(lambda: ReusableResource(_Client()), id="reusable-direct"),
    pytest.param(lambda: OneShotResource(_Client()), id="one-shot-direct"),
    pytest.param(lambda: ReusableResource.from_external(_Client()), id="external"),
    pytest.param(
        lambda: OneShotResource.from_factory(dict, cleanup=False), id="factory"
    ),
    pytest.param(lambda: ReusableResource.from_lifecycle(gen_client), id="lifecycle"),
]


CONTEXT_FACTORY_REJECTIONS = [
    pytest.param("scalar", id="scalar"),
    pytest.param("connection", id="connection"),
    pytest.param("sync_contextmanager", id="sync-context-manager"),
    pytest.param("one_shot_resource", id="one-shot"),
]


RESOLVED_VALUE_REJECTIONS = [
    pytest.param("scalar", "Must provide a Closeable value", id="scalar"),
    pytest.param("sync_contextmanager", _RESOLVED, id="sync-context-manager"),
    pytest.param("one_shot_resource", _RESOLVED, id="one-shot"),
    pytest.param("external_resource", _RESOLVED, id="external"),
]


NON_FACTORY_VALUES = [
    pytest.param("scalar", id="scalar"),
    pytest.param("connection", id="connection"),
    pytest.param("one_shot_resource", id="one-shot"),
    pytest.param("external_resource", id="external"),
]


class TestResource:
    def test_pickle_and_copy_round_trip(self):
        resource = Resource.from_factory(gen_client, retries=[1, 2], lazy=True)

        pickled = loads(dumps(resource))  # noqa: S301

        for restored in (pickled, deepcopy(resource)):
            assert isinstance(restored, ReusableResource)
            assert isinstance(restored._plan, SyncLifecyclePlan)
            assert restored._plan.source is gen_client
            assert restored.lazy
            assert restored._plan.kwargs["retries"] == (1, 2)

    @pytest.mark.parametrize(
        ("factory", "classification"),
        [
            pytest.param(sync_gen_factory, SyncLifecyclePlan, id="sync-gen"),
            pytest.param(async_gen_factory, AsyncLifecyclePlan, id="async-gen"),
            pytest.param(sync_cm_factory, SyncLifecyclePlan, id="sync-cm"),
            pytest.param(async_cm_factory, AsyncLifecyclePlan, id="async-cm"),
            pytest.param(
                wrapped_sync_gen_factory, SyncLifecyclePlan, id="wraps-sync-gen"
            ),
            pytest.param(
                wrapped_async_gen_factory, AsyncLifecyclePlan, id="wraps-async-gen"
            ),
            pytest.param(
                wrapped_sync_cm_factory, SyncLifecyclePlan, id="wraps-sync-cm"
            ),
            pytest.param(
                wrapped_async_cm_factory, AsyncLifecyclePlan, id="wraps-async-cm"
            ),
        ],
    )
    def test_lifecycle_factory_metadata[T](
        self, factory: LifecycleFactory[T], classification: type
    ):
        assert isinstance(build_lifecycle_plan(factory), classification)
        test_metadata = partial(check_metadata, classification=classification)

        context = Context().with_resource("factory", factory)
        resource = context.resources["factory"]
        test_metadata(resource, ReusableResource, external=False, reusable=True)

        resource = Resource.from_lifecycle(factory)
        test_metadata(resource, OneShotResource, external=False, reusable=False)

        resource = Resource.from_factory(factory)
        test_metadata(resource, ReusableResource, external=False, reusable=True)

    @pytest.mark.parametrize(
        ("factory", "cleanup", "is_async"),
        [
            (sync_callable_factory, close_connection, False),
            (async_callable_factory, close_async_connection, True),
        ],
    )
    def test_value_factory_metadata[T](
        self, factory: ValueFactory[T], cleanup, is_async: bool
    ):
        plan = build_factory_plan(factory, cleanup=cleanup)
        assert isinstance(plan, ValueFactoryPlan)
        assert plan.is_async is is_async
        test_metadata = partial(check_metadata, typ=ReusableResource, reusable=True)

        resource = Resource.from_external(factory)
        test_metadata(resource, external=True)

        resource = Resource.from_factory(factory, cleanup=cleanup)
        test_metadata(resource, external=False, classification=ValueFactoryPlan)

    @pytest.mark.parametrize(("factory", "cleanup"), VALUE_FACTORIES)
    def test_value_factory_carries_credential_and_lazy[T](
        self, factory: ValueFactory[T], cleanup
    ):
        resource = Resource.from_factory(
            factory, cleanup=cleanup, credential=CREDENTIAL, lazy=True
        )
        check_credential_and_lazy(resource)

    @pytest.mark.parametrize(
        ("build", "strategy", "async_native", "has_value"), RESOURCE_SHAPES
    )
    def test_plan_derived_properties(
        self,
        build: Callable[[], Resource[Any]],
        strategy: ResourceStrategy,
        async_native: bool,
        has_value: bool,
    ):
        resource = build()
        assert resource.strategy is strategy
        assert resource.async_native is async_native

        if has_value:
            assert isinstance(resource.value, Connection)
        else:
            with pytest.raises(AttributeError, match="no value until acquired"):
                _ = resource.value

    @pytest.mark.parametrize("func", GENERATOR_FUNCS)
    def test_generator_object_points_to_from_lifecycle(self, func):
        started = func()
        assert is_closeable(started)

        with pytest.raises(TypeError, match=r"generator object.*from_lifecycle"):
            Resource(started)

    @pytest.mark.parametrize("factory", [sync_callable_factory, async_callable_factory])
    def test_value_factory_needs_from_factory_and_cleanup[T](
        self, factory: ValueFactory[T]
    ):
        with pytest.raises(TypeError, match=r"Invalid resource factory.*one-shot"):
            Context().with_resource(  # pyright: ignore[reportCallIssue]
                "factory",
                factory,  # pyright: ignore[reportArgumentType]
            )

        with pytest.raises(TypeError, match="Must provide a Closeable value"):
            Resource(factory)

        with pytest.raises(TypeError, match="Invalid lifecycle factory"):
            Resource.from_lifecycle(factory)  # pyright: ignore[reportArgumentType]

        with pytest.raises(TypeError, match=r"ValueFactory requires.*cleanup function"):
            Resource.from_factory(factory)  # pyright: ignore[reportArgumentType]

    @pytest.mark.parametrize("construct", MARKER_CONSTRUCTION_CASES)
    def test_marker_types_cannot_be_constructed(self, construct: Callable[[], object]):
        with pytest.raises(TypeError, match="is a declaration type"):
            construct()

    @pytest.mark.parametrize("fixture", CONTEXT_FACTORY_REJECTIONS)
    def test_context_rejects_a_non_factory_value(self, fixture, request):
        with pytest.raises(TypeError, match="Invalid resource factory"):
            Context().with_resource("value", request.getfixturevalue(fixture))

    @pytest.mark.parametrize(("fixture", "match"), RESOLVED_VALUE_REJECTIONS)
    def test_resource_rejects_an_unresolved_value(self, fixture, match, request):
        with pytest.raises(TypeError, match=match):
            Resource(request.getfixturevalue(fixture))

    @pytest.mark.parametrize("fixture", NON_FACTORY_VALUES)
    def test_factories_reject_a_non_factory_value(self, fixture, request):
        value = request.getfixturevalue(fixture)

        with pytest.raises(TypeError, match="Invalid lifecycle factory"):
            Resource.from_lifecycle(value)

        with pytest.raises(TypeError, match="Invalid resource factory"):
            Resource.from_factory(value)


class TestResourceFreezing:
    def test_factory_arguments_are_read_only(self):
        resource = Resource.from_factory(
            gen_client, ["arg"], headers={"accept": ["json"]}
        )
        assert isinstance(resource._plan, SyncLifecyclePlan)
        headers = resource._plan.kwargs["headers"]

        assert resource._plan.args == (("arg",),)
        assert isinstance(headers, FrozenDict)
        assert headers["accept"] == ("json",)

    def test_opaque_argument_values_are_untouched(self):
        client = _Client()
        resource = Resource.from_factory(gen_client, client, session=client)

        assert isinstance(resource._plan, SyncLifecyclePlan)
        assert resource._plan.args[0] is client
        assert resource._plan.kwargs["session"] is client

    @pytest.mark.parametrize("name", ["_plan", "credential", "lazy", "extra"])
    def test_fields_cannot_be_set(self, name: str):
        resource = Resource.from_factory(gen_client)

        with pytest.raises(AttributeError):
            setattr(resource, name, None)

        with pytest.raises(AttributeError):
            delattr(resource, name)

    def test_plan_fields_are_read_only(self):
        resource = Resource.from_factory(sync_gen_factory)

        with pytest.raises(AttributeError):
            resource._plan.enter = sync_gen_factory  # pyright: ignore[reportAttributeAccessIssue]


class TestWorkflowFields:
    def test_pickle_and_copy_round_trip(self):
        node = ModuleNode(
            id="a",
            name="loop",
            conf=untyped_inputs(rules=[{"field": "x", "nested": {"ids": [1, 2]}}]),
            embed={"name": "tokenizer", "conf": {"delimiter": " "}},
            resources={"db": "primary_db"},
        )
        flow = Workflow(nodes=[node], outputs={}, inputs={"q": {"type": "string"}})

        pickled = loads(dumps(flow))  # noqa: S301

        for restored in (pickled, deepcopy(flow)):
            assert restored == flow
            restored_node = restored.nodes["a"]
            assert isinstance(restored_node, ModuleNode)
            rules = restored_node.conf["rules"]
            assert isinstance(rules, tuple)
            assert isinstance(rules[0], FrozenDict)
            assert rules == ({"field": "x", "nested": {"ids": (1, 2)}},)
            assert restored_node.resources == {"db": "primary_db"}
            assert isinstance(restored.inputs["q"], FrozenDict)

    def test_encoder_rejects_a_value_a_workflow_cannot_hold(self):
        with pytest.raises(TypeError, match="not JSON serializable"):
            json.dumps(object(), cls=WorkflowEncoder)


_EXISTING_IDS = [
    pytest.param((), "fetch-1", id="empty"),
    pytest.param(("fetch-1",), "fetch-2", id="next"),
    pytest.param(("fetch-a",), "fetch-1", id="custom-id"),
    pytest.param(("fetch-2",), "fetch-1", id="gap"),
]


class TestNormalizeInternals:
    @pytest.mark.parametrize(("ids", "expected"), _EXISTING_IDS)
    def test_get_node_id_matches_a_normalized_id(self, ids, expected):
        existing = [{"id": node_id, "name": "fetch"} for node_id in ids]
        normalized = list(_build_nodes([*existing, {"name": "fetch"}]))[-1]
        flow = Workflow(nodes=[ModuleNode(**node) for node in existing])
        assert flow.get_node_id("fetch") == normalized == expected

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

    def test_every_document_node_family_has_a_builder(self):
        families = set(get_args(DocumentNodeFamily.__value__))
        assert set(_NODE_BUILDERS) == families
        assert {builder.family for builder in _NODE_BUILDERS.values()} == families


BAD_PORTS = [
    pytest.param("sideways", "invalid port direction", id="direction-sideways"),
    pytest.param("up:1", "invalid port direction", id="direction-up-1"),
    pytest.param("", "invalid port direction", id="direction-empty"),
    pytest.param("out:-1", "invalid port", id="qualifier-out-negative"),
    pytest.param("out:", "invalid port", id="qualifier-out-empty"),
    pytest.param("out:a b", "invalid port", id="qualifier-out-a-b"),
    pytest.param("in:", "invalid port", id="qualifier-in-empty"),
    pytest.param("in:-1", "invalid port", id="qualifier-in-negative"),
    pytest.param("in:a b", "invalid port", id="qualifier-in-a-b"),
    pytest.param("out:0", "invalid port", id="zero-position"),
]


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

    @pytest.mark.parametrize(("port", "match"), BAD_PORTS)
    def test_parse_port_rejects(self, port, match):
        with pytest.raises(ValueError, match=match):
            parse_port(port)


def _attrs_fields(*classes) -> set[str]:
    return {name for cls in classes for name in fields_dict(cls)}


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

    def test_raw_call_options_matches_record(self):
        record, raw = get_type_hints(CallOptions), get_type_hints(RawCallOptions)
        assert record.keys() == raw.keys()
        assert all(record[key] == hint | None for key, hint in raw.items())

    def test_call_options_kwargs_covers_every_option(self):
        options = RawCallOptions(emit=True, assign="a", field="f", count="first")
        assert CallOptions(**options).kwargs == options

    def test_raw_requiredness_matches_contract(self):
        assert "id" in RawNode.__annotations__
        assert typed_dict_keys(RawNode)[0] == {"name"}
        assert typed_dict_keys(RawEndpoint)[0] == {"node"}
        assert typed_dict_keys(RawEdge)[0] == {"source", "target"}


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


class TestExecutionSettings:
    def test_a_none_shutdown_timeout_raises(self) -> None:
        # ``with_execution`` turns ``None`` into the default, so only direct
        # construction can pass it through.
        with pytest.raises(TypeError, match="a number"):
            ExecutionSettings(shutdown_timeout=None)  # pyright: ignore[reportArgumentType]


class TestWriteMode:
    def test_mode_values(self):
        assert [m.value for m in WriteMode] == ["append", "merge", "replace", "delete"]


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


class TestResolveFormat:
    def test_explicit_format_wins(self):
        assert resolve_format("out.csv", "json") == "json"

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError, match="Invalid Formats"):
            resolve_format("out.txt", None)


class TestFileCapabilities:
    @pytest.mark.parametrize(
        ("dest", "appendable", "incremental"),
        [("out.csv", True, True), ("out.geojson", False, False)],
    )
    def test_target_owns_format_behavior(self, dest, appendable, incremental):
        capabilities = FileTarget(dest).get_capabilities()

        assert capabilities.serializes is True
        assert capabilities.appendable is appendable
        assert (WriteMode.APPEND in capabilities.modes) is appendable
        assert capabilities.incremental is incremental
        assert WriteMode.REPLACE in capabilities.modes


class TestValidateTargetMode:
    def test_match_keyed_without_keys_rejected(self):
        capabilities = RecordStore().get_capabilities()
        with pytest.raises(ValueError, match="requires 'keys'"):
            validate_target_mode(RecordStore(), WriteMode.MERGE, capabilities)

    @pytest.mark.parametrize(
        ("mode", "keys"),
        [
            pytest.param(WriteMode.MERGE, ("id",), id="match-keyed"),
            pytest.param(WriteMode.APPEND, (), id="idempotent-unkeyed"),
            pytest.param(WriteMode.APPEND, ("id",), id="idempotent-keyed"),
        ],
    )
    def test_supported_key_combinations(self, mode, keys):
        capabilities = RecordStore().get_capabilities()
        validate_target_mode(RecordStore(), mode, capabilities, keys=keys)

    def test_unkeyed_mode_with_keys_rejected(self):
        capabilities = FileTarget("out.csv").get_capabilities()
        target = FileTarget("out.csv")

        with pytest.raises(ValueError, match="forbids 'keys'"):
            validate_target_mode(target, WriteMode.APPEND, capabilities, keys=("x",))


class TestBuildWrite:
    def test_path_defaults_to_extension_format_and_replace(self):
        prepared = build_write("out.csv")
        assert prepared.fmt is Formats.CSV
        assert prepared.operation.mode is WriteMode.REPLACE

    def test_record_store_binds_match_keys(self):
        prepared = build_write(RecordStore(), "merge", keys="endpoint_id")

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
