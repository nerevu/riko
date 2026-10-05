"""
Graph traversal and topological sorting helpers.

Derived from the public-domain implementation by Paul Harrison.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Hashable, Iterable, Mapping
from graphlib import CycleError, TopologicalSorter
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal, overload

import networkx as nx

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


def scc_sort[T: Hashable](graph: Graph[T], reverse: bool | None = False) -> SCC[T]:
    """
    Identifies strongly connected components in a graph using Tarjan's algorithm.

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
    digraph = nx.DiGraph({node: list(targets) for node, targets in graph.items()})
    component_group: Iterable[set[T]] = nx.strongly_connected_components(digraph)
    scc = [tuple(components) for components in component_group]
    return scc if reverse else scc[::-1]


def native_topological_sort[T: Hashable](
    graph: Graph[T],
    reverse: bool | None = False,
    key: Callable[[T], SupportsRichComparison] | None = None,
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
    ts = TopologicalSorter(graph)

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


@overload
def topological_sort[T: Hashable](  # noqa: E704
    graph: Graph[T], *, ssc: Literal[True]
) -> SCC[T]: ...
@overload  # noqa: E302
def topological_sort[T: Hashable](  # noqa: E704
    graph: Graph[T], *, strict: Literal[True]
) -> NodeList[T]: ...
@overload  # noqa: E302
def topological_sort[T: Hashable](  # noqa: E704
    graph: Graph[T], *, ssc: bool = ...
) -> NodeList[T] | SCC[T]: ...
@overload  # noqa: E302
def topological_sort[T: Hashable](  # noqa: E704
    graph: Graph[T], *, ssc: bool = ..., strict: bool = ...
) -> NodeList[T] | SCC[T]: ...
def topological_sort[T: Hashable](  # noqa: E302
    graph: Graph[T],
    *,
    reverse: bool | None = False,
    ssc: bool | None = False,
    strict: bool | None = False,
    key: Callable[[T], SupportsRichComparison] | None = None,
) -> NodeList[T] | SCC[T]:
    """
    Topological sort.

    Unless ``strict`` is set, a cyclic graph falls back to its strongly connected
    components in order.

    Raises:

        CycleError: If ``strict`` is set and the graph has a cycle.

    Examples:

        # A --> B --> C --> D
        >>> graph = {"A": {"B"}, "B": {"C"}, "C": {"D"}}
        >>> topological_sort(graph)
        ['A', 'B', 'C', 'D']

        # A --> B <--> C --> D
        >>> graph = {"A": {"B"}, "B": {"C"}, "C": {"B", "D"}}
        >>> topological_sort(graph)
        [('A',), ('B', 'C'), ('D',)]

        # A --> B --> D --> E
        # ↓           ↑
        # + --> C ----+
        >>> graph = {"A": {"B", "C"}, "B": {"D"}, "C": {"D"}, "D": {"E"}}
        >>> topological_sort(graph)
        ['A', 'C', 'B', 'D', 'E']
        >>> topological_sort(graph, reverse=True)
        ['E', 'D', 'B', 'C', 'A']

        # 0 --> 1 --> 2 --> 3
        #       ↑     ↓
        #       +-----+
        >>> graph = {0: [1], 1: [2], 2: [1, 3]}
        >>> topological_sort(graph)
        [(0,), (1, 2), (3,)]

        #             6 ----+
        #             ↓     ↓
        # 0 --> 1 --> 2 --> 3
        #       ↓     ↑
        #       +---> 4 <-- 5
        >>> graph = {0: [1], 1: [2, 4], 4: [2], 2: [3], 5: [4], 6: [2, 3]}
        >>> topological_sort(graph)
        [0, 5, 1, 6, 4, 2, 3]

    """
    if ssc:
        result = scc_sort(graph, reverse=reverse)
    else:
        try:
            result = native_topological_sort(graph, reverse=reverse, key=key)
        except CycleError:
            if strict:
                raise

            result = scc_sort(graph, reverse=reverse)

    return result


def topological_groups[T: Hashable](
    graph: Graph[T], reverse: bool | None = False
) -> SCC[T]:
    """
    Orders a graph's nodes as groups, whether or not it has a cycle.

    An acyclic graph sorts into one-node groups, and a cyclic one falls back to its
    strongly connected components.

    Args:

        graph: Each node mapped to the nodes that come after it.
        reverse: Whether to return the groups last first.

    Returns:

        The nodes in dependency order, grouped by strongly connected component.

    Examples:

        >>> topological_groups({"a": {"b"}, "b": set()})
        [('a',), ('b',)]
        >>> topological_groups({"a": {"b"}, "b": {"a"}, "c": set()})
        [('c',), ('b', 'a')]

    """
    try:
        nodes = native_topological_sort(graph, reverse=reverse)
    except CycleError:
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
        groups: The graph's ``topological_groups``, when already computed.

    Returns:

        The cyclic nodes, in group order.

    Examples:

        >>> cyclic_nodes({"a": {"b"}, "b": {"a"}, "c": {"c"}, "d": set()})
        ['c', 'b', 'a']

    """
    _groups = topological_groups(graph) if groups is None else groups
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
    Flips a graphs edges by mapping each node to the nodes that point to it.

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


def freeze_graph[T: Hashable](
    graph: AnyGraph[T], key: Callable[[T], SupportsRichComparison] | None = None
) -> FrozenGraph[T]:
    if key is None:
        items = graph.items()
    else:
        items = [(k, graph[k]) for k in sorted(graph, key=key)]

    return MappingProxyType({k: frozenset(v) for k, v in items})


def descendants[T: Hashable](
    source: T, graph: AnyGraph[T] = MappingProxyType({})
) -> frozenset[T]:
    known = set(graph)

    for targets in graph.values():
        known.update(targets)

    if source not in known:
        raise KeyError(source)

    seen: set[T] = set()
    stack = list(graph.get(source, ()))

    while stack:
        if (node := stack.pop()) == source or node in seen:
            continue

        seen.add(node)
        stack.extend(graph.get(node, ()))

    return frozenset(seen)
