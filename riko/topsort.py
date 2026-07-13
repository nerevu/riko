"""
Tarjan's algorithm and topological sorting implementation in Python

by Paul Harrison

Public domain, do with it as you will
"""

from collections.abc import Iterable, Mapping, Sequence
from graphlib import CycleError, TopologicalSorter
from typing import (
    TypeVar,
)

import networkx as nx

T = TypeVar("T", bound=str | int)

# After upgrading to Python 3.12, we can use the new TypeAlias syntax and remove the
# redundant type constraints:
# https://docs.python.org/3/reference/compound_stmts.html#generic-type-aliases
# type Nodes[T: (str | int)] = Sequence[T]
# type Graph[T: (str | int)] = Mapping[T, Sequence[T]]
# type NodeList[T: (str | int)] = list[T]


def scc_sort(graph: Mapping[T, Sequence[T]], reverse=False) -> list[tuple[T, ...]]:
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
    G = nx.DiGraph(graph)
    components: Iterable[set[T]] = nx.strongly_connected_components(G)
    order = [tuple(c) for c in components]
    return order if reverse else order[::-1]


def native_topological_sort(graph: Mapping[T, Sequence[T]], reverse=False) -> list[T]:
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


def topological_sort(
    graph: Mapping[T, Sequence[T]], **kwargs
) -> list[T] | list[tuple[T, ...]]:
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
    try:
        result = native_topological_sort(graph, **kwargs)
    except CycleError:
        result = scc_sort(graph, **kwargs)

    return result
