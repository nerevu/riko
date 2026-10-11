# vim: sw=4:ts=4:expandtab
"""Tests that definition and plan fields reject malformed values when built."""

from __future__ import annotations

import copy
import pickle  # noqa: S403
from typing import Any

import pytest

from riko.base.exceptions import InvalidPipelineError
from riko.definitions._context import Context
from riko.definitions._workflow import (
    ActionNode,
    CacheNode,
    ModuleNode,
    PipelineDefinition,
    StreamEdge,
    SubscribeNode,
    Workflow,
    WriteNode,
)
from riko.definitions._write import WriteMode, WriteOperation
from riko.execution._prepared import ExecutionPlan, PreparedNode, ResolvedModule
from riko.execution._resource_view import ResourceView
from riko.modules.hash import pipe as hash_pipe
from riko.types._workflow import Endpoint

_OUT = {"default": Endpoint("a", "out")}


_HASH = ResolvedModule("hash", sync_pipe=hash_pipe)


class TestResourceBinding:
    @pytest.mark.parametrize(
        "resources",
        [b"db", "", {"db": 1}, {"db": None}, {1: "db"}, {"": "db"}, ["db", 1]],
    )
    def test_names_must_be_non_empty_strings(self, resources: Any):
        with pytest.raises(InvalidPipelineError, match="must bind non-empty strings"):
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


class TestWriteOperationFields:
    def test_mode_is_normalized(self):
        assert WriteOperation("replace").mode is WriteMode.REPLACE

    def test_an_unknown_mode_is_rejected(self):
        with pytest.raises(ValueError, match="bogus"):
            WriteOperation("bogus")

    def test_a_bare_key_is_not_split(self):
        operation = WriteOperation(WriteMode.MERGE, keys="id")
        assert operation.keys == ("id",)


class TestExecutionPlanFields:
    def test_workflow_must_be_a_workflow(self):
        with pytest.raises(InvalidPipelineError, match="ExecutionPlan 'workflow'"):
            ExecutionPlan(workflow={"nodes": []}, modules={})  # pyright: ignore[reportArgumentType]

    @pytest.mark.parametrize(
        "modules", [{}, {"a": _HASH, "b": _HASH}], ids=["missing", "extra"]
    )
    def test_modules_must_match_the_workflow(self, modules: dict[str, ResolvedModule]):
        workflow = Workflow(nodes=[ModuleNode(id="a", name="hash")], outputs=_OUT)

        with pytest.raises(InvalidPipelineError, match="modules must match"):
            ExecutionPlan(workflow=workflow, modules=modules)

    @pytest.mark.parametrize(
        ("embed", "embeds"),
        [({"name": "hash", "conf": {}}, {}), (None, {"a": _HASH})],
        ids=["missing", "extra"],
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


@pytest.mark.parametrize(
    "duplicate",
    [copy.copy, copy.deepcopy, lambda view: pickle.loads(pickle.dumps(view))],  # noqa: S301
    ids=["copy", "deepcopy", "pickle"],
)
def test_resource_view_can_be_copied(duplicate):
    assert dict(duplicate(ResourceView({"db": 1}))) == {"db": 1}
