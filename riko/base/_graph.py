"""
Graph traversal and topological sorting helpers.

Derived from the public-domain implementation by Paul Harrison.
"""

from __future__ import annotations

from collections.abc import Collection, Hashable, Iterable, Iterator, Mapping, Sequence
from graphlib import CycleError, TopologicalSorter
from itertools import chain
from typing import TYPE_CHECKING

import networkx as nx

from ._funcutils import map_values
from ._iterutils import sort_stably

if TYPE_CHECKING:
    from riko.types._frozendict import FrozenDict, SortKey

type GraphNode[T: Hashable] = T
type GraphEdge[T] = tuple[GraphNode[T], GraphNode[T]]
type GraphNodes[T: Hashable] = Collection[GraphNode[T]]
type NodeList[T: Hashable] = list[GraphNode[T]]
type NodeSet[T: Hashable] = set[GraphNode[T]]
type FrozenNodeSet[T: Hashable] = frozenset[GraphNode[T]]
type SCC[T: Hashable] = list[tuple[GraphNode[T], ...]]
type Graph[T: Hashable] = Mapping[GraphNode[T], GraphNodes[T]]
type SetGraph[T: Hashable] = Mapping[GraphNode[T], NodeSet[T]]
type FrozenGraph[T: Hashable] = FrozenDict[T, FrozenNodeSet[T]]
type AnyGraph[T: Hashable] = Graph[T] | FrozenGraph[T]


def _build_digraph[T: Hashable](graph: Graph[T]) -> nx.DiGraph[T]:
    return nx.DiGraph(map_values(sort_stably, graph))


def scc_sort[T: Hashable](graph: Graph[T], reverse: bool | None = False) -> SCC[T]:
    """
    Identifies strongly connected components in a graph.

    ``graph`` maps node names to sequences of successor nodes.

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
    components = nx.strongly_connected_components(_build_digraph(graph))
    scc = map(sort_stably, components)
    return list(scc if reverse else reversed(list(scc)))


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
        static_order: Sequence[T] = []

        while ts.is_active():
            ready = sorted(ts.get_ready(), key=key, reverse=not reverse)
            static_order.extend(ready)
            ts.done(*ready)

    return static_order if reverse else static_order[::-1]


def topological_sort[T: Hashable](
    graph: Graph[T], *, reverse: bool = False, key: SortKey[T] = None
) -> SCC[T]:
    """
    Orders a graph's nodes as groups, whether or not it has a cycle.

    An acyclic graph sorts into one-node groups, and a cyclic one falls back to its
    strongly connected components.

    Args:

        graph: Each node mapped to the nodes that come after it.

    Kwargs:

        reverse: Whether to return the groups last first.
        key: Orders the nodes that become ready together in an acyclic graph.

    Returns:

        The nodes in topological order, grouped by strongly connected component.

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
        result = scc_sort(graph, reverse=reverse)
    else:
        result = [(node,) for node in nodes]

    return result


def cyclic_nodes[T: Hashable](
    graph: Graph[T], groups: SCC[T] | None = None
) -> NodeList[T]:
    """
    Collects the nodes that lie on a cycle.

    A node lies on a cycle when its strongly connected component has more than one
    node, or when it is its own successor.

    Args:

        graph: Each node mapped to the nodes that come after it.

    Kwargs:

        groups: The graph's ``topological_sort`` groups, when already computed.

    Returns:

        The cyclic nodes, in group order.

    Examples:

        >>> cyclic_nodes({"a": {"b"}, "b": {"a"}, "c": {"c"}, "d": set()})
        ['c', 'a', 'b']

    """
    _groups = topological_sort(graph) if groups is None else groups
    is_cyclic = lambda group: len(group) > 1 or group[0] in graph.get(group[0], ())
    return list(chain.from_iterable(filter(is_cyclic, _groups)))


def get_cycle[T: Hashable](graph: AnyGraph[T], source: GraphNode[T]) -> NodeList[T]:
    """
    Gets the first cycle reachable from a node.

    Args:

        graph: Each node mapped to the nodes that come after it.
        source: The node to start from.

    Returns:

        The cycle's nodes in edge order, starting where the path from ``source`` enters
        it, or an empty list when no cycle is reachable.

    Examples:

        >>> get_cycle({"a": {"b"}, "b": {"c"}, "c": {"b"}}, "a")
        ['b', 'c']
        >>> get_cycle({"a": {"b"}}, "a")
        []

    """
    try:
        edges = nx.find_cycle(_build_digraph(graph), source)
    except nx.NetworkXNoCycle:
        edges = []

    return [node for node, _ in edges]


def edges_to_graph[T: Hashable](
    edges: Iterable[tuple[T, T]], *nodes: GraphNode[T]
) -> SetGraph[T]:
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
    graph: SetGraph[T] = {node: set() for node in nodes}

    for source, target in edges:
        graph.setdefault(source, set()).add(target)
        graph.setdefault(target, set())

    return graph


def reverse_graph[T: Hashable](graph: AnyGraph[T]) -> SetGraph[T]:
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
    reversed_: SetGraph[T] = {node: set() for node in graph}

    for source, targets in graph.items():
        for target in targets:
            reversed_.setdefault(target, set()).add(source)

    return reversed_


def leaves[T: Hashable](graph: AnyGraph[T]) -> NodeList[T]:
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


def gen_redundant_edges[T: Hashable](graph: AnyGraph[T]) -> Iterator[GraphEdge[T]]:
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
    digraph = _build_digraph(graph)
    kept = nx.transitive_reduction(digraph).edges
    yield from sort_stably(set(digraph.edges).difference(kept))


def descendants[T: Hashable](
    graph: AnyGraph[T], source: GraphNode[T]
) -> FrozenNodeSet[T]:
    digraph = _build_digraph(graph)

    if source not in digraph:
        raise KeyError(source)

    return frozenset(nx.descendants(digraph, source))
