"""
   Tarjan's algorithm and topological sorting implementation in Python

   by Paul Harrison

   Public domain, do with it as you will
"""

from graphlib import TopologicalSorter, CycleError
from collections import Counter
from operator import add
from functools import reduce


def _gen_result(graph, count, *ready):
    while ready:
        node = ready.pop()
        yield node

        for x in graph.get(node, []):
            assert count[x]
            count[x] -= 1

            if not count[x]:
                ready.append(x)


def _visit(node, *stack, low=None, **graph):
    low = low or {}

    if node not in low:
        num = len(low)
        low[node] = len(low)
        position = len(stack)
        stack.append(node)

        for x in graph.get(node, [node]):
            _visit(x, *stack, low=low, **graph)
            low[node] = min(low[node], low[x])

        if num == low[node]:
            component = tuple(stack[position:])
            del stack[position:]
            [low.update({x: len(graph)}) for x in component]
            return component


def _gen_node_component(components):
    for component in components:
        for node in component:
            yield (node, component)


def _gen_graph_value(value, node, node_component):
    for x in value:
        _value = node_component.get(x, (x,))

        if node_component[node] != _value:
            yield _value


def _gen_graph_component(graph, node_component, value_generator):
    for node in graph:
        value = list(value_generator(graph[node], node, node_component))
        yield (node_component[node], value)


def get_graph_component(graph):
    """Identify strongly connected components in a graph using
    Tarjan's algorithm.

    graph should be a dictionary mapping node names to an
    iterable of successor nodes.
    # A --> B <--> C --> D
    >>> graph = {"A": {"B"}, "B": {"C"}, "C": {"B", "D"}}
    >>> get_graph_component(graph)
    {('A',): [('C', 'B')], ('C', 'B'): [('D',)], ('D',): []}

    # 0 --> 1 --> 2 --> 3
    #       ↑     ↓
    #       +-----+
    >>> graph = {0: [1], 1: [2], 2: [1, 3], 3: [3]}
    >>> get_graph_component(graph)
    {(0,): [(2, 1)], (2, 1): [(3,)], (3,): []}
    """
    components = (_visit(g, **graph) for g in graph)
    node_component = dict(_gen_node_component(components))
    graph_component = {component: [] for component in components}
    updates = dict(_gen_graph_component(graph, node_component, _gen_graph_value))
    graph_component.update(updates)
    return graph_component


def ext_topological_sort(graph_component):
    """
    # A --> B <--> C --> D
    >>> graph = {"A": {"B"}, "B": {"C"}, "C": {"B", "D"}}
    >>> ext_topological_sort(get_graph_component(graph))
    [('A',), ('C', 'B'), ('D',)]

    # 0 --> 1 --> 2 --> 3
    #       ↑     ↓
    #       +-----+
    >>> graph = {0: [1], 1: [2], 2: [1, 3]}
    >>> ext_topological_sort(get_graph_component(graph))
    [(0,), (2, 1), (3,)]
    >>> native_topological_sort(graph)
    CycleError: ('nodes are in a cycle', [1, 2, 1])

    #             6 ----+
    #             ↓     ↓
    # 0 --> 1 --> 2 --> 3
    #       ↓     ↑
    #       +---> 4 <-- 5
    >>> graph = {0: [1], 1: [2, 4], 4: [2], 2: [3], 5: [4], 6: [2, 3]}
    >>> ext_topological_sort(get_graph_component(graph))
    [(6,), (5,), (0,), (1,), (4,), (2,), (3,)]
    """
    count = reduce(add, map(Counter, graph_component.values()))
    ready = [node for node in graph_component if not count[node]]
    return list(_gen_result(graph_component, count, *ready))


def native_topological_sort(graph, as_predecessors=False):
    """
    # A --> B --> D --> E
    # ↓           ↑
    # +---> C ----+
    >>> graph = {"E": {"D"}, "D": {"B", "C"}, "C": {"A"}, "B": {"A"}}
    >>> ts = TopologicalSorter(graph)
    >>> tuple(ts.static_order())
    ('A', 'C', 'B', 'D', 'E')

    # A --> B --> D --> E
    # ↓           ↑
    # +---> C ----+
    >>> graph = {"A": {"B", "C"}, "B": {"D"}, "C": {"D"}, "D": {"E"}}
    >>> tuple(reversed(tuple(TopologicalSorter(graph).static_order())))
    ('A', 'C', 'B', 'D', 'E')
    >>> native_topological_sort(graph)
    ('A', 'C', 'B', 'D', 'E')
    >>> ext_topological_sort(get_graph_component(graph))
    [('A',), ('C',), ('B',), ('D',), ('E',)]
    >>> native_topological_sort(get_graph_component(graph))
    [('A',), ('C',), ('B',), ('D',), ('E',)]
    """
    ts = TopologicalSorter(graph)
    static_order = tuple(ts.static_order())
    return static_order if as_predecessors else tuple(reversed(static_order))


def topological_sort(graph_or_component, **kwargs):
    try:
        result = native_topological_sort(graph_or_component, **kwargs)
    except CycleError:
        result = ext_topological_sort(graph_or_component)

    return result
