# Inference

Riko should not depend on Langly or LangChain. Langly should be treated as a prototype containing useful patterns to reimplement natively in Riko.

The current features branch confirms why: its package metadata declares only click, while runtime code imports LangChain, LangGraph, Chroma, Anthropic, OpenAI, document loaders, and related packages.

The target should be:

Riko core
    stream processing
    lightweight AI protocols
    prompt rendering
    model selection
    tool execution
    bounded agent loop
    evaluation metadata

Optional provider extras
    openai
    anthropic
    local/OpenAI-compatible

No LangChain compatibility layer is necessary initially.

What to extract from Langly
Langly concept  Riko treatment
Model cost/context metadata Rewrite as lightweight dataclasses
Cost/balanced/performance optimization  Retain as model-selection policies
Named prompt catalog    Retain with standard string rendering
Tool definitions    Rewrite as native callable wrappers
Structured output   Retain using JSON Schema
Bounded graph/agent execution   Rewrite as a small agent loop
Scenario-based evaluation   Retain as offline evaluation fixtures
Model performance history   Retain for stage-level model selection
RAG workflow patterns   Rebuild using Riko pipelines
Multi-agent supervisor  Defer
LangChain runnables Drop
LangGraph state graphs  Drop
Pydantic-specific output parsers    Drop
Chroma-specific implementation  Make optional
CLI monolith    Drop
Runtime breakpoint() handling   Drop

Langly’s strongest ideas are not its LangChain objects. They are its:

model profiles;
optimization modes;
prompts;
named abilities;
structured outputs;
tools;
evaluation scenarios;
model-performance feedback loop.
Revised package structure
riko/
  ai/
    __init__.py
    types.py
    models.py
    prompts.py
    providers.py
    runtime.py
    tools.py
    agents.py
    evaluation.py

    adapters/
      __init__.py
      openai.py
      anthropic.py
      compatible.py

  modules/
    infer.py
    agent.py
    embed.py       # later
    retrieve.py    # later

The initial implementation only needs:

riko/ai/types.py
riko/ai/models.py
riko/ai/prompts.py
riko/ai/providers.py
riko/ai/runtime.py
riko/modules/infer.py
1. Native message and response types

Do not expose provider or LangChain message objects.

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, TypeAlias


JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = (
    JsonScalar
    | list["JsonValue"]
    | dict[str, "JsonValue"]
)

MessageRole: TypeAlias = Literal[
    "system",
    "user",
    "assistant",
    "tool",
]


@dataclass(frozen=True, slots=True)
class Message:
    role: MessageRole
    content: str
    name: str | None = None
    tool_call_id: str | None = None


@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class TokenUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class ModelResponse:
    value: JsonValue
    message: Message | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    model: str | None = None
    finish_reason: str | None = None
    usage: TokenUsage | None = None
    metadata: dict[str, JsonValue] = field(default_factory=dict)

This is enough for:

plain inference;
structured output;
tool calls;
agent loops;
usage tracking.
2. Separate model metadata from optimization policy

Langly combines a model with one optimization category. It also defines gpt_4 twice, so the second assignment overwrites the first.

Instead, models describe facts:

from dataclasses import dataclass
from enum import StrEnum


class ModelCapability(StrEnum):
    TOOLS = "tools"
    STRUCTURED_OUTPUT = "structured_output"
    VISION = "vision"
    STREAMING = "streaming"


@dataclass(frozen=True, slots=True)
class ModelSpec:
    id: str
    provider: str
    name: str
    context_window: int
    input_cost: float | None = None
    output_cost: float | None = None
    capabilities: frozenset[ModelCapability] = frozenset()

Policies make selections:

class Optimization(StrEnum):
    COST = "cost"
    BALANCED = "balanced"
    PERFORMANCE = "performance"


@dataclass(frozen=True, slots=True)
class ModelPolicy:
    optimization: Optimization = Optimization.BALANCED
    required_capabilities: frozenset[ModelCapability] = frozenset()
    maximum_cost: float | None = None

Langly’s cost, balanced, and performance selection behavior is worth retaining, but it should operate over independent model and evaluation records.

class ModelRegistry:
    def __init__(self) -> None:
        self._models: dict[str, ModelSpec] = {}

    def register(self, model: ModelSpec) -> None:
        if model.id in self._models:
            raise ValueError(f"Duplicate model ID {model.id!r}")

        self._models[model.id] = model

    def get(self, model_id: str) -> ModelSpec:
        try:
            return self._models[model_id]
        except KeyError:
            raise KeyError(f"Unknown model {model_id!r}") from None

    def candidates(
        self,
        policy: ModelPolicy,
    ) -> tuple[ModelSpec, ...]:
        return tuple(
            model
            for model in self._models.values()
            if policy.required_capabilities <= model.capabilities
        )
3. Minimal provider protocol

Riko only needs a provider capable of completing messages.

from collections.abc import Mapping, Sequence
from typing import Protocol


class ChatProvider(Protocol):
    def complete(
        self,
        messages: Sequence[Message],
        *,
        model: ModelSpec,
        tools: Sequence["ToolSpec"] = (),
        response_schema: Mapping[str, JsonValue] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
    ) -> ModelResponse: ...

    async def acomplete(
        self,
        messages: Sequence[Message],
        *,
        model: ModelSpec,
        tools: Sequence["ToolSpec"] = (),
        response_schema: Mapping[str, JsonValue] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
    ) -> ModelResponse: ...

Providers are registered independently:

class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, ChatProvider] = {}

    def register(
        self,
        name: str,
        provider: ChatProvider,
    ) -> None:
        self._providers[name] = provider

    def get(self, name: str) -> ChatProvider:
        try:
            return self._providers[name]
        except KeyError:
            raise KeyError(f"Unknown AI provider {name!r}") from None

Direct SDK adapters become optional:

riko[openai]     → OpenAI SDK
riko[anthropic]  → Anthropic SDK

A local or OpenAI-compatible adapter could use an existing HTTP dependency or a small standard-library client.

4. Retain Langly’s prompt catalog

Langly’s prompt catalog is useful. It separates:

prompt ID;
instructions;
ability;
template variables such as first, last, and penultimate.

Reimplement it without ChatPromptTemplate.

from dataclasses import dataclass
from string import Formatter


@dataclass(frozen=True, slots=True)
class PromptSpec:
    id: str
    instructions: str
    ability: str = ""

    @property
    def variables(self) -> frozenset[str]:
        return frozenset(
            field_name
            for _, field_name, _, _ in Formatter().parse(
                self.instructions
            )
            if field_name
        )

    def render(self, values: Mapping[str, object]) -> str:
        missing = self.variables - values.keys()

        if missing:
            names = ", ".join(sorted(missing))
            raise ValueError(
                f"Prompt {self.id!r} missing variables: {names}"
            )

        return self.instructions.format_map(values)

Catalog:

class PromptCatalog:
    def __init__(
        self,
        prompts: Iterable[PromptSpec] = (),
    ) -> None:
        self._prompts = {
            prompt.id: prompt
            for prompt in prompts
        }

    def get(self, prompt_id: str) -> PromptSpec:
        try:
            return self._prompts[prompt_id]
        except KeyError:
            raise KeyError(
                f"Unknown prompt {prompt_id!r}"
            ) from None

The existing Langly prompts can be copied as data after reviewing their wording.

For Riko, dynamic item references remain Riko configuration:

conf = {
    "prompt": "rewrite",
    "variables": {
        "first": {
            "subkey": "description",
        },
    },
}

Riko resolves subkey; the AI layer receives:

{
    "first": "Original description",
}
5. Structured output without Pydantic

Langly binds Pydantic classes as tools and parses their responses through LangChain.

Riko should use JSON Schema as the canonical serialized format:

ticket_schema = {
    "type": "object",
    "properties": {
        "category": {
            "type": "string",
        },
        "urgency": {
            "type": "string",
            "enum": ["low", "medium", "high"],
        },
        "summary": {
            "type": "string",
        },
    },
    "required": [
        "category",
        "urgency",
        "summary",
    ],
    "additionalProperties": False,
}

Adapters may use:

provider-native structured output;
provider tool calling;
JSON mode;
plain JSON parsing.

The runtime always returns:

ModelResponse(
    value={
        "category": "technical",
        "urgency": "high",
        "summary": "User cannot access the account.",
    }
)

Python-only callers could optionally convert dataclasses or TypedDict definitions to JSON Schema, but that does not need to be part of the first version.

6. Native tools

Langly’s typed tool examples and concurrent tool execution are worth borrowing.

The Riko representation can be much smaller:

from collections.abc import Callable
from dataclasses import dataclass


ToolHandler = Callable[
    [dict[str, JsonValue]],
    JsonValue,
]


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, JsonValue]
    handler: ToolHandler

    def invoke(
        self,
        arguments: dict[str, JsonValue],
    ) -> JsonValue:
        return self.handler(arguments)

Registry:

class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, tool: ToolSpec) -> None:
        if tool.name in self._tools:
            raise ValueError(
                f"Duplicate tool {tool.name!r}"
            )

        self._tools[tool.name] = tool

    def resolve_many(
        self,
        names: Iterable[str],
    ) -> tuple[ToolSpec, ...]:
        return tuple(self._tools[name] for name in names)

Do not scan module globals as Langly currently does. Langly identifies tools by inspecting module attributes for BaseTool instances.

Explicit registration is clearer and safer.

7. Small bounded agent loop

LangGraph is unnecessary for the basic tool-using agent.

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AgentConfig:
    max_steps: int = 5
    parallel_tools: bool = True


class AgentRunner:
    def __init__(
        self,
        provider_registry: ProviderRegistry,
    ) -> None:
        self.providers = provider_registry

    def run(
        self,
        messages: list[Message],
        *,
        model: ModelSpec,
        tools: tuple[ToolSpec, ...],
        config: AgentConfig,
        response_schema: dict[str, JsonValue] | None = None,
    ) -> ModelResponse:
        provider = self.providers.get(model.provider)
        tools_by_name = {
            tool.name: tool
            for tool in tools
        }

        for _ in range(config.max_steps):
            response = provider.complete(
                messages,
                model=model,
                tools=tools,
                response_schema=response_schema,
            )

            if response.message is not None:
                messages.append(response.message)

            if not response.tool_calls:
                return response

            results = self._execute_calls(
                response.tool_calls,
                tools_by_name,
                parallel=config.parallel_tools,
            )

            for call, value in results:
                messages.append(
                    Message(
                        role="tool",
                        name=call.name,
                        tool_call_id=call.id,
                        content=serialize_json(value),
                    )
                )

        raise AgentStepLimitError(
            f"Agent exceeded {config.max_steps} steps"
        )

Tool execution:

def _execute_call(
    call: ToolCall,
    tools: Mapping[str, ToolSpec],
) -> tuple[ToolCall, JsonValue]:
    try:
        tool = tools[call.name]
    except KeyError:
        raise UnknownToolError(call.name) from None

    return call, tool.invoke(call.arguments)


def _execute_calls(
    self,
    calls: tuple[ToolCall, ...],
    tools: Mapping[str, ToolSpec],
    *,
    parallel: bool,
) -> list[tuple[ToolCall, JsonValue]]:
    if not parallel or len(calls) < 2:
        return [
            _execute_call(call, tools)
            for call in calls
        ]

    with ThreadPoolExecutor(
        max_workers=len(calls)
    ) as executor:
        return list(
            executor.map(
                lambda call: _execute_call(call, tools),
                calls,
            )
        )

This captures the useful part of Langly’s ToolNode without importing LangGraph.

8. Let Riko own most workflows

Several Langly “agents” are better represented as Riko pipelines.

Rewriter

Langly:

rewriter agent

Riko:

pipe.infer(
    field="question",
    conf={"prompt": "rewrite"},
    assign="rewritten_question",
)
Decomposer

Langly uses a structured Decompose output containing sub_tasks.

Riko:

pipe.infer(
    field="task",
    conf={
        "prompt": "breakdown",
        "response_schema": {
            "type": "object",
            "properties": {
                "sub_tasks": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["sub_tasks"],
        },
    },
    assign="decomposition",
)
Evaluator

Langly defines binary and ternary grading outputs for question quality, document relevance, hallucination checks, and answer completeness.

These become reusable prompt/schema presets:

pipe.infer(
    conf={
        "prompt": "evaluate_answer",
        "response_schema": TERNARY_SCORE_SCHEMA,
    },
    assign="evaluation",
)
Deterministic RAG

Instead of LangGraph:

rewrite → retrieve → grade → answer

use a Riko pipeline:

infer(rewrite)
    → retrieve
    → infer(grade documents)
    → filter(relevant)
    → infer(answer)
    → infer(grade answer)

The pipeline already supplies the orchestration.

Only use the bounded agent loop when the model must dynamically choose tools.

9. Riko pipeline tools

This remains one of the strongest ideas.

def tool_from_pipeline(
    *,
    name: str,
    description: str,
    input_schema: dict[str, JsonValue],
    pipeline: Callable[[Iterable[dict]], Iterable[dict]],
) -> ToolSpec:
    def handler(
        arguments: dict[str, JsonValue],
    ) -> JsonValue:
        results = list(
            pipeline(iter((arguments,)))
        )

        if len(results) == 1:
            return results[0]

        return results

    return ToolSpec(
        name=name,
        description=description,
        input_schema=input_schema,
        handler=handler,
    )

That allows agents to invoke deliberately exposed Riko pipelines without giving them access to all modules.

runtime.tools.register(
    tool_from_pipeline(
        name="normalize_address",
        description="Normalize a mailing address.",
        input_schema=address_schema,
        pipeline=normalize_address,
    )
)
10. Preserve evaluation-driven model selection

Langly’s scenario suite is valuable. It contains:

task definitions;
agent configurations;
tools;
model choices;
expected answers;
evaluation methods;
supervisor configurations.

Split it into:

@dataclass(frozen=True, slots=True)
class AIStageSpec:
    id: str
    prompt: str
    response_schema: dict[str, JsonValue] | None = None
    tools: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EvaluationCase:
    stage_id: str
    input: JsonValue
    expected: JsonValue | None
    evaluator: str

Evaluation results:

@dataclass(frozen=True, slots=True)
class ModelEvaluation:
    stage_id: str
    model_id: str
    prompt_hash: str
    schema_hash: str
    tool_hash: str
    accuracy: float
    average_cost: float | None
    sample_count: int

This improves on Langly’s current key, which includes a hash of the exact query.

The model selector should learn:

ticket-classification-v2 performs best with model X

not:

this exact ticket text performed best with model X
11. Lightweight runtime
class AIRuntime:
    def __init__(
        self,
        *,
        models: ModelRegistry,
        providers: ProviderRegistry,
        prompts: PromptCatalog,
        tools: ToolRegistry | None = None,
        selector: ModelSelector | None = None,
    ) -> None:
        self.models = models
        self.providers = providers
        self.prompts = prompts
        self.tools = tools or ToolRegistry()
        self.selector = selector or ModelSelector(models)
        self.agents = AgentRunner(providers)

    def infer(
        self,
        value: object,
        *,
        config: Mapping[str, object],
    ) -> ModelResponse:
        model = self.selector.select(config)
        provider = self.providers.get(model.provider)
        messages = build_messages(
            value,
            config=config,
            prompts=self.prompts,
        )

        return provider.complete(
            messages,
            model=model,
            response_schema=config.get("response_schema"),
            temperature=config.get("temperature"),
            max_tokens=config.get("max_tokens"),
        )

The Riko module stays thin:

from . import processor


OPTS = {
    "assign": "inference",
    "emit": False,
}


def parser(
    item,
    extraction,
    objconf,
    **kwargs,
):
    runtime: AIRuntime = kwargs["runtime"]
    value = extraction if extraction is not None else item
    result = runtime.infer(
        value,
        config=objconf,
    )
    return result.value


@processor({}, **OPTS)
def pipe(*args, **kwargs):
    return parser(*args, **kwargs)
12. Dependency boundary

Core Riko AI functionality can use only:

dataclasses
typing
enum
json
string
inspect
concurrent.futures
hashlib

Optional extras:

[project.optional-dependencies]
openai = [
    "openai>=...",
]

anthropic = [
    "anthropic>=...",
]

schema = [
    "jsonschema>=...",
]

rag = [
    # selected embedding/vector-store dependencies
]

No:

langchain
langchain-core
langgraph
langchain-community
langchain-experimental

Provider-independent tests use a fake provider:

class FakeProvider:
    def complete(
        self,
        messages,
        *,
        model,
        tools=(),
        response_schema=None,
        **kwargs,
    ):
        return ModelResponse(
            value={
                "text": messages[-1].content,
            },
            model=model.id,
        )
Recommended implementation order
Phase 1: infer

Extract and rewrite:

message/result types;
model catalog;
provider protocol and registry;
prompt catalog;
runtime;
fake provider;
Riko infer processor;
direct OpenAI adapter;
direct Anthropic adapter.
Phase 2: tools and agent

Add:

native ToolSpec;
tool registry;
bounded agent loop;
concurrent tool calls;
Riko agent processor;
tool_from_pipeline().
Phase 3: evaluation and optimization

Add:

stage specifications;
evaluation cases;
persisted result store;
cost/performance/balanced selectors;
prompt/schema/tool hashing.
Phase 4: RAG

Add:

embed;
vector-store protocol;
retrieve;
optional vector-store adapters;
reusable Riko RAG pipelines.

The central design is therefore:

Langly provides the research prototype and test cases.

Riko receives native implementations of:
    model policies
    prompt catalogs
    JSON structured output
    tools
    bounded agent loops
    evaluation-driven selection

LangChain and LangGraph are not part of the resulting architecture.

Yes. Riko should replace both LangChain and LangGraph orchestration, not merely call provider SDKs without LangChain.

The resulting architecture should be:

Langly prototype concept          Native Riko replacement
────────────────────────────────────────────────────────────
RunnableLambda                   udf / processor
RunnablePassthrough              identity stream
RunnablePassthrough.assign       processor assign semantics
RunnableSequence (`a | b`)       SyncPipe / AsyncPipe chaining
RunnableParallel                 DAG fan-out + fan-in
Runnable.batch                   parallel SyncPipe / AsyncPipe
Runnable.stream                  iterator / async iterator
Runnable.invoke                  consume one pipeline result
RunnableConfig                   Context + module conf
configurable_alternatives        model-selection processor
LangGraph StateGraph             compiled Riko pipeline DAG
LangGraph conditional edges      filter/router + branch wiring
LangGraph ToolNode               native tool executor
AgentExecutor                    bounded Riko agent operator
checkpointer                     explicit state-store interface

Riko already provides the main sequence abstraction through dynamic SyncPipe and AsyncPipe chaining. Each attribute access constructs another pipe whose source is the preceding pipe.

It also already provides per-item parallel processing for processor modules and asynchronous concurrency through AsyncPipe.

The key design rule

Do not build this:

class RikoRunnable:
    def invoke(...): ...
    def ainvoke(...): ...
    def batch(...): ...
    def stream(...): ...
    def assign(...): ...
    def __or__(...): ...

That would recreate LangChain inside Riko.

Build normal Riko modules:

infer
agent
tool
route
retry

and execute them through normal Riko pipelines:

result = (
    SyncPipe("input", source=items)
    .infer(
        model=model,
        field="question",
        assign="rewritten",
        conf={"prompt": "rewrite"},
    )
    .retrieve(
        field="rewritten",
        assign="documents",
    )
    .infer(
        assign="answer",
        conf={"prompt": "answer"},
    )
)
LangChain runnable replacements
RunnableSequence

Langly uses runnable composition such as:

mapped | prompt | chat_model | output_parser

The Riko equivalent is ordinary pipeline composition:

(
    SyncPipe("input", source=items)
    .map_prompt(conf=prompt_conf)
    .infer(model=model)
    .parse_output(conf=output_conf)
)

However, those steps do not all need to be public modules.

For simple inference, prompt rendering, provider invocation, and response normalization should remain internal to infer:

SyncPipe("input", source=items).infer(
    model=model,
    conf={
        "prompt": "rewrite",
        "response_schema": schema,
    },
    assign="result",
)

Only expose a separate module when users may reasonably compose it independently.

For example:

infer            yes
embed            yes
retrieve         yes
renderprompt      probably not initially
parseairesponse   no
RunnableLambda

Langly uses TypedRunnableLambda to insert small conversion functions throughout a chain.

Riko already has the correct abstraction: a processor wrapping a callable. The existing processor contract handles:

extracting a field;
parsing dynamic configuration;
assigning output;
emitting replacement records;
skipping items;
sync and async implementations.

For arbitrary user functions, reuse or improve udf:

pipe.udf(
    func=normalize_messages,
    assign="messages",
)

Internally defined conversions should usually just be Python functions called by the owning module:

def parser(item, extraction, objconf, **kwargs):
    messages = build_messages(item, extraction, objconf)
    response = invoke_model(messages, **kwargs)
    return normalize_response(response)

There is no need to represent every internal function as a pipeline node.

RunnablePassthrough

A Riko pipe with no named module already acts as an identity pipe:

SyncPipe(source=items)

The default pipe function returns its source unchanged.

No explicit passthrough class is needed.

RunnablePassthrough.assign

This maps directly to Riko’s existing assignment semantics.

Riko processors can assign their result onto the original item:

pipe.infer(
    field="question",
    assign="answer",
    emit=False,
)

The processor machinery already merges the result using:

item | {assign: value}

and handles iterator-valued assignments.

For example, Langly’s:

RunnablePassthrough.assign(
    first=nth_message(),
    last=nth_message(-1),
)

should not be reimplemented as a passthrough operation. It should become either dynamic configuration:

conf = {
    "variables": {
        "first": {"subkey": "messages.0.content"},
        "last": {"subkey": "messages.-1.content"},
    },
}

or an internal prompt-context builder:

context = {
    "first": first_message(item),
    "last": last_message(item),
    "penultimate": penultimate_message(item),
}

Those are prompt concerns, not general runnable concerns.

RunnableParallel

This is where a genuine Riko improvement is useful.

LangChain’s RunnableParallel takes one value and runs multiple branches:

{
    "summary": summarize,
    "sentiment": classify,
    "entities": extract,
}

Riko already has stream-level fan-out through split, which creates identical stream copies, and documents union as the reverse operation.

But the current split implementation eagerly materializes and deep-copies the entire source stream.

That is not the ideal replacement for per-item AI fan-out.

The better native design is graph branching:

                    ┌─ infer(summary) ─────┐
input → normalize ──┼─ infer(sentiment) ───┼─ join
                    └─ infer(entities) ────┘

This should use Riko’s existing pipeline DAG representation rather than a RunnableParallel object.

A Python convenience API could be added:

result = (
    SyncPipe("input", source=items)
    .branch(
        summary=lambda pipe: pipe.infer(
            model=model,
            conf={"prompt": "summarize"},
        ),
        sentiment=lambda pipe: pipe.infer(
            model=model,
            conf={"prompt": "sentiment"},
        ),
        entities=lambda pipe: pipe.infer(
            model=model,
            conf={"prompt": "entities"},
        ),
    )
    .join_fields()
)

But internally this should compile to graph nodes and edges:

normalize → summary
normalize → sentiment
normalize → entities
summary   → join
sentiment → join
entities  → join

Not:

RunnableParallel(...)

For the MVP, users can simply run separate sequential inference fields:

(
    pipe
    .infer(assign="summary", conf={"prompt": "summarize"})
    .infer(assign="sentiment", conf={"prompt": "sentiment"})
    .infer(assign="entities", conf={"prompt": "entities"})
)

Graph-level parallel branches can follow later.

invoke

Riko is stream-oriented, so it should not adopt invoke() as its primary API.

Equivalent operations are:

result = next(pipe)
results = list(pipe)

A convenience method is reasonable:

result = pipe.one()

implemented as:

def one(self, default=None):
    return next(iter(self), default)

But invoke() should not become a second execution model.

batch

Langly uses runnable batch execution for parallel model or graph calls.

Riko already supports parallel processor execution:

SyncPipe(
    "infer",
    source=items,
    parallel=True,
    workers=8,
    threads=True,
    model=model,
)

The synchronous pipe maps processor modules over input items and supports thread or process pools.

The asynchronous equivalent should use AsyncPipe:

AsyncPipe(
    "infer",
    source=source,
    connections=8,
    model=model,
)

Its processor path maps the async module over the source using the configured connection count.

Provider-native batch APIs can later be implemented as an inferbatch operator, but should not define general Riko batching.

stream

Riko streams are already iterators:

for item in pipe:
    ...

And asynchronous streams are async iterators:

async for item in pipe:
    ...

Token streaming should not be represented as normal pipeline records by default. The infer processor should yield one completed transformed item.

Token events can be passed through an optional callback or Context event sink:

pipe.infer(
    model=model,
    on_event=events.append,
)
RunnableConfig

Langly uses RunnableConfig for:

recursion limits;
concurrency;
thread IDs;
configurable models.

Those concerns belong in existing Riko surfaces.

LangChain setting   Riko destination
concurrency parallel, workers, connections
recursion limit agent module configuration
thread/session ID   item field or Context
callbacks   Context
model alternative   model policy/registry
tags/metadata   Context or module conf
timeout provider/module conf

Example:

pipe.agent(
    runtime=runtime,
    conf={
        "max_steps": 5,
        "session": {"subkey": "customer_id"},
        "timeout": 60,
    },
)
configurable_alternatives

Langly uses LangChain’s configurable alternatives to swap models dynamically.

This should be replaced with a native selector before provider invocation:

model = model_registry.select(
    stage="ticket_classification",
    policy=ModelPolicy(
        optimization=Optimization.BALANCED,
        required_capabilities={
            ModelCapability.STRUCTURED_OUTPUT,
        },
    ),
)

Then:

provider.complete(
    messages,
    model=model,
    response_schema=schema,
)

Model choice is configuration, not a composable runnable.

Replace LangGraph with Riko DAGs

Langly’s deterministic graphs should become ordinary Riko pipelines.

Langly self-RAG

Current conceptual flow:

grade question
    ├─ no  → rewrite → retrieve
    └─ yes → retrieve
                 ↓
          grade documents
             ├─ no  → retrieve
             └─ yes → answer
                          ↓
                 grade hallucination
                    ├─ no  → answer
                    └─ yes → end

The acyclic portion maps naturally to a Riko graph.

The retry edges require bounded loop support:

rewrite/retrieve retry
answer/regenerate retry

That can be expressed with an explicit Riko loop module or a specialized bounded operator, rather than adopting a state-graph engine.

For example:

pipeline = (
    SyncPipe("input", source=questions)
    .infer(conf={"prompt": "grade_question"}, assign="question_grade")
    .route(conf={"field": "question_grade.binary_score"})
)

At the serialized DAG level:

grade_question → route
route[yes]     → retrieve
route[no]      → rewrite
rewrite        → retrieve
retrieve       → grade_documents

For repeated retrieval, wrap the relevant subpipeline:

.retrieve_until(
    predicate=document_is_relevant,
    max_iterations=3,
)

or use the existing generic loop machinery if it can express this cleanly.

Keep the agent loop local

A model-driven tool loop is genuinely cyclic and dynamic:

model → tool → model → tool → final

That should not require a general LangGraph replacement in the first version.

Implement it inside agent:

@processor({}, assign="answer", emit=False)
def pipe(item, extraction, objconf, **kwargs):
    runtime = kwargs["runtime"]
    task = extraction if extraction is not None else item

    return runtime.run_agent(
        task,
        tools=objconf.tools,
        model=objconf.model,
        max_steps=objconf.max_steps,
    ).value

The module is one Riko DAG node:

fetch → clean → agent → export

Internally it uses a bounded Python loop, not a nested runnable graph.

Later, if users need to inspect each tool step as a Riko graph, the loop can be promoted into native loop/subpipeline constructs.

Native modules to extract from Langly

The useful Langly functions should become these Riko modules or internals:

Langly functionality    Native implementation
nth_message()   internal message helper or field extraction
transform() processor assign
assign_tool_output()    processor assign
get_tool_output()   output normalization helper
enter_chain()   agent message-state helper
ToolNode    native tool executor
get_chat_model()    model registry + provider adapter
create_node()   pipeline/module configuration
create_agent_team() future Riko subpipeline/DAG
run_graph() iterate a compiled Riko pipeline
start_task()    construct source and consume result
optimize_node() native model selector
LangChain converters    small typed conversion functions
Small Riko additions worth making

Most runnable concepts already map to Riko, but four improvements would make the replacement clean.

1. Callable processor API

Improve udf or add a public helper:

pipe.call(
    normalize_messages,
    assign="messages",
)

Equivalent to:

pipe.udf(
    func=normalize_messages,
    assign="messages",
)

It should support sync and async callables cleanly.

2. Graph branch API

Add graph-native fan-out:

pipe.branch(
    summary=summary_pipeline,
    sentiment=sentiment_pipeline,
)

This is the real replacement for RunnableParallel.

3. Keyed fan-in

Add a merge that combines branch results by source item identity:

.branch(...)
.merge_fields()

This differs from union, which concatenates streams.

The graph executor needs a stable correlation key, perhaps internal metadata:

{
    "_riko": {
        "item_id": "...",
        "branch": "summary",
    }
}

or an execution-side envelope that is not exposed to normal item data.

4. Context events

Add a lightweight event callback surface for:

model request started;
token received;
tool called;
retry;
usage recorded;
agent completed.

This replaces LangChain callbacks and tracing without changing stream output.

context.emit(
    "ai.tool.completed",
    tool="search",
    duration=0.42,
)
Final boundary
Riko pipeline engine
    sequence
    fan-out/fan-in
    parallel item processing
    assignment
    filtering/routing
    loops
    sync/async iteration
    execution context

Riko AI modules
    infer
    agent
    embed
    retrieve

Riko AI kernel
    messages
    model metadata
    provider protocols
    prompt catalog
    structured output
    tool registry
    bounded tool loop
    model selection

Provider adapters
    direct OpenAI SDK
    direct Anthropic SDK
    OpenAI-compatible HTTP

The architecture should therefore have no runnable abstraction at all. Langly’s runnable chains become either:

internal implementation details inside one Riko module;
ordinary Riko pipeline stages;
Riko DAG branches;
a bounded loop inside the agent module.
how would branch differ from split and can it just be a conf option in split
Worked for 47s

branch should use split underneath, but it should not be implemented as ordinary split module configuration.

Semantic difference

Current split is a stream primitive:

stream ── split(3) ──┬─ copy 1
                     ├─ copy 2
                     └─ copy 3

It:

creates a specified number of equivalent streams;
returns them positionally;
knows nothing about what each resulting stream will do;
does not recombine results.

The current implementation eagerly materializes the entire source, then creates a deep-copied stream for each split.

A proposed branch is a graph-construction operation:

                         ┌─ infer(summary) ────┐
stream ── fan out ───────┼─ infer(sentiment) ─┼─ merge
                         └─ infer(entities) ───┘

It adds:

named outputs;
different downstream pipelines;
optional concurrent execution;
optional correlated fan-in.

The fan-out itself is still split. The rest is graph wiring.

When branch adds no new runtime behavior

Without recombination:

summary, sentiment = pipe.split(conf={"splits": 2})

summary = summary.infer(
    conf={"prompt": "summarize"},
    assign="summary",
)

sentiment = sentiment.infer(
    conf={"prompt": "classify_sentiment"},
    assign="sentiment",
)

That already represents branching. A separate branch module would be redundant.

At most, branch() would be fluent API sugar:

branches = pipe.branch(
    summary=lambda branch: branch.infer(
        conf={"prompt": "summarize"},
        assign="summary",
    ),
    sentiment=lambda branch: branch.infer(
        conf={"prompt": "classify_sentiment"},
        assign="sentiment",
    ),
)

Conceptually, it lowers to:

summary, sentiment = pipe.split(conf={"splits": 2})

followed by the specified pipelines.

Why it should not be a normal conf option

Something like this is the wrong layer:

pipe.split(
    conf={
        "branches": {
            "summary": [...],
            "sentiment": [...],
        },
    }
)

Riko module configuration describes how a module transforms data. Branch definitions describe pipeline topology.

Putting downstream pipelines in conf creates several problems:

split becomes responsible for constructing and executing pipelines;
graph edges become hidden inside module configuration;
dependency and topology inspection becomes harder;
Python callables cannot be represented in serialized pipeline definitions;
branch configuration may be confused with Riko’s dynamic, item-derived configuration;
the module’s return contract changes depending on configuration.

The compiler should see actual nodes and wires:

input → split
split → summary_infer
split → sentiment_infer

not one opaque split node whose conf secretly contains two pipelines.

A good compromise: builder option, not module configuration

You could expose branching through split() without adding branch():

branches = pipe.split(
    branches={
        "summary": lambda branch: branch.infer(
            conf={"prompt": "summarize"},
        ),
        "sentiment": lambda branch: branch.infer(
            conf={"prompt": "classify_sentiment"},
        ),
    }
)

But branches= here would be consumed by SyncPipe.split() or a graph builder. It would not be passed to riko.modules.split.pipe() as conf.

Internally:

def split(
    self,
    *,
    branches: Mapping[str, BranchBuilder] | None = None,
    **kwargs,
):
    if branches is None:
        return existing_split_behavior(self, **kwargs)

    streams = existing_split_behavior(
        self,
        conf={"splits": len(branches)},
        **kwargs,
    )

    return {
        name: builder(stream)
        for (name, builder), stream in zip(
            branches.items(),
            streams,
        )
    }

This lets split remain the public fan-out API without corrupting the module’s configuration contract.

The real missing feature is fan-in

LangChain’s RunnableParallel does not merely split execution. It returns branch results correlated to the same input:

{
    "summary": "...",
    "sentiment": "...",
    "entities": [...],
}

Current Riko union is not that operation. It concatenates streams:

stream A: A1, A2
stream B: B1, B2

union: A1, A2, B1, B2

It does not combine A1 with B1.

Runnable-parallel semantics need a keyed merge:

summary(item 1)   ─┐
sentiment(item 1) ─┼─ item 1 result
entities(item 1)  ─┘

That could be:

branches = pipe.split(
    branches={
        "summary": summarize,
        "sentiment": classify,
        "entities": extract,
    }
)

result = branches.merge_fields()

Or:

result = pipe.branch(
    summary=summarize,
    sentiment=classify,
    entities=extract,
).merge_fields()

merge_fields() would need to preserve input correlation. That is separate from split.

Current split may need an implementation change

The current implementation does:

source = list(stream)

for _ in range(splits):
    yield map(deepcopy, source)

That means an AI branch over 100,000 records loads and duplicates the full source before any inference branch starts.

For branch-oriented execution, a better implementation would incrementally distribute each item:

item 1 → all branches
item 2 → all branches
item 3 → all branches

Possible implementations include:

a graph executor that dispatches each item to every successor;
buffered broadcast queues;
itertools.tee for simple single-threaded cases;
an execution envelope carrying an internal correlation ID.

This improvement belongs in split or the DAG executor. A branches conf option would not address it.

Recommended design

Do not create riko.modules.branch.

Keep:

split = fan-out data primitive

Add one of these fluent APIs:

pipe.branch(...)

or:

pipe.split(branches=...)

Implement either as compile-time sugar that produces:

split node
+ named outgoing edges
+ child pipelines

Keep recombination explicit:

branches.merge_fields()

The cleanest API is probably:

result = (
    pipe
    .branch(
        summary=lambda p: p.infer(
            conf={"prompt": "summarize"},
        ),
        sentiment=lambda p: p.infer(
            conf={"prompt": "sentiment"},
        ),
    )
    .merge_fields()
)

But internally, branch() should be nothing more than named split plus graph wiring. The name is an ergonomic distinction, not a new execution primitive.

so that is just my broadcast/dispatch funcs then
Worked for 48s

Yes. The proposed branch behavior is already conceptually your broadcast/dispatch pair.

The important distinction is:

split       one stream → multiple equivalent streams
broadcast   one item   → same item through multiple functions
dispatch    N values   → each value through its corresponding function

Your broadcast() delivers the same item to every function and returns the results as a tuple. That is the core behavior of LangChain’s RunnableParallel.

results = broadcast(
    item,
    summarize,
    classify_sentiment,
    extract_entities,
)

Conceptually:

                  ┌─ summarize(item)
item ─────────────┼─ classify_sentiment(item)
                  └─ extract_entities(item)

Your dispatch() handles the complementary case: it pairs each existing value with its corresponding function.

results = dispatch(
    split_values,
    summarize,
    classify_sentiment,
    extract_entities,
)

Conceptually:

value 1 → summarize
value 2 → classify_sentiment
value 3 → extract_entities
RunnableParallel is primarily broadcast

This LangChain-style construct:

parallel = {
    "summary": summarize,
    "sentiment": classify_sentiment,
    "entities": extract_entities,
}

is natively:

names = tuple(parallel)
results = broadcast(item, *parallel.values())
output = dict(zip(names, results, strict=True))

A lightweight helper could be:

from collections.abc import Callable, Mapping
from typing import TypeVar


T = TypeVar("T")
R = TypeVar("R")


def broadcast_mapping(
    item: T,
    funcs: Mapping[str, Callable[[T], R]],
) -> dict[str, R]:
    results = broadcast(item, *funcs.values())
    return dict(zip(funcs, results, strict=True))

Usage:

result = broadcast_mapping(
    item,
    {
        "summary": summarize,
        "sentiment": classify_sentiment,
        "entities": extract_entities,
    },
)

Output:

{
    "summary": "...",
    "sentiment": "positive",
    "entities": ["Riko", "Nerevu"],
}

That replaces RunnableParallel without introducing branch.

Where split fits

The current split module duplicates an entire input stream:

summary_stream, sentiment_stream = pipe.split(
    conf={"splits": 2},
)

Its implementation materializes the stream and creates deep-copy iterators.

That is useful when the resulting streams continue independently:

source stream ── split ──┬─ pipeline A
                         └─ pipeline B

But it is not needed for per-item parallel transformations:

item ── broadcast ──┬─ operation A
                    ├─ operation B
                    └─ operation C

So my earlier branch concept conflated two levels:

stream-level branching: existing split;
item-level parallel transformation: existing broadcast.

There is no need for a separate branch primitive.

How it maps to Riko pipelines

For a regular processor, each item can be broadcast internally:

def parser(item, extraction, objconf, **kwargs):
    value = extraction if extraction is not None else item

    funcs = {
        "summary": build_inference_func(
            prompt="summarize",
            **kwargs,
        ),
        "sentiment": build_inference_func(
            prompt="sentiment",
            **kwargs,
        ),
        "entities": build_inference_func(
            prompt="entities",
            **kwargs,
        ),
    }

    return broadcast_mapping(value, funcs)

Then:

pipe.infer(
    conf={
        "tasks": {
            "summary": {"prompt": "summarize"},
            "sentiment": {"prompt": "sentiment"},
            "entities": {"prompt": "entities"},
        },
    },
    assign="analysis",
)

Produces:

{
    "content": "...",
    "analysis": {
        "summary": "...",
        "sentiment": "positive",
        "entities": ["Riko"],
    },
}

This could be part of infer rather than a new public module.

Parallelism is the remaining issue

Your current broadcast() executes the functions sequentially:

return tuple(func(item, **kwargs) for func in funcs)

So it provides fan-out semantics, but not concurrent execution.

For AI calls, that distinction matters because three independent model calls should usually run concurrently.

The native additions would be variants of broadcast, not branch:

def thread_broadcast(
    item,
    *funcs,
    executor,
    **kwargs,
):
    futures = [
        executor.submit(func, item, **kwargs)
        for func in funcs
    ]
    return tuple(
        future.result()
        for future in futures
    )

And async:

async def async_broadcast(
    item,
    *funcs,
    **kwargs,
):
    return tuple(
        await asyncio.gather(
            *(
                func(item, **kwargs)
                for func in funcs
            )
        )
    )

More generally:

broadcast          synchronous fan-out
thread_broadcast   concurrent sync/I/O fan-out
async_broadcast    concurrent async fan-out

Existing outer SyncPipe(parallel=True) parallelizes across source items. Inner concurrent broadcast parallelizes independent operations for one item:

outer parallelism:
item 1, item 2, item 3 processed concurrently

inner broadcast:
summary, sentiment, entities for item 1 processed concurrently

Those should remain separately controllable to avoid multiplying concurrency unexpectedly.

Recommended correction

Drop the proposed branch() API.

Use:

split       stream fan-out
union       stream concatenation
broadcast   item fan-out
dispatch    positional item/function routing

Add only what is missing:

named broadcast result
async/concurrent broadcast
possibly explicit concurrency limits

For example:

results = broadcast(
    item,
    **{
        "summary": summarize,
        "sentiment": classify,
    },
)

Changing broadcast itself to accept named functions would break or complicate its current tuple-returning contract, so a distinct wrapper such as broadcast_mapping() is probably cleaner.

The direct mapping becomes:

LangChain feature   Existing Riko feature
RunnableSequence    pipeline chaining
RunnableLambda  processor/udf
RunnablePassthrough.assign  processor assign
RunnableParallel    broadcast
positional parallel transforms  dispatch
stream fan-out  split
stream concatenation    union
batch execution pipe parallelism
streaming   iterators/async iterators

So yes: the runnable replacement should be built around your existing broadcast and dispatch, not a new branch abstraction.

With LangChain runnables replaced by native Riko pipelines, processors, broadcast/dispatch, split, union, parallel execution, and loop, the remaining Langly features are mostly AI-specific.

Langly feature  In Riko Outside Riko    Recommendation
Provider/model invocation   Protocols and normalized request/response types OpenAI, Anthropic, local-model adapters Core protocols in Riko; adapters as extras
Model registry  Model IDs, capabilities, context limits, pricing metadata   Regularly updated model catalogs    Small registry in Riko; catalog data external
Cost/balanced/performance selection Selection policy interface  Evaluation history and pricing updates  Policy in Riko; data supplied externally
Prompt catalog  Named prompts, rendering, dynamic Riko conf Prompt files or application-specific catalogs   Implement in Riko
Structured output   JSON Schema configuration and normalized values Optional jsonschema validation or dataclass/Pydantic conversion Core schema support in Riko; validators optional
Tool definitions    Native callable schema, registry, execution Application tools and service integrations  Implement tool protocol in Riko
Tool-using agent loop   Bounded loop around model and tool processors   None required   Implement natively using Riko
Multi-agent supervisor  Riko graph, routing, broadcast/dispatch, loops  Higher-level agent templates    Defer until single-agent support is stable
Retry/rate limiting Generic retry/backoff configuration Provider-specific error classification  Retry mechanism in Riko; classifiers in adapters
Memory/checkpointing    State-store protocol and session-key extraction SQLite, Redis, database adapters    Protocol in Riko; persistence outside
RAG ingestion   Existing fetch, parse, tokenize, transform pipelines    Heavy file parsers and OCR  Keep orchestration in Riko
Embeddings/retrieval    embed and retrieve modules plus store protocol  Chroma, pgvector, FAISS adapters    Modules in Riko; stores optional
Evaluation scenarios    Pipeline execution and result collection    Benchmark datasets, evaluator models, reporting CLI Separate riko-eval package or optional extra
Automatic model optimization    Consume evaluation profiles during inference    Generate and persist profiles offline   Runtime selector in Riko; evaluation outside
Tracing/callbacks   Context events for model, tool, retry, usage    OpenTelemetry or vendor exporters   Event hooks in Riko; exporters outside
Token streaming Context callback/event sink UI transport such as SSE or WebSocket   Do not emit tokens as normal stream items
Document loaders    Existing Riko modules where possible    PDF/OCR/Office-specific dependencies    Keep heavy loaders outside core
Scenario/agent CLI  Pipeline compiler and module configuration  Dedicated CLI package   Outside Riko core
Suggested boundary
Riko core
    pipeline orchestration
    broadcast / dispatch
    split / union
    loop and routing
    dynamic configuration
    assignment and emission
    AI request/response protocols
    prompt rendering
    tool execution
    bounded agent loop
    model-selection interface
    Context events

Optional Riko extras
    OpenAI adapter
    Anthropic adapter
    JSON Schema validation
    embeddings
    vector-store adapters
    persistence adapters

Outside Riko
    model catalog updates
    evaluation datasets/results
    benchmark CLI
    application prompts and tools
    heavy document loaders
    telemetry exporters

The immediate missing implementation set is therefore small:

Native message/request/response types.
Provider and model protocols.
Prompt rendering.
JSON structured-output handling.
Tool registry and executor.
infer processor.
Bounded agent processor using loop, broadcast, and dispatch.
Direct provider adapters.

RAG, persistent memory, evaluation-driven optimization, and multi-agent supervision can remain later or optional layers.

# Riko AI-Infer Addendum

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

