"""
Tarjan's algorithm and topological sorting implementation in Python

by Paul Harrison

Public domain, do with it as you will
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Hashable, Iterable, Mapping
from graphlib import CycleError, TopologicalSorter
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal, overload

import networkx as nx

from riko.base.exceptions import InvalidArchitectureError

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
    Identify strongly connected components in a graph using Tarjan's algorithm.

    graph should be a dictionary mapping node names to an
    sequence of successor nodes.

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
    digraph = nx.DiGraph(graph)
    component_group: Iterable[set[T]] = nx.strongly_connected_components(digraph)
    scc = [tuple(components) for components in component_group]
    return scc if reverse else scc[::-1]


def native_topological_sort[T: Hashable](
    graph: Graph[T],
    reverse: bool | None = False,
    key: Callable[[T], SupportsRichComparison] | None = None,
) -> NodeList[T]:
    """
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
    graph: Graph[T], *, ssc: Literal[True], name: str | None = ...
) -> SCC[T]: ...
@overload  # noqa: E302
def topological_sort[T: Hashable](  # noqa: E704
    graph: Graph[T], *, strict: Literal[True], name: str | None = ...
) -> NodeList[T]: ...
@overload  # noqa: E302
def topological_sort[T: Hashable](  # noqa: E704
    graph: Graph[T], *, ssc: bool = ..., name: str | None = ...
) -> NodeList[T] | SCC[T]: ...
@overload  # noqa: E302
def topological_sort[T: Hashable](  # noqa: E704
    graph: Graph[T], *, ssc: bool = ..., strict: bool = ..., name: str | None = ...
) -> NodeList[T] | SCC[T]: ...
def topological_sort[T: Hashable](  # noqa: E302
    graph: Graph[T],
    *,
    reverse: bool | None = False,
    ssc: bool | None = False,
    strict: bool | None = False,
    key: Callable[[T], SupportsRichComparison] | None = None,
    name: str | None = None,
) -> NodeList[T] | SCC[T]:
    """
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
        except CycleError as e:
            if strict:
                graph_name = f" '{name}'" if name else ""
                msg = f"cyclic layer graph{graph_name}: {e}"
                raise InvalidArchitectureError(msg) from e

            result = scc_sort(graph, reverse=reverse)

    return result


def edges_to_graph[T](edges: Iterable[tuple[T, T]]) -> Graph[T]:
    nodes: set[T] = {node for edge in edges for node in edge}
    graph: dict[T, set[T]] = {node: set() for node in nodes}

    for source, target in edges:
        graph[source].add(target)

    return graph


def freeze_graph[T: Hashable](
    graph: AnyGraph[T], key: Callable[[T], SupportsRichComparison] | None = None
) -> FrozenGraph[T]:
    if key is None:
        items = graph.items()
    else:
        items = [(k, graph[k]) for k in sorted(graph, key=key)]

    return MappingProxyType({k: frozenset(v) for k, v in items})


def descendants[T: Hashable](source: T, graph: AnyGraph[T]) -> frozenset[T]:
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
