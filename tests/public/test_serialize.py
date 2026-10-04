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
            "type": "read",
            "backend": "http",
            "fmt": "json",
        },
        {"id": "filter-1", "name": "filter", "conf": {"rule": {"field": "x"}}},
        {"id": "sub-1", "name": "listen", "type": "subscribe", "policy": {"buffer": 0}},
        {
            "id": "write-1",
            "name": "store",
            "type": "write",
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
            "type": "publish",
        },
        {"source": {"node": "filter-1"}, "target": {"node": "write-1"}},
    ],
    "outputs": {"default": {"node": "write-1", "port": "out"}},
}

RICH_GOLDEN = (
    b'{"edges":[{"source":{"node":"read-1","port":"out"},"target":{"node":"filter-1",'
    b'"port":"in"},"type":"stream"},{"source":{"node":"filter-1","port":"out"},"target'
    b'":{"node":"sub-1","port":"in"},"type":"publish"},{"source":{"node":"filter-1","'
    b'port":"out"},"target":{"node":"write-1","port":"in"},"type":"stream"}],"inputs":'
    b'{"since":{"type":"string"}},"nodes":{"filter-1":{"conf":{"rule":{"field":"x"}},'
    b'"id":"filter-1","name":"filter","type":"module"},"read-1":{"backend":"http","fmt'
    b'":"json","id":"read-1","name":"read","type":"read"},"sub-1":{"id":"sub-1","name"'
    b':"listen","policy":{"buffer":0},"type":"subscribe"},"write-1":{"backend":"file",'
    b'"fmt":"csv","id":"write-1","keys":["id"],"mode":"append","name":"store","resource'
    b's":{"db":"db"},"type":"write"}},"outputs":{"default":{"node":"write-1","port":"'
    b'out"}},"resources":["db"],"version":"2"}'
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
                "type": "read",
                "backend": "s3",
                "fmt": "jsonl",
            },
            {
                "id": "w",
                "name": "store",
                "type": "write",
                "backend": "file",
                "keys": ["k"],
            },
        ],
        "edges": [{"source": {"node": "r"}, "target": {"node": "w"}}],
        "outputs": {"default": {"node": "w", "port": "out"}},
    },
    "cache": {
        "nodes": [{"id": "c", "name": "cache", "type": "cache", "policy": {"ttl": 5}}]
    },
    "action": {
        "nodes": [
            {
                "id": "a",
                "name": "notify",
                "type": "action",
                "backend": "intune",
                "params": {"scope": "all"},
            }
        ]
    },
    "publish-subscribe": {
        "nodes": [
            {"id": "p", "name": "produce"},
            {"id": "s", "name": "listen", "type": "subscribe"},
        ],
        "edges": [
            {"source": {"node": "p"}, "target": {"node": "s"}, "type": "publish"}
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
                    "type": "write",
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
