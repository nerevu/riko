# Agent scenarios gameplan

## 1. Mission

Promote the useful configuration and evaluation patterns from the Langly and AutoGen
inspiration into a deterministic, policy-aware scenario layer that reuses Riko's capability
catalog and ordinary `Pipeline` architecture.

This plan extends:

* `_docs/gameplans/agents.md` for Pipeline/loop/pubsub agent execution semantics;
* `_docs/gameplans/ai-inference.md` for model invocation;
* `_docs/gameplans/mcp.md` for tool/capability policy;
* `_docs/gameplans/connectors.md` for external resources.

The goal is not to make Riko an agent framework clone. The goal is to make agent-assisted
Riko workflows serializable, inspectable, testable, and safe without introducing a second
agent graph or executor.

## 2. Inspiration integrated by this plan

Langly and the earlier AutoGen CLI both demonstrate useful patterns:

* JSON-defined reusable scenarios;
* per-agent instructions and roles;
* multiple model providers;
* semantic model-selection tiers such as cost/balanced/performance;
* supervised versus peer/team routing;
* explicit tools and OpenAPI-derived functions;
* retrieval over configured document collections;
* repeatable evaluation cases and machine-readable results;
* generated/reusable agent profiles.

They also demonstrate patterns Riko should **not** adopt directly:

* unrestricted dynamic tool definition from arbitrary remote OpenAPI documents;
* arbitrary local Python execution with no sandbox/policy boundary;
* tool permissions encoded only in prompt text;
* hard-coded provider model names as durable workflow semantics;
* one universal agent executor that obscures ordinary Pipeline semantics;
* a second agent-only DAG/schema/runtime parallel to `Pipeline`.

## 3. Architectural invariant

Agent scenarios are configuration that compiles to the same Pipeline execution model used by
ordinary Riko workflows:

```text
shared contracts
    capability catalog
    immutable Pipeline DAG
    publish / subscribe / split topology
    loop iterative state
    Context / Resource definitions
    FeedState / StateStore
    artifact references
    credential references
    event schema

scenario layer
    reviewed agent/model/tool/retrieval/policy configuration
    lowering into ordinary Pipeline nodes/branches/loop scopes
    evaluation fixtures and run records
```

There is no separate `AgentGraph`, `AgentNetwork`, or agent executor. An agent step may invoke
a registered model/provider/tool capability, and iterative reasoning/tool use is represented by
the common `loop` state model while the underlying Pipeline DAG remains acyclic.

A scenario does not turn every Riko module into an unconstrained LLM tool automatically.

## 4. AgentScenario

Define a versioned serialized scenario:

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class AgentScenario:
    schema_version: str
    id: str
    task: str | None
    agents: tuple[AgentSpec, ...]
    links: tuple[AgentLink, ...]
    tools: tuple[str, ...]
    retrieval: tuple[RetrievalSpec, ...]
    policy: str | None
    evaluation: EvaluationSpec | None
```

Scenario files are data and may be stored, diffed, reviewed, and executed repeatedly. The
scenario compiler resolves this data into ordinary Pipeline topology and registered capability
references before execution.

Do not serialize API keys, prompt-time access tokens, arbitrary Python callables, or raw
credential material.

## 5. AgentSpec

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class AgentSpec:
    id: str
    role: str
    instructions: str
    model_policy: str
    tools: tuple[str, ...] = ()
    retrieval: tuple[str, ...] = ()
    temperature: float | None = None
```

`role` is semantic; implementation-specific classes such as `AssistantAgent` or
`RetrieveUserProxyAgent` are adapter details.

An `AgentSpec` is configuration for one or more ordinary Pipeline nodes/loop steps; it is not a
runtime actor object with an independently owned event loop or checkpoint store.

## 6. Semantic model policy

Langly's cost/balanced/performance abstraction is more durable than persisting specific
model names in every scenario.

Example:

```python
ModelPolicy(
    id="balanced",
    objective="balanced",
    requirements={
        "tool_calling": True,
        "context_tokens": 32_000,
    },
)
```

A provider adapter resolves that policy to an available model at run time and records the
resolved provider/model/version in execution metadata.

Possible objectives:

```text
cost
balanced
quality
latency
local
```

Hard model pins remain supported when reproducibility requires them, but should be
explicitly distinguished from semantic policies.

## 7. Tool references

Scenario tools are capability IDs:

```json
{
  "tools": [
    "calculator",
    "github.issue.read",
    "microsoft.user.lookup"
  ]
}
```

The capability catalog ([mcp.md § 6–§ 8](mcp.md)) supplies each tool's input/output schema,
description, effect/risk classification, credential requirements, rate/concurrency metadata,
and policy tags. Scenarios reference capability IDs and add no tool metadata of their own.

No scenario may reference an import path and cause arbitrary callable loading from serialized
configuration.

Tool/provider calls remain ordinary Pipeline side effects and therefore inherit the common
identity/idempotency, retry, resource, and checkpoint rules from `execution-semantics.md`.

## 8. OpenAPI-derived tools

OpenAPI-derived tools are discovered, normalized, fingerprinted, policy-gated, and versioned
through the shared MCP/OpenAPI capability machinery owned by
[mcp.md § 11 (discovery) and § 13 (security policy)](mcp.md). Scenarios do not restate those
rules.

The scenario-specific rule: an agent may *propose* adding a discovered capability, but it
cannot grant itself permission to execute it. Discovery never self-authorizes.

## 9. Tool caller/executor separation

Earlier agent scenarios encode which agent may call a function and which executes it. Keep
that useful distinction in policy rather than framework-specific runtime actor fields:

```python
ToolGrant(
    capability="browser.search",
    caller="researcher",
    executor="tool-runtime",
)
```

This enables:

* least privilege per agent;
* central execution/audit;
* separate credentials from model context;
* safe remote or sandbox execution.

`executor` identifies the authorized capability/runtime service; it does not imply a second
agent executor. Actual execution still occurs through the ordinary Pipeline/provider/tool
execution path.

## 10. Code execution

Do not inherit AutoGen's unsandboxed local code execution pattern.

If a code-execution capability exists it must declare:

```text
runtime/sandbox
filesystem policy
network policy
CPU/time/memory limits
artifact input/output policy
package policy
side-effect classification
```

Default agent scenarios have no arbitrary code-execution tool.

A deterministic Riko callable pipe remains preferable when the operation is known in advance.

## 11. Agent team topology

Scenarios may describe interaction policy such as:

```text
supervised
    one supervisor/policy step selects the next eligible agent

static DAG
    values/events follow declared Pipeline branches

peer/unsupervised
    an agent may select among explicitly granted recipients/capabilities
```

These are scenario-level routing semantics that lower to the common Pipeline topology:

```text
ordinary data edge
publish / subscribe branch
split / route branch
loop iteration
```

The Pipeline DAG remains acyclic. Repeated agent turns are represented by `loop`, not a cycle in
a separate agent graph.

For peer routing, the allowed recipient/capability set is explicit policy. "Unsupervised" does
not mean arbitrary network creation at run time.

Scenario validation may use the same Pipeline DAG query/visualization infrastructure after
lowering; it does not maintain a parallel shared-DAG object whose semantics can drift from
Pipeline execution.

## 12. RetrievalSpec

RAG configuration is an external-resource capability, not hidden initialization code:

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class RetrievalSpec:
    id: str
    source: str
    index: str
    search: Literal["similarity", "mmr", "threshold"]
    result_count: int
    filters: Mapping[str, JsonValue]
```

The source may refer to local/library artifacts, connector resources, or an external vector
store through a registered adapter.

Document ingestion records:

```text
artifact/document ID
content fingerprint
chunking strategy
embedding model/version
index namespace
```

so results are reproducible enough to diagnose changes.

Live retrievers/vector-store clients are declared resources and remain execution-owned rather
than being stored as mutable runtime values on public `Context`.

## 13. Retrieval policy

Retrieval permissions are distinct from tool permissions. A scenario must not gain access
to sensitive documents merely because it can call a general retriever.

Policy can limit:

```text
allowed source namespaces
data sensitivity
maximum retrieved bytes/chunks
metadata fields returned to model
cross-tenant access
```

Retrieved text is untrusted model input and cannot redefine tool policy.

## 14. Agent profile library

Reusable roles can be stored as reviewed profiles:

```python
AgentProfile(
    id="researcher",
    instructions="...",
    recommended_model_policy="balanced",
    allowed_tool_tags=("read", "research"),
)
```

Generated profiles may be proposed by a model but must be materialized as ordinary data and
reviewed/versioned before production use.

A profile library is convenience configuration, not an autonomous authority system.

## 15. Scenario parameters

Avoid copying entire scenarios for small input changes. Permit declared parameters:

```json
{
  "parameters": {
    "company": {"type": "string"},
    "max_results": {"type": "integer", "default": 10}
  }
}
```

Substitution is schema-validated and restricted to declared fields. It must not support
arbitrary expression/code evaluation.

## 16. EvaluationSpec

Evaluation is first-class scenario data:

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class EvaluationSpec:
    cases: tuple[EvaluationCase, ...]
    evaluators: tuple[EvaluatorSpec, ...]
```

Initial deterministic evaluators may include:

```text
exact
contains
regex
json_schema
numeric_tolerance
set_equivalence
```

Model-judged evaluation is allowed only as an explicitly non-deterministic evaluator with
its own pinned/recorded model policy and rubric.

Avoid a vague `fuzzy` score without documented algorithm/threshold.

## 17. Tool-call evaluation

For agent systems, final answer correctness alone is insufficient. Evaluation cases may
assert:

```text
required capability invoked
forbidden capability not invoked
maximum tool calls
specific side effect remained dry-run
expected artifact produced
expected citations/provenance present
policy denial occurred
```

This makes safety and workflow behavior regression-testable.

## 18. Golden scenario fixtures

Ship small deterministic scenarios for:

```text
calculator/read-only tool
pipeline invocation
retrieval over fixed fixture documents
supervised two-agent routing
policy-denied write
OpenAPI capability from pinned local schema
structured JSON output
bounded loop/tool iteration with checkpoint fixture
```

Network-dependent/provider-dependent evaluations belong to optional integration suites.

## 19. Run record

Every scenario execution records:

```text
scenario ID + fingerprint
resolved scenario parameters
resolved Pipeline/stateful-owner identity
agent/profile versions
model policy + resolved model
capability/tool versions
retrieval index fingerprints
turn/tool-call events
checkpoint/state references when applicable
policy decisions
artifacts
usage/cost metrics when available
final status
```

This record is the basis for evaluation, replay diagnostics, and cost analysis. It does not
become a second recovery/checkpoint system; recovery uses the common `StateStore` contract.

## 20. Cost and usage

Provider adapters may normalize:

```text
input/output tokens
cached tokens
model calls
tool calls
latency
provider-reported cost or locally computed estimate
```

Cost estimates must identify the pricing/version source and should not be treated as exact
billing records unless supplied authoritatively by the provider.

## 21. CLI surface

Potential commands:

```text
riko agent validate scenario.json
riko agent describe scenario.json
riko agent run scenario.json --param company=...
riko agent eval scenario.json
```

`describe` can report the lowered Pipeline topology, capabilities, credential/resource
references, stateful loop/checkpoint scopes, model policies, retrieval sources, and risk without
executing the scenario.

CLI command/plugin mechanics remain owned by `cli.md`.

## 22. Testing strategy

Required contract tests include:

1. scenario serialization/fingerprinting;
2. unknown agent/tool/profile references fail validation;
3. model policy resolves and resolved model is recorded;
4. hard model pin remains reproducible;
5. tool grants enforce caller/executor restrictions;
6. dynamically discovered OpenAPI operations require explicit registration/policy;
7. arbitrary import paths cannot become tools;
8. code execution is unavailable unless explicitly configured with sandbox policy;
9. retrieval source permissions prevent cross-namespace access;
10. static/supervised/peer semantics lower to valid explicit Pipeline topology;
11. repeated turns use `loop` rather than a cyclic/parallel agent graph;
12. loop/checkpoint state uses the common `FeedState` / `StateStore` contract;
13. deterministic evaluators produce stable results;
14. tool-call/policy assertions are evaluated;
15. model judge is labeled non-deterministic and records judge model;
16. run record contains fingerprints, tool events, artifacts, state references, and usage.

## 23. Phases

```text
AS0  AgentScenario / AgentSpec schema + Pipeline lowering contract
AS1  semantic model policies
AS2  capability tool grants and policy
AS3  Pipeline/pubsub/loop team-routing lowering
AS4  RetrievalSpec + declared resource/provenance integration
AS5  profile library
AS6  deterministic evaluation framework
AS7  tool-call/safety/state evaluation
AS8  CLI validate/describe/run/eval adapter
AS9  OpenAPI discovery proposal workflow
```

These scenario phases specialize the common runtime. Forward cross-cutting implementation order
remains owned by `implementation-sequence.md`, especially R9/R11.

## 24. Definition of done

1. Agent workflows can be represented as reviewed/versioned data.
2. Scenarios compile to ordinary `Pipeline`/pubsub/loop structures; there is no separate agent
   executor or graph runtime.
3. Scenarios reference registered capabilities, not arbitrary imports.
4. Model selection can use semantic policy while recording the concrete resolved model.
5. OpenAPI discovery cannot self-authorize execution.
6. Retrieval has explicit sources, fingerprints, resource bindings, and access policy.
7. Arbitrary code execution is not a default tool.
8. Repeated turns/checkpoints reuse common loop/`FeedState`/`StateStore` semantics.
9. Scenario behavior can be evaluated beyond final response text.
10. Tool-policy violations and side-effect expectations are regression-testable.
11. Runs emit enough metadata for cost, provenance, state/recovery diagnostics, and reproducibility
    analysis without defining a second persistence model.
