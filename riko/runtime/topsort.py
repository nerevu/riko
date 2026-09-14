"""
Tarjan's algorithm and topological sorting implementation in Python

by Paul Harrison

Public domain, do with it as you will
"""

from collections.abc import Iterable
from graphlib import CycleError, TopologicalSorter
from typing import Literal, overload

import networkx as nx

from riko.types.modules import SCC, Graph, NodeList


def scc_sort[T: str | int](graph: Graph[T], reverse: bool | None = False) -> SCC[T]:
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


def native_topological_sort[T: str | int](
    graph: Graph[T], reverse: bool | None = False
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
    static_order = list(ts.static_order())
    return static_order if reverse else static_order[::-1]


@overload
def topological_sort[T: str | int](  # noqa: E704
    graph: Graph[T], *, ssc: Literal[True]
) -> SCC[T]: ...
@overload  # noqa: E302
def topological_sort[T: str | int](  # noqa: E704
    graph: Graph[T], *, strict: Literal[True]
) -> NodeList[T]: ...
@overload  # noqa: E302
def topological_sort[T: str | int](  # noqa: E704
    graph: Graph[T], *, ssc: bool = ...
) -> NodeList[T] | SCC[T]: ...
@overload  # noqa: E302
def topological_sort[T: str | int](  # noqa: E704
    graph: Graph[T], *, ssc: bool = ..., strict: bool = ...
) -> NodeList[T] | SCC[T]: ...
def topological_sort[T: str | int](  # noqa: E302
    graph: Graph[T],
    *,
    reverse: bool | None = False,
    ssc: bool | None = False,
    strict: bool | None = False,
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
            result = native_topological_sort(graph, reverse=reverse)
        except CycleError:
            if strict:
                raise

            result = scc_sort(graph, reverse=reverse)

    return result
