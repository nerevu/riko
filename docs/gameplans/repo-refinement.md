# Repo refinement gameplan
Guiding decisions

These should be treated as settled:

Return behavior is inferred, never duplicated in decorator metadata.
return annotation
→ generator/async-generator detection
→ narrow AST inference
→ actionable error

No kind="stream" or kind="value".

A pipe instance represents one execution and cannot be restarted.
Each module parser receives its explicit parsed configuration type.
Generic framework code does not enumerate all module configurations. It type-erases the concrete config/parser relationship after preparation.
Execution/inspection behavior uses an ExecutionMode enum, not combinations of boolean flags.
Phase 1: Establish API boundaries

Define three supported levels.

Stable user API
    SyncPipe
    AsyncPipe
    SyncCollection
    AsyncCollection
    Context
    ExecutionMode
    public exceptions

Supported extension API
    processor
    operator
    splitter
    ParsedConf
    parser protocols
    ModuleMetadata
    module registration

Private implementation
    AST inference
    assignment machinery
    prepared-module internals
    pool handles
    pub/sub registries
    compiler helpers

Suggested layout:

riko/
  __init__.py
  api.py
  exceptions.py
  context.py

  ext/
    __init__.py
    config.py
    decorators.py
    protocols.py
    registry.py

  modules/
    __init__.py
    _assignment.py
    _inference.py
    _prepare.py
    _wrappers.py

Actions:

Add deliberate __all__ declarations.
Make riko.__init__ mostly re-exports.
Stop exposing incidental imports.
Add temporary compatibility imports for moved names.
Document what follows semantic versioning guarantees.
Add py.typed.
Definition of done

A developer can determine whether an object is stable, extension-facing, or private from its import path alone.

Phase 2: Replace Objconf
Runtime model

Introduce a singular marker/base type:

class ParsedConf:
    """Base type for parsed module configuration."""

Each module gets an explicit frozen dataclass:

from dataclasses import dataclass


@dataclass(frozen=True, slots=True, kw_only=True)
class ReceiveConf(ParsedConf):
    name: str = ""
    wait: float = 0.1
    max_wait: float = 5.0
    max_len: int = 256

The parser uses its concrete type:

def parser(
    stream: Stream,
    objconf: ReceiveConf,
    tuples: PipeTuples,
    **kwargs,
) -> Stream:
    ...

Raw serialized configuration remains a TypedDict:

class ReceiveRawConf(TypedDict, total=False):
    name: Required[Value]
    wait: Value
    max_wait: Value
    max_len: Value

The distinction becomes:

ReceiveRawConf
    dynamic/serialized input

ReceiveConf
    parsed runtime contract
Infer the config type

Do not add redundant decorator metadata.

The framework derives it from the parser annotation:

def get_conf_type(parser: Callable[..., object]) -> type[ParsedConf]:
    annotation = get_type_hints(parser).get("objconf")

    if (
        isinstance(annotation, type)
        and issubclass(annotation, ParsedConf)
    ):
        return annotation

    return DynamicConf
Type erasure after preparation

Bind the correctly typed parser and configuration into a callable:

@dataclass(frozen=True, slots=True)
class PreparedModule:
    name: str
    conf: ParsedConf
    invoke: Callable[..., ParserOutput]
    opts: Opts
    assign: str
    emit: EmitOption

Preparation remains locally generic:

def prepare_parser[C: ParsedConf](
    parser: Callable[..., ParserOutput],
    conf_type: type[C],
    values: Mapping[str, object],
) -> tuple[C, Callable[..., ParserOutput]]:
    conf = fromdict(conf_type, **values)

    def invoke(*args, **kwargs):
        return parser(*args, objconf=conf, **kwargs)

    return conf, invoke

The remainder of modules/__init__.py calls prepared.invoke(...); it does not deal with 30 configuration types or a large union.

Compatibility path

Provide:

@dataclass(frozen=True, slots=True)
class DynamicConf(ParsedConf):
    values: Mapping[str, object]

Use it temporarily for unconverted or external modules without explicit config annotations.

Definition of done
No global list of every possible config attribute.
Every built-in parser has a precise config type.
Generic wrapper code sees only ParsedConf and PreparedModule.invoke.
Raw pipeline JSON still works unchanged.
Phase 3: Decompose modules/__init__.py

Split it by responsibility without changing behavior.

_inference.py
    return annotation analysis
    generator detection
    AST inference
    inference diagnostics

_prepare.py
    parse config
    construct concrete ParsedConf
    bind parser invocation
    PreparedModule

_assignment.py
    get_assignment
    gen_assignments

_metadata.py
    module type/subtype derivation
    ModuleMetadata

_wrappers.py
    sync and async execution wrappers

_decorators.py
    processor
    operator
    splitter

_registry.py
    module registration and lookup

riko.modules.__init__ should only re-export the supported module-development surface.

Definition of done

No package initializer contains the framework implementation.

Phase 4: Formalize inference diagnostics

Preserve the existing inference precedence.

Add a richer internal result:

@dataclass(frozen=True, slots=True)
class ReturnInference:
    kind: OperatorReturnKind
    source: Literal[
        "annotation",
        "generator",
        "ast",
        "unknown",
    ]
    reason: str | None = None

Examples:

stream inferred from Iterator[Item] return annotation

stream inferred because parser is a generator function

nonstream inferred from final return expression sum(items)

unknown because build_result is not a recognized callable;
add a return annotation

Do not expose an override that can drift from the function.

Add focused tests for:

sync generators;
async generators;
annotated unions;
Annotated;
aliases;
built-ins;
itertools;
passthrough wrappers;
unavailable source;
ambiguous calls;
nested decorators with wraps;
invalid or contradictory annotations.
Definition of done

Every inference failure explains how to fix the function contract.

Phase 5: Formalize one-shot lifecycle

Add explicit lifecycle state:

class PipeState(StrEnum):
    NEW = "new"
    RUNNING = "running"
    EXHAUSTED = "exhausted"
    CLOSED = "closed"
    FAILED = "failed"

Rules:

NEW
    may be chained
    may begin iteration

RUNNING
    may continue iteration
    may be closed
    may not be reconfigured or chained

EXHAUSTED
    remains exhausted
    may be closed
    cannot restart

CLOSED
    close is idempotent
    cannot iterate or chain

FAILED
    retains original failure
    resources are released
    cannot restart

Avoid silently returning a new execution from iter(pipe) after exhaustion.

Expose read-only state:

pipe.state
pipe.closed
pipe.exhausted

Raise a stable PipelineStateError for invalid transitions.

Definition of done

One-shot behavior is documented, tested, and identical for sync and async pipes.

Phase 6: Replace context boolean combinations

Add:

class ExecutionMode(StrEnum):
    RUN = "run"
    DESCRIBE_INPUTS = "describe_inputs"
    DESCRIBE_DEPENDENCIES = "describe_dependencies"
    DESCRIBE = "describe"

Then:

@dataclass(slots=True)
class Context:
    mode: ExecutionMode = ExecutionMode.RUN
    inputs: Mapping[str, object] = field(default_factory=dict)
    verbose: bool = False
    test: bool = False
    submodule: bool = False

Compatibility properties can temporarily remain:

@property
def describe_input(self) -> bool:
    return self.mode in {
        ExecutionMode.DESCRIBE_INPUTS,
        ExecutionMode.DESCRIBE,
    }

Later additions should go into Context rather than pipe kwargs:

run ID
deadline
cancellation
event sink
resource registry
metadata
tenant/session context
Definition of done

Invalid inspection-mode combinations become impossible.

Phase 7: Make sync and async contracts equivalent

Create matching _chain() implementations.

Both should propagate:

Context
inputs
execution mode
parallelism settings
ordering
resource ownership
cancellation

Remove full-stream materialization between async stages. An AsyncPipe source should accept:

AsyncIterable[Item]

rather than converting the previous stage into a completed list before the next stage begins.

Define parity tests for:

chaining;
dynamic conf;
assignment;
emit;
exceptions;
close/cancel;
split;
send/receive;
ordering;
context propagation;
one-shot behavior.
Definition of done

Differences between SyncPipe and AsyncPipe are execution mechanics, not observable pipeline semantics.

Phase 8: Introduce a module registry

Replace hardcoded import-only resolution with a registry:

class ModuleRegistry:
    def register(self, name: str, module: ModuleMetadata) -> None: ...
    def resolve(self, name: str) -> ModuleMetadata: ...
    def names(self) -> tuple[str, ...]: ...

Resolution order:

runtime registrations
→ installed entry points
→ built-in modules
→ local/compiled pipeline resolution

Support package entry points:

[project.entry-points."riko.modules"]
graph = "riko_microsoft.graph"
powershell = "riko_microsoft.powershell"
infer = "riko_ai.infer"

Registry metadata should include:

name
sync parser
async parser
module type/subtypes
parsed config type
raw config schema
pollable/loopable flags

Most metadata should still be inferred from implementation contracts.

Definition of done

An external package can add modules without modifying Riko core.

Phase 9: Improve fluent API discoverability

Keep dynamic chaining:

pipe.tokenizer(...)

Add an explicit fallback:

pipe.then("tokenizer", ...)

Then generate development-time stubs from the module registry:

class SyncPipe:
    def tokenizer(
        self,
        *,
        conf: TokenizerRawConf | TokenizerConf | None = ...,
        field: str | None = ...,
        assign: str | None = ...,
        emit: bool | None = ...,
    ) -> SyncPipe: ...

Also add:

pipe.available_modules()
pipe.describe_module("tokenizer")

and __dir__() support.

Unknown modules should suggest close names.

Definition of done

IDE completion and Pyright understand built-in fluent methods without removing runtime extensibility.

Phase 10: Add bounded parallelism and backpressure

Avoid consuming the entire source before parallel execution.

Add explicit execution settings:

SyncPipe(
    ...,
    parallel=True,
    executor="thread",
    workers=8,
    prefetch=32,
    ordered=False,
)

Supported executors:

inline
thread
process

Async equivalent:

bounded task group
semaphore/concurrency limit
ordered or completion-order output

Define how nested parallelism behaves:

pipeline-level item concurrency
broadcast-level operation concurrency
provider-level connection limits

Do not let these multiply accidentally without a shared budget.

Definition of done

Large, infinite, and event-driven streams can use parallel execution with bounded memory.

Phase 11: Stabilize pub/sub and polling primitives

Move global registry access behind protocols:

class Publisher(Protocol):
    def publish(self, topic: str, item: object) -> None: ...


class Subscription(Protocol):
    def receive(
        self,
        timeout: float | None = None,
    ) -> object | None: ...

    def close(self) -> None: ...

The current local send/receive machinery becomes one implementation.

.poll should support:

interval
event
hybrid

Hybrid remains the recommended mode:

event wakes the poller
→ authoritative API status is checked
→ interval remains a fallback

Store broker/subscription resources in Context.resources, not process globals, while retaining a global compatibility adapter initially.

Definition of done

The same poll operator works with in-process pub/sub, Azure Service Bus, Event Grid, Redis, or webhook adapters.

Phase 12: Expand stable errors and observability

Introduce:

class RikoError(Exception): ...

class ConfigurationError(RikoError): ...
class ModuleDefinitionError(RikoError): ...
class ModuleExecutionError(RikoError): ...
class UnsupportedModuleError(ModuleDefinitionError, ImportError): ...
class PipelineStateError(RikoError): ...
class PollTimeoutError(RikoError, TimeoutError): ...
class PublishError(RikoError): ...
class SubscriptionError(RikoError): ...

ModuleExecutionError should preserve:

module name
stage name
input item/correlation ID
original exception

Add a small event sink:

class EventSink(Protocol):
    def emit(self, event: RuntimeEvent) -> None: ...

Events:

pipeline.started
pipeline.completed
stage.started
stage.completed
stage.failed
poll.waiting
poll.status
publish.sent
subscription.received
retry.scheduled
Definition of done

Azure, PowerShell, and AI integrations can expose diagnostics without printing or depending on a specific telemetry vendor.

Phase 13: Public contract and typing tests

Separate black-box public tests from internal tests:

tests/
  public/
    test_imports.py
    test_pipe_lifecycle.py
    test_sync_async_parity.py
    test_module_extension.py
    test_context_modes.py
    test_exceptions.py

  typing/
    valid/
    invalid/

  internal/
    test_inference.py
    test_preparation.py
    test_assignment.py

Add tests for:

exact public imports;
no accidental internal exports;
extension package example;
parser-specific config typing;
legacy DynamicConf;
generated fluent stubs;
one-shot lifecycle;
inference diagnostics;
sync/async parity.
Definition of done

Public API compatibility can be evaluated independently from implementation refactors.

Phase 14: Build integrations outside core

Once extension contracts are stable:

riko-microsoft
    auth
    Graph
    ARM
    PowerShell
    Service Bus/Event Grid subscriptions
    desired-state tools

riko-ai
    providers
    infer
    tools
    agent loop
    embedding/retrieval adapters

Core should provide only:

module registration
typed parsed config
pipeline execution
polling
pub/sub protocols
retry
context/resources
events
Recommended implementation order
1. Public/private/extension API boundary
2. Split modules/__init__.py
3. ParsedConf + explicit per-parser config dataclasses
4. Type-erased PreparedModule.invoke
5. Return-inference diagnostics
6. PipeState and one-shot enforcement
7. ExecutionMode
8. Sync/async parity and true async streaming
9. Module registry and entry points
10. Generated fluent API stubs
11. Bounded concurrency/backpressure
12. Pub/sub and poll protocols
13. Stable errors/events
14. Microsoft and AI extension packages

The first milestone should stop after step 7. That gives Riko a coherent developer contract before changing concurrency or adding external integrations.

---

# Shelf integration addendum

## Extension families after core stabilization

The Shelf confirms that most future integrations should not become built-in Riko core
modules. Once the extension contracts are stable, use these package families:

```text
riko-connect
    URI/source resolution
    HTTP response adapters
    object storage
    FTP/SFTP
    mail
    broker publishers and consumers
    CKAN, Prometheus, and tabular-file connectors
    Singer-to-RDP adapters

riko-sql
    Ibis connection adapters
    SQL reads and writes
    query planning and push-down
    Arrow/Narwhals batch bridges

riko-dbt
    dbt invocation services
    manifest and run-result normalization
    optional dbt-ibis helpers

riko-orchestration
    Airflow, Prefect, and Dagster adapters
    webhook entrypoints
    schedules and deployment helpers

riko-enrichment
    optional near-duplicate and contact-extraction modules
```

## Generic hooks permitted in core

Core may add only contracts that are useful without any specific integration:

```text
SourceResolver
RecordCodec
CheckpointStore
ExecutionResource
EventSource / EventSink
ArtifactRef
```

A contract is not added merely because one extension needs it. It must have at least two
independent consumers and preserve the one-shot pipeline lifecycle.

## Source resolution boundary

Do not implement a hard-coded universal `fetch` switch in `riko.modules`.

Use a registry whose resolvers return immutable plans:

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class SourcePlan:
    resolver: str
    uri: str
    media_type: str | None
    capability_id: str
    options: Mapping[str, JsonValue]
```

Resolution and execution remain separate:

```text
URI + explicit hints
→ deterministic resolver selection
→ inspectable SourcePlan
→ policy and credential resolution
→ connector execution
```

This supports plugin schemes without growing a monolithic dispatch table and gives the
CLI, MCP catalog, and AI selector a stable object to inspect.

## Updated implementation order

After the existing fourteen steps:

```text
15. Generic source-plan and checkpoint contracts, if justified by two extensions
16. riko-connect protocol and storage adapters
17. riko-sql and riko-dbt
18. riko-orchestration and optional enrichment packages
```

None of these steps should delay the HigherGov vertical slice or RDP/Connect core.
