"""Tests graph traversal edge cases not covered by the graph doctests."""

from types import MappingProxyType

import pytest

from riko.base._graph import cyclic_nodes, descendants, freeze_graph


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
