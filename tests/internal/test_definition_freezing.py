# vim: sw=4:ts=4:expandtab
"""Tests that definition snapshots freeze their nested containers."""

from __future__ import annotations

from collections import ChainMap
from copy import deepcopy
from dataclasses import dataclass
from pickle import dumps, loads  # noqa: S403
from typing import Any

import pytest

from riko.base.exceptions import InvalidPipelineError
from riko.definitions._context import Context
from riko.definitions._nodes import ModuleNode
from riko.definitions._resource_definition import Resource, ReusableResource
from riko.definitions._workflow import Workflow
from riko.definitions._write import WriteMode, WriteOperation
from riko.execution._execution import SyncExecution
from riko.execution._prepared import ExecutionPlan
from riko.types._collections import FrozenDict
from riko.types._resource import FactoryKind


def untyped_inputs(**values: Any) -> dict[str, Any]:
    """Builds inputs whose nested values fall outside the declared scalar type."""
    return values


def gen_client(*_args: object, **_kwargs: object):
    yield object()


class _Client:
    closed = False

    def close(self) -> None:
        self.closed = True


@dataclass
class _Rule:
    field: str


class TestFrozenDict:
    @pytest.mark.parametrize(
        "source", [[("ids", [1])], ChainMap({"ids": [1]})], ids=["pairs", "chain-map"]
    )
    def test_values_are_frozen_from_any_source(self, source: Any):
        assert FrozenDict(source)["ids"] == (1,)


class TestContextFreezing:
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

    def test_invalid_mode_is_rejected(self):
        with pytest.raises(ValueError, match="Invalid ExecutionMode: 5"):
            Context(mode=5)  # pyright: ignore[reportArgumentType]

    def test_derived_inputs_are_read_only(self):
        derived = Context().replace(inputs=untyped_inputs(tags=["a"]))
        assert derived.inputs is not None
        assert derived.inputs["tags"] == ("a",)

    def test_inputs_are_detached_from_the_source(self):
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
            ({"_external": True}, "must be reusable"),
            ({"_factory": len}, "factory and its kind"),
            ({"_kind": FactoryKind.SYNC_CALLABLE_FACTORY}, "factory and its kind"),
            (
                {
                    "_external": True,
                    "_factory": len,
                    "_kind": FactoryKind.SYNC_CALLABLE_FACTORY,
                },
                "cannot carry a factory",
            ),
        ],
        ids=["external-one-shot", "factory-only", "kind-only", "external-factory"],
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


class TestWriteOperationFreezing:
    def test_keys_are_a_tuple(self):
        operation = WriteOperation(WriteMode.MERGE, keys=["id"])

        assert operation.keys == ("id",)
        assert operation == WriteOperation(WriteMode.MERGE, keys=("id",))
        assert hash(operation) == hash(WriteOperation(WriteMode.MERGE, keys=("id",)))


class TestWorkflowFreezing:
    @pytest.mark.parametrize(
        ("fields", "match"),
        [
            (
                {"nodes": [1], "outputs": {}},
                "Workflow node position 0 must be of type Node",
            ),
            (
                {"nodes": [], "outputs": {"o": 1}},
                "Workflow output 'o' must be of type Endpoint",
            ),
        ],
        ids=["nodes", "outputs"],
    )
    def test_mapping_values_must_have_the_field_type(
        self, fields: dict[str, Any], match: str
    ):
        with pytest.raises(InvalidPipelineError, match=match):
            Workflow(**fields)

    def test_execution_plan_modules_must_be_resolved_modules(self):
        workflow = Workflow(nodes=[], outputs={})

        with pytest.raises(InvalidPipelineError, match="ExecutionPlan module 'n'"):
            ExecutionPlan(workflow=workflow, modules={"n": 1})  # pyright: ignore[reportArgumentType]

    @pytest.mark.parametrize("field", ["nodes", "outputs", "inputs"])
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

    @pytest.mark.parametrize("modules", ["abc", None])
    def test_execution_plan_modules_must_be_a_mapping(self, modules: Any):
        workflow = Workflow(nodes=[], outputs={})

        with pytest.raises(InvalidPipelineError, match="ExecutionPlan 'modules'"):
            ExecutionPlan(workflow=workflow, modules=modules)

    @pytest.mark.xfail(
        strict=True,
        reason="owned by the pending workflow input declarations work: a strict "
        "Workflow accepts an input declaration that is not a JSON Schema mapping",
    )
    @pytest.mark.parametrize("declaration", [5, "string"])
    def test_non_schema_inputs_are_rejected(self, declaration: object):
        with pytest.raises(InvalidPipelineError, match="Workflow 'inputs'"):
            Workflow(nodes=[], outputs={}, inputs={"q": declaration})

    def test_node_resources_accept_shorthand_bindings(self):
        named = ModuleNode(id="a", name="x", resources="db")
        listed = ModuleNode(id="a", name="x", resources=["db"])
        assert named.resources == listed.resources == {"db": "db"}

    def test_node_resources_reject_non_bindings(self):
        with pytest.raises(InvalidPipelineError, match="node 'resources' must be"):
            ModuleNode(id="a", name="x", resources=5)  # pyright: ignore[reportArgumentType]

    def test_module_conf_accepts_floats_and_none(self):
        node = ModuleNode(id="a", name="sleep", conf={"wait": 1.5, "join_key": None})
        assert node.conf == {"wait": 1.5, "join_key": None}

    def test_module_conf_rejects_dataclass_values(self):
        conf = {"rule": _Rule("x")}

        with pytest.raises(InvalidPipelineError, match="not JSON-native"):
            ModuleNode(id="a", name="sort", conf=conf)  # pyright: ignore[reportArgumentType]

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
