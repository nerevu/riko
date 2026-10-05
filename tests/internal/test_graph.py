"""Tests graph traversal edge cases not covered by the graph doctests."""

import pytest

from riko.coercion._graph import descendants


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
