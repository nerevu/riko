# vim: sw=4:ts=4:expandtab
"""Tests deterministic ``Workflow`` serialization, round-trips, and migrated output."""

import json
from datetime import date
from decimal import Decimal
from types import MappingProxyType

import pytest

from riko.base.exceptions import InvalidPipelineError
from riko.definitions._workflow import WriteNode
from riko.ext import (
    migrate_v1_to_v2,
    normalize_workflow,
    parse_document,
    serialize_workflow,
)

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

PIPE_DEF = {
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


@pytest.mark.parametrize("document", ["{bad", b"\xff", "[]"])
def test_unparseable_documents_are_invalid_pipelines(document):
    with pytest.raises(InvalidPipelineError):
        parse_document(document)


def test_golden_bytes():
    workflow = normalize_workflow(RICH_RAW)
    assert serialize_workflow(workflow, indent=None) == RICH_GOLDEN


def test_default_form_is_indented():
    workflow = normalize_workflow(RICH_RAW)
    assert serialize_workflow(workflow) == serialize_workflow(workflow, indent=4)
    assert serialize_workflow(workflow) != serialize_workflow(workflow, indent=None)


@pytest.mark.parametrize("raw", TOPOLOGIES.values(), ids=TOPOLOGIES.keys())
def test_topologies_round_trip(raw):
    workflow = normalize_workflow(raw)
    assert parse_document(serialize_workflow(workflow)) == workflow


@pytest.mark.parametrize("raw", TOPOLOGIES.values(), ids=TOPOLOGIES.keys())
def test_serialization_is_idempotent(raw):
    workflow = normalize_workflow(raw)
    once = serialize_workflow(workflow)
    assert serialize_workflow(parse_document(once)) == once


@pytest.mark.parametrize("raw", TOPOLOGIES.values(), ids=TOPOLOGIES.keys())
def test_indented_output_round_trips(raw):
    workflow = normalize_workflow(raw)
    assert parse_document(serialize_workflow(workflow, indent=4)) == workflow


def test_indented_output_is_readable_and_sorted():
    workflow = normalize_workflow(RICH_RAW)
    document = serialize_workflow(workflow, indent=2).decode("utf-8")
    top_level = [line[2:] for line in document.splitlines() if line.startswith('  "')]
    keys = [line.split('"')[1] for line in top_level]

    assert document.endswith("\n")
    assert keys == sorted(keys)
    assert '\n  "version": "2"\n' in document


def test_serialization_is_order_independent():
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
    first = serialize_workflow(normalize_workflow(reordered))
    second = serialize_workflow(normalize_workflow(forward))
    assert first == second


def test_write_node_keys_and_mode_survive():
    workflow = normalize_workflow(TOPOLOGIES["read-write"])
    restored = parse_document(serialize_workflow(workflow)).nodes["w"]
    assert isinstance(restored, WriteNode)
    assert restored.keys == ("k",)
    assert restored.mode.value == "replace"


def test_write_node_destination_survives():
    workflow = normalize_workflow(
        {
            "nodes": [
                {
                    "id": "w",
                    "name": "store",
                    "family": "write",
                    "backend": "file",
                    "dest": "out.jsonl",
                    "fmt": "jsonl",
                }
            ]
        }
    )
    restored = parse_document(serialize_workflow(workflow)).nodes["w"]
    assert isinstance(restored, WriteNode)
    assert restored.dest == "out.jsonl"


def test_migration_then_serialization_emits_no_pipe_def_structure():
    data = serialize_workflow(migrate_v1_to_v2(PIPE_DEF), indent=None)
    text = data.decode("utf-8")
    assert b'"version":"2"' in data

    for token in ("_OUTPUT", "_INPUT", "wires", '"src"', '"tgt"', '"type":"output"'):
        assert token not in text


def test_call_options_are_serialized_apart_from_conf():
    workflow = normalize_workflow(TOPOLOGIES["call-options"])
    data = serialize_workflow(workflow, indent=None)
    assert b'"options":{"count":"first","emit":true}' in data
    assert b'"conf":{"delimiter":{"value":","}}' in data


def test_json_native_conf_round_trips_by_equality():
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
    assert parse_document(serialize_workflow(workflow)) == workflow


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
def test_non_json_native_conf_value_rejected(value):
    raw = {"nodes": [{"id": "n", "name": "tag", "conf": {"x": value}}]}

    with pytest.raises(InvalidPipelineError):
        normalize_workflow(raw)


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


@pytest.mark.parametrize("value", [Decimal("1.50"), {"a", "b"}, b"bytes", float("nan")])
@pytest.mark.parametrize("placement", sorted(_NODE_VALUE_PLACEMENTS))
def test_non_json_native_node_value_rejected(placement, value):
    raw = {"nodes": [{"id": "n", **_NODE_VALUE_PLACEMENTS[placement](value)}]}

    with pytest.raises(InvalidPipelineError, match="JSON-native"):
        normalize_workflow(raw)


def test_non_string_policy_key_rejected():
    raw = {
        "nodes": [{"id": "n", "family": "cache", "name": "cache", "policy": {1: True}}]
    }

    with pytest.raises(InvalidPipelineError, match="mapping key must be of type str"):
        normalize_workflow(raw)


def test_migrated_output_pseudo_node_is_not_a_node():
    workflow = migrate_v1_to_v2(PIPE_DEF)
    assert "_OUTPUT" not in workflow.nodes
    assert workflow.outputs["default"].node == "sw-2"


def test_loop_embed_serializes_as_a_node_field():
    raw = {
        "nodes": [
            {
                "id": "loop-1",
                "name": "loop",
                "embed": {"name": "tokenizer", "conf": {"delimiter": {"value": " "}}},
            }
        ]
    }
    workflow = normalize_workflow(raw)
    document = json.loads(serialize_workflow(workflow))
    node = document["nodes"]["loop-1"]

    assert node["embed"] == {"name": "tokenizer", "conf": {"delimiter": {"value": " "}}}
    assert "conf" not in node
    assert parse_document(serialize_workflow(workflow)) == workflow
