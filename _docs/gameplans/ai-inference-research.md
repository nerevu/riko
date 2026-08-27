# AI inference — prior-art research & extraction notes

> Research/ADR notebook behind [ai-inference.md](ai-inference.md) (the actionable
> gameplan). Prototype analysis of Langly/LangChain and the native-reimplementation
> sketches — kept for rationale and traceability, not as a task list.

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
Model performance history   Retain for pipe-level model selection
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
class AIPipeSpec:
    id: str
    prompt: str
    response_schema: dict[str, JsonValue] | None = None
    tools: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EvaluationCase:
    pipe_id: str
    input: JsonValue
    expected: JsonValue | None
    evaluator: str

Evaluation results:

@dataclass(frozen=True, slots=True)
class ModelEvaluation:
    pipe_id: str
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

pipe specifications;
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

> **`a | b` is literal, not just attribute chaining.** Native `__or__`/`__ror__` on
> `SyncPipe`/`AsyncPipe` (shipped; see [module-enums.md](module-enums.md),
> alongside a value-taking `.pipe("filter", …)`) makes `pipe | Transforms.FILTER` and
> `data | pipe` the direct `RunnableSequence` equivalent for LCEL migrants. This lives **on the pipe
> itself** — it does **not** reintroduce the forbidden `RikoRunnable` wrapper below; it is sugar over
> `_chain`, adding no second object model.

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
    pipe="ticket_classification",
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
ordinary Riko pipes;
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
