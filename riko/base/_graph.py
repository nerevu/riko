"""
Graph traversal and topological sorting helpers.

Derived from the public-domain implementation by Paul Harrison.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Hashable, Iterable, Iterator, Mapping
from graphlib import CycleError, TopologicalSorter
from types import MappingProxyType
from typing import TYPE_CHECKING

import networkx as nx

from ._iterutils import map_values, sort_stably

if TYPE_CHECKING:
    from _typeshed import SupportsRichComparison

type Nodes[T: Hashable] = Collection[T]
type Graph[T: Hashable] = Mapping[T, Nodes[T]]
type NodeList[T: Hashable] = list[T]
type NodeSet[T: Hashable] = set[T]
type SetGraph[T: Hashable] = Mapping[T, NodeSet[T]]
type SCC[T: Hashable] = list[tuple[T, ...]]
type FrozenGraph[T: Hashable] = MappingProxyType[T, frozenset[T]]
type AnyGraph[T] = Graph[T] | FrozenGraph[T]
type SortKey[T] = Callable[[T], SupportsRichComparison] | None


def scc_sort[T: Hashable](graph: Graph[T], reverse: bool | None = False) -> SCC[T]:
    """
    Identifies strongly connected components in a graph.

    graph should be a dictionary mapping node names to an
    sequence of successor nodes.

    Examples:

        # A --> B --> C --> D
        >>> graph = {"A": {"B"}, "B": {"C"}, "C": {"D"}}
        >>> scc_sort(graph)
        [('A',), ('B',), ('C',), ('D',)]

        # A --> B <--> C --> D
        >>> graph = {"A": {"B"}, "B": {"C"}, "C": {"B", "D"}}
        >>> scc_sort(graph)
        [('A',), ('B', 'C'), ('D',)]

        # A --> B --> D --> E
        # ↓           ↑
        # + --> C ----+
        >>> graph = {"A": {"B", "C"}, "B": {"D"}, "C": {"D"}, "D": {"E"}}
        >>> scc_sort(graph)
        [('A',), ('C',), ('B',), ('D',), ('E',)]

        # 0 --> 1 --> 2 --> 3
        #       ↑     ↓
        #       +-----+
        >>> graph = {0: [1], 1: [2], 2: [1, 3]}
        >>> scc_sort(graph)
        [(0,), (1, 2), (3,)]

        #             6 ----+
        #             ↓     ↓
        # 0 --> 1 --> 2 --> 3
        #       ↓     ↑
        #       +---> 4 <-- 5
        >>> graph = {0: [1], 1: [2, 4], 4: [2], 2: [3], 5: [4], 6: [2, 3]}
        >>> scc_sort(graph)
        [(6,), (5,), (0,), (1,), (4,), (2,), (3,)]

    """
    digraph = nx.DiGraph(map_values(sort_stably, graph))
    components = nx.strongly_connected_components(digraph)
    scc = [tuple(sort_stably(component)) for component in components]
    return scc if reverse else scc[::-1]


def native_topological_sort[T: Hashable](
    graph: Graph[T], reverse: bool | None = False, key: SortKey[T] = None
) -> NodeList[T]:
    """
    Native topological sort.

    Examples:

        # A --> B --> C --> D
        >>> graph = {"A": {"B"}, "B": {"C"}, "C": {"D"}}
        >>> native_topological_sort(graph)
        ['A', 'B', 'C', 'D']

        # A --> B <--> C --> D
        >>> graph = {"A": {"B"}, "B": {"C"}, "C": {"B", "D"}}
        >>> native_topological_sort(graph)
        Traceback (most recent call last):
        ...
        graphlib.CycleError: ('nodes are in a cycle', ['B', 'C', 'B'])

        # A --> B --> D --> E
        # ↓           ↑
        # + --> C ----+
        >>> graph = {"A": {"B", "C"}, "B": {"D"}, "C": {"D"}, "D": {"E"}}
        >>> native_topological_sort(graph)
        ['A', 'C', 'B', 'D', 'E']
        >>> native_topological_sort(graph, reverse=True)
        ['E', 'D', 'B', 'C', 'A']

        # 0 --> 1 --> 2 --> 3
        #       ↑     ↓
        #       +-----+
        >>> graph = {0: [1], 1: [2], 2: [1, 3]}
        >>> native_topological_sort(graph)
        Traceback (most recent call last):
        ...
        graphlib.CycleError: ('nodes are in a cycle', [1, 2, 1])

        #             6 ----+
        #             ↓     ↓
        # 0 --> 1 --> 2 --> 3
        #       ↓     ↑
        #       +---> 4 <-- 5
        >>> graph = {0: [1], 1: [2, 4], 4: [2], 2: [3], 5: [4], 6: [2, 3]}
        >>> native_topological_sort(graph)
        [0, 5, 1, 6, 4, 2, 3]

    """
    ts = TopologicalSorter(map_values(sort_stably, graph))

    if key is None:
        static_order = list(ts.static_order())
    else:
        ts.prepare()
        static_order: list[T] = []

        while ts.is_active():
            ready = sorted(ts.get_ready(), key=key, reverse=not reverse)
            static_order.extend(ready)
            ts.done(*ready)

    return static_order if reverse else static_order[::-1]


def topological_sort[T: Hashable](
    graph: Graph[T],
    *,
    reverse: bool | None = False,
    strict: bool | None = False,
    key: SortKey[T] = None,
) -> SCC[T]:
    """
    Orders a graph's nodes as groups, whether or not it has a cycle.

    An acyclic graph sorts into one-node groups, and a cyclic one falls back to its
    strongly connected components unless ``strict`` is set.

    Args:

        graph: Each node mapped to the nodes that come after it.
        reverse: Whether to return the groups last first.
        strict: Whether a cycle raises instead of falling back to components.
        key: Orders the nodes that become ready together in an acyclic graph.

    Returns:

        The nodes in topological order, grouped by strongly connected component.

    Raises:

        CycleError: If ``strict`` is set and the graph has a cycle.

    Examples:

        # A --> B --> D --> E
        # ↓           ↑
        # + --> C ----+
        >>> graph = {"A": {"B", "C"}, "B": {"D"}, "C": {"D"}, "D": {"E"}}
        >>> topological_sort(graph)
        [('A',), ('C',), ('B',), ('D',), ('E',)]
        >>> topological_sort(graph, reverse=True)
        [('E',), ('D',), ('B',), ('C',), ('A',)]

        # A --> B <--> C --> D
        >>> graph = {"A": {"B"}, "B": {"C"}, "C": {"B", "D"}}
        >>> topological_sort(graph)
        [('A',), ('B', 'C'), ('D',)]

        #             6 ----+
        #             ↓     ↓
        # 0 --> 1 --> 2 --> 3
        #       ↓     ↑
        #       +---> 4 <-- 5
        >>> graph = {0: [1], 1: [2, 4], 4: [2], 2: [3], 5: [4], 6: [2, 3]}
        >>> topological_sort(graph)
        [(0,), (5,), (1,), (6,), (4,), (2,), (3,)]

    """
    try:
        nodes = native_topological_sort(graph, reverse=reverse, key=key)
    except CycleError:
        if strict:
            raise

        result = scc_sort(graph, reverse=reverse)
    else:
        result = [(node,) for node in nodes]

    return result


def cyclic_nodes[T: Hashable](graph: Graph[T], groups: SCC[T] | None = None) -> list[T]:
    """
    Collects the nodes that lie on a cycle.

    A node lies on a cycle when its strongly connected component has more than one
    node, or when it is its own successor.

    Args:

        graph: Each node mapped to the nodes that come after it.
        groups: The graph's ``topological_sort`` groups, when already computed.

    Returns:

        The cyclic nodes, in group order.

    Examples:

        >>> cyclic_nodes({"a": {"b"}, "b": {"a"}, "c": {"c"}, "d": set()})
        ['c', 'a', 'b']

    """
    _groups = topological_sort(graph) if groups is None else groups
    is_cyclic = lambda group: len(group) > 1 or group[0] in graph.get(group[0], ())
    return [node for group in _groups if is_cyclic(group) for node in group]


def edges_to_graph[T: Hashable](
    edges: Iterable[tuple[T, T]], *nodes: T
) -> dict[T, set[T]]:
    """
    Builds a successor graph from ``(source, target)`` edges.

    Args:

        edges: The directed edges.
        nodes: Nodes to include first, even when no edge touches them.

    Returns:

        Each node mapped to the nodes its edges point to.

    Examples:

        >>> edges_to_graph([("a", "b")], "c")
        {'c': set(), 'a': {'b'}, 'b': set()}

    """
    graph: dict[T, set[T]] = {node: set() for node in nodes}

    for source, target in edges:
        graph.setdefault(source, set()).add(target)
        graph.setdefault(target, set())

    return graph


def reverse_graph[T: Hashable](graph: AnyGraph[T]) -> dict[T, set[T]]:
    """
    Flips a graph's edges by mapping each node to the nodes that point to it.

    Args:

        graph: Each node mapped to the nodes that come after it.

    Returns:

        Each node, in ``graph`` order, mapped to the nodes that come before it.

    Examples:

        >>> reverse_graph({"a": {"b"}, "b": set()})
        {'a': set(), 'b': {'a'}}

    """
    reversed_: dict[T, set[T]] = {node: set() for node in graph}

    for source, targets in graph.items():
        for target in targets:
            reversed_.setdefault(target, set()).add(source)

    return reversed_


def leaves[T: Hashable](graph: AnyGraph[T]) -> list[T]:
    """
    Collects the nodes nothing comes after.

    Args:

        graph: Each node mapped to the nodes that come after it.

    Returns:

        The nodes with no successors, in ``graph`` order.

    Examples:

        >>> leaves({"a": {"b"}, "b": set(), "c": set()})
        ['b', 'c']

    """
    return [node for node, successors in graph.items() if not successors]


def gen_redundant_edges[T: Hashable](graph: AnyGraph[T]) -> Iterator[tuple[T, T]]:
    """
    Lists the edges of an acyclic graph that another path already implies.

    Args:

        graph: Each node mapped to the nodes that come after it.

    Yields:

        Each ``(source, target)`` edge that another path already implies.

    Examples:

        >>> next(gen_redundant_edges({"a": {"b", "c"}, "b": {"c"}}))
        ('a', 'c')

    """
    digraph = nx.DiGraph(map_values(sort_stably, graph))
    kept = nx.transitive_reduction(digraph).edges
    yield from sort_stably(set(digraph.edges).difference(kept))


def freeze_graph[T: Hashable](
    graph: AnyGraph[T], key: SortKey[T] = None
) -> FrozenGraph[T]:
    if key is None:
        items = graph.items()
    else:
        items = [(k, graph[k]) for k in sorted(graph, key=key)]

    return MappingProxyType({k: frozenset(v) for k, v in items})


def descendants[T: Hashable](
    source: T, graph: AnyGraph[T] = MappingProxyType({})
) -> frozenset[T]:
    digraph = nx.DiGraph(map_values(sort_stably, graph))

    if source not in digraph:
        raise KeyError(source)

    return frozenset(nx.descendants(digraph, source))
