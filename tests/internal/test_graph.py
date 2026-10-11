"""Tests graph traversal edge cases not covered by the graph doctests."""

import os
import subprocess
import sys
from graphlib import CycleError
from types import MappingProxyType

import pytest

from riko.base._graph import cyclic_nodes, descendants, freeze_graph, topological_sort
from riko.base._paths import ROOT_DIR
from riko.base.exceptions import InvalidArchitectureError
from riko.cli._lint_import_architecture import _validate_graph


@pytest.mark.parametrize(
    ("node", "graph", "expected"),
    [
        pytest.param(
            "a", {"a": {"b"}, "b": {"c"}}, frozenset({"b", "c"}), id="transitive"
        ),
        pytest.param("b", {"a": {"b"}}, frozenset(), id="referenced-only-node"),
        pytest.param("a", {"a": {"b"}, "b": {"a"}}, frozenset({"b"}), id="cycle"),
    ],
)
def test_descendants(node, graph, expected):
    assert descendants(node, graph) == expected


def test_descendants_rejects_unknown_node():
    with pytest.raises(KeyError):
        descendants("c", {"a": {"b"}})


def test_cyclic_nodes_accepts_a_frozen_graph():
    graph = freeze_graph({"a": {"b"}, "b": {"a"}, "c": set()})
    assert isinstance(graph, MappingProxyType)
    assert sorted(cyclic_nodes(graph)) == ["a", "b"]


def test_topological_sort_key_orders_ready_nodes():
    graph = {"a": {"c"}, "b": {"c"}, "c": set()}
    ordered = topological_sort(graph, key=lambda node: node != "b")
    assert ordered == [("b",), ("a",), ("c",)]


def test_topological_sort_strict_raises_on_a_cycle():
    with pytest.raises(CycleError):
        topological_sort({"a": {"b"}, "b": {"a"}}, strict=True)


def test_topological_sort_groups_a_cycle_by_default():
    assert topological_sort({"a": {"b"}, "b": {"a"}}) == [("a", "b")]


@pytest.mark.parametrize(
    ("graph", "match"),
    [
        pytest.param(
            {"a": {"b", "c"}, "b": {"c"}, "c": set()},
            "redundant dependency: a -> c",
            id="redundant",
        ),
        pytest.param({"a": {"b"}, "b": {"a"}}, "cyclic layer graph", id="cyclic"),
        pytest.param({"a": {"b"}}, "undeclared layers: b", id="undeclared"),
    ],
)
def test_layer_graph_validation_rejects(graph, match):
    with pytest.raises(InvalidArchitectureError, match=match):
        _validate_graph("test", graph)


def test_layer_graph_validation_accepts_a_reduced_dag():
    _validate_graph("test", {"a": {"b"}, "b": {"c"}, "c": set()})


_SEEDED_ORDER = """
from riko.base._graph import scc_sort, topological_sort
print(topological_sort({"a": {"b"}, "b": {"a"}, "c": set()}))
print(topological_sort({"a": {"b", "c", "d"}, "e": {"f", "g"}}))
print(scc_sort({"A": {"B", "C"}, "B": {"D"}, "C": {"D"}, "D": {"E"}}))
"""


def _get_seeded_order(seed: str) -> list[str]:
    env = {**os.environ, "PYTHONHASHSEED": seed}
    args = [sys.executable, "-c", _SEEDED_ORDER]
    run = subprocess.run(
        args, capture_output=True, check=True, cwd=ROOT_DIR, env=env, text=True
    )
    return run.stdout.splitlines()


def test_graph_order_ignores_hash_seed():
    expected = [
        "[('c',), ('a', 'b')]",
        "[('e',), ('a',), ('g',), ('f',), ('d',), ('c',), ('b',)]",
        "[('A',), ('C',), ('B',), ('D',), ('E',)]",
    ]
    assert _get_seeded_order("1") == expected
    assert _get_seeded_order("2") == expected
