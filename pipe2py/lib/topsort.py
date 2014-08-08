"""
   Tarjan's algorithm and topological sorting implementation in Python

   by Paul Harrison

   Public domain, do with it as you will
"""


def _gen_result(graph, ready, count):
    while ready:
        node = ready.pop(-1)
        yield node

        for x in graph[node]:
            count.update({x: count[x] - 1})
            ready.append(x) if count[x] == 0 else None


def _visit(node, graph, low=None, stack=None):
    low = low or {}
    stack = stack or []

    if node not in low:
        num = len(low)
        low[node] = len(low)
        position = len(stack)
        stack.append(node)

        for x in graph[node]:
            _visit(x, graph, low, stack)
            low[node] = min(low[node], low[x])

        if num == low[node]:
            component = tuple(stack[position:])
            del stack[position:]
            map(lambda x: low.update({x: len(graph)}), component)
            return component


def _gen_node_component(components):
    for component in components:
        for node in component:
            yield (node, component)


def _gen_graph_value(value, node, node_component):
    for x in value:
        if node_component[node] != node_component[x]:
            yield node_component[x]


def _gen_graph_component(graph, node_component, value_generator):
    for node in graph:
        value = list(value_generator(graph[node], node, node_component))
        yield (node_component[node], value)


def get_graph_component(graph):
    """ Identify strongly connected components in a graph using
        Tarjan's algorithm.

        graph should be a dictionary mapping node names to
        lists of successor nodes.
    """
    components = map(lambda x: _visit(x, graph), graph)
    node_component = dict(_gen_node_component(components))
    graph_component = {component: [] for component in components}
    graph_component.update(
        dict(_gen_graph_component(graph, node_component, _gen_graph_value)))

    return graph_component


def topological_sort(graph):
    count = {node: 0 for node in graph}
    set_count = lambda x: count.update({x: count[x] + 1})
    map(lambda item: map(set_count, item[1]), graph.items())
    ready = [node for node in graph if count[node] == 0]
    return list(_gen_result(graph, ready, count))


if __name__ == '__main__':
    graph = {0: [1], 1: [2], 2: [1, 3], 3: [3]}
    graph_component = get_graph_component(graph)
    print topological_sort(graph_component)
