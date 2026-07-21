# Agents

The main opportunity is to share the graph definition and planning layer, not the execution layer.

A pipeline DAG and an agent DAG have the same structural operations:

nodes
directed edges
roots
sinks
predecessors
successors
fan-in
fan-out
cycle detection
topological ordering
subgraphs
ancestors/descendants

But they have different execution semantics:

Pipeline DAG    Agent DAG
Node is a Riko module invocation    Node is a long-lived agent
Edge carries a lazy stream  Edge pushes discrete events
One pipeline run    Many independent agent runs
Usually finite  Long-lived
Runs in topological dependency order    Agents run concurrently
Fan-in combines streams during one run  Fan-in means several publishers share a receiver
Failure normally stops the pipeline Failure should affect one delivery or agent

So the correct rule is:

Reuse graph construction, validation, querying, serialization, and visualization. Keep pipeline and agent executors separate.

Existing Riko code that can be reused

Riko already has:

utils.gen_graph() to convert wires into source-target pairs;
utils.gen_parented_graph() to remove orphan nodes;
topological_sort() for DAG ordering;
NetworkX-based strongly connected component detection;
parse_pipe_def() to normalize a serialized definition into modules, wires, and a graph;
_gen_steps() to bind graph nodes to executable module functions.

The first four should become generic DAG infrastructure. The last two remain pipeline-specific.

Recommended extraction

Create:

riko/
  graph.py

or:

riko/
  graph/
    __init__.py
    dag.py

The shared abstraction should be small.

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Generic, TypeVar

import networkx as nx


NodeT = TypeVar("NodeT", bound=str)


@dataclass(slots=True)
class Dag(Generic[NodeT]):
    graph: nx.DiGraph

    @classmethod
    def from_edges(
        cls,
        nodes: Iterable[NodeT],
        edges: Iterable[tuple[NodeT, NodeT]],
    ) -> Dag[NodeT]:
        graph = nx.DiGraph()
        graph.add_nodes_from(nodes)
        graph.add_edges_from(edges)

        dag = cls(graph)
        dag.validate()
        return dag

    def validate(self) -> None:
        if self_loops := tuple(nx.selfloop_edges(self.graph)):
            raise ValueError(f"Self-referencing edges: {self_loops}")

        if not nx.is_directed_acyclic_graph(self.graph):
            cycle = nx.find_cycle(self.graph)
            raise ValueError(f"Graph contains a cycle: {cycle}")

    @property
    def nodes(self) -> tuple[NodeT, ...]:
        return tuple(self.graph.nodes)

    @property
    def edges(self) -> tuple[tuple[NodeT, NodeT], ...]:
        return tuple(self.graph.edges)

    @property
    def roots(self) -> tuple[NodeT, ...]:
        return tuple(
            node
            for node, degree in self.graph.in_degree()
            if degree == 0
        )

    @property
    def sinks(self) -> tuple[NodeT, ...]:
        return tuple(
            node
            for node, degree in self.graph.out_degree()
            if degree == 0
        )

    @property
    def order(self) -> tuple[NodeT, ...]:
        return tuple(nx.topological_sort(self.graph))

    def predecessors(self, node: NodeT) -> tuple[NodeT, ...]:
        return tuple(self.graph.predecessors(node))

    def successors(self, node: NodeT) -> tuple[NodeT, ...]:
        return tuple(self.graph.successors(node))

    def ancestors(self, node: NodeT) -> frozenset[NodeT]:
        return frozenset(nx.ancestors(self.graph, node))

    def descendants(self, node: NodeT) -> frozenset[NodeT]:
        return frozenset(nx.descendants(self.graph, node))

    def subgraph(self, nodes: Iterable[NodeT]) -> Dag[NodeT]:
        graph = self.graph.subgraph(nodes).copy()
        return type(self)(graph)

This becomes the common object used by both systems.

Pipeline reuse

Currently, parse_pipe_def() stores a plain dictionary graph generated from wires, and build_pipeline() calls topological_sort() before generating executable steps.

Change the parsed representation from:

class ParsedPipeDef(TypedDict):
    name: str
    modules: dict[str, PipeModule]
    embed: dict[str, PipeModule]
    graph: dict[str, str | list[str]]
    wires: dict[str, Wire]

to conceptually:

@dataclass(slots=True)
class ParsedPipeline:
    name: str
    modules: dict[str, PipeModule]
    embedded: dict[str, PipeModule]
    dag: Dag[str]
    wires: dict[str, Wire]

The pipeline parser creates the shared DAG:

def parse_pipe_def(
    pipe_def: PipeDef,
    pipe_name: str = "anonymous",
) -> ParsedPipeline:
    modules = dict(utils.gen_modules(pipe_def))
    embedded = dict(utils.gen_modules(pipe_def, embedded=True))
    modules.update(embedded)

    edges = tuple(utils.gen_graph(pipe_def))

    dag = Dag.from_edges(
        nodes=modules,
        edges=edges,
    )

    return ParsedPipeline(
        name=utils.pythonise(pipe_name),
        modules=modules,
        embedded=embedded,
        dag=dag,
        wires=dict(utils.gen_wires(pipe_def)),
    )

Then:

module_ids = parsed_pipe_def.dag.order

instead of:

module_ids = topological_sort(parsed_pipe_def["graph"])
What remains pipeline-specific

These should not move into Dag:

_get_pyarg()
_gen_pykwargs()
_gen_steps()
build_pipeline()
stringify_pipe()

They know about:

Riko module imports;
conf;
embedded loop modules;
_INPUT and _OUTPUT;
forever;
stream iterators;
generated Python source.

That is execution and compilation behavior, not graph behavior.

Agent reuse

The agent network stores its agents as NetworkX node attributes:

network.graph.add_node(
    name,
    agent=agent,
)

and connections as edges:

network.graph.add_edge(source, receiver)

It can instead wrap the same Dag:

@dataclass(slots=True)
class AgentNetwork:
    dag: Dag[str]
    agents: dict[str, Agent]

Construction:

network = AgentNetwork.from_definitions(
    agents={
        "normalize": normalize_agent,
        "enrich": enrich_agent,
        "collect": collect_agent,
    },
    links=[
        ("normalize", "enrich"),
        ("enrich", "collect"),
    ],
)

Implementation:

@classmethod
def from_definitions(
    cls,
    agents: dict[str, Agent],
    links: Iterable[tuple[str, str]],
) -> AgentNetwork:
    return cls(
        agents=agents,
        dag=Dag.from_edges(agents, links),
    )

Publishing becomes:

def publish(self, source: str, item: Item) -> None:
    for receiver in self.dag.successors(source):
        send(receiver, dict(item))

Startup becomes:

def start(self) -> None:
    for name in reversed(self.dag.order):
        self.agents[name].start()

Shutdown becomes:

def stop(self) -> None:
    for name in self.dag.order:
        self.agents[name].stop()

Sources and receivers use the same graph API:

network.dag.predecessors("collect")
network.dag.successors("normalize")
network.dag.roots
network.dag.sinks
Shared graph definition format

The pipeline format already represents nodes and wires separately:

{
  "modules": [
    {"id": "normalize", "type": "regex", "conf": {}},
    {"id": "collect", "type": "sort", "conf": {}}
  ],
  "wires": [
    {
      "id": "wire-1",
      "src": {"moduleid": "normalize", "id": "_OUTPUT"},
      "tgt": {"moduleid": "collect", "id": "_INPUT"}
    }
  ]
}

Agent definitions can reuse the same broad shape:

{
  "agents": [
    {
      "id": "incoming",
      "pipeline": "incoming_pipeline"
    },
    {
      "id": "normalize",
      "pipeline": "normalize_pipeline"
    }
  ],
  "links": [
    {
      "id": "link-1",
      "src": {"agentid": "incoming"},
      "tgt": {"agentid": "normalize"}
    }
  ]
}

A more reusable generic shape would be:

{
  "nodes": [
    {
      "id": "incoming",
      "kind": "agent",
      "config": {}
    },
    {
      "id": "normalize",
      "kind": "agent",
      "config": {}
    }
  ],
  "edges": [
    {
      "id": "edge-1",
      "source": "incoming",
      "target": "normalize"
    }
  ]
}

Then pipeline and agent loaders interpret node config differently.

However, changing the existing Yahoo Pipes-compatible format solely for symmetry is probably not worthwhile. Share the internal Dag, not necessarily the external JSON schema.

Shared validation

Both DAG types can use the same checks.

Structural validation
dag.validate()

Checks:

duplicate node IDs;
edges referencing missing nodes;
self-loops;
cycles;
isolated nodes;
no roots;
no sinks.

Some checks should be configurable:

@dataclass(frozen=True, slots=True)
class DagPolicy:
    allow_isolated: bool = False
    require_root: bool = True
    require_sink: bool = True
    allow_cycles: bool = False

Pipeline policy:

PIPELINE_POLICY = DagPolicy(
    allow_isolated=False,
    require_root=True,
    require_sink=True,
    allow_cycles=False,
)

POC agent policy:

AGENT_POLICY = DagPolicy(
    allow_isolated=True,
    require_root=False,
    require_sink=False,
    allow_cycles=False,
)

An isolated agent may be valid because it can receive an external push and have a side effect without emitting anything.

Domain validation remains separate

Pipeline-specific:

validate_pipeline_nodes(parsed)
validate_pipeline_ports(parsed)
validate_embedded_modules(parsed)

Agent-specific:

validate_agent_definitions(network)
validate_registered_receivers(network)
validate_agent_modes(network)
Shared graph queries

These become useful to both systems:

dag.roots
dag.sinks
dag.predecessors(node)
dag.successors(node)
dag.ancestors(node)
dag.descendants(node)
dag.order

Examples:

# Pipeline: which earlier modules affect this output?
pipeline.dag.ancestors("output")

# Agent network: which agents may eventually receive this event?
network.dag.descendants("webhook")

# Pipeline: which modules have no inputs?
pipeline.dag.roots

# Agent network: which agents have no downstream receivers?
network.dag.sinks
Shared visualization

This is one of the best reuse opportunities.

A single graph renderer can display either:

def to_mermaid(
    dag: Dag[str],
    labels: Mapping[str, str] | None = None,
) -> str:
    lines = ["flowchart LR"]

    for source, target in dag.edges:
        source_label = labels.get(source, source) if labels else source
        target_label = labels.get(target, target) if labels else target

        lines.append(
            f'    {source}["{source_label}"] --> '
            f'{target}["{target_label}"]'
        )

    return "\n".join(lines)

Pipeline:

fetch --> regex --> filter --> sort

Agent network:

webhook --> normalize --> notify
                      --> audit

The same renderer can support:

Mermaid;
DOT/Graphviz;
NetworkX node-link JSON;
adjacency lists;
terminal summaries.
Shared graph transformations

Both can benefit from common graph transformations.

Select a branch
dag.subgraph(
    dag.ancestors("target") | {"target"}
)

Pipeline use: execute only the nodes needed for one output.

Agent use: inspect or start only the agents upstream of a target.

Impact analysis
affected = dag.descendants(changed_node)

Pipeline use: determine which steps are affected by a module configuration change.

Agent use: determine which downstream agents may be affected by changing an agent.

Pruning
def prune_to_sinks(
    dag: Dag[str],
    sinks: Iterable[str],
) -> Dag[str]:
    selected = set(sinks)

    for sink in sinks:
        selected.update(dag.ancestors(sink))

    return dag.subgraph(selected)
Composition

A pipeline or agent network could be inserted into a larger graph:

def compose(*dags: Dag[str]) -> Dag[str]:
    graph = nx.compose_all([dag.graph for dag in dags])
    result = Dag(graph)
    result.validate()
    return result

This could support subpipelines and agent scenario groups.

Shared testing

A generic DAG test suite could run against both pipeline and agent graph builders:

@pytest.mark.parametrize(
    "builder",
    [
        build_pipeline_dag,
        build_agent_dag,
    ],
)
def test_rejects_missing_node(builder):
    ...


@pytest.mark.parametrize(
    "builder",
    [
        build_pipeline_dag,
        build_agent_dag,
    ],
)
def test_detects_cycles(builder):
    ...


@pytest.mark.parametrize(
    "builder",
    [
        build_pipeline_dag,
        build_agent_dag,
    ],
)
def test_finds_roots_and_sinks(builder):
    ...

Property-based tests could also establish:

set(dag.order) == set(dag.nodes)

and:

position = {
    node: index
    for index, node in enumerate(dag.order)
}

assert all(
    position[source] < position[target]
    for source, target in dag.edges
)
What should not be shared

Avoid creating one generic “DAG executor.”

It would likely acquire flags such as:

execute(
    mode="pipeline" | "agent",
    streaming=True,
    concurrent=False,
    persistent=False,
    push=False,
    ...
)

That abstraction would obscure important differences.

Keep:

Dag
├── PipelineCompiler / PipelineRunner
└── AgentNetwork / AgentWorker

Not:

UniversalDagExecutor

The shared boundary should look like:

class Pipeline:
    dag: Dag[str]

    def run(self, source: Stream) -> Stream:
        ...


class AgentNetwork:
    dag: Dag[str]

    def start(self) -> None:
        ...

    def push(self, agent: str, item: Item) -> None:
        ...
Best concrete refactor

I would make these changes:

riko/topsort.py
    ↓ replace or reduce

riko/graph.py
    Dag
    DagPolicy
    GraphValidationError
    CycleError
    to_mermaid()

Then:

riko/compile.py
    parse_pipe_def() creates Dag
    build_pipeline() reads dag.order

riko/agents/network.py
    AgentNetwork stores Dag
    publish() reads dag.successors()
    start()/stop() read dag.order

Existing helpers can be progressively moved:

Existing code   Destination
utils.gen_graph()   Pipeline-specific adapter into Dag.from_edges()
utils.gen_parented_graph()  Probably remove; use explicit isolated-node policy
topsort.scc_sort()  graph.py, only if cycles remain supported
topsort.native_topological_sort()   Replace with nx.topological_sort()
topsort.topological_sort()  Replace with Dag.order
_gen_steps()    Keep in compile.py
Agent connect() Delegate to Dag.add_edge()
Agent routing   Delegate lookup to Dag.successors()
Bottom line

The most valuable shared pieces are:

one internal directed-graph representation;
one validation framework;
one set of root/sink/predecessor/successor queries;
one topological planner;
one serialization and visualization layer;
one graph test suite;
common subgraph, impact-analysis, and composition utilities.

The executors should remain separate because a pipeline DAG describes data dependencies within one computation, while an agent DAG describes event routing between independent computations.

