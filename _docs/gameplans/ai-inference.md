# AI inference gameplan

> **Scope.** Provider-neutral inference for the `riko-ai` package. The prior-art
> analysis (Langly/LangChain extraction) and native-reimplementation sketches live in
> [ai-inference-research.md](ai-inference-research.md); this file is the actionable plan.

## 1. Mission

Extend the planned `riko-ai` package beyond basic text inference so it can provide model-driven reasoning for the capability system without owning external execution.

`riko-ai` must support:

1. Provider-neutral inference.
2. Structured output.
3. Model profiles and routing.
4. Cost and token budgets.
5. Semantic capability retrieval.
6. Capability selection.
7. Bounded task decomposition.
8. Model-based verification.
9. Large-content summarization.
10. Bounded research workflows.
11. Reusable workflow profiles.
12. Evaluation-driven model optimization.

`riko-ai` proposes plans. It does not bypass `riko-mcp` validation, approval, credentials, or execution policy.

---

# 2. Package boundaries

## `riko-ai` owns

* provider SDK adapters;
* `infer`;
* structured generation;
* model metadata;
* model routing;
* semantic ranking;
* capability selection;
* task planning;
* response verification;
* summarization;
* evidence-backed research;
* AI usage accounting;
* AI evaluations.

## `riko-mcp` owns

* authoritative capability schemas;
* MCP and OpenAPI connectivity;
* catalog fingerprints;
* deterministic filtering;
* plan validation;
* execution;
* approval;
* credentials;
* artifacts;
* deterministic verification;
* external usage telemetry.

## Execution rule

```text
riko-ai proposal
→ riko-mcp validation
→ execution policy
→ approval policy
→ capability executor
```

`riko-ai` may not:

* open MCP sessions;
* launch subprocesses;
* resolve secrets;
* call arbitrary URLs;
* mutate a catalog;
* execute an unvalidated plan;
* expand network allowlists.

---

# 3. Langly and AutoGen concepts assigned to AI

The reviewed projects contained several useful model-driven ideas that do not belong in the MCP layer.

## Provider abstraction

AutoGen contained custom adaptation between Anthropic and OpenAI-style message and tool formats.

Retain the idea of provider normalization, but expose provider-neutral Riko types rather than framework response classes.

## Model optimization

Langly grouped models by performance, balance, and cost, and later used task scores and prices to choose a model.

Retain:

* explicit model profiles;
* cost-aware selection;
* task-family evaluation;
* recorded selection rationale.

## Decomposition

Langly implemented prompted and structured decomposition.

Retain decomposition as a bounded typed plan, not as an open-ended agent conversation.

## Retrieval

Langly generated hypothetical questions linked to source documents to improve retrieval.

Apply the technique to capability retrieval and document retrieval, but treat generated retrieval aids as non-authoritative.

## Verification

Langly graded questions, retrieved documents, final answers, and hallucination risk.

Retain model verification only after deterministic validation.

## Large-context processing

Langly calculated chunk sizes from model context windows and supported context-aware chunking.

Retain token-aware chunking and bounded map-reduce summarization.

## Agent libraries

Replace persona-heavy agent libraries with reusable workflow profiles containing:

* model policy;
* capability policy;
* planner settings;
* verifier settings;
* budget;
* output contract.

---

# 4. Provider-neutral inference contracts

## Provider

```python
class AiProvider(Protocol):
    async def generate(
        self,
        request: InferenceRequest,
    ) -> InferenceResult:
        ...

    async def generate_structured[T](
        self,
        request: StructuredInferenceRequest[T],
    ) -> StructuredInferenceResult[T]:
        ...
```

## Content

```python
type AiContent = (
    AiTextContent
    | AiImageContent
    | AiToolProposal
    | AiReasoningSummary
)
```

Do not expose private reasoning or provider-specific chain-of-thought fields.

## Result

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class InferenceResult:
    content: tuple[AiContent, ...]
    finish_reason: str | None
    usage: ModelUsage
```

## Structured output

Use standard typed Python models and JSON Schema.

Do not require Pydantic as the public domain model.

Provider-specific schema conversion remains internal.

---

# 5. Public Riko modules

## `infer`

Generate or enrich content.

```python
flow.infer(
    conf={
        "field": "body",
        "instruction": "Write a two-sentence summary.",
    },
    assign="summary",
)
```

## `capabilityselect`

Consume a `CapabilityCatalog` and emit a `SelectionOutcome`.

```python
plan = catalog.capabilityselect(
    conf={
        "task": "Convert 100 USD to GBP.",
        "input": {
            "amount": 100,
            "source_currency": "USD",
            "target_currency": "GBP",
        },
        "allow_discovery": True,
        "discovery_providers": [
            "apis_guru",
        ],
        "minimum_confidence": 0.80,
    }
)
```

## `taskplan`

Produce a bounded multi-step plan.

## `verify`

Apply model-based verification after deterministic checks.

## `summarize`

Apply token-aware large-content summarization.

## `research`

Run a bounded evidence-backed research workflow.

---

# 6. Model profiles

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class ModelProfile:
    provider: str
    model: str

    context_window: int

    input_cost: Decimal
    output_cost: Decimal

    capabilities: frozenset[ModelCapability]
    optimization_tier: OptimizationTier
```

```python
class OptimizationTier(StrEnum):
    PERFORMANCE = "performance"
    BALANCED = "balanced"
    COST = "cost"
```

Model data must come from configuration or a maintained provider registry.

Do not hard-code stale prices in selection logic.

---

# 7. Model selection

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class ModelSelectionPolicy:
    optimization: OptimizationTier

    required_capabilities: (
        frozenset[ModelCapability]
    )

    minimum_quality_score: float | None = None
    maximum_cost: Decimal | None = None
    maximum_latency_ms: int | None = None
```

Selection order:

1. Remove models missing required capabilities.
2. Remove models outside hard budgets.
3. Apply task-family quality information.
4. Apply optimization policy.
5. Record the selected model and rationale.

Operator-specified models override automatic selection.

---

# 8. AI usage and budgets

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class ModelUsage:
    provider: str
    model: str

    input_tokens: int
    output_tokens: int
    cached_input_tokens: int = 0

    input_cost: Decimal = Decimal(0)
    output_cost: Decimal = Decimal(0)

    latency_ms: int
    retries: int = 0
```

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class AiBudget:
    maximum_cost: Decimal | None = None
    maximum_calls: int | None = None

    maximum_input_tokens: int | None = None
    maximum_output_tokens: int | None = None

    deadline_seconds: float | None = None
```

Budget exhaustion must produce a structured failure rather than silently selecting a cheaper or weaker model unless policy explicitly permits fallback.

---

# 9. Semantic capability retrieval

## Goal

Reduce a large capability catalog to a bounded model-facing candidate set.

Flow:

```text
task
→ deterministic capability query
→ keyword retrieval
→ optional vector retrieval
→ optional model reranking
→ top-K candidates
→ capability selection
```

## Retrieval aid

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class CapabilityRetrievalAid:
    capability_id: str
    generated_tasks: tuple[str, ...]

    model: str
    source_fingerprint: str
```

Example for an exchange-rate capability:

```text
Convert USD to GBP.
Find the current EUR/USD exchange rate.
Retrieve rates using EUR as a base currency.
```

Generated retrieval aids:

* are non-authoritative;
* cannot alter schemas or effects;
* are invalidated when the capability changes;
* are never used during plan validation.

A keyword-only path must always remain available.

---

# 10. Capability selection

## Request

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class CapabilitySelectionRequest:
    task: str
    input: JsonValue

    candidates: tuple[CapabilityInfo, ...]

    policy_summary: SelectionPolicySummary
    budget: AiBudget
```

## Output

```text
CapabilityPlan
CapabilityDiscoveryPlan
NoCapabilityMatch
```

## Requirements

The model may propose only IDs present in the supplied candidate set.

It may not:

* invent a capability;
* invent a server;
* alter the catalog;
* alter effects;
* add network hosts;
* add credentials;
* execute the plan;
* override confirmation requirements.

## Confidence defaults

```text
below 0.60
    NoCapabilityMatch or request more information

0.60–0.84
    plan requires confirmation

0.85 and above
    follow normal execution policy
```

Confidence does not relax write or destructive-operation policy.

---

# 11. Bounded discovery loop

When no existing capability fits:

```text
selection
→ CapabilityDiscoveryPlan
→ riko-mcp expands catalog
→ selection runs again
```

Defaults:

```text
maximum discovery rounds = 1
maximum APIs.guru summaries = 20
maximum schemas = 5
maximum operations = 30
```

The AI may formulate the discovery query but cannot directly fetch schemas.

---

# 12. Bounded task decomposition

## Plan

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class TaskPlan:
    id: str
    objective: str

    steps: tuple[PlanStep, ...]

    maximum_steps: int
    maximum_parallel_steps: int

    budget: WorkflowBudget
    catalog_fingerprint: str
```

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class PlanStep:
    id: str
    task: str

    depends_on: tuple[str, ...]
    input_bindings: Mapping[str, ValueBinding]

    resolution: (
        CapabilityPlan
        | CapabilityDiscoveryPlan
        | None
    )

    output_key: str | None
    verification: VerificationPolicy | None
```

## Example

```text
Request:
    Find the country associated with an IP,
    determine its currency,
    convert 100 USD to that currency.

Step 1
    select IP-geolocation capability

Step 2
    extract country and currency

Step 3
    select or discover exchange-rate capability

Step 4
    perform conversion
```

## Limits

* fixed maximum steps;
* acyclic dependencies;
* fixed discovery rounds;
* no recursive planner calls;
* no implicit execution;
* no invented credentials;
* no model-controlled catalog mutation.

---

# 13. Model-based verification

Deterministic validation runs first.

Model verification may then evaluate:

* semantic completeness;
* grounding;
* contradictions;
* relevance;
* unsupported claims;
* source quality;
* whether the result fulfills the task.

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class VerificationResult:
    passed: bool
    score: float

    reasons: tuple[str, ...]
    unsupported_claims: tuple[str, ...]

    recommended_action: str | None
```

Recovery actions:

```text
fail
retry same capability
reselect from existing catalog
request bounded API discovery
rewrite the task
send output to draft review
request human review
```

```python
VerificationPolicy(
    maximum_attempts=2,
    on_failure="reselect",
)
```

No unbounded “try again” behavior.

---

# 14. Large-content summarization

```python
class SummarizationStrategy(StrEnum):
    STUFF = "stuff"
    MAP_REDUCE = "map_reduce"
    REFINE = "refine"
    HIERARCHICAL = "hierarchical"
```

Inputs:

* text;
* text iterables;
* record collections;
* `CapabilityArtifact`;
* MCP resource references;
* OpenAPI response artifacts.

Requirements:

* token-aware chunks;
* model-specific context limits;
* stable overlap;
* chunk provenance;
* bounded concurrent map phase;
* deterministic output ordering;
* budget enforcement;
* retained source references.

Example:

```python
artifact.summarize(
    conf={
        "strategy": "map_reduce",
        "instruction": "Summarize key findings.",
        "maximum_cost": "0.25",
    }
)
```

---

# 15. Bounded research workflow

```text
rewrite question
→ select search capability
→ search
→ rank sources
→ select retrieval capability
→ fetch sources
→ extract evidence
→ verify evidence
→ synthesize
→ emit citations
```

## Source

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class ResearchSource:
    uri: str
    title: str | None
    publisher: str | None

    retrieved_at: datetime
    content_hash: str
    artifact_uri: str | None
```

## Evidence

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class Evidence:
    source: ResearchSource
    locator: str | None

    excerpt_hash: str
    claim_ids: tuple[str, ...]
```

## Limits

* maximum search rounds;
* maximum sources;
* maximum retrievals;
* duplicate-source removal;
* domain policy;
* publication-date checks;
* evidence required for factual claims;
* complete provenance.

This replaces search/scrape agent teams with one typed workflow.

---

# 16. Reusable workflow profiles

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class AiWorkflowProfile:
    name: str
    description: str

    model_policy: ModelSelectionPolicy
    capability_query: CapabilityQuery

    planner: PlannerConfig | None
    verifier: VerificationPolicy | None

    budget: WorkflowBudget
```

Initial profiles:

```text
api-capability-selector
public-content-summarizer
technical-researcher
site-draft-reviewer
repository-analyzer
data-quality-reviewer
```

Profiles contain behavior and policy, not simulated job titles or personalities.

Example:

```toml
[profiles.api-capability-selector]
description = "Select or discover a read-only API."
optimization = "balanced"
maximum_steps = 3
maximum_discovery_rounds = 1
approval = "policy"
```

---

# 17. AI evaluation framework

## Scenario

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class AiScenario:
    id: str
    task: str
    input: JsonValue

    profile: str

    expected_capabilities: tuple[str, ...] = ()
    expected_output: JsonValue | None = None

    evaluator: EvaluationKind

    maximum_cost: Decimal | None = None
    maximum_latency_ms: int | None = None
```

## Evaluate independently

* model selection;
* capability retrieval;
* capability selection;
* argument generation;
* discovery-query quality;
* decomposition;
* verification;
* summarization;
* final answer;
* cost;
* latency.

## Initial scenarios

### Native versus MCP

```text
Fetch a JSON API into records.
Expected: native fetchdata.
```

```text
Fetch a webpage as clean model-readable text.
Expected: Fetch MCP.
```

### APIs.guru discovery

```text
Convert 100 USD to GBP.
Expected: exchange-rate API discovery and valid operation plan.
```

### Translation

```text
Translate an English sentence to Swahili.
Expected: translation-capable API discovery or NoCapabilityMatch
when credentials are unavailable.
```

### IP geolocation

```text
Resolve IPv4 and IPv6 addresses to city,
region, and country.
```

### Multi-step plan

```text
Find an IP’s country, determine its currency,
and convert 100 USD.
```

### Authentication failure

The best API requires an unavailable credential.

Expected:

```text
NoCapabilityMatch
```

or a lower-ranked usable API.

---

# 18. Historical optimization

Evaluation history may inform model routing.

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class ModelTaskScore:
    task_family: str
    model: str

    quality: float
    average_cost: Decimal
    average_latency_ms: int

    sample_count: int
```

Rules:

* task-family-specific;
* minimum sample threshold;
* profile versioning;
* explicit activation;
* recorded rationale;
* no silent production changes.

---

# 19. Proposed repository layout

```text
riko_ai/
├── __init__.py
├── py.typed
├── exceptions.py
│
├── types/
│   ├── content.py
│   ├── inference.py
│   ├── models.py
│   ├── usage.py
│   ├── plans.py
│   ├── verification.py
│   └── research.py
│
├── providers/
│   ├── protocol.py
│   ├── openai.py
│   ├── anthropic.py
│   └── registry.py
│
├── models/
│   ├── profiles.py
│   ├── selection.py
│   ├── pricing.py
│   └── history.py
│
├── inference/
│   ├── generate.py
│   ├── structured.py
│   ├── prompts.py
│   └── normalization.py
│
├── capabilities/
│   ├── retrieval.py
│   ├── semantic_index.py
│   ├── selection.py
│   └── discovery_queries.py
│
├── planning/
│   ├── decomposition.py
│   ├── validation.py
│   └── bindings.py
│
├── verification/
│   ├── answer.py
│   ├── grounding.py
│   └── recovery.py
│
├── summarization/
│   ├── chunks.py
│   ├── map_reduce.py
│   ├── refine.py
│   └── hierarchical.py
│
├── research/
│   ├── workflow.py
│   ├── sources.py
│   ├── evidence.py
│   └── synthesis.py
│
├── profiles/
│   ├── loading.py
│   └── defaults.py
│
├── modules/
│   ├── infer.py
│   ├── capabilityselect.py
│   ├── taskplan.py
│   ├── verify.py
│   ├── summarize.py
│   └── research.py
│
└── evaluations/
    ├── scenarios.py
    ├── evaluators.py
    ├── reports.py
    └── fixtures.py
```

---

# 20. Implementation phases

## AI0 — Provider architecture

* define provider-neutral types;
* implement provider registry;
* implement structured output;
* normalize usage;
* isolate SDK imports;
* implement deterministic fake provider.

**Acceptance:** `infer` works without exposing provider SDK classes.

## AI1 — Model profiles and budgets

* implement model profiles;
* implement optimization tiers;
* implement model-selection policy;
* implement usage;
* implement budget enforcement;
* add configuration loading.

**Acceptance:** model selection is explainable and bounded.

## AI2 — Base `infer`

* implement processor and operator forms;
* support field extraction;
* support assignment;
* support structured output;
* support bounded concurrency;
* preserve provenance;
* emit usage.

**Acceptance:** normal Riko AI enrichment works without capability selection.

## AI3 — Capability retrieval

* consume `CapabilityCatalog`;
* implement deterministic candidate filtering;
* integrate keyword index;
* add optional vector index;
* implement generated retrieval aids;
* add candidate-limit enforcement.

**Acceptance:** large catalogs reduce to stable top-K candidates.

## AI4 — Capability selection

* implement `CapabilitySelectionRequest`;
* implement structured selection output;
* validate IDs against candidates;
* emit `CapabilityPlan`, `CapabilityDiscoveryPlan`, or `NoCapabilityMatch`;
* add confidence rules.

**Acceptance:** model cannot invent executable capabilities.

## AI5 — APIs.guru discovery queries

* formulate bounded API-discovery queries;
* evaluate exchange-rate, translation, and IP-geolocation tasks;
* preserve discovery and execution separation.

**Acceptance:** discovery plans are useful but non-executable.

## AI6 — Task decomposition

* implement `TaskPlan`;
* implement `PlanStep`;
* validate dependency graph;
* enforce step and discovery limits;
* support independent parallel steps.

**Acceptance:** multi-step plans are finite, typed, and inspectable.

## AI7 — Verification and recovery

* run deterministic validation first;
* implement semantic verification;
* identify unsupported claims;
* implement bounded recovery actions;
* emit structured verification results.

**Acceptance:** no open-ended retries.

## AI8 — Large-content summarization

* implement token-aware chunking;
* implement stuff, map-reduce, refine, and hierarchical strategies;
* support artifacts;
* preserve source references;
* enforce cost budgets.

**Acceptance:** large inputs remain bounded and traceable.

## AI9 — Research workflow

* implement search selection;
* implement retrieval selection;
* rank sources;
* extract evidence;
* synthesize with citations;
* enforce source and round limits.

**Acceptance:** research output is evidence-backed and bounded.

## AI10 — Workflow profiles

* implement profile schema;
* add initial profiles;
* version profiles;
* support context overrides;
* prohibit hidden persona behavior.

**Acceptance:** reusable workflows are declarative and reviewable.

## AI11 — Evaluations and routing optimization

* port relevant Langly scenarios;
* implement deterministic and model evaluators;
* record task-family scores;
* generate cost/quality reports;
* support explicit profile updates.

**Acceptance:** optimization changes require a versioned configuration decision.

---

# 21. Testing requirements

## Unit tests

Cover:

* provider adapters;
* structured output;
* model routing;
* budgets;
* capability serialization;
* candidate validation;
* decomposition;
* verification;
* chunking;
* evidence;
* profiles.

## Deterministic fake provider

Provide a fake provider capable of:

* exact output;
* malformed structured output;
* low confidence;
* invented capability ID;
* timeout;
* token-limit failure;
* partial response.

## Golden fixtures

Use golden fixtures for:

* selection requests;
* capability plans;
* discovery plans;
* task plans;
* verification results;
* summaries;
* research evidence;
* evaluation reports.

## Type checking

All public code must pass strict Pyright.

Provider SDK `Any` usage must remain isolated inside adapters.

---

# 21.1 Connector selection boundary

AI may select among connector, MCP, OpenAPI, SQL, and native Riko capabilities only after
those capabilities have been deterministically discovered and normalized.

The model must not:

* invent a URI scheme handler;
* choose an arbitrary storage bucket, broker, database, or proxy host;
* place credentials in a URI or module configuration;
* trigger content-type probing as an implicit side effect of semantic retrieval;
* convert a read request into a write operation;
* select a long-lived feed or webhook source without an explicit runtime budget and
  checkpoint policy.

A universal source request is represented to the model as an inspectable `SourcePlan` or
catalog capability. Deterministic resolution, policy, credentials, and execution remain
outside the model.

# 22. Explicit non-goals

Do not implement:

* a required LangChain dependency;
* a required LangGraph dependency;
* open-ended agent teams;
* simulated organizational personas;
* hidden chain-of-thought storage;
* autonomous network execution;
* direct credential access;
* arbitrary code execution;
* unbounded retries;
* automatic production model changes;
* AI-generated security policy;
* model verification instead of deterministic validation;
* silent catalog mutation.

---

# 23. Initial Claude Code prompt

```text
You are implementing AI0 of the authoritative Riko AI-Infer addendum.

Repositories:
- nerevu/riko, most current branch
- new repository nerevu/riko-ai
- nerevu/langly and nerevu/autogen for historical reference only

Assumptions:
- Riko’s AnyIO migration is complete.
- riko-mcp capability contracts exist or are represented by fixtures.
- Provider SDK objects must not appear in public APIs.
- LangChain and LangGraph must not become required dependencies.

Execute AI0 only.

Required:
1. Inspect Riko execution and typing conventions.
2. Define provider-neutral inference and content types.
3. Define AiProvider and registry contracts.
4. Implement one real provider adapter behind an optional extra.
5. Implement a deterministic fake provider for tests.
6. Implement structured-output normalization.
7. Implement model-usage normalization.
8. Record provider errors without leaking secrets.
9. Add strict Pyright and unit tests.
10. Stop after AI0.

Do not implement capability selection, task planning,
research, model optimization, or MCP execution.
```

